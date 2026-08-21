"""Safety manager for Sim2Real controller.

Encapsulates KP ramp, joint limits, and velocity safety checks.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from numpy.typing import NDArray

from teleopit.runtime.common import cfg_get
from teleopit.sim2real.unitree_g1 import UnitreeG1Robot

Float32Array = NDArray[np.float32]
logger = logging.getLogger(__name__)


class Sim2RealSafetyManager:
    """KP ramp, joint limits, and velocity safety checks."""

    def __init__(
        self,
        cfg: Any,
        robot: UnitreeG1Robot,
        policy_hz: float,
        num_actions: int,
    ) -> None:
        self._robot = robot
        self._policy_hz = policy_hz
        real_cfg = cfg_get(cfg, "real_robot")

        # Kp ramp gradually increases PD gains after episode-reset.
        startup_ramp_duration = float(cfg_get(cfg, "startup_ramp_duration", 2.0))
        self._default_kp_ramp_duration_steps: int = max(1, int(startup_ramp_duration * policy_hz))
        self._kp_ramp_duration_steps: int = self._default_kp_ramp_duration_steps
        self._kp_ramp_step: int = 0
        self._kp_ramp_active: bool = False
        self._kp_nominal = np.asarray(cfg_get(real_cfg, "kp_real", [100] * num_actions), dtype=np.float32)
        self._kd_nominal = np.asarray(cfg_get(real_cfg, "kd_real", [2] * num_actions), dtype=np.float32)
        self._default_kp_ramp_floor_ratio: float = float(cfg_get(cfg, "kp_ramp_floor_ratio", 0.1))
        self._kp_ramp_floor_ratio: float = self._default_kp_ramp_floor_ratio

        # Joint safety limits
        self._joint_vel_limit: float = float(
            cfg_get(cfg, "joint_vel_limit", cfg_get(real_cfg, "joint_vel_limit", 10.0))
        )
        joint_pos_lower = cfg_get(real_cfg, "joint_pos_lower", None)
        joint_pos_upper = cfg_get(real_cfg, "joint_pos_upper", None)
        if joint_pos_lower is not None and joint_pos_upper is not None:
            self._joint_pos_lower = np.asarray(joint_pos_lower, dtype=np.float32)
            self._joint_pos_upper = np.asarray(joint_pos_upper, dtype=np.float32)
        else:
            self._joint_pos_lower = None
            self._joint_pos_upper = None

    @property
    def kp_ramp_active(self) -> bool:
        return self._kp_ramp_active

    def compute_kp_ramp_gains(self) -> tuple[Float32Array, Float32Array] | None:
        """Return (kp, kd) for current Kp-ramp step, or None if ramp inactive."""
        if not self._kp_ramp_active:
            return None

        factor = min(1.0, self._kp_ramp_step / self._kp_ramp_duration_steps)
        kp = self._kp_nominal * (self._kp_ramp_floor_ratio + (1.0 - self._kp_ramp_floor_ratio) * factor)

        self._kp_ramp_step += 1
        if self._kp_ramp_step >= self._kp_ramp_duration_steps:
            self._kp_ramp_active = False
            logger.info("Kp ramp complete (%d steps)", self._kp_ramp_duration_steps)

        return np.asarray(kp, dtype=np.float32), self._kd_nominal.copy()

    def start_kp_ramp(
        self,
        *,
        duration_s: float | None = None,
        floor_ratio: float | None = None,
    ) -> None:
        """Arm the Kp ramp for gradual PD gain increase."""
        if duration_s is None:
            self._kp_ramp_duration_steps = self._default_kp_ramp_duration_steps
        else:
            self._kp_ramp_duration_steps = max(1, int(float(duration_s) * self._policy_hz))
        if floor_ratio is None:
            self._kp_ramp_floor_ratio = self._default_kp_ramp_floor_ratio
        else:
            self._kp_ramp_floor_ratio = float(floor_ratio)
        self._kp_ramp_step = 0
        self._kp_ramp_active = True
        logger.info(
            "Kp ramp armed: %d steps (%.1fs), floor_ratio=%.2f",
            self._kp_ramp_duration_steps,
            self._kp_ramp_duration_steps / self._policy_hz,
            self._kp_ramp_floor_ratio,
        )

    def send_positions(self, target_dof_pos: Float32Array) -> None:
        """Send position targets, applying Kp ramp gains if active."""
        gains = self.compute_kp_ramp_gains()
        if gains is not None:
            kp, kd = gains
            self._robot.send_positions(target_dof_pos, kp=kp, kd=kd)
        else:
            self._robot.send_positions(target_dof_pos)

    def clip_to_joint_limits(self, target_dof_pos: Float32Array) -> Float32Array:
        """Clip target positions to configured joint limits."""
        if self._joint_pos_lower is not None and self._joint_pos_upper is not None:
            return np.clip(target_dof_pos, self._joint_pos_lower, self._joint_pos_upper)
        return target_dof_pos

    def check_joint_velocity_safety(self) -> bool:
        """Check joint velocities against safety limit. Returns True if violation detected."""
        state = self._robot.get_state()
        max_vel = np.max(np.abs(state.qvel))
        if max_vel > self._joint_vel_limit:
            logger.error(
                "SAFETY: joint velocity %.2f rad/s exceeds limit %.2f",
                max_vel, self._joint_vel_limit,
            )
            return True
        return False


def velocity_safety_verdict(
    state: Any,
    *,
    joint_vel_limit: "float | list[float] | Any",
    tilt_graceful_rad: float,
    tilt_damping_rad: float,
) -> str | None:
    """bsi-realhw-05 envelope check for the real-robot VELOCITY mode.

    Returns "damping" (overspeed or falling: enter DAMPING now), "standing"
    (recoverable tilt: graceful 0.3s-ramp exit to STANDING), or None.
    Checked once per policy step, VELOCITY mode only — same discipline as the
    sim's VelocityStepController.check_safety, with the real dual tilt lines.

    ``joint_vel_limit`` is a scalar OR a per-joint array (length must match
    ``state.qvel``; bsi-realhw-05 per-joint deliverable). All comparisons are
    strict ``>``. Log severity: damping-class breaches log ERROR, the 30-45°
    graceful band logs WARNING so ERROR stays reserved for hard stops.
    """
    import numpy as np

    from teleopit.controllers.twist_observation import _quat_rotate_inv_np

    qvel = np.abs(np.asarray(state.qvel, dtype=np.float64))
    limits = np.asarray(joint_vel_limit, dtype=np.float64).reshape(-1)
    if limits.size == 1:
        over = qvel > limits[0]
    else:
        if limits.size != qvel.size:
            raise ValueError(
                f"joint_vel_limit has {limits.size} entries but state.qvel has {qvel.size}"
            )
        over = qvel > limits
    if bool(np.any(over)):
        idx = int(np.argmax(np.where(over, qvel - np.minimum(limits, qvel), -1.0)))
        max_vel = float(qvel[idx])
        joint_cap = float(limits[0]) if limits.size == 1 else float(limits[idx])
        logger.error(
            "SAFETY: joint %d velocity %.2f rad/s exceeds %.2f -> DAMPING",
            idx, max_vel, joint_cap,
        )
        return "damping"
    quat = np.asarray(state.quat, dtype=np.float32)
    gravity_b = _quat_rotate_inv_np(quat, np.array([0.0, 0.0, -1.0], dtype=np.float32))
    tilt = float(np.arccos(np.clip(-gravity_b[2], -1.0, 1.0)))
    if tilt > float(tilt_damping_rad):
        logger.error("SAFETY: tilt %.2f rad over %.2f -> DAMPING", tilt, tilt_damping_rad)
        return "damping"
    if tilt > float(tilt_graceful_rad):
        logger.warning("SAFETY: tilt %.2f rad over %.2f -> STANDING", tilt, tilt_graceful_rad)
        return "standing"
    return None
