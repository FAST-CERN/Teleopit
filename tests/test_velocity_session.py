"""VelocitySimSession: STANDING(mimic) <-> VELOCITY(twist) <-> STOP mode machine.

Stubs duck-type PolicyStepRunner's public surface (last_action, controller,
obs_builder, num_actions, prepare_static_motion_command, compute_target_dof_pos,
apply_control, finish_step, validate_observation_for_policy). The mimic obs
builder stub follows the real 6-arg anchor-velocity build contract that
dispatch_build_observation invokes; the twist builder stub follows
TwistCmdObservationBuilder.build(state, cmd, last_action).
"""
from __future__ import annotations

import dataclasses
from typing import Any

import numpy as np

from teleopit.interfaces import RobotState
from teleopit.sim.velocity_session import VelocityMode, VelocitySimSession

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
_SUMMARY_KEYS = {
    "steps",
    "mode_switches",
    "max_target_jump_rad",
    "cmd_track_err_mps",
    "min_root_height_m",
}


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

    def get_state(self):
        quat = (
            np.array([0.5, 0.5, 0.5, 0.5], dtype=np.float64)
            if self.tilted
            else np.array([1.0, 0.0, 0.0, 0.0])
        )
        return RobotState(
            qpos=self.qpos,
            qvel=np.zeros(29),
            quat=quat,
            ang_vel=np.zeros(3),
            timestamp=float(self.steps),
            base_pos=np.array([0.0, 0.0, 0.75]),
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


class _FakeKeyEvent:
    def __init__(self, key: str) -> None:
        self.key = key


class _ScriptedKeyboard:
    """Each poll() consumes the next scripted batch; afterwards returns nothing."""

    def __init__(self, script: list[list[str]]) -> None:
        self._script = list(script)

    def poll(self):
        if self._script:
            return tuple(_FakeKeyEvent(k) for k in self._script.pop(0))
        return ()

    def close(self):
        pass


class _RecordingConsole:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, str | None]] = []

    def key_feedback(self, key: str, action: str, *, result: str | None = None) -> None:
        self.events.append((key, action, result))


def _components(
    mimic_dim=167,
    velocity_dim=98,
    mimic_neutral=0.0,
    velocity_neutral=0.0,
    mimic_scale=1.0,
    velocity_scale=1.0,
    mimic_default=None,
):
    robot = _StubRobot()
    mimic_runner = _StubRunner(
        robot,
        _StubController(mimic_dim, mimic_neutral, action_scale=mimic_scale, default_dof_pos=mimic_default),
        _StubMimicObsBuilder(mimic_dim),
    )
    vel_runner = _StubRunner(
        robot,
        _StubController(velocity_dim, velocity_neutral, action_scale=velocity_scale),
        _StubTwistObsBuilder(velocity_dim),
    )
    return robot, mimic_runner, vel_runner


def _cfg(transition_duration_s: float = 1.0, **overrides):
    cfg = {
        "modes": {"transition_duration_s": transition_duration_s},
        "safety": {"joint_vel_limit": 10.0, "tilt_threshold_rad": 1.0},
        "policy_hz": 50.0,
        "pose_b": POSE_B.copy(),
    }
    cfg.update(overrides)
    return cfg


