"""merged_bsi factory assembly (cyclonedds-free via injected reader_factory)."""
from __future__ import annotations

import sys
from types import SimpleNamespace

import numpy as np
import pytest

from teleopit.commands.bsi_factory import build_merged_bsi_provider, sanitize_bridge_coexistence_env
from teleopit.commands.bsi_twist import INTENT_FORWARD


class _Joy:
    def get_cmd(self):
        return np.zeros(6, dtype=np.float32)

    def reset(self): ...

    def close(self): ...


class _JoyFwd:
    def get_cmd(self):
        return np.array([0.4, 0, 0, 0, 0, 0.1], dtype=np.float32)

    def reset(self): ...

    def close(self): ...


class _FakeSource:
    """Fake reader-backed source emitting FORWARD forever, stamped by the clock."""

    def __init__(self, cfg, clock):
        self._clock = clock

    def poll(self):
        from teleopit.commands.bsi_twist import DiscreteIntent
        return DiscreteIntent(command=INTENT_FORWARD, rx_time_s=self._clock())

    def close(self): ...


class ManualClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def test_build_merged_bsi_uses_secondary_when_joystick_zero():
    clock = ManualClock()
    merged = build_merged_bsi_provider(
        _Joy(), {}, clock=clock, reader_factory=lambda cfg, clock: _FakeSource(cfg, clock)
    )
    for _ in range(300):
        merged.get_cmd()
        clock.advance(0.02)
    assert merged.get_cmd()[0] == pytest.approx(0.6, abs=0.01)


def test_build_merged_bsi_joystick_priority_whole_packet():
    merged = build_merged_bsi_provider(
        _JoyFwd(), {}, clock=ManualClock(),
        reader_factory=lambda cfg, clock: _FakeSource(cfg, clock),
    )
    np.testing.assert_allclose(
        merged.get_cmd(), np.array([0.4, 0, 0, 0, 0, 0.1], dtype=np.float32)
    )


def test_build_merged_bsi_passes_bsi_params():
    clock = ManualClock()
    merged = build_merged_bsi_provider(
        _Joy(),
        {"speeds": {"forward": 0.3, "turn": 0.5}, "alpha": 0.5},
        clock=clock,
        reader_factory=lambda cfg, clock: _FakeSource(cfg, clock),
    )
    for _ in range(400):
        merged.get_cmd()
        clock.advance(0.02)
    assert merged.get_cmd()[0] == pytest.approx(0.3, abs=0.01)


# ── Orin dual-DDS coexistence env guard (bsi-realhw 06-5 field finding) ──────
# The Orin bashrc exports CYCLONEDDS_HOME at a source-build install;
# cyclonedds-python then loads THAT libddsc as a second, independent
# CycloneDDS instance beside g1_bridge_sdk's bundled one — two runtimes in
# one process corrupt handles (Topic init -> DDS_RETCODE_BAD_PARAMETER).


def test_sanitize_drops_cyclonedds_home_when_bridge_loaded(monkeypatch) -> None:
    monkeypatch.setenv("CYCLONEDDS_HOME", "/home/unitree/cyclonedds_ws/install/cyclonedds")
    monkeypatch.setitem(sys.modules, "g1_bridge_sdk", SimpleNamespace())
    assert sanitize_bridge_coexistence_env() is True
    import os

    assert "CYCLONEDDS_HOME" not in os.environ


def test_sanitize_keeps_env_without_bridge(monkeypatch) -> None:
    monkeypatch.setenv("CYCLONEDDS_HOME", "/somewhere/cyclonedds")
    monkeypatch.delitem(sys.modules, "g1_bridge_sdk", raising=False)
    assert sanitize_bridge_coexistence_env() is False
    import os

    assert os.environ["CYCLONEDDS_HOME"] == "/somewhere/cyclonedds"


def test_sanitize_noop_without_env(monkeypatch) -> None:
    monkeypatch.delenv("CYCLONEDDS_HOME", raising=False)
    monkeypatch.setitem(sys.modules, "g1_bridge_sdk", SimpleNamespace())
    assert sanitize_bridge_coexistence_env() is False
