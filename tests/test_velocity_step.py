"""VelocityStepController: the shared step core extracted from VelocitySimSession.

Same stubs as test_velocity_session.py (copied verbatim) so the two suites
exercise the same duck-typed PolicyStepRunner surface. Here the unit under
test is the mode-machine-free step core: seeding, hand-off, safety verdicts,
and the two step bodies returning their byproducts as tuples.
"""
from __future__ import annotations

import dataclasses
from typing import Any

import numpy as np

from teleopit.interfaces import RobotState
from teleopit.sim.velocity_step import VelocityStepController

POSE_B = np.array(
    [
        -0.1, 0, 0, 0.3, -0.2, 0,
        -0.1, 0, 0, 0.3, -0.2, 0,
        0, 0, 0,
        0.35, 0.18, 0, 0.87, 0, 0, 0,
        0.35, -0.18, 0, 0.87, 0, 0, 0,
    ],
    dtype=np.float64,
)

_ZERO_CMD = [0.0] * 6


class _StubController:
    def __init__(self, dim_in: int, neutral_out: float = 0.0, action_scale=1.0, default_dof_pos=None):
        self.dim_in = dim_in
        self._neutral = neutral_out
        self.action_scale = np.asarray(action_scale, dtype=np.float64)
        self.default_dof_pos = (
            None if default_dof_pos is None else np.asarray(default_dof_pos, dtype=np.float64)
        )
        self.reset_called = 0
        self.compute_called = 0

    def reset(self):
        self.reset_called += 1

    def compute_action(self, obs):
        self.compute_called += 1
        assert obs.shape[-1] == self.dim_in
        return np.full(29, self._neutral, dtype=np.float32)

    def get_target_dof_pos(self, action):
        return np.asarray(action, dtype=np.float32)


class _StubMimicObsBuilder:
    """Records (motion_qpos, last_action) per build; emits a dim-correct zero obs."""

    def __init__(self, total: int):
        self.total_obs_size = total
        self.reset_called = 0
        self.builds: list[tuple[np.ndarray, np.ndarray]] = []

    def reset(self):
        self.reset_called += 1

    def build(self, state, motion_qpos, motion_joint_vel, last_action, anchor_lin_w, anchor_ang_w):
        self.builds.append((np.asarray(motion_qpos).copy(), np.asarray(last_action).copy()))
        return np.zeros(self.total_obs_size, dtype=np.float32)


class _StubTwistObsBuilder:
    """Records (cmd, last_action) per build; emits a dim-correct zero obs."""

    def __init__(self, total: int):
        self.total_obs_size = total
        self.reset_called = 0
        self.cmds: list[np.ndarray] = []
        self.prev_actions: list[np.ndarray] = []

    def reset(self):
        self.reset_called += 1

    def build(self, state, cmd, last_action):
        self.cmds.append(np.asarray(cmd).copy())
        self.prev_actions.append(np.asarray(last_action).copy())
        return np.zeros(self.total_obs_size, dtype=np.float32)


class _StubRobot:
    def __init__(self):
        self.launched = False
        self.steps = 0
        self.qpos = np.zeros(29)
        self.tilted = False
        self.quat_override: np.ndarray | None = None
        self.base_pos_override: np.ndarray | None = None

    def get_state(self):
        if self.quat_override is not None:
            quat = np.asarray(self.quat_override, dtype=np.float64)
        else:
            quat = (
                np.array([0.5, 0.5, 0.5, 0.5], dtype=np.float64)
                if self.tilted
                else np.array([1.0, 0.0, 0.0, 0.0])
            )
        base_pos = (
            np.asarray(self.base_pos_override, dtype=np.float64)
            if self.base_pos_override is not None
            else np.array([0.0, 0.0, 0.75])
        )
        return RobotState(
            qpos=self.qpos,
            qvel=np.zeros(29),
            quat=quat,
            ang_vel=np.zeros(3),
            timestamp=float(self.steps),
            base_pos=base_pos,
            base_lin_vel=np.array([1.0, 0.0, 0.0]),
        )


