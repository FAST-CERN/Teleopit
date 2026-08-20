"""Pico joystick twist source: controller sticks -> 6D body-frame twist.

Left stick = translation (Y -> lin_x push-forward, X -> lin_y), right stick X
-> ang_z. Sticks in [-1, 1] pass a deadzone, then map linearly onto the
policy cmd limits (asymmetric per-axis: stick +1 -> hi, stick -1 -> lo).

Zero-command guarantees (locked decision 4): no snapshot yet, controllers
absent, or a snapshot older than `max_age_s` all read as zero twist — the
robot stands still on disconnect; nothing auto-exits VELOCITY mode.
"""
from __future__ import annotations

import time
from typing import Any

import numpy as np

_DEFAULT_DEADZONE = 0.15
_DEFAULT_CMD_LIMITS = {
    "lin_vel_x": [-1.0, 2.0],
    "lin_vel_y": [-0.5, 0.5],
    "ang_vel_z": [-1.0, 1.0],
}


def _deadzone(value: float, deadzone: float) -> float:
    return 0.0 if abs(value) <= deadzone else value


class PicoJoystickProvider:
    """Maps Pico controller thumbsticks onto the CommandProvider twist seam."""

    def __init__(
        self,
        input_provider: Any,
        *,
        deadzone: float = _DEFAULT_DEADZONE,
        cmd_limits: dict[str, list[float]] | None = None,
        max_age_s: float = 0.5,
        clock: Any = time.monotonic,
    ) -> None:
        if not 0.0 <= float(deadzone) < 1.0:
            raise ValueError(f"deadzone must be in [0, 1), got {deadzone}")
        self._input_provider = input_provider
        self._deadzone = float(deadzone)
        limits = dict(_DEFAULT_CMD_LIMITS)
        if cmd_limits:
            limits.update(cmd_limits)
        self._lin_x = (float(limits["lin_vel_x"][0]), float(limits["lin_vel_x"][1]))
        self._lin_y = (float(limits["lin_vel_y"][0]), float(limits["lin_vel_y"][1]))
        self._ang_z = (float(limits["ang_vel_z"][0]), float(limits["ang_vel_z"][1]))
        self._max_age_s = float(max_age_s)
        self._clock = clock

    @staticmethod
    def _scale(stick: float, lo: float, hi: float) -> float:
        """Linear map stick [-1,1] onto [lo, hi], asymmetric at zero."""
        return float(stick * hi if stick >= 0.0 else stick * abs(lo))

    def _read_sticks(self) -> tuple[float, float, float] | None:
        """Return (left_x, left_y, right_x), or None when data is unusable."""
        get_snapshot = getattr(self._input_provider, "get_controller_snapshot", None)
        if not callable(get_snapshot):
            return None
        snapshot = get_snapshot()
        if snapshot is None:
            return None
        if self._max_age_s > 0.0:
            age = float(self._clock()) - float(snapshot.timestamp_s)
            if age > self._max_age_s:
                return None
        left = getattr(snapshot, "left", None)
        right = getattr(snapshot, "right", None)
        if left is None or right is None:
            return None
        if not (bool(getattr(left, "present", False)) and bool(getattr(right, "present", False))):
            return None
        left_x = _deadzone(float(getattr(left, "axis_x", 0.0)), self._deadzone)
        left_y = _deadzone(float(getattr(left, "axis_y", 0.0)), self._deadzone)
        right_x = _deadzone(float(getattr(right, "axis_x", 0.0)), self._deadzone)
        return left_x, left_y, right_x

    def get_cmd(self) -> np.ndarray:
        cmd = np.zeros(6, dtype=np.float32)
        sticks = self._read_sticks()
        if sticks is None:
            return cmd
        left_x, left_y, right_x = sticks
        cmd[0] = self._scale(left_y, *self._lin_x)
        cmd[1] = self._scale(left_x, *self._lin_y)
        cmd[5] = self._scale(right_x, *self._ang_z)
        return cmd

    def reset(self) -> None:
        return None  # stateless: every get_cmd re-reads the snapshot

    def close(self) -> None:
        return None  # input provider owns the bridge lifetime
