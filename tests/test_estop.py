"""EstopController: latch + 0.3s ramp + exit request (wayfinder bsi-dds-03/07)."""
from __future__ import annotations

import numpy as np
import pytest

from teleopit.sim.estop import EstopController, EstopState


class ManualClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


_CMD = np.array([0.6, 0, 0, 0, 0, 0], dtype=np.float32)


def test_inactive_passthrough_is_bitwise():
    clock = ManualClock()
    estop = EstopController(clock=clock)
    out = estop.apply(_CMD)
    np.testing.assert_array_equal(out, _CMD)


def test_toggle_in_velocity_engages_ramp_then_latch():
    clock = ManualClock()
    estop = EstopController(clock=clock)
    assert estop.toggle(in_velocity=True) == "estop"
    assert estop.state == EstopState.RAMPING
    clock.advance(0.02)  # one policy tick after toggle
    first = estop.apply(_CMD)
    assert 0.0 < first[0] < 0.6  # decaying, not stepped
    # Ramp is 0.3s of exponential decay: well under the 0.8s gate at <0.1.
    t_start = clock.t
    half_seen = None
    while clock.t - t_start < 1.0:
        clock.advance(0.02)
        v = estop.apply(_CMD)[0]
        if v < 0.1:
            half_seen = clock.t - t_start
            break
    assert half_seen is not None and half_seen <= 0.8
    # Continue past the ramp end (0.3s) -> LATCHED.
    while clock.t - t_start < 1.0:
        clock.advance(0.02)
        estop.apply(_CMD)
    assert estop.state == EstopState.LATCHED


def test_ramp_completes_request_exit_once():
    clock = ManualClock()
    estop = EstopController(clock=clock)
    estop.toggle(in_velocity=True)
    assert estop.consume_exit_request() is False  # mid-ramp: no request yet
    for _ in range(50):  # 1.0s
        clock.advance(0.02)
        estop.apply(_CMD)
    assert estop.consume_exit_request() is True  # exactly once
    assert estop.consume_exit_request() is False


def test_latched_suppresses_any_source_to_zero():
    clock = ManualClock()
    estop = EstopController(clock=clock)
    estop.toggle(in_velocity=True)
    for _ in range(50):
        clock.advance(0.02)
        estop.apply(_CMD)
    np.testing.assert_array_equal(estop.apply(_CMD), np.zeros(6, dtype=np.float32))


def test_same_key_toggle_releases():
    clock = ManualClock()
    estop = EstopController(clock=clock)
    estop.toggle(in_velocity=True)
    for _ in range(50):
        clock.advance(0.02)
        estop.apply(_CMD)
    assert estop.toggle(in_velocity=True) == "released"
    np.testing.assert_array_equal(estop.apply(_CMD), _CMD)  # passthrough again


def test_toggle_while_standing_is_ignored():
    estop = EstopController(clock=ManualClock())
    assert estop.toggle(in_velocity=False) == "ignored"
    assert estop.state == EstopState.INACTIVE


def test_on_standing_preserves_latched_lock():
    # Estop -> ramp -> LATCHED -> session lands in STANDING. The latch MUST
    # persist: it is the operator's lock, cleared only by the same E toggle
    # (wayfinder bsi-dds-03: 同键 toggle 解锁). Auto-clearing here was the bug
    # that made estop unlatch immediately on landing — "切不回去".
    clock = ManualClock()
    estop = EstopController(clock=clock)
    estop.toggle(in_velocity=True)
    for _ in range(50):
        clock.advance(0.02)
        estop.apply(_CMD)
    assert estop.state == EstopState.LATCHED
    estop.on_standing()  # session landed in STANDING via the estop exit
    assert estop.state == EstopState.LATCHED  # lock persists
    # Same E key releases the lock (operator then presses V to re-enter).
    assert estop.toggle(in_velocity=False) == "released"
    assert estop.state == EstopState.INACTIVE


def test_on_standing_aborts_in_progress_ramp():
    # Operator X'd out mid-ramp (RAMPING, not yet LATCHED): landing in STANDING
    # aborts the ramp so a stale decay cannot resume on next VELOCITY entry.
    clock = ManualClock()
    estop = EstopController(clock=clock)
    estop.toggle(in_velocity=True)
    clock.advance(0.02)
    estop.apply(_CMD)  # RAMPING, mid-decay
    assert estop.state == EstopState.RAMPING
    estop.on_standing()
    assert estop.state == EstopState.INACTIVE


def test_toggle_in_standing_releases_latched_lock():
    # E pressed in STANDING while LATCHED -> release (the unlock path).
    clock = ManualClock()
    estop = EstopController(clock=clock)
    estop.toggle(in_velocity=True)
    for _ in range(50):
        clock.advance(0.02)
        estop.apply(_CMD)
    assert estop.state == EstopState.LATCHED
    assert estop.toggle(in_velocity=False) == "released"
    assert estop.state == EstopState.INACTIVE
