# tests/test_sim2real_velocity_safety.py
"""bsi-realhw-05 真机阈值：joint-vel 10.0 / tilt 30° 优雅 / 45° damping。"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from teleopit.sim2real.safety import velocity_safety_verdict

LIMITS = dict(joint_vel_limit=10.0, tilt_graceful_rad=0.524, tilt_damping_rad=0.785)


def _state(*, tilt_deg: float = 0.0, qvel_fill: float = 0.0) -> SimpleNamespace:
    theta = np.deg2rad(tilt_deg)
    quat = np.array(
        [np.cos(theta / 2.0), np.sin(theta / 2.0), 0.0, 0.0], dtype=np.float32
    )
    return SimpleNamespace(
        qpos=np.zeros(29, dtype=np.float32),
        qvel=np.full(29, qvel_fill, dtype=np.float32),
        quat=quat,
        ang_vel=np.zeros(3, dtype=np.float32),
    )


def test_normal_walking_state_is_clean() -> None:
    assert velocity_safety_verdict(_state(tilt_deg=5.0, qvel_fill=3.0), **LIMITS) is None


def test_joint_vel_over_limit_demands_damping() -> None:
    assert velocity_safety_verdict(_state(qvel_fill=11.0), **LIMITS) == "damping"


def test_tilt_over_graceful_line_demands_standing() -> None:
    assert velocity_safety_verdict(_state(tilt_deg=35.0), **LIMITS) == "standing"


def test_tilt_over_damping_line_demands_damping() -> None:
    assert velocity_safety_verdict(_state(tilt_deg=50.0), **LIMITS) == "damping"


def test_joint_vel_wins_over_tilt_when_both_exceeded() -> None:
    assert (
        velocity_safety_verdict(_state(tilt_deg=50.0, qvel_fill=11.0), **LIMITS)
        == "damping"
    )
