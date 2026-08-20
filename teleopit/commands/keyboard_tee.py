"""Shared terminal-keyboard fan-out for multiple per-step consumers.

Extracted from scripts/run/run_velocity_sim.py (Task 6): when a sim session
(mode keys) and a keyboard twist provider (WASD/QE) both read the operator's
console, they must share ONE TerminalKeyboardReader. Two independent readers
race on the same OS console buffer: whichever polls first drains the keys,
and the other consumer's keys are silently dropped (SimLoopSession's handler
ignores w/s/d/e; the twist provider ignores v/x/y/q).
"""
from __future__ import annotations

import time
from typing import Any

from teleopit.runtime.terminal_keyboard import TerminalKeyboardReader


class KeyboardTee:
    """Deliver one physical key batch to every consumer within a step period.

    Both consumers call poll() once per policy step; the first poll drains
    the shared reader and caches the batch, and every poll() inside the same
    refresh window (one policy period) receives that same batch, so both
    consumers act on disjoint key sets. Redelivery across periods is benign:
    mode requests collapse (repeated v/x are no-ops once in the target mode)
    and the twist provider's hold-to-move latching is absolute (idempotent),
    never incremental.

    ``active`` mirrors the underlying reader so session-side activity checks
    (``reader is not None and reader.active``) work unchanged. close()
    delegates to the reader and is idempotent, matching TerminalKeyboardReader.

    Single-run contract: construct one tee (and one reader) per run; the
    session's finally-close ends the reader's lifetime, exactly like a
    privately-owned TerminalKeyboardReader today.
    """

    def __init__(self, reader: TerminalKeyboardReader, refresh_s: float) -> None:
        self._reader = reader
        self._refresh_s = float(refresh_s)
        self._last_drain = 0.0
        self._batch: tuple[Any, ...] = ()

    @property
    def active(self) -> bool:
        return bool(self._reader.active)

    def poll(self) -> tuple[Any, ...]:
        now = time.monotonic()
        if now - self._last_drain >= self._refresh_s:
            self._batch = self._reader.poll()
            self._last_drain = now
        return self._batch

    def close(self) -> None:
        self._reader.close()
