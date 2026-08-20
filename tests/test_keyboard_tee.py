"""KeyboardTee: one terminal reader fanned out to per-step consumers.

Regression coverage for the two-reader race (Task 6 Part B): the sim session
(mode keys) and the keyboard twist provider (WASD/QE) must share ONE
TerminalKeyboardReader via a tee, because whichever of two independent
readers polls first drains the console buffer and silently drops the other
consumer's keys.
"""
from __future__ import annotations

from teleopit.commands import KeyboardTee
from teleopit.runtime.terminal_keyboard import TerminalKeyEvent


class _ScriptedReader:
    """Scripted TerminalKeyboardReader stand-in (active, batch per poll)."""

    def __init__(self, batches: list[tuple[TerminalKeyEvent, ...]]) -> None:
        self._batches = list(batches)
        self.polls = 0
        self.closed = False

    @property
    def active(self) -> bool:
        return not self.closed

    def poll(self) -> tuple[TerminalKeyEvent, ...]:
        self.polls += 1
        return self._batches.pop(0) if self._batches else ()

    def close(self) -> None:
        self.closed = True


def test_two_consumers_see_the_same_key_batch() -> None:
    """Core contract: every consumer polling within one period gets the batch."""
    reader = _ScriptedReader(
        [(TerminalKeyEvent("v"), TerminalKeyEvent("w")), (TerminalKeyEvent("x"),)]
    )
    # refresh_s far beyond the test duration: one drain, cached for the period.
    tee = KeyboardTee(reader, refresh_s=1000.0)

    session_batch = tee.poll()   # session polls first (drains the reader)
    provider_batch = tee.poll()  # twist provider polls second (same period)

    assert session_batch == (TerminalKeyEvent("v"), TerminalKeyEvent("w"))
    assert provider_batch == session_batch  # NOT starved: same physical batch
    assert reader.polls == 1                 # reader drained exactly once


def test_new_batch_delivered_after_refresh_window() -> None:
    """After a period elapses, the next poll drains a fresh batch."""
    reader = _ScriptedReader(
        [(TerminalKeyEvent("v"),), (TerminalKeyEvent("w"),)]
    )
    # refresh_s=0: every poll re-drains (each poll is a new policy period).
    tee = KeyboardTee(reader, refresh_s=0.0)

    first = tee.poll()
    second = tee.poll()
    assert first == (TerminalKeyEvent("v"),)
    assert second == (TerminalKeyEvent("w"),)
    assert reader.polls == 2


def test_batch_redelivered_to_late_consumer_within_period() -> None:
    """A consumer that polls twice in one period sees the batch twice.

    Redelivery is benign by design: mode requests collapse once in the
    target mode and the twist provider's hold-to-move latching is absolute.
    """
    reader = _ScriptedReader([(TerminalKeyEvent("w"),)])
    tee = KeyboardTee(reader, refresh_s=1000.0)

    assert tee.poll() == (TerminalKeyEvent("w"),)
    assert tee.poll() == (TerminalKeyEvent("w"),)
    assert reader.polls == 1


def test_empty_batches_flow_through() -> None:
    """No keys pressed: both consumers observe an empty batch."""
    reader = _ScriptedReader([()])
    tee = KeyboardTee(reader, refresh_s=1000.0)
    assert tee.poll() == ()
    assert tee.poll() == ()


def test_active_mirrors_reader_and_close_delegates() -> None:
    """Tee satisfies the session's reader contract: active + close()."""
    reader = _ScriptedReader([])
    tee = KeyboardTee(reader, refresh_s=1.0)
    assert tee.active is True
    tee.close()
    assert reader.closed is True
    assert tee.active is False
