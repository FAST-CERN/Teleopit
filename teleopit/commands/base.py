"""Transport-agnostic twist command seam.

Implementations translate a source (keyboard, Pico joystick, Unitree remote,
future DDS topic) into a 6D body-frame twist. Nothing above this module may
depend on any transport specifics -- that boundary is what keeps a later
LAN/DDS host-machine provider a drop-in addition.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np


@dataclass(frozen=True)
class TwistCommand:
    lin_x: float = 0.0
    lin_y: float = 0.0
    lin_z: float = 0.0
    ang_x: float = 0.0
    ang_y: float = 0.0
    ang_z: float = 0.0

    def vec6(self) -> np.ndarray:
        return np.array(
            [self.lin_x, self.lin_y, self.lin_z, self.ang_x, self.ang_y, self.ang_z],
            dtype=np.float32,
        )


@runtime_checkable
class CommandProvider(Protocol):
    """Provides the current 6D twist command (clamped by the builder downstream)."""

    def get_cmd(self) -> np.ndarray:
        """Return current command as float32 (6,)."""
        ...

    def reset(self) -> None:
        """Clear any latched command state."""
        ...

    def close(self) -> None:
        """Release transport resources (no-op for stateless sources)."""
        ...
