"""Keyboard twist source: WASD/QE latch commands, X clears."""
from __future__ import annotations

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


class KeyboardTwistProvider:
    """Hold-to-move semantics: a key press latches the direction until `x` or reset.

    Uses TerminalKeyboardReader when available; degrades to zero command when
    stdin is not a tty (tests, CI).
    """

    def __init__(self, speeds: dict[str, float] | None = None, keyboard: Any = None) -> None:
        self._speeds = dict(_DEFAULT_SPEEDS)
        if speeds:
            self._speeds.update(speeds)
        self._keyboard = keyboard
        self._latched = TwistCommand()

    def get_cmd(self) -> np.ndarray:
        if self._keyboard is None:
            return np.zeros(6, dtype=np.float32)
        for event in self._keyboard.poll():
            key = getattr(event, "key", "")
            if key == "x":
                self._latched = TwistCommand()
            elif key in _KEY_MAP:
                axis, sign = _KEY_MAP[key]
                self._latched = TwistCommand(**{axis: sign * self._speeds[axis]})
        return self._latched.vec6()

    def reset(self) -> None:
        self._latched = TwistCommand()

    def close(self) -> None:
        if self._keyboard is not None and callable(getattr(self._keyboard, "close", None)):
            self._keyboard.close()
