# tests/test_sim2real_velocity_safety.py
"""bsi-realhw-05 真机阈值：joint-vel 10.0 / tilt 30° 优雅 / 45° damping。"""
from __future__ import annotations

import logging
from types import SimpleNamespace

import numpy as np
import pytest

from teleopit.sim2real.safety import velocity_safety_verdict

LIMITS = dict(joint_vel_limit=10.0, tilt_graceful_rad=0.524, tilt_damping_rad=0.785)


def _state(*, tilt_deg: float = 0.0, qvel_fill: float = 0.0) -> SimpleNamespace:
    theta = np.deg2rad(tilt_deg)
    return _state_rad(tilt_rad=float(theta), qvel=np.full(29, qvel_fill, dtype=np.float32))


def _state_rad(*, tilt_rad: float = 0.0, qvel: np.ndarray | None = None) -> SimpleNamespace:
    quat = np.array(
        [np.cos(tilt_rad / 2.0), np.sin(tilt_rad / 2.0), 0.0, 0.0], dtype=np.float32
    )
    return SimpleNamespace(
        qpos=np.zeros(29, dtype=np.float32),
        qvel=np.zeros(29, dtype=np.float32) if qvel is None else qvel,
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


# ── per-joint limit array (bsi-realhw-05 deliverable before L3) ──────────────


def test_per_joint_array_catches_slow_joint_overspeed() -> None:
    qvel = np.zeros(29, dtype=np.float32)
    qvel[7] = 5.0  # under the 10.0 scalar, over joint 7's own 4.0 line
    limits = [10.0] * 29
    limits[7] = 4.0
    verdict = velocity_safety_verdict(
        _state_rad(qvel=qvel),
        joint_vel_limit=limits,
        tilt_graceful_rad=0.524,
        tilt_damping_rad=0.785,
    )
    assert verdict == "damping"


def test_per_joint_uniform_array_matches_scalar() -> None:
    limits = [10.0] * 29
    assert (
        velocity_safety_verdict(_state(qvel_fill=3.0), joint_vel_limit=limits,
                                tilt_graceful_rad=0.524, tilt_damping_rad=0.785)
        is None
    )
    assert (
        velocity_safety_verdict(_state(qvel_fill=11.0), joint_vel_limit=limits,
                                tilt_graceful_rad=0.524, tilt_damping_rad=0.785)
        == "damping"
    )


def test_numpy_array_limits_accepted() -> None:
    limits = np.full(29, 10.0, dtype=np.float64)
    limits[3] = 2.0
    qvel = np.zeros(29, dtype=np.float32)
    qvel[3] = 2.5
    assert (
        velocity_safety_verdict(_state_rad(qvel=qvel), joint_vel_limit=limits,
                                tilt_graceful_rad=0.524, tilt_damping_rad=0.785)
        == "damping"
    )


def test_wrong_length_limits_raise() -> None:
    with pytest.raises(ValueError):
        velocity_safety_verdict(
            _state(qvel_fill=0.0), joint_vel_limit=[10.0] * 5,
            tilt_graceful_rad=0.524, tilt_damping_rad=0.785,
        )


# ── threshold boundary pins (strict >, ticket 05 deferred item) ──────────────


def test_joint_vel_exactly_at_limit_is_clean() -> None:
    assert velocity_safety_verdict(_state(qvel_fill=10.0), **LIMITS) is None


def test_joint_vel_epsilon_over_limit_demands_damping() -> None:
    assert velocity_safety_verdict(_state(qvel_fill=10.0 + 1e-4), **LIMITS) == "damping"


def test_tilt_just_under_graceful_line_is_clean() -> None:
    # epsilon below (not exact: float32 quat roundtrip makes exact-equality pins flaky)
    assert velocity_safety_verdict(_state_rad(tilt_rad=0.524 - 1e-3), **LIMITS) is None


def test_tilt_epsilon_over_graceful_demands_standing() -> None:
    assert velocity_safety_verdict(_state_rad(tilt_rad=0.524 + 1e-3), **LIMITS) == "standing"


def test_tilt_just_under_damping_line_still_graceful() -> None:
    """Pins strict >: below 0.785 is NOT damping, it falls through to standing."""
    assert velocity_safety_verdict(_state_rad(tilt_rad=0.785 - 1e-3), **LIMITS) == "standing"


def test_tilt_epsilon_over_damping_demands_damping() -> None:
    assert velocity_safety_verdict(_state_rad(tilt_rad=0.785 + 1e-3), **LIMITS) == "damping"


# ── log severity: ERROR reserved for damping-class, graceful band is WARNING ──


def test_graceful_tilt_logs_warning_not_error(caplog) -> None:
    with caplog.at_level(logging.DEBUG, logger="teleopit.sim2real.safety"):
        assert velocity_safety_verdict(_state(tilt_deg=35.0), **LIMITS) == "standing"
    safety_records = [r for r in caplog.records if r.message.startswith("SAFETY:")]
    assert safety_records, "graceful verdict must log"
    assert all(r.levelno == logging.WARNING for r in safety_records)


def test_damping_verdicts_log_error(caplog) -> None:
    with caplog.at_level(logging.DEBUG, logger="teleopit.sim2real.safety"):
        velocity_safety_verdict(_state(qvel_fill=11.0), **LIMITS)
        velocity_safety_verdict(_state(tilt_deg=50.0), **LIMITS)
    assert any(r.levelno == logging.ERROR for r in caplog.records)
