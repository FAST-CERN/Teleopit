"""Linear standing-reference interpolation for mode transitions.

STANDING↔VELOCITY hand-off: the reference ramps from the held pose to the
mode's standing pose (pose B) over a configurable duration instead of
step-jumping (which causes the jitter observed on MOCAP→STANDING today).
"""
from __future__ import annotations

import numpy as np

from teleopit.controllers.observation import align_motion_qpos_yaw

ROOT_DIM = 7


class StandingReferenceInterpolator:
    """Linear joint-space ramp with root xy pinned to the start pose."""

    def __init__(self, start_qpos: np.ndarray, target_qpos: np.ndarray, duration_s: float) -> None:
        if duration_s <= 0.0:
            raise ValueError("duration_s must be positive")
        self._start = np.asarray(start_qpos, dtype=np.float64).copy()
        self._target = np.asarray(target_qpos, dtype=np.float64).copy()
        self._duration_s = float(duration_s)

    @classmethod
    def from_hold(
        cls,
        hold_qpos: np.ndarray,
        target_qpos: np.ndarray,
        duration_s: float,
    ) -> StandingReferenceInterpolator:
        target = np.asarray(target_qpos, dtype=np.float64).copy()
        align_motion_qpos_yaw(
            np.asarray(hold_qpos[3:7], dtype=np.float32), target
        )
        return cls(hold_qpos, target, duration_s)

    def sample(self, t_s: float) -> np.ndarray:
        alpha = float(np.clip(t_s / self._duration_s, 0.0, 1.0))
        out = self._start + alpha * (self._target - self._start)
        out[0:2] = self._start[0:2]  # root xy pinned: no translation drift on hand-off
        return out

    def finished(self, t_s: float) -> bool:
        return t_s >= self._duration_s
