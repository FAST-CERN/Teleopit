from __future__ import annotations

import numpy as np

from teleopit.controllers.observation import align_motion_qpos_yaw
from teleopit.sim.reference_interpolation import StandingReferenceInterpolator


def _qpos(knee: float, yaw: float = 0.0) -> np.ndarray:
    q = np.zeros(36, dtype=np.float64)
    q[2] = 0.76
    half = yaw / 2.0
    q[3:7] = [np.cos(half), 0.0, 0.0, np.sin(half)]
    q[7:] = 0.1
    q[7 + 3] = knee
    return q


def test_midpoint_interpolates_joints_linearly():
    a, b = _qpos(0.0), _qpos(0.6)
    interp = StandingReferenceInterpolator(a, b, duration_s=1.0)
    mid = interp.sample(0.5)
    np.testing.assert_allclose(mid[7 + 3], 0.3, atol=1e-9)


def test_clamps_at_boundaries():
    a, b = _qpos(0.0), _qpos(0.6)
    interp = StandingReferenceInterpolator(a, b, duration_s=1.0)
    np.testing.assert_allclose(interp.sample(-1.0)[7 + 3], 0.0, atol=1e-9)
    np.testing.assert_allclose(interp.sample(2.0)[7 + 3], 0.6, atol=1e-9)
    assert interp.finished(2.0)
    assert not interp.finished(0.5)


def test_root_height_interpolated_xy_held():
    a, b = _qpos(0.0), _qpos(0.6)
    b[0:2] = [5.0, 5.0]  # target xy far away
    interp = StandingReferenceInterpolator(a, b, duration_s=1.0)
    mid = interp.sample(0.5)
    np.testing.assert_allclose(mid[0:2], a[0:2], atol=1e-9)  # xy pinned to start
    np.testing.assert_allclose(mid[2], 0.76, atol=1e-9)


def test_from_hold_aligns_target_yaw():
    hold = _qpos(0.3, yaw=np.pi / 2)
    target = _qpos(0.3, yaw=0.0)
    interp = StandingReferenceInterpolator.from_hold(hold, target, duration_s=1.0)
    end = interp.sample(1.0)
    # target yaw rotated into hold frame → end yaw ≈ hold yaw
    q = end[3:7]
    yaw = 2.0 * np.arctan2(q[3], q[0])
    assert abs(yaw - np.pi / 2) < 1e-6
