"""Keyboard twist source: hold-to-move WASD/QE, X latches zero.

Hold-to-move: the command is active only while the key is (or was very
recently) seen in poll batches. A key not observed for `release_after_s`
seconds reads as released, so the command returns to zero when the operator
lets go — no explicit X needed. X remains as an immediate full stop.

Output is exponentially smoothed toward the target twist (alpha per
get_cmd call), so direction changes and releases ramp instead of stepping.
"""
from __future__ import annotations

import time
from typing import Any

import numpy as np

from teleopit.commands.base import TwistCommand

_DEFAULT_SPEEDS = {"lin_x": 1.0, "lin_y": 0.5, "ang_z": 1.0}
_KEY_MAP: dict[str, tuple[str, float]] = {
    "w": ("lin_x", 1.0),
    "s": ("lin_x", -1.0),
    "a": ("lin_y", 1.0),
    "d": ("lin_y", -1.0),
    "q": ("ang_z", 1.0),
    "e": ("ang_z", -1.0),
}
_AXIS_INDEX = {"lin_x": 0, "lin_y": 1, "ang_z": 5}


class KeyboardTwistProvider:
    """Hold-to-move with release-to-zero and smoothed output.

    Uses TerminalKeyboardReader when available; degrades to zero command when
    stdin is not a tty (tests, CI). The smoother state persists across
    get_cmd calls; reset() zeroes both latch and smoother.
    """

    def __init__(
        self,
        speeds: dict[str, float] | None = None,
        keyboard: Any = None,
        *,
        alpha: float = 0.3,
        release_after_s: float = 0.2,
    ) -> None:
        self._speeds = dict(_DEFAULT_SPEEDS)
        if speeds:
            self._speeds.update(speeds)
        if not 0.0 < float(alpha) <= 1.0:
            raise ValueError(f"alpha must be in (0, 1], got {alpha}")
        self._alpha = float(alpha)
        self._release_after_s = float(release_after_s)
        self._keyboard = keyboard
        self._held: dict[str, float] = {}  # axis -> signed speed while held
        self._last_seen: dict[str, float] = {}  # axis -> last press time
        self._smoothed: np.ndarray = np.zeros(6, dtype=np.float32)

    def _observe_events(self) -> None:
        if self._keyboard is None:
            return
        now = time.monotonic()
        for event in self._keyboard.poll():
            key = getattr(event, "key", "")
            if key == "x":
                self._held.clear()
                self._last_seen.clear()
            elif key in _KEY_MAP:
                axis, sign = _KEY_MAP[key]
                self._held[axis] = sign * self._speeds[axis]
                self._last_seen[axis] = now

    def _target_twist(self) -> np.ndarray:
        now = time.monotonic()
        target = np.zeros(6, dtype=np.float32)
        for axis in list(self._held):
            last = self._last_seen.get(axis)
            if last is None or (now - last) > self._release_after_s:
                # Key not re-observed recently: released — drop to zero.
                self._held.pop(axis, None)
                self._last_seen.pop(axis, None)
                continue
            target[_AXIS_INDEX[axis]] = np.float32(self._held[axis])
        return target

    def get_cmd(self) -> np.ndarray:
        self._observe_events()
        target = self._target_twist()
        # Exponential approach: same form as ExponentialVecSmoother, inlined
        # so the provider owns its release+smooth semantics as one unit.
        self._smoothed = np.asarray(
            self._smoothed + self._alpha * (target - self._smoothed),
            dtype=np.float32,
        )
        return self._smoothed.copy()

    def reset(self) -> None:
        self._held.clear()
        self._last_seen.clear()
        self._smoothed = np.zeros(6, dtype=np.float32)

    def close(self) -> None:
        if self._keyboard is not None and callable(getattr(self._keyboard, "close", None)):
            self._keyboard.close()
