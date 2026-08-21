# teleopit/commands/forward_only.py
"""L2 caretaker gate: whole-channel forward-only cap (wayfinder bsi-realhw-07).

Applied above the merged provider so BOTH halves (BSI intents and Pico
joystick) obey the same envelope: lin_x clamped to [0, max_lin_x] (reverse
squelched too), lin_y and ang_z forced to zero. L3 runs without this wrapper.
"""
from __future__ import annotations

from typing import Any

import numpy as np


class ForwardOnlyCapProvider:
    """Wrap a CommandProvider with the L2 forward-only envelope.

    A command shorter than 6 elements passes through uncapped: the envelope
    assumes the 6D twist contract, so shorter output is treated as
    malformed-but-harmless rather than raising.
    """

    def __init__(self, inner: Any, *, max_lin_x: float) -> None:
        if float(max_lin_x) <= 0.0:
            raise ValueError(f"max_lin_x must be > 0, got {max_lin_x}")
        self._inner = inner
        self._max_lin_x = float(max_lin_x)

    def get_cmd(self) -> np.ndarray:
        cmd = np.asarray(self._inner.get_cmd(), dtype=np.float32).reshape(-1).copy()
        if cmd.shape[0] < 6:
            return cmd
        cmd[0] = np.clip(cmd[0], 0.0, self._max_lin_x)
        cmd[1] = 0.0
        cmd[5] = 0.0
        return cmd

    def reset(self) -> None:
        self._inner.reset()

    def close(self) -> None:
        self._inner.close()

    @property
    def muted(self) -> bool:
        return bool(getattr(self._inner, "muted", False))

    def toggle_mute(self) -> bool | None:
        """Delegate BSI mute through the cap so TOGGLE_MUTE survives wrapping."""
        toggle = getattr(self._inner, "toggle_mute", None)
        return bool(toggle()) if callable(toggle) else None
