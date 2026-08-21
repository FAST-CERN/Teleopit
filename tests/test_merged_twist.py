"""MergedTwistProvider: whole-packet arbitration, joystick (primary) priority."""
from __future__ import annotations

import numpy as np

from teleopit.commands.merged_twist import MergedTwistProvider


class _Vec:
    """Minimal CommandProvider stand-in returning a fixed vector."""

    def __init__(self, vec):
        self._vec = np.asarray(vec, dtype=np.float32)
        self.reset_calls = 0
        self.close_calls = 0

    def get_cmd(self):
        return self._vec.copy()

    def reset(self):
        self.reset_calls += 1

    def close(self):
        self.close_calls += 1


_BSI = _Vec([0.6, 0, 0, 0, 0, 0])
_JOY_ZERO = _Vec([0.0, 0, 0, 0, 0, 0])
_JOY_FWD = _Vec([0.4, 0, 0, 0, 0, 0.1])


def test_secondary_used_when_primary_zero():
    m = MergedTwistProvider(_JOY_ZERO, _BSI)
    np.testing.assert_allclose(m.get_cmd()[0], 0.6)


def test_primary_wins_whole_packet_when_nonzero():
    m = MergedTwistProvider(_JOY_FWD, _BSI)
    out = m.get_cmd()
    np.testing.assert_allclose(out, np.array([0.4, 0, 0, 0, 0, 0.1], dtype=np.float32))


def test_preempt_switches_within_two_cycles():
    class Flipping:
        def __init__(self):
            self.vec = np.zeros(6, dtype=np.float32)

        def get_cmd(self):
            return self.vec.copy()

        def reset(self): ...

        def close(self): ...

    joy = Flipping()
    m = MergedTwistProvider(joy, _BSI)
    np.testing.assert_allclose(m.get_cmd()[0], 0.6)  # joy zero -> BSI
    joy.vec[0] = 0.3  # operator grabs
    np.testing.assert_allclose(m.get_cmd()[0], 0.3)  # preempted on cycle 1
    joy.vec[0] = 0.0  # released
    np.testing.assert_allclose(m.get_cmd()[0], 0.6)  # BSI back on cycle 1


def test_reset_and_close_delegate_to_both():
    a, b = _JOY_ZERO, _BSI
    m = MergedTwistProvider(a, b)
    m.reset()
    m.close()
    assert a.reset_calls == 1 and a.close_calls == 1
    assert b.reset_calls == 1 and b.close_calls == 1


def test_toggle_mute_none_when_secondary_unmutable():
    m = MergedTwistProvider(_JOY_ZERO, _BSI)  # _BSI has no toggle_mute
    assert m.toggle_mute() is None
    assert m.muted is False


def test_toggle_mute_delegates_and_exposes_secondary():
    bsi = _Vec([0.6, 0, 0, 0, 0, 0])
    bsi.toggle_mute = lambda: True
    bsi.muted = True
    m = MergedTwistProvider(_JOY_ZERO, bsi)
    assert m.secondary is bsi
    assert m.toggle_mute() is True
    assert m.muted is True
