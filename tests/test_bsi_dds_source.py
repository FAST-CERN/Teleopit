"""DdsIntentSource: raw DDS reader -> DiscreteIntent adapter (cyclonedds-free)."""
from __future__ import annotations

import pytest

from teleopit.commands.bsi_dds_source import DdsIntentSource
from teleopit.commands.bsi_twist import (
    INTENT_FORWARD,
    INTENT_IDLE,
    INTENT_TURN_LEFT,
)


class _CmdValue:
    def __init__(self, value):
        self.value = value


class _Sample:
    def __init__(self, value):
        self.command = _CmdValue(value)


class _FakeReader:
    def __init__(self, batches):
        self._batches = list(batches)  # one list-of-samples per drain()
        self._i = 0
        self.closed = False

    def drain(self):
        if self._i >= len(self._batches):
            return []
        batch = self._batches[self._i]
        self._i += 1
        return batch

    def close(self):
        self.closed = True


class ManualClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def test_empty_drain_returns_none():
    src = DdsIntentSource(_FakeReader([]), clock=ManualClock())
    assert src.poll() is None


def test_sample_maps_to_discrete_intent_with_local_stamp():
    clock = ManualClock()
    src = DdsIntentSource(_FakeReader([[ _Sample(INTENT_FORWARD) ]]), clock=clock)
    clock.advance(1.5)
    intent = src.poll()
    assert intent.command == INTENT_FORWARD
    assert intent.rx_time_s == 1.5


def test_latest_sample_wins_when_batch_has_many():
    src = DdsIntentSource(
        _FakeReader([[ _Sample(INTENT_IDLE), _Sample(INTENT_TURN_LEFT) ]]),
        clock=ManualClock(),
    )
    assert src.poll().command == INTENT_TURN_LEFT


def test_unknown_value_fails_safe_to_idle():
    src = DdsIntentSource(_FakeReader([[ _Sample(99) ]]), clock=ManualClock())
    assert src.poll().command == INTENT_IDLE


def test_close_delegates_to_reader():
    reader = _FakeReader([])
    DdsIntentSource(reader, clock=ManualClock()).close()
    assert reader.closed is True
