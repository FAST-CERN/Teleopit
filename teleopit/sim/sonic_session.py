"""SONIC sim2sim closed-loop session (sonic-wbc t02).

One policy step at 50 Hz: read state -> push history -> encoder obs ->
token -> decoder obs -> action -> q_target (blocked order) -> builtin-PD
position target -> ``decimation`` physics steps at sim_dt 0.005 (the
pd_hz-200 invariant shared with the official SONIC MuJoCo loop and the
local velocity sim). The reference stream advances one frame per policy
step; lookahead beyond its end clamps (hold-tail), matching the C++
streamed-motion merger.

The session owns only the loop and metrics — no mode machine, no estop
(those integrate at ticket 03 acceptance); a pelvis-height fall guard
stops the run early instead.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

from teleopit.policies.sonic.joint_order import from_isaaclab_order
from teleopit.policies.sonic.observation import SonicObsBuilder, SonicReferenceStream, decode_action

logger = logging.getLogger(__name__)

_ARM_MJ = list(range(15, 29))  # blocked-order arm joints for tracking metrics


def _field(state: Any, name: str):
    value = getattr(state, name, None)
    if value is None and isinstance(state, dict):
        value = state.get(name)
    return value


class SonicSimSession:
    """Closed sim2sim loop wiring MuJoCoRobot to the SONIC policy pair."""

    def __init__(
        self,
        *,
        robot: Any,
        policy: Any,
        policy_hz: float = 50.0,
        decimation: int = 4,
        fall_height_m: float = 0.4,
    ) -> None:
        if decimation <= 0:
            raise ValueError("decimation must be positive")
        self._robot = robot
        self._policy = policy
        self._policy_hz = policy_hz
        self._decimation = decimation
        self._fall_height_m = fall_height_m
        self._builder = SonicObsBuilder()
        self._stream: SonicReferenceStream | None = None
        self._last_action_il = np.zeros(29, dtype=np.float64)

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def attach_reference(self, stream: SonicReferenceStream) -> None:
        self._stream = stream

    # ------------------------------------------------------------------
    # Loop
    # ------------------------------------------------------------------

    def _is_fallen(self, state: Any) -> bool:
        base_pos = _field(state, "base_pos")
        if base_pos is None:
            return False
        return float(np.asarray(base_pos).reshape(-1)[2]) < self._fall_height_m

    def run(self, num_steps: int) -> dict[str, float | int | bool]:
        """Run up to *num_steps* policy steps; stop early on the fall guard."""
        if self._stream is None:
            raise RuntimeError("no reference stream attached — call attach_reference() first")

        arm_errors: list[np.ndarray] = []
        min_root_height = float("inf")
        max_abs_action = 0.0
        steps_done = 0
        fell = False

        for _ in range(num_steps):
            state = self._robot.get_state()
            if self._is_fallen(state):
                fell = True
                logger.warning("SONIC sim2sim fall guard tripped at step %d", steps_done)
                break

            ref_arm_mj = from_isaaclab_order(
                self._stream.lookahead(1, step=1).joint_pos[0]
            )[_ARM_MJ]

            self._builder.push_history(state, self._last_action_il)
            encoder_obs = self._builder.build_encoder_obs(
                base_quat_wxyz=np.asarray(state.quat, dtype=np.float64).reshape(4),
                stream=self._stream,
            )
            token = self._policy.encode(encoder_obs)
            decoder_obs = self._builder.build_decoder_obs(token)
            action_il = np.asarray(self._policy.decode(decoder_obs), dtype=np.float64).reshape(-1)

            q_target_mj = decode_action(action_il)
            self._robot.set_position_target(q_target_mj)
            for _ in range(self._decimation):
                self._robot.step()

            self._last_action_il = action_il.copy()
            self._stream.advance()
            steps_done += 1

            state_after = self._robot.get_state()
            base_pos_after = _field(state_after, "base_pos")
            if base_pos_after is not None:
                min_root_height = min(min_root_height, float(np.asarray(base_pos_after).reshape(-1)[2]))
            arm_errors.append(np.asarray(state_after.qpos, dtype=np.float64)[_ARM_MJ] - ref_arm_mj)
            max_abs_action = max(max_abs_action, float(np.max(np.abs(action_il))))

        if arm_errors:
            errors = np.stack(arm_errors)
            upper_rmse = float(np.sqrt(np.mean(errors**2)))
            upper_max = float(np.max(np.abs(errors)))
        else:
            upper_rmse = upper_max = 0.0

        return {
            "steps": steps_done,
            "fell": fell,
            "min_root_height_m": min_root_height if np.isfinite(min_root_height) else 0.0,
            "upper_track_rmse_rad": upper_rmse,
            "upper_track_max_rad": upper_max,
            "max_abs_action": max_abs_action,
        }
