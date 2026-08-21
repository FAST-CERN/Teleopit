"""BsiTwistProvider: intent -> twist pipeline (debounce/map/smooth/silence/mute)."""
from __future__ import annotations

import numpy as np
import pytest

from teleopit.commands.bsi_twist import (
    INTENT_FORWARD,
    INTENT_IDLE,
    INTENT_TURN_LEFT,
    INTENT_TURN_RIGHT,
    BsiTwistProvider,
    ScriptedIntentSource,
)


class ManualClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def _provider(script, **kw):
    clock = kw.pop("clock", ManualClock())
    src = ScriptedIntentSource(script, clock=clock)
    return BsiTwistProvider(src, clock=clock, **kw), clock


def test_idle_maps_to_zero():
    p, _ = _provider([(INTENT_IDLE, 10.0)])
    np.testing.assert_allclose(p.get_cmd(), np.zeros(6, dtype=np.float32))


def test_forward_debounce_three_packets_then_ramps_to_0_6():
    # FORWARD held 10s at 10 Hz polling; debounce=3 -> effective intent at 3rd packet.
    clock = ManualClock()
    p = BsiTwistProvider(
        ScriptedIntentSource([(INTENT_FORWARD, 10.0)], clock=clock),
        clock=clock,
    )
    # Two packets (t=0.0 and t=0.1): debounce not satisfied -> still IDLE target.
    p.get_cmd(); clock.advance(0.1)
    p.get_cmd(); clock.advance(0.1)
    # t=0.2 is still between packets? No: 0.1s since last emit -> packet 3
    # arrives ON this call and satisfies debounce, so the ramp starts HERE.
    third = p.get_cmd()
    assert 0.0 < third[0] < 0.6  # packet 3 switched intent; ramping toward 0.6
    clock.advance(0.1)
    fourth = p.get_cmd()
    assert fourth[0] > third[0]  # ramp continues monotonically toward 0.6


def test_forward_reaches_half_target_within_1s_gate():
    clock = ManualClock()
    p = BsiTwistProvider(
        ScriptedIntentSource([(INTENT_FORWARD, 60.0)], clock=clock),
        clock=clock,
    )
    # Simulate 10 Hz intent polls with 50 Hz get_cmd (policy rate): each 0.1s
    # one new packet arrives; between packets get_cmd still steps smoothing.
    t_switch = None
    for i in range(200):  # 4 s at 50 Hz
        p.get_cmd()
        if t_switch is None and p.get_cmd()[0] > 0.0:
            t_switch = clock.t
        if t_switch is not None and p.get_cmd()[0] >= 0.3:
            assert clock.t - t_switch <= 1.0
            return
        clock.advance(0.02)
    pytest.fail("never reached 0.3 m/s")


def test_turn_left_maps_in_place_positive_ang_z():
    clock = ManualClock()
    p = BsiTwistProvider(
        ScriptedIntentSource([(INTENT_TURN_LEFT, 60.0)], clock=clock),
        clock=clock,
    )
    # Pump past debounce + smoothing to convergence.
    for _ in range(300):
        p.get_cmd()
        clock.advance(0.02)
    cmd = p.get_cmd()
    assert cmd[0] == pytest.approx(0.0, abs=1e-3)  # in-place: no lin_x
    assert cmd[5] == pytest.approx(0.6, abs=0.01)


def test_turn_right_converges_negative_ang_z():
    clock = ManualClock()
    p = BsiTwistProvider(
        ScriptedIntentSource([(INTENT_TURN_RIGHT, 60.0)], clock=clock),
        clock=clock,
    )
    for _ in range(300):
        p.get_cmd()
        clock.advance(0.02)
    assert p.get_cmd()[5] == pytest.approx(-0.6, abs=0.01)


def test_single_misclassified_packet_is_filtered():
    # FORWARD stream with a single TURN_LEFT packet injected: intent must not switch.
    clock = ManualClock()
    script = [(INTENT_FORWARD, 1.0), (INTENT_TURN_LEFT, 0.1), (INTENT_FORWARD, 30.0)]
    p = BsiTwistProvider(ScriptedIntentSource(script, clock=clock), clock=clock)
    for _ in range(100):  # settle into FORWARD
        p.get_cmd()
        clock.advance(0.02)
    # The 0.1s LEFT segment yields exactly one packet — filtered.
    for _ in range(10):
        p.get_cmd()
        clock.advance(0.02)
    cmd = p.get_cmd()
    assert cmd[0] > 0.4  # still ramped FORWARD
    assert abs(cmd[5]) < 0.01  # never turned


