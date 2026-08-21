"""Whole-packet twist arbitration: primary (joystick) overrides secondary (BSI).

Locked decision (wayfinder bsi-dds-04): when the primary source's command is
a non-zero vector, its WHOLE packet wins; otherwise the secondary's whole
packet is used. Never per-axis blending — a merged composite intent (brain
forward + hand turn) is unobservable behavior. No extra cross-fade ramp:
both sources are already smooth (joystick continuous, BSI alpha-smoothed).
"""
from __future__ import annotations

import numpy as np


class MergedTwistProvider:
    """CommandProvider wrapping two sources with whole-packet priority."""

    def __init__(self, primary, secondary) -> None:
        self._primary = primary
        self._secondary = secondary

    def get_cmd(self) -> np.ndarray:
        primary = np.asarray(self._primary.get_cmd(), dtype=np.float32).reshape(-1)
        if bool(np.any(primary != 0.0)):
            return primary
        return np.asarray(self._secondary.get_cmd(), dtype=np.float32).reshape(-1)

    def reset(self) -> None:
        self._primary.reset()
        self._secondary.reset()

    def close(self) -> None:
        self._primary.close()
        self._secondary.close()
