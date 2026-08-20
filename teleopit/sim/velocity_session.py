"""STANDING(mimic)↔VELOCITY(twist) simulation session.

Deliberately separate from SimLoopSession: no mocap input stack, no reference
windows. Reuses PolicyStepRunner primitives for PD control and mirrors the
real-robot mode machine (STANDING ⇄ VELOCITY ⇄ STOP) so sim results transfer
to Phase B/C hardware runs.
"""
from __future__ import annotations

import logging
import time
from enum import Enum
from typing import Any

import mujoco
import numpy as np

from teleopit.commands.base import CommandProvider
from teleopit.constants import FULL_QPOS_DIM, ROOT_DIM
from teleopit.controllers import reference_processing as ref_proc
from teleopit.runtime.common import cfg_get
from teleopit.sim.reference_interpolation import StandingReferenceInterpolator
from teleopit.sim.runtime_components import PolicyStepRunner

logger = logging.getLogger(__name__)

_STOP_KEY_NAMES = ("\x1b", "\x03")  # Esc, Ctrl-C


class VelocityMode(Enum):
    STANDING = "standing"
    VELOCITY = "velocity"
    STOP = "stop"


class VelocitySimSession:
    """Mode machine driving two :class:`PolicyStepRunner` stacks over one robot.

    The session owns only orchestration: mode transitions, safety checks,
    keyboard handling, and per-run metrics. Both runners (mimic standing,
    twist velocity) are constructed by the entry script and injected here.
    """

    def __init__(
        self,
        *,
        robot: Any,
        mimic_runner: PolicyStepRunner,
        velocity_runner: PolicyStepRunner,
        command_provider: CommandProvider,
        cfg: Any,
        console: Any = None,
        keyboard: Any = None,
    ) -> None:
        self._robot = robot
        self._mimic_runner = mimic_runner
        self._velocity_runner = velocity_runner
        self._cmd = command_provider
        self._cfg = cfg
        self._console = console
        self._keyboard = keyboard

        self._policy_hz = float(cfg_get(cfg, "policy_hz", 50.0))
        modes_cfg = cfg_get(cfg, "modes", {}) or {}
        safety_cfg = cfg_get(cfg, "safety", {}) or {}
        self._transition_duration_s = float(cfg_get(modes_cfg, "transition_duration_s", 1.0))
        self._joint_vel_limit = float(cfg_get(safety_cfg, "joint_vel_limit", 10.0))
        self._tilt_threshold_rad = float(cfg_get(safety_cfg, "tilt_threshold_rad", 1.0))
        self._realtime = bool(cfg_get(cfg, "realtime", False))

        # Debug perturbation (key T): lateral pelvis impulse, the substitute
        # for MuJoCo viewer ctrl-drag which cannot reach this process.
        perturb_cfg = cfg_get(cfg, "perturb", {}) or {}
        self._perturb_force_n = float(cfg_get(perturb_cfg, "force_n", 220.0))
        self._perturb_burst_steps = int(cfg_get(perturb_cfg, "burst_policy_steps", 5))
        self._perturb_body_name = str(cfg_get(perturb_cfg, "body_name", "pelvis"))
        self._perturb_steps_remaining = 0

        self._pose_b = np.asarray(cfg_get(cfg, "pose_b"), dtype=np.float64).reshape(-1)
        self._pose_b_qpos = self._standing_qpos_of_pose(self._pose_b)
        # Standing reference actually held by the STANDING step. Starts at the
        # identity-yaw pose B; each VELOCITY->STANDING transition replaces it
        # with the yaw-aligned endpoint of the hand-off interpolator, so the
        # reference never snaps the robot's heading back to world yaw 0 after
        # the robot walked and turned.
        self._standing_ref_qpos: np.ndarray = self._pose_b_qpos.copy()

        self.mode = VelocityMode.STANDING
        self._pending_mode: VelocityMode | None = None
        self._interpolator: StandingReferenceInterpolator | None = None
        self._steps_in_mode = 0

        # Metrics. Mode switches, target jump, and cmd tracking accumulate over
        # the session's lifetime (across run() calls); only `steps` is per-run.
        self._steps_done = 0
        self._max_target_jump = 0.0
        self._cmd_errs: list[float] = []
        self._min_root_height = float("inf")
        self._mode_switches = 0
        self._prev_target: np.ndarray | None = None

    # ------------------------------------------------------------------
    # Public control
    # ------------------------------------------------------------------

    def request_mode(self, mode: VelocityMode) -> None:
        """Queue a mode change. STOP always applies; a request for the current
        mode is a no-op."""
        if mode == VelocityMode.STOP or mode != self.mode:
            self._pending_mode = mode

    # ------------------------------------------------------------------
    # Standing qpos helpers (pose B)
    # ------------------------------------------------------------------

    def _standing_qpos_of_pose(self, joint_pose: np.ndarray) -> np.ndarray:
        qpos = np.zeros(FULL_QPOS_DIM, dtype=np.float64)
        qpos[2] = 0.76  # matches mujoco_default_qpos root height
        qpos[3] = 1.0
        qpos[ROOT_DIM:FULL_QPOS_DIM] = joint_pose[: FULL_QPOS_DIM - ROOT_DIM]
        return qpos

    def _current_hold_qpos(self, state: Any) -> np.ndarray:
        qpos = np.zeros(FULL_QPOS_DIM, dtype=np.float64)
        base_pos = getattr(state, "base_pos", None)
        if base_pos is not None:
            qpos[0:3] = np.asarray(base_pos, dtype=np.float64)[:3]
        qpos[3:7] = np.asarray(getattr(state, "quat"), dtype=np.float64)[:4]
        qpos[ROOT_DIM:FULL_QPOS_DIM] = np.asarray(getattr(state, "qpos"), dtype=np.float64)[
            : FULL_QPOS_DIM - ROOT_DIM
        ]
        return qpos

    # ------------------------------------------------------------------
    # Transitions
    # ------------------------------------------------------------------

    def _velocity_prev_action_seed(self) -> np.ndarray:
        """Joint-space-equivalent prev_action for the first velocity step.

        The velocity policy decodes ``target = pose_B + vel_scale * action``;
        seeding its prev_action channel with the action whose decoded target is
        the mimic policy's currently commanded target makes the observation
        continuous in joint space across the hand-off:

            seed = (mimic_target_dof_pos - pose_B) / vel_action_scale

        ``mimic_target_dof_pos`` is computed through the mimic runner's own
        decode (its scale, its pose A) so the two decodes never mix. Falls back
        to zeros when the mimic controller exposes no default pose (its
        decode would be identity, which is not the mimic target in joint
        space).
        """
        num = self._velocity_runner.num_actions
        mimic_ctrl = self._mimic_runner.controller
        if getattr(mimic_ctrl, "default_dof_pos", None) is None or np.asarray(
            mimic_ctrl.default_dof_pos
        ).size == 0:
            return np.zeros(num, dtype=np.float32)
        mimic_target = np.asarray(
            self._mimic_runner.compute_target_dof_pos(
                np.asarray(self._mimic_runner.last_action, dtype=np.float32)
            ),
            dtype=np.float64,
        ).reshape(-1)
        vel_scale = np.asarray(
            getattr(self._velocity_runner.controller, "action_scale", None),
            dtype=np.float64,
        ).reshape(-1)
        seed = (mimic_target - self._pose_b) / vel_scale
        return np.clip(seed, -10.0, 10.0).astype(np.float32)

    def _apply_pending_mode(self, state: Any) -> None:
        if self._pending_mode is None:
            return
        target = self._pending_mode
        self._pending_mode = None
        if target == self.mode:
            return
        if target == VelocityMode.STOP:
            self.mode = VelocityMode.STOP
            self._mode_switches += 1
            logger.warning("VELOCITY session -> STOP")
            return

        # Arm the STANDING-side reference interpolator from the currently held
        # pose toward pose-B standing. The twist policy never consumes it; it
        # only keeps the standing reference continuous on hand-off. from_hold
        # yaw-aligns the pose-B target into the robot's current heading, so the
        # ramp does not twist the robot back to world yaw 0.
        hold = self._current_hold_qpos(state)
        self._interpolator = StandingReferenceInterpolator.from_hold(
            hold, self._pose_b_qpos, self._transition_duration_s,
        )
        if target == VelocityMode.VELOCITY:
            # Seed prev_action with the JOINT-SPACE equivalent of the mimic
            # policy's current output, not its raw action: the two policies
            # decode actions with different action_scales and different neutral
            # poses (A vs B), so the same raw value claims a different joint
            # offset under each (Q8/Q9: no artificial jump in the first
            # velocity-step observation).
            self._velocity_runner.last_action = self._velocity_prev_action_seed()
            self._velocity_runner.controller.reset()
            self._velocity_runner.obs_builder.reset()
        else:  # STANDING
            self._mimic_runner.controller.reset()
            self._mimic_runner.obs_builder.reset()
            # last_action deliberately kept — the mimic builder consumes the
            # pre-transition action via the standing prepare path.
        self.mode = target
        self._steps_in_mode = 0
        self._mode_switches += 1
        logger.info("mode -> %s", target.value)

    # ------------------------------------------------------------------
    # Safety (VELOCITY only)
    # ------------------------------------------------------------------

    def _tilt_angle(self, state: Any) -> float:
        from teleopit.controllers.twist_observation import _quat_rotate_inv_np

        quat = np.asarray(state.quat, dtype=np.float32)
        gravity_b = _quat_rotate_inv_np(quat, np.array([0.0, 0.0, -1.0], dtype=np.float32))
        return float(np.arccos(np.clip(-gravity_b[2], -1.0, 1.0)))

    def _check_safety(self, state: Any) -> None:
        if self.mode != VelocityMode.VELOCITY:
            return
        if float(np.max(np.abs(np.asarray(state.qvel, dtype=np.float64)))) > self._joint_vel_limit:
            logger.error(
                "SAFETY: joint velocity over %.1f rad/s -> STOP", self._joint_vel_limit,
            )
            self.request_mode(VelocityMode.STOP)
            return
        if self._tilt_angle(state) > self._tilt_threshold_rad:
            logger.error(
                "SAFETY: tilt over %.2f rad -> STANDING", self._tilt_threshold_rad,
            )
            self.request_mode(VelocityMode.STANDING)

    # ------------------------------------------------------------------
    # Step bodies
    # ------------------------------------------------------------------

    def _standing_step(self) -> None:
        state = self._robot.get_state()
        qpos = self._standing_ref_qpos
        if self._interpolator is not None:
            t_s = self._steps_in_mode * (1.0 / self._policy_hz)
            qpos = self._interpolator.sample(t_s)
            if self._interpolator.finished(t_s):
                # Adopt the interpolator endpoint (pose B yaw-aligned to the
                # hand-off heading) as the standing reference for as long as
                # this STANDING stint lasts — do NOT fall back to the fixed
                # identity-yaw _pose_b_qpos, which would command a 180° turn
                # back to world yaw 0 after a walk.
                self._standing_ref_qpos = np.asarray(qpos, dtype=np.float64).copy()
                self._interpolator = None
                qpos = self._standing_ref_qpos
        prep = self._mimic_runner.prepare_static_motion_command(qpos)
        obs = self._mimic_runner_build_obs(state, prep)
        action = np.asarray(
            self._mimic_runner.controller.compute_action(
                self._mimic_runner.validate_observation_for_policy(obs)
            ),
            dtype=np.float32,
        ).reshape(-1)
        target = self._mimic_runner.compute_target_dof_pos(action)
        self._record_metrics(target, state, cmd=None)
        _, final_state = self._mimic_runner.apply_control(target)
        self._mimic_runner.finish_step(action, np.asarray(prep.qpos, dtype=np.float64))
        self._track_root_height(final_state)

    def _mimic_runner_build_obs(self, state: Any, prep: Any) -> np.ndarray:
        """Standing mimic observation — the exact static-reference path the real
        runtime uses (Sim2RealReferenceProcessor.build_observation with
        reference_window=None)."""
        motion_qpos = np.asarray(
            prep.qpos[: ROOT_DIM + self._mimic_runner.num_actions], dtype=np.float32,
        )
        motion_joint_vel = np.asarray(prep.motion_joint_vel, dtype=np.float32)
        anchor_lin = (
            np.asarray(prep.motion_anchor_lin_vel_w, dtype=np.float32)
            if prep.motion_anchor_lin_vel_w is not None
            else np.zeros(3, dtype=np.float32)
        )
        anchor_ang = (
            np.asarray(prep.motion_anchor_ang_vel_w, dtype=np.float32)
            if prep.motion_anchor_ang_vel_w is not None
            else np.zeros(3, dtype=np.float32)
        )
        return ref_proc.dispatch_build_observation(
            self._mimic_runner.obs_builder,
            state,
            None,
            None,
            motion_qpos,
            motion_joint_vel,
            self._mimic_runner.last_action,
            anchor_lin,
            anchor_ang,
        )

    def _velocity_step(self) -> None:
        self._apply_perturbation()
        state = self._robot.get_state()
        cmd = self._cmd.get_cmd()
        obs = self._velocity_runner.obs_builder.build(
            state, cmd, self._velocity_runner.last_action
        )
        obs = self._velocity_runner.validate_observation_for_policy(obs)
        action = np.asarray(
            self._velocity_runner.controller.compute_action(obs), dtype=np.float32,
        ).reshape(-1)
        target = self._velocity_runner.compute_target_dof_pos(action)
        self._record_metrics(target, state, cmd=cmd)
        _, final_state = self._velocity_runner.apply_control(target)
        self._velocity_runner.finish_step(action, self._pose_b_qpos)
        self._track_root_height(final_state)

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def _record_metrics(self, target: np.ndarray, state: Any, cmd: np.ndarray | None) -> None:
        target = np.asarray(target, dtype=np.float32).reshape(-1)
        if self._prev_target is not None:
            self._max_target_jump = max(
                self._max_target_jump,
                float(np.max(np.abs(target - self._prev_target))),
            )
        self._prev_target = target.copy()
        if cmd is not None and float(np.linalg.norm(np.asarray(cmd)[:3])) > 0.5:
            # RobotState.base_lin_vel is the body-frame base linear velocity.
            actual = getattr(state, "base_lin_vel", None)
            if actual is not None:
                self._cmd_errs.append(
                    float(
                        np.linalg.norm(
                            np.asarray(actual, dtype=np.float64)[:2]
                            - np.asarray(cmd, dtype=np.float64)[:2]
                        )
                    )
                )

    def _track_root_height(self, state: Any) -> None:
        base_pos = getattr(state, "base_pos", None)
        if base_pos is not None:
            self._min_root_height = min(self._min_root_height, float(np.asarray(base_pos)[2]))

    # ------------------------------------------------------------------
    # Keyboard
    # ------------------------------------------------------------------

    def _handle_keyboard(self) -> None:
        if self._keyboard is None:
            return
        for event in self._keyboard.poll():
            key = getattr(event, "key", "")
            if key == "v":
                self.request_mode(VelocityMode.VELOCITY)
                self._key_feedback("V", "velocity", "VELOCITY")
            elif key == "b":
                self.request_mode(VelocityMode.STANDING)
                self._key_feedback("B", "standing", "STANDING")
            elif key == "t":
                self._request_perturbation()
            elif key in _STOP_KEY_NAMES:
                self.request_mode(VelocityMode.STOP)
                self._key_feedback("Esc", "stop", "STOP")

    def _request_perturbation(self) -> None:
        """Queue a lateral impulse for the next velocity step (debug key T).

        The viewer is a separate mirror process, so MuJoCo ctrl-drag
        perturbations never reach this simulation. T injects the same kind
        of push directly: a body-frame +Y force on the pelvis for a short
        burst of physics substeps, exactly the disturbance the tilt safety
        check exists to catch.
        """
        if self.mode != VelocityMode.VELOCITY:
            self._key_feedback("T", "perturb", "ignored (not in VELOCITY)")
            return
        self._perturb_steps_remaining = self._perturb_burst_steps
        self._key_feedback("T", "perturb", f"{self._perturb_force_n}N x {self._perturb_burst_steps} steps")

    def _apply_perturbation(self) -> None:
        """Write the queued impulse into the robot's MuJoCo xfrc_applied slot."""
        if self._perturb_steps_remaining <= 0:
            return
        data = getattr(self._robot, "data", None)
        model = getattr(self._robot, "model", None)
        if data is None or model is None:
            return  # non-MuJoCo robot (tests): impulse silently unavailable
        body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, self._perturb_body_name)
        if body_id < 0:
            return
        # Body-frame +Y push: rotate the body frame into world via xquat.
        quat = np.asarray(data.xquat[body_id], dtype=np.float64)
        force_b = np.array([0.0, self._perturb_force_n, 0.0])
        # w-first quaternion rotation of force_b into world frame.
        w, x, y, z = quat
        t = 2.0 * np.cross([x, y, z], force_b)
        force_w = force_b + w * t + np.cross([x, y, z], t)
        data.xfrc_applied[body_id, 0:3] = force_w
        data.xfrc_applied[body_id, 3:6] = 0.0
        self._perturb_steps_remaining -= 1
        if self._perturb_steps_remaining == 0:
            data.xfrc_applied[body_id, :] = 0.0  # clear on burst end

    def _key_feedback(self, key: str, action: str, result: str) -> None:
        if self._console is not None:
            self._console.key_feedback(key, action, result=result)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self, num_steps: int) -> dict[str, float | int]:
        """Run up to *num_steps* policy steps (0 = until STOP).

        KeyboardInterrupt ends gracefully and still returns the summary.
        """
        max_steps = num_steps if num_steps > 0 else 2**63
        wall_start = time.monotonic() if self._realtime else 0.0
        self._steps_done = 0
        try:
            while self._steps_done < max_steps and self.mode != VelocityMode.STOP:
                state = self._robot.get_state()
                self._apply_pending_mode(state)
                # Safety runs before the step body, only in VELOCITY mode. A
                # trip queues a transition which is applied immediately below,
                # so the flagged step body never executes.
                self._check_safety(state)
                self._apply_pending_mode(state)
                if self.mode == VelocityMode.STOP:
                    break

                if self.mode == VelocityMode.STANDING:
                    self._standing_step()
                else:
                    self._velocity_step()

                self._handle_keyboard()

                # Real-time pacing (wall-clock sleep to policy_dt), mirroring
                # SimLoopSession. Off unless cfg realtime is truthy (tests).
                if self._realtime:
                    sim_time = (self._steps_done + 1) / self._policy_hz
                    sleep_time = sim_time - (time.monotonic() - wall_start)
                    if sleep_time > 0:
                        time.sleep(sleep_time)

                self._steps_in_mode += 1
                self._steps_done += 1
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt — ending velocity session gracefully")
        finally:
            self._cmd.close()
        return {
            "steps": self._steps_done,
            "mode_switches": self._mode_switches,
            "max_target_jump_rad": self._max_target_jump,
            "cmd_track_err_mps": float(np.mean(self._cmd_errs)) if self._cmd_errs else 0.0,
            "min_root_height_m": (
                float(self._min_root_height) if np.isfinite(self._min_root_height) else 0.0
            ),
        }