def test_idle_enters_after_two_packets():
    clock = ManualClock()
    script = [(INTENT_FORWARD, 4.0), (INTENT_IDLE, 20.0)]
    p = BsiTwistProvider(ScriptedIntentSource(script, clock=clock), clock=clock)
    for _ in range(39):  # 3.9s at 0.1s cadence: settle into FORWARD at 0.6
        p.get_cmd()
        clock.advance(0.1)
    assert p.get_cmd()[0] == pytest.approx(0.6, abs=0.01)
    # IDLE: 2 packets to enter (asymmetric, stop-first). Packets land on the
    # 0.1s cadence: t=4.0 is idle pkt 1, t=4.1 is idle pkt 2 -> switch.
    clock.advance(0.1)
    p.get_cmd(); clock.advance(0.1)  # t=4.0: idle pkt 1
    p.get_cmd()                       # t=4.1: idle pkt 2 -> intent switches
    mid = p.get_cmd().copy()          # first decaying output
    clock.advance(0.1)
    after = p.get_cmd()
    assert after[0] < mid[0] < 0.6  # decaying


def test_silence_falls_to_idle_within_1s_and_zero_by_1_5s():
    # A source that goes permanently quiet after its script ends (Task 2's
    # end-of-script semantics): link loss -> provider falls to IDLE.
    class _QuietAfter:
        """Emits FORWARD at 10Hz for 2s, then never again (link lost)."""

        def __init__(self, clock):
            self._clock = clock
            self._last = None

        def poll(self):
            now = self._clock()
            if now >= 2.0:
                return None
            if self._last is not None and now - self._last < 0.1:
                return None
            self._last = now
            from teleopit.commands.bsi_twist import DiscreteIntent
            return DiscreteIntent(command=INTENT_FORWARD, rx_time_s=now)

        def close(self):
            return None

    clock = ManualClock()
    p = BsiTwistProvider(_QuietAfter(clock), clock=clock)
    for _ in range(100):  # 2.0s: settle into FORWARD at 0.6
        p.get_cmd()
        clock.advance(0.02)
    assert p.get_cmd()[0] == pytest.approx(0.6, abs=0.01)
    clock.advance(1.1)  # past the 1.0s silence timeout since the last packet
    cmd = p.get_cmd()
    assert cmd[0] < 0.6  # intent already fell to IDLE on this first call
    for _ in range(60):  # 1.2s decay pump: smoothed output reaches ~0
        cmd = p.get_cmd()
        clock.advance(0.02)
    assert cmd[0] == pytest.approx(0.0, abs=1e-6)


def test_mute_forces_idle_next_cycle_and_unmute_restores():
    clock = ManualClock()
    p = BsiTwistProvider(
        ScriptedIntentSource([(INTENT_FORWARD, 60.0)], clock=clock),
        clock=clock,
    )
    for _ in range(200):
        p.get_cmd()
        clock.advance(0.02)
    assert p.get_cmd()[0] == pytest.approx(0.6, abs=0.01)
    assert p.toggle_mute() is True
    decaying = p.get_cmd()[0]
    assert decaying < 0.6  # next cycle already decaying toward zero
    for _ in range(200):
        p.get_cmd()
        clock.advance(0.02)
    assert p.get_cmd()[0] == pytest.approx(0.0, abs=1e-3)
    assert p.toggle_mute() is False  # unmute
    for _ in range(200):  # intent stream still FORWARD -> recovers
        p.get_cmd()
        clock.advance(0.02)
    assert p.get_cmd()[0] == pytest.approx(0.6, abs=0.01)


def test_mute_survives_reset():
    p, _ = _provider([(INTENT_FORWARD, 60.0)])
    p.toggle_mute()
    p.reset()
    assert p.muted is True


def test_unknown_command_value_fails_safe_to_idle():
    clock = ManualClock()
    p = BsiTwistProvider(
        ScriptedIntentSource([(99, 60.0)], clock=clock),
        clock=clock,
    )
    for _ in range(300):
        p.get_cmd()
        clock.advance(0.02)
    np.testing.assert_allclose(p.get_cmd(), np.zeros(6, dtype=np.float32))