@dataclasses.dataclass
class _StubPrep:
    qpos: np.ndarray
    motion_joint_vel: np.ndarray
    motion_anchor_lin_vel_w: np.ndarray | None = None
    motion_anchor_ang_vel_w: np.ndarray | None = None


@dataclasses.dataclass
class _StubRunner:
    robot: Any
    controller: Any
    obs_builder: Any
    num_actions: int = 29
    last_action: np.ndarray = dataclasses.field(
        default_factory=lambda: np.zeros(29, dtype=np.float32)
    )

    def __post_init__(self):
        self.prepared_qpos: list[np.ndarray] = []

    def prepare_static_motion_command(self, qpos):
        q = np.asarray(qpos, dtype=np.float64).reshape(-1).copy()
        self.prepared_qpos.append(q.copy())
        return _StubPrep(
            qpos=q,
            motion_joint_vel=np.zeros(self.num_actions, dtype=np.float32),
            motion_anchor_lin_vel_w=np.zeros(3, dtype=np.float32),
            motion_anchor_ang_vel_w=np.zeros(3, dtype=np.float32),
        )

    def compute_target_dof_pos(self, action):
        # Joint-space decode: scale + own neutral pose, like RLPolicyController.
        ctrl = self.controller
        scale = np.asarray(getattr(ctrl, "action_scale", 1.0), dtype=np.float64)
        default = getattr(ctrl, "default_dof_pos", None)
        default = (
            np.zeros(self.num_actions) if default is None else np.asarray(default, dtype=np.float64)
        )
        return (np.asarray(action, dtype=np.float64) * scale + default).astype(np.float32)

    def apply_control(self, target):
        self.robot.steps += 1
        return np.zeros(self.num_actions, dtype=np.float32), self.robot.get_state()

    def finish_step(self, action, qpos):
        self.last_action = np.asarray(action, dtype=np.float32)

    def validate_observation_for_policy(self, obs):
        return obs


class _StubCmd:
    def __init__(self, cmd):
        self._cmd = np.asarray(cmd, dtype=np.float32)

    def get_cmd(self):
        return self._cmd

    def reset(self):
        pass

    def close(self):
        pass


def _controller(**kwargs):
    robot = _StubRobot()
    vel_runner = _StubRunner(robot, _StubController(98, action_scale=1.0), _StubTwistObsBuilder(98))
    defaults = dict(
        velocity_runner=vel_runner,
        cmd_provider=_StubCmd([0.0] * 6),
        pose_b=POSE_B.copy(),
        policy_hz=50.0,
        transition_duration_s=1.0,
        joint_vel_limit=10.0,
        tilt_threshold_rad=1.0,
    )
    defaults.update(kwargs)
    return VelocityStepController(**defaults), robot, vel_runner


def _mimic_runner(robot, pose_a=None):
    return _StubRunner(
        robot, _StubController(167, action_scale=1.0, default_dof_pos=pose_a),
        _StubMimicObsBuilder(167),
    )


def test_seed_joint_space_equivalent_of_mimic_action():
    robot = _StubRobot()
    mimic_runner = _mimic_runner(robot, pose_a=np.full(29, 0.1))
    mimic_runner.last_action = np.full(29, 0.3, dtype=np.float32)
    ctrl, _, _ = _controller()
    np.testing.assert_allclose(
        ctrl.velocity_prev_action_seed(mimic_runner),
        (0.3 + np.full(29, 0.1) - POSE_B).astype(np.float32),
    )


def test_seed_falls_back_to_zeros_without_mimic_default():
    robot = _StubRobot()
    mimic_runner = _mimic_runner(robot, pose_a=None)
    ctrl, _, _ = _controller()
    np.testing.assert_allclose(
        ctrl.velocity_prev_action_seed(mimic_runner), np.zeros(29, dtype=np.float32)
    )