def _session(robot, mimic_runner, vel_runner, cmd=None, cfg=None, **kwargs):
    return VelocitySimSession(
        robot=robot,
        mimic_runner=mimic_runner,
        velocity_runner=vel_runner,
        command_provider=_StubCmd(_ZERO_CMD if cmd is None else cmd),
        cfg=_cfg() if cfg is None else cfg,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Initial mode + step routing
# ---------------------------------------------------------------------------


def test_initial_mode_is_standing_and_steps():
    robot, mimic_runner, vel_runner = _components()
    session = _session(robot, mimic_runner, vel_runner)
    summary = session.run(num_steps=5)
    assert session.mode == VelocityMode.STANDING
    assert robot.steps == 5
    assert summary["steps"] == 5
    assert summary["mode_switches"] == 0
    assert summary["max_target_jump_rad"] == 0.0  # constant targets -> no jump
    assert summary["cmd_track_err_mps"] == 0.0  # standing: cmd not tracked
    np.testing.assert_allclose(summary["min_root_height_m"], 0.75)
    # Standing steps route through the mimic builder only.
    assert len(mimic_runner.obs_builder.builds) == 5
    assert vel_runner.obs_builder.prev_actions == []


def test_summary_keys_exact():
    robot, mimic_runner, vel_runner = _components()
    session = _session(robot, mimic_runner, vel_runner)
    assert set(session.run(num_steps=1)) == _SUMMARY_KEYS


# ---------------------------------------------------------------------------
# STANDING -> VELOCITY transition
# ---------------------------------------------------------------------------


def test_switch_to_velocity_uses_twist_builder_and_seeds_joint_space_action():
    pose_a = np.full(29, 0.1)
    robot, mimic_runner, vel_runner = _components(
        mimic_scale=1.0, velocity_scale=1.0, mimic_default=pose_a,
    )
    seed = np.full(29, 0.3, dtype=np.float32)
    mimic_runner.last_action = seed.copy()
    session = _session(robot, mimic_runner, vel_runner, cmd=[1.0, 0, 0, 0, 0, 0])
    session.request_mode(VelocityMode.VELOCITY)
    session.run(num_steps=3)
    assert session.mode == VelocityMode.VELOCITY
    # Twist builder built every step; mimic builder never ran:
    assert len(vel_runner.obs_builder.prev_actions) == 3
    assert mimic_runner.obs_builder.builds == []
    # prev_action observation was seeded with the joint-space equivalent of the
    # mimic action (0.3 + pose_a - pose_B with unit scales), not zeroed:
    expected = (0.3 + pose_a - POSE_B).astype(np.float32)
    np.testing.assert_allclose(vel_runner.obs_builder.prev_actions[0], expected)
    assert not np.allclose(vel_runner.obs_builder.prev_actions[0], 0.0)
    # Subsequent steps consume the velocity policy's own actions:
    np.testing.assert_allclose(vel_runner.obs_builder.prev_actions[1], 0.0)
    assert vel_runner.obs_builder.reset_called >= 1  # gait + policy reset on entry
    assert vel_runner.controller.reset_called >= 1
    summary = session.run(num_steps=1)
    assert set(summary) == _SUMMARY_KEYS


def test_apply_pending_mode_seeds_velocity_last_action_immediately():
    pose_a = np.full(29, 0.1)
    robot, mimic_runner, vel_runner = _components(mimic_default=pose_a)
    raw = np.full(29, 0.3, dtype=np.float32)
    mimic_runner.last_action = raw.copy()
    session = _session(robot, mimic_runner, vel_runner)
    session.request_mode(VelocityMode.VELOCITY)
    session._apply_pending_mode(robot.get_state())
    np.testing.assert_allclose(
        vel_runner.last_action, (0.3 + pose_a - POSE_B).astype(np.float32)
    )
    assert session.mode == VelocityMode.VELOCITY


def test_velocity_seed_rescales_mimic_action_into_joint_space():
    """Seed = (mimic_target - pose_B) / vel_action_scale, NOT the raw action.

    Mimic and velocity policies decode with different scales and different
    neutral poses (A vs B); the same raw number means a different joint offset
    under each. The seed must make the two decodes agree in joint space.
    """
    pose_a = np.linspace(-0.2, 0.2, 29)  # any non-zero pose A
    robot, mimic_runner, vel_runner = _components(
        mimic_scale=0.5475, velocity_scale=0.44, mimic_default=pose_a,
    )
    raw = np.full(29, 0.7, dtype=np.float32)  # large raw mimic action
    mimic_runner.last_action = raw.copy()
    session = _session(robot, mimic_runner, vel_runner)
    session.request_mode(VelocityMode.VELOCITY)
    session._apply_pending_mode(robot.get_state())

    mimic_target = 0.7 * 0.5475 + pose_a
    expected_seed = np.asarray((mimic_target - POSE_B) / 0.44, dtype=np.float32)
    np.testing.assert_allclose(vel_runner.last_action, expected_seed, rtol=1e-5)
    # And definitively NOT the raw action:
    assert not np.allclose(vel_runner.last_action, raw)


def test_velocity_seed_falls_back_to_zeros_without_mimic_default():
    robot, mimic_runner, vel_runner = _components(mimic_default=None)
    mimic_runner.last_action = np.full(29, 0.9, dtype=np.float32)
    session = _session(robot, mimic_runner, vel_runner)
    session.request_mode(VelocityMode.VELOCITY)
    session._apply_pending_mode(robot.get_state())
    np.testing.assert_allclose(vel_runner.last_action, 0.0)


def test_velocity_seed_clipped_to_clip_range():
    """Pathological mimic targets must not blow the prev_action channel past
    the policy's clip range ([-10, 10] for velocity_v1)."""
    robot, mimic_runner, vel_runner = _components(
        mimic_scale=0.5475, velocity_scale=0.07, mimic_default=np.zeros(29),
    )
    mimic_runner.last_action = np.full(29, 9.9, dtype=np.float32)
    session = _session(robot, mimic_runner, vel_runner)
    session.request_mode(VelocityMode.VELOCITY)
    session._apply_pending_mode(robot.get_state())
    unclipped = (9.9 * 0.5475 - POSE_B) / 0.07  # >> 10 on most joints
    assert np.abs(vel_runner.last_action).max() <= 10.0
    assert np.abs(unclipped).max() > 10.0  # the clip actually engaged


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------


def test_tilt_triggers_return_to_standing():
    robot, mimic_runner, vel_runner = _components()
    session = _session(robot, mimic_runner, vel_runner, cmd=[1.0, 0, 0, 0, 0, 0])
    session.request_mode(VelocityMode.VELOCITY)
    session.run(num_steps=2)
    assert session.mode == VelocityMode.VELOCITY
    robot.tilted = True  # quat now 90 deg off vertical -> tilt = pi/2 > 1.0
    session.run(num_steps=1)
    assert session.mode == VelocityMode.STANDING


def test_joint_vel_overflow_stops():
    robot, mimic_runner, vel_runner = _components()

    class _FastRobot(_StubRobot):
        def get_state(self):
            st = super().get_state()
            return dataclasses.replace(st, qvel=np.full(29, 20.0))

    fast = _FastRobot()
    mimic_runner.robot = fast
    vel_runner.robot = fast
    session = _session(fast, mimic_runner, vel_runner, cmd=[1.0, 0, 0, 0, 0, 0])
    session.request_mode(VelocityMode.VELOCITY)
    summary = session.run(num_steps=1)
    assert session.mode == VelocityMode.STOP
    assert summary["steps"] == 0  # safety fires before the step body
    assert summary["mode_switches"] == 2  # STANDING->VELOCITY, VELOCITY->STOP


def test_velocity_below_thresholds_keeps_running():
    robot, mimic_runner, vel_runner = _components()
    session = _session(robot, mimic_runner, vel_runner, cmd=[1.0, 0, 0, 0, 0, 0])
    session.request_mode(VelocityMode.VELOCITY)
    session.run(num_steps=5)
    assert session.mode == VelocityMode.VELOCITY
    assert robot.steps == 5


# ---------------------------------------------------------------------------
# Request semantics
# ---------------------------------------------------------------------------


def test_request_current_mode_is_noop():
    robot, mimic_runner, vel_runner = _components()
    session = _session(robot, mimic_runner, vel_runner)
    session.request_mode(VelocityMode.STANDING)  # already standing
    summary = session.run(num_steps=2)
    assert session.mode == VelocityMode.STANDING
    assert summary["mode_switches"] == 0
    assert mimic_runner.controller.reset_called == 0
    assert mimic_runner.obs_builder.reset_called == 0

    session.request_mode(VelocityMode.VELOCITY)
    session.request_mode(VelocityMode.VELOCITY)  # duplicate request collapses
    summary = session.run(num_steps=1)
    assert summary["mode_switches"] == 1
    assert vel_runner.controller.reset_called == 1
    assert vel_runner.obs_builder.reset_called == 1


# ---------------------------------------------------------------------------
# VELOCITY -> STANDING transition
# ---------------------------------------------------------------------------


def test_transition_to_standing_resets_mimic_and_keeps_last_action():
    robot, mimic_runner, vel_runner = _components()
    session = _session(robot, mimic_runner, vel_runner)
    session.run(num_steps=2)  # standing warm-up
    mimic_seed = np.full(29, 0.7, dtype=np.float32)
    mimic_runner.last_action = mimic_seed.copy()

    session.request_mode(VelocityMode.VELOCITY)
    session.run(num_steps=1)
    assert session.mode == VelocityMode.VELOCITY

    session.request_mode(VelocityMode.STANDING)
    summary = session.run(num_steps=1)
    assert session.mode == VelocityMode.STANDING
    assert summary["mode_switches"] == 2
    # Mimic controller + obs builder reset on entry:
    assert mimic_runner.controller.reset_called >= 1
    assert mimic_runner.obs_builder.reset_called >= 1
    # ...but the velocity stack is untouched by the STANDING transition:
    assert vel_runner.controller.reset_called == 1
    assert vel_runner.obs_builder.reset_called == 1
    # mimic last_action kept: first standing obs consumed the pre-transition seed.
    np.testing.assert_allclose(mimic_runner.obs_builder.builds[-1][1], mimic_seed)


def test_standing_transition_interpolates_then_holds_pose_b():
    robot, mimic_runner, vel_runner = _components()
    cfg = _cfg(transition_duration_s=0.04)  # 2 steps at 50 Hz
    session = _session(robot, mimic_runner, vel_runner, cfg=cfg)
    session.request_mode(VelocityMode.VELOCITY)
    session.run(num_steps=1)
    session.request_mode(VelocityMode.STANDING)
    session.run(num_steps=3)
    prepared = mimic_runner.prepared_qpos  # exactly the 3 standing preps
    assert len(prepared) == 3
    # Step 1 (t=0): reference == currently held pose -> no jump at the switch.
    np.testing.assert_allclose(prepared[0][7:], np.zeros(29), atol=1e-9)
    np.testing.assert_allclose(prepared[0][2], 0.75, atol=1e-9)
    # Step 3 (t=0.04 >= duration): ramp finished at pose B, interpolator cleared.
    np.testing.assert_allclose(prepared[2][7:], POSE_B, atol=1e-9)
    np.testing.assert_allclose(prepared[2][2], 0.76, atol=1e-9)
    assert session._interpolator is None


def test_standing_transition_arms_yaw_aligning_interpolator():
    """Transition arming must preserve the robot's heading (from_hold), not ramp
    yaw back to world 0 (raw ctor). Mirrors
    test_reference_interpolation.py::test_from_hold_aligns_target_yaw."""
    robot, mimic_runner, vel_runner = _components()

    class _YawedRobot(_StubRobot):
        def get_state(self):
            st = super().get_state()
            half = np.pi / 4.0  # yaw pi/2
            quat = np.array([np.cos(half), 0.0, 0.0, np.sin(half)], dtype=np.float64)
            return dataclasses.replace(st, quat=quat)

    yawed = _YawedRobot()
    mimic_runner.robot = yawed
    vel_runner.robot = yawed
    session = _session(yawed, mimic_runner, vel_runner)
    session.request_mode(VelocityMode.VELOCITY)
    session._apply_pending_mode(yawed.get_state())
    interpolator = session._interpolator
    assert interpolator is not None
    end = interpolator.sample(session._transition_duration_s)
    q = np.asarray(end[3:7], dtype=np.float64)
    yaw = 2.0 * np.arctan2(q[3], q[0])
    assert abs(yaw - np.pi / 2) < 1e-6


# ---------------------------------------------------------------------------
# Keyboard
# ---------------------------------------------------------------------------


def test_keyboard_switches_modes_and_esc_stops_infinite_run():
    robot, mimic_runner, vel_runner = _components()
    keyboard = _ScriptedKeyboard([["v"], ["b"], ["\x1b"]])
    console = _RecordingConsole()
    session = _session(
        robot, mimic_runner, vel_runner, cmd=[1.0, 0, 0, 0, 0, 0],
        console=console, keyboard=keyboard,
    )
    summary = session.run(num_steps=0)  # 0 = run until STOP
    assert session.mode == VelocityMode.STOP
    assert summary["steps"] == 3
    assert len(mimic_runner.obs_builder.builds) == 2  # steps 1 and 3
    assert len(vel_runner.obs_builder.prev_actions) == 1  # step 2
    assert console.events == [
        ("V", "velocity", "VELOCITY"),
        ("B", "standing", "STANDING"),
        ("Esc", "stop", "STOP"),
    ]


def test_keyboard_none_runs_velocity_with_provider_cmds():
    robot, mimic_runner, vel_runner = _components()
    session = _session(robot, mimic_runner, vel_runner, cmd=[1.0, 0, 0, 0, 0, 0])
    session.request_mode(VelocityMode.VELOCITY)
    session.run(num_steps=2)  # headless: no keyboard, provider cmds flow
    np.testing.assert_allclose(vel_runner.obs_builder.cmds[0][:3], [1.0, 0.0, 0.0])


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def test_max_target_jump_recorded_across_mode_switch():
    robot, mimic_runner, vel_runner = _components(mimic_neutral=0.1, velocity_neutral=-0.2)
    session = _session(robot, mimic_runner, vel_runner)
    session.run(num_steps=1)  # standing target = 0.1
    session.request_mode(VelocityMode.VELOCITY)
    summary = session.run(num_steps=1)  # velocity target = -0.2
    np.testing.assert_allclose(summary["max_target_jump_rad"], 0.3, atol=1e-6)


def test_cmd_tracking_error_metric():
    robot, mimic_runner, vel_runner = _components()
    session = _session(robot, mimic_runner, vel_runner, cmd=[1.5, 0, 0, 0, 0, 0])
    session.request_mode(VelocityMode.VELOCITY)
    summary = session.run(num_steps=2)
    # actual base_lin_vel_b[:2] = [1, 0], cmd[:2] = [1.5, 0] -> |err| = 0.5
    np.testing.assert_allclose(summary["cmd_track_err_mps"], 0.5, atol=1e-6)
