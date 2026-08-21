"""Session-level emergency stop: latched suppression with a 0.3s decay.

Locked decisions (wayfinder bsi-dds-03): session-scope (any VELOCITY
session, all command sources), cmd decays to zero then the session runs its
X-exit path into STANDING (NOT damping — the joint-vel/overspeed damping
gates stay as they are). Same key toggles engage/release. The latch PERSISTS
after the estop-triggered STANDING landing — it is the operator's lock,
cleared only by the same E toggle (同键 toggle 解锁); landing in STANDING via
a normal X-exit only aborts an in-progress ramp, it does NOT clear a
completed latch.
"""
from __future__ import annotations

import time
from enum import Enum
from typing import Callable

import numpy as np


class EstopState(Enum):
    INACTIVE = "inactive"
    RAMPING = "ramping"
    LATCHED = "latched"


class EstopController:
    """Owns the estop latch; the session consults it after get_cmd()."""

    def __init__(
        self,
        *,
        ramp_s: float = 0.3,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ramp_s = float(ramp_s)
        self._clock = clock
        self._state = EstopState.INACTIVE
        self._ramp_start: float | None = None
        self._exit_requested = False
        self._exit_consumed = True

    @property
    def state(self) -> EstopState:
        return self._state

    def toggle(self, in_velocity: bool) -> str:
        if self._state == EstopState.INACTIVE:
            if not in_velocity:
                return "ignored"  # STANDING press: no-op, no deadlock
            self._state = EstopState.RAMPING
            self._ramp_start = self._clock()
            self._exit_requested = False
            self._exit_consumed = False
            return "estop"
        # RAMPING or LATCHED: same key releases.
        self._state = EstopState.INACTIVE
        self._ramp_start = None
        return "released"

    def apply(self, cmd: np.ndarray) -> np.ndarray:
        cmd = np.asarray(cmd, dtype=np.float32)
        if self._state == EstopState.INACTIVE:
            return cmd
        if self._state == EstopState.RAMPING:
            now = self._clock()
            elapsed = now - (self._ramp_start if self._ramp_start is not None else now)
            scaled = cmd * float(np.exp(-3.0 * elapsed / max(self._ramp_s, 1e-6)))
            if elapsed >= self._ramp_s:
                self._state = EstopState.LATCHED
                self._exit_requested = True
                return np.zeros_like(cmd)
            return scaled.astype(np.float32)
        return np.zeros_like(cmd)  # LATCHED

    def consume_exit_request(self) -> bool:
        if self._exit_requested and not self._exit_consumed:
            self._exit_consumed = True
            return True
        return False

    def latch(self) -> None:
        """Force LATCHED without an exit request (damping entry, bsi-realhw-05).

        Any DAMPING entry locks VELOCITY re-entry until the operator's E
        toggle releases it. No ramp/exit semantics: the caller has already
        left VELOCITY by harder means.
        """
        self._state = EstopState.LATCHED
        self._ramp_start = None
        self._exit_requested = False
        self._exit_consumed = True

    def on_standing(self) -> None:
        # Landing in STANDING aborts an in-progress ramp (operator X'd out
        # mid-decay) but PRESERVES a completed latch: the latch is the
        # operator's estop lock, cleared only by the same E toggle. Auto-
        # clearing here was the bug that made the robot re-enterable right
        # after an estop ("切不回去" / could escape to mocap).
        if self._state == EstopState.RAMPING:
            self._state = EstopState.INACTIVE
            self._ramp_start = None
            self._exit_requested = False
            self._exit_consumed = True
        # LATCHED and INACTIVE pass through unchanged.
