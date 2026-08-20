"""Shared step core for the STANDING(mimic)↔VELOCITY(twist) mode machine.

Two entry points drive this core: VelocitySimSession (the dedicated velocity
sim) and the VELOCITY mode of the general sim loop. Both must run the SAME
safety checks, the SAME joint-space prev_action seeding on hand-off, and the
SAME standing-reference interpolation — only orchestration (mode machine,
metrics, keyboard, perturbation) differs per entry point. Keeping the step
bodies here means the two entries cannot drift apart.

The step methods return their byproducts as tuples (cmd/action/target and
final robot state) so each entry point can run its own metrics without
re-deriving them; the core mutates nothing but the runners.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

from teleopit.commands.base import CommandProvider
from teleopit.constants import FULL_QPOS_DIM, ROOT_DIM
from teleopit.controllers import reference_processing as ref_proc
from teleopit.sim.reference_interpolation import StandingReferenceInterpolator
from teleopit.sim.runtime_components import PolicyStepRunner

logger = logging.getLogger(__name__)


class VelocityStepController:
    """Step core shared by every STANDING↔VELOCITY entry point.

    Owns the two step bodies (``velocity_step``/``standing_step``), the
    safety verdicts, and the hand-off seeding/interpolation helpers. It holds
    no mode state: callers decide when to transition and act on the strings
    ``check_safety`` returns.
    """

    def __init__(
        self,
        *,
        velocity_runner: PolicyStepRunner,
        cmd_provider: CommandProvider,
        pose_b: np.ndarray,
        policy_hz: float,
        transition_duration_s: float,
        joint_vel_limit: float,
        tilt_threshold_rad: float,
    ) -> None:
        self.velocity_runner = velocity_runner
        self._cmd = cmd_provider
        self._pose_b = np.asarray(pose_b, dtype=np.float64).reshape(-1)
        self._pose_b_qpos = self.standing_qpos_of_pose(self._pose_b)
        self._policy_hz = float(policy_hz)
        self._transition_duration_s = float(transition_duration_s)
        self._joint_vel_limit = float(joint_vel_limit)
        self._tilt_threshold_rad = float(tilt_threshold_rad)

    # ------------------------------------------------------------------
    # Standing qpos helpers (pose B)
    # ------------------------------------------------------------------

    @property
    def pose_b_qpos(self) -> np.ndarray:
        return self._pose_b_qpos

    def standing_qpos_of_pose(self, joint_pose: np.ndarray) -> np.ndarray:
        qpos = np.zeros(FULL_QPOS_DIM, dtype=np.float64)
        qpos[2] = 0.76  # matches mujoco_default_qpos root height
        qpos[3] = 1.0
        qpos[ROOT_DIM:FULL_QPOS_DIM] = joint_pose[: FULL_QPOS_DIM - ROOT_DIM]
        return qpos

    @staticmethod
    def current_hold_qpos(state: Any) -> np.ndarray:
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

    def arm_standing_interpolator(
        self, hold_qpos: np.ndarray, target_qpos: np.ndarray
    ) -> StandingReferenceInterpolator:
        """from_hold yaw-aligns the pose-B target into the robot's current
        heading, so the ramp does not twist the robot back to world yaw 0."""
        return StandingReferenceInterpolator.from_hold(
            hold_qpos, target_qpos, self._transition_duration_s,
        )

    def velocity_prev_action_seed(self, mimic_runner: PolicyStepRunner) -> np.ndarray:
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
        num = self.velocity_runner.num_actions
        mimic_ctrl = mimic_runner.controller
        if getattr(mimic_ctrl, "default_dof_pos", None) is None or np.asarray(
            mimic_ctrl.default_dof_pos
        ).size == 0:
            return np.zeros(num, dtype=np.float32)
        mimic_target = np.asarray(
            mimic_runner.compute_target_dof_pos(
                np.asarray(mimic_runner.last_action, dtype=np.float32)
            ),
            dtype=np.float64,
        ).reshape(-1)
        vel_scale = np.asarray(
            getattr(self.velocity_runner.controller, "action_scale", None),
            dtype=np.float64,
        ).reshape(-1)
        seed = (mimic_target - self._pose_b) / vel_scale
        return np.clip(seed, -10.0, 10.0).astype(np.float32)

    def begin_velocity_handoff(self, mimic_runner: PolicyStepRunner, hold_qpos: np.ndarray) -> None:
        """Enter VELOCITY: seed prev_action with the JOINT-SPACE equivalent of
        the mimic policy's current output, not its raw action: the two policies
        decode actions with different action_scales and different neutral
        poses (A vs B), so the same raw value claims a different joint
        offset under each (Q8/Q9: no artificial jump in the first
        velocity-step observation). Then reset the velocity stack."""
        self.velocity_runner.last_action = self.velocity_prev_action_seed(mimic_runner)
        self.velocity_runner.controller.reset()
        self.velocity_runner.obs_builder.reset()

    # ------------------------------------------------------------------
    # Safety (VELOCITY only)
    # ------------------------------------------------------------------

    @staticmethod
    def tilt_angle(state: Any) -> float:
        from teleopit.controllers.twist_observation import _quat_rotate_inv_np

        quat = np.asarray(state.quat, dtype=np.float32)
        gravity_b = _quat_rotate_inv_np(quat, np.array([0.0, 0.0, -1.0], dtype=np.float32))
        return float(np.arccos(np.clip(-gravity_b[2], -1.0, 1.0)))

    def check_safety(self, state: Any) -> str | None:
        """Verdict only — the caller owns the mode machine and acts on the
        returned string (``"stop"``/``"standing"``/``None``)."""
        if float(np.max(np.abs(np.asarray(state.qvel, dtype=np.float64)))) > self._joint_vel_limit:
            logger.error(
                "SAFETY: joint velocity over %.1f rad/s -> STOP", self._joint_vel_limit,
            )
            return "stop"
        if self.tilt_angle(state) > self._tilt_threshold_rad:
            logger.error(
                "SAFETY: tilt over %.2f rad -> STANDING", self._tilt_threshold_rad,
            )
            return "standing"
        return None

    # ------------------------------------------------------------------
    # Step bodies
    # ------------------------------------------------------------------

    def standing_step(
        self,
        robot: Any,
        mimic_runner: PolicyStepRunner,
        standing_ref_qpos: np.ndarray,
        interpolator: StandingReferenceInterpolator | None,
        steps_in_mode: int,
    ) -> tuple[np.ndarray, StandingReferenceInterpolator | None, np.ndarray, Any]:
        """One STANDING step. Returns the possibly-updated standing reference
        (interpolator endpoint adopted when the ramp finishes), the possibly
        cleared interpolator, and the step's target/final state for caller-side
        metrics."""
        state = robot.get_state()
        qpos = standing_ref_qpos
        if interpolator is not None:
            t_s = steps_in_mode * (1.0 / self._policy_hz)
            qpos = interpolator.sample(t_s)
            if interpolator.finished(t_s):
                # Adopt the interpolator endpoint (pose B yaw-aligned to the
                # hand-off heading) as the standing reference for as long as
                # this STANDING stint lasts — do NOT fall back to the fixed
                # identity-yaw _pose_b_qpos, which would command a 180° turn
                # back to world yaw 0 after a walk.
                standing_ref_qpos = np.asarray(qpos, dtype=np.float64).copy()
                interpolator = None
                qpos = standing_ref_qpos
        prep = mimic_runner.prepare_static_motion_command(qpos)
        obs = self._mimic_runner_build_obs(mimic_runner, state, prep)
        action = np.asarray(
            mimic_runner.controller.compute_action(
                mimic_runner.validate_observation_for_policy(obs)
            ),
            dtype=np.float32,
        ).reshape(-1)
        target = mimic_runner.compute_target_dof_pos(action)
        _, final_state = mimic_runner.apply_control(target)
        mimic_runner.finish_step(action, np.asarray(prep.qpos, dtype=np.float64))
        return standing_ref_qpos, interpolator, target, final_state

    def _mimic_runner_build_obs(self, mimic_runner: PolicyStepRunner, state: Any, prep: Any) -> np.ndarray:
        """Standing mimic observation — the exact static-reference path the real
        runtime uses (Sim2RealReferenceProcessor.build_observation with
        reference_window=None)."""
        motion_qpos = np.asarray(
            prep.qpos[: ROOT_DIM + mimic_runner.num_actions], dtype=np.float32,
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
            mimic_runner.obs_builder,
            state,
            None,
            None,
            motion_qpos,
            motion_joint_vel,
            mimic_runner.last_action,
            anchor_lin,
            anchor_ang,
        )

    def velocity_step(self, robot: Any) -> tuple[np.ndarray, np.ndarray, np.ndarray, Any]:
        """One VELOCITY step. Returns (cmd, action, target, final_state) for
        caller-side metrics and perturbation handling."""
        state = robot.get_state()
        cmd = self._cmd.get_cmd()
        obs = self.velocity_runner.obs_builder.build(
            state, cmd, self.velocity_runner.last_action
        )
        obs = self.velocity_runner.validate_observation_for_policy(obs)
        action = np.asarray(
            self.velocity_runner.controller.compute_action(obs), dtype=np.float32,
        ).reshape(-1)
        target = self.velocity_runner.compute_target_dof_pos(action)
        _, final_state = self.velocity_runner.apply_control(target)
        self.velocity_runner.finish_step(action, self._pose_b_qpos)
        return cmd, action, target, final_state