def test_begin_velocity_handoff_seeds_and_resets():
    robot = _StubRobot()
    mimic_runner = _mimic_runner(robot, pose_a=np.full(29, 0.1))
    mimic_runner.last_action = np.full(29, 0.3, dtype=np.float32)
    ctrl, _, vel_runner = _controller()
    ctrl.begin_velocity_handoff(mimic_runner, np.zeros(43))
    assert vel_runner.controller.reset_called == 1
    assert vel_runner.obs_builder.reset_called == 1
    np.testing.assert_allclose(
        vel_runner.last_action, (0.3 + np.full(29, 0.1) - POSE_B).astype(np.float32)
    )


def test_velocity_step_runs_full_twist_pipeline():
    ctrl, robot, vel_runner = _controller(cmd_provider=_StubCmd([1.0, 0, 0, 0, 0, 0]))
    cmd, action, target, final_state = ctrl.velocity_step(robot)
    assert robot.steps == 1
    assert len(vel_runner.obs_builder.cmds) == 1
    np.testing.assert_allclose(cmd[:3], [1.0, 0, 0])


def test_check_safety_joint_vel_returns_stop():
    class _FastRobot(_StubRobot):
        def get_state(self):
            from teleopit.interfaces import RobotState
            return RobotState(
                qpos=self.qpos, qvel=np.full(29, 20.0),
                quat=np.array([1.0, 0, 0, 0]), ang_vel=np.zeros(3),
                timestamp=0.0, base_pos=np.array([0, 0, 0.75]),
            )

    ctrl, _, _ = _controller()
    assert ctrl.check_safety(_FastRobot().get_state()) == "stop"


def test_check_safety_tilt_returns_standing():
    ctrl, _, _ = _controller()
    tilted = _StubRobot()
    tilted.tilted = True
    assert ctrl.check_safety(tilted.get_state()) == "standing"


def test_check_safety_healthy_returns_none():
    ctrl, _, _ = _controller()
    assert ctrl.check_safety(_StubRobot().get_state()) is None


def test_standing_step_interpolates_then_adopts_endpoint():
    ctrl, robot, _ = _controller()
    mimic_runner = _mimic_runner(robot, pose_a=np.zeros(29))
    standing_ref = np.zeros(36)  # FULL_QPOS_DIM (root 7 + 29 joints)
    interpolator = ctrl.arm_standing_interpolator(standing_ref, ctrl.pose_b_qpos)
    ref, interp, _, _ = ctrl.standing_step(
        robot, mimic_runner, standing_ref, interpolator, steps_in_mode=100
    )
    assert interp is None  # 100 steps * 0.02 s = 2 s > 1 s duration: finished
    assert not np.array_equal(ref, standing_ref)


def test_velocity_step_estop_none_is_passthrough():
    """estop=None (default) leaves velocity_step cmd untouched (zero regression)."""
    from teleopit.sim.estop import EstopController, EstopState

    ctrl, robot, _ = _controller(cmd_provider=_StubCmd([0.6, 0, 0, 0, 0, 0]))
    cmd, _action, _target, _state = ctrl.velocity_step(robot)
    np.testing.assert_allclose(cmd[0], 0.6)  # no estop wrapper: raw cmd reaches downstream


def test_velocity_step_applies_estop_when_engaged():
    """velocity_step consults estop.apply() after get_cmd — latched estop zeroes it."""
    from teleopit.sim.estop import EstopController, EstopState

    estop = EstopController(clock=lambda: 0.0)
    estop.toggle(in_velocity=True)
    estop._state = EstopState.LATCHED  # skip the 0.3s ramp for determinism
    ctrl, robot, _ = _controller(
        cmd_provider=_StubCmd([0.6, 0, 0, 0, 0, 0]), estop=estop
    )
    cmd, _action, _target, _state = ctrl.velocity_step(robot)
    assert not np.any(cmd)  # estop latched: downstream sees zero twist
