"""98D twist-command observation builder for the Unitree velocity policy.

Layout (deploy.yaml term order, 3+3+3+2+29+29+29 = 98):
  [ 0: 3] base_ang_vel          (body frame, RobotState.ang_vel)
  [ 3: 6] projected_gravity     (body frame)
  [ 6: 9] velocity_commands     (clamped lin_x/lin_y/ang_z)
  [ 9:11] gait_phase            (sin/cos of phase clock; zeroed below cmd norm threshold)
  [11:40] joint_pos_rel         (qpos - pose B)
  [40:69] joint_vel_rel
  [69:98] last_action
"""
from __future__ import annotations

import logging
import math
from typing import final

import numpy as np

from teleopit.interfaces import RobotState
from teleopit.runtime.common import cfg_get

_logger = logging.getLogger(__name__)

FloatVec = np.ndarray[tuple[int, ...], np.dtype[np.float32]]
ConfigType = dict[str, object] | object
_GRAVITY_UNIT_W = np.array([0.0, 0.0, -1.0], dtype=np.float32)
_CMD_DIM = 6


def _quat_rotate_inv_np(q: FloatVec, v: FloatVec) -> FloatVec:
    """Rotate v by the inverse of unit quaternion q (wxyz). Pure numpy."""
    w, x, y, z = float(q[0]), float(q[1]), float(q[2]), float(q[3])
    # v' = q* ⊗ v ⊗ q  expanded (rotation by conjugate)
    tx = 2.0 * (y * v[2] - z * v[1])
    ty = 2.0 * (z * v[0] - x * v[2])
    tz = 2.0 * (x * v[1] - y * v[0])
    return np.asarray(
        [
            v[0] - w * tx + (y * tz - z * ty),
            v[1] - w * ty + (z * tx - x * tz),
            v[2] - w * tz + (x * ty - y * tx),
        ],
        dtype=np.float32,
    )


@final
class TwistCmdObservationBuilder:
    """Stateful 98D observation builder for the velocity_v1 ONNX policy."""

    def __init__(self, cfg: ConfigType) -> None:
        self.num_actions: int = int(cfg_get(cfg, "num_actions"))
        self.default_dof_pos: FloatVec = np.asarray(
            cfg_get(cfg, "default_dof_pos"), dtype=np.float32
        ).reshape(-1)
        if self.default_dof_pos.shape[0] != self.num_actions:
            raise ValueError("default_dof_pos length must match num_actions")

        limits = cfg_get(cfg, "cmd_limits")
        self._cmd_lo = np.array(
            [
                float(cfg_get(limits, "lin_vel_x")[0]),
                float(cfg_get(limits, "lin_vel_y")[0]),
                float(cfg_get(limits, "ang_vel_z")[0]),
            ],
            dtype=np.float32,
        )
        self._cmd_hi = np.array(
            [
                float(cfg_get(limits, "lin_vel_x")[1]),
                float(cfg_get(limits, "lin_vel_y")[1]),
                float(cfg_get(limits, "ang_vel_z")[1]),
            ],
            dtype=np.float32,
        )

        self._gait_period_s = float(cfg_get(cfg, "gait_period_s", 0.6))
        if self._gait_period_s <= 0.0:
            raise ValueError("gait_period_s must be positive")
        self._gait_zero_cmd_norm = float(cfg_get(cfg, "gait_zero_cmd_norm", 0.1))
        self._policy_dt = float(cfg_get(cfg, "policy_dt", 0.02))
        if self._policy_dt <= 0.0:
            raise ValueError("policy_dt must be positive")

        self._gait_phase: float = 0.0
        self.total_obs_size = 3 + 3 + 3 + 2 + self.num_actions * 3
        if self.num_actions != 29:
            raise ValueError(
                f"TwistCmdObservationBuilder expects 29 joints (velocity_v1 policy), got {self.num_actions}"
            )

    def reset(self) -> None:
        self._gait_phase = 0.0

    def _advance_gait(self, cmd3: FloatVec) -> FloatVec:
        self._gait_phase = math.fmod(
            self._gait_phase + self._policy_dt / self._gait_period_s, 1.0
        )
        if float(np.linalg.norm(cmd3)) < self._gait_zero_cmd_norm:
            return np.zeros(2, dtype=np.float32)
        angle = 2.0 * math.pi * self._gait_phase
        return np.array([math.sin(angle), math.cos(angle)], dtype=np.float32)

    def build(self, state: RobotState, cmd: FloatVec, last_action: FloatVec) -> FloatVec:
        cmd_vec = np.asarray(cmd, dtype=np.float32).reshape(-1)
        if cmd_vec.shape[0] != _CMD_DIM:
            raise ValueError(f"cmd must be 6D twist, got {cmd_vec.shape[0]}")
        prev_action = np.asarray(last_action, dtype=np.float32).reshape(-1)
        if prev_action.shape[0] != self.num_actions:
            raise ValueError(f"last_action must be {self.num_actions}D, got {prev_action.shape[0]}")

        qpos = np.asarray(state.qpos, dtype=np.float32).reshape(-1)[: self.num_actions]
        qvel = np.asarray(state.qvel, dtype=np.float32).reshape(-1)[: self.num_actions]
        quat = np.asarray(state.quat, dtype=np.float32).reshape(-1)
        if quat.shape[0] != 4:
            raise ValueError(f"state.quat must be 4D (wxyz), got {quat.shape[0]}")
        ang_vel_b = np.asarray(state.ang_vel, dtype=np.float32).reshape(-1)
        if ang_vel_b.shape[0] != 3:
            raise ValueError(f"state.ang_vel must be 3D, got {ang_vel_b.shape[0]}")

        cmd3 = np.clip(cmd_vec[:3] * np.array([1.0, 1.0, 1.0], dtype=np.float32), self._cmd_lo, self._cmd_hi).astype(np.float32)
        gait = self._advance_gait(cmd3)
        projected_gravity_b = _quat_rotate_inv_np(quat, _GRAVITY_UNIT_W)
        joint_pos_rel = qpos - self.default_dof_pos

        obs = np.concatenate(
            [ang_vel_b, projected_gravity_b, cmd3, gait, joint_pos_rel, qvel, prev_action],
            dtype=np.float32,
        )
        if obs.shape[0] != self.total_obs_size:
            raise ValueError(f"Expected {self.total_obs_size}D observation, got {obs.shape[0]}")
        if not np.all(np.isfinite(obs)):
            bad = np.where(~np.isfinite(obs))[0]
            _logger.warning("NaN/inf in twist observation at indices %s, replacing with zeros", bad.tolist())
            obs = np.where(np.isfinite(obs), obs, np.float32(0.0))
        return obs
