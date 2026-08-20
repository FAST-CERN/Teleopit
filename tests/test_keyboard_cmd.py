from __future__ import annotations

import time

import numpy as np
import pytest

from teleopit.commands.base import CommandProvider, TwistCommand
from teleopit.commands.keyboard_cmd import KeyboardTwistProvider


class _FakeKeyEvent:
    def __init__(self, key: str) -> None:
        self.key = key


class _FakeKeyboard:
    def __init__(self, script: list[str]) -> None:
        self._script = list(script)
        self.active = True

    def poll(self):
        keys = self._script
        self._script = []
        return tuple(_FakeKeyEvent(k) for k in keys)

    def close(self) -> None:
        pass


def test_twist_command_vec6_roundtrip():
    t = TwistCommand(lin_x=0.5, lin_y=-0.2, lin_z=0.0, ang_x=0.0, ang_y=0.0, ang_z=0.3)
    assert t.vec6().shape == (6,)
    np.testing.assert_allclose(t.vec6(), [0.5, -0.2, 0.0, 0.0, 0.0, 0.3])


def test_keyboard_w_converges_while_held_and_k_stops():
    # Hold-to-move: a single observed press holds the target within the
    # release window, and get_cmd converges toward it exponentially.
    p = KeyboardTwistProvider(keyboard=_FakeKeyboard(["w"]), alpha=1.0)  # type: ignore[arg-type]
    np.testing.assert_allclose(p.get_cmd()[0], 1.0, atol=1e-6)
    np.testing.assert_allclose(p.get_cmd()[2], 0.0, atol=1e-6)  # no turn axis
    p = KeyboardTwistProvider(keyboard=_FakeKeyboard(["w", "k"]), alpha=1.0)  # type: ignore[arg-type]
    p.get_cmd()  # consumes both events
    np.testing.assert_allclose(p.get_cmd(), np.zeros(6), atol=1e-6)  # k cleared


def test_keyboard_legacy_conflicting_keys_are_gone():
    """Session-mode keys must never double as twist keys (operator fix 2026-08-20).

    Old WASD/QE/x mapping collided with the SimLoopSession mode machine on
    the keyboard-fallback path: q quit the session when the operator meant
    turn-left, a toggled mocap pause when they meant strafe-left, and x
    exited VELOCITY when they meant zero-twist. The tee delivers every key
    to BOTH consumers, so the twist map must avoid the session's keys
    (h q y v x a b r space p) entirely.
    """
    for legacy in ("a", "d", "q", "e", "x"):
        p = KeyboardTwistProvider(keyboard=_FakeKeyboard([legacy]), alpha=1.0)  # type: ignore[arg-type]
        np.testing.assert_allclose(
            p.get_cmd(), np.zeros(6), atol=1e-6,
            err_msg=f"legacy key {legacy!r} must not produce a twist",
        )


def test_keyboard_release_returns_to_zero():
    # Q2 (visual-check): letting go of the key returns the command to zero
    # after the release window, without pressing x.
    p = KeyboardTwistProvider(keyboard=_FakeKeyboard(["w"]), alpha=1.0,
                              release_after_s=0.05)  # type: ignore[arg-type]
    assert p.get_cmd()[0] == 1.0  # held (just observed)
    time.sleep(0.08)  # past release window, no fresh press
    assert p.get_cmd()[0] == 0.0


def test_keyboard_smoothed_direction_change():
    # Q3 (visual-check): switching directions interpolates instead of stepping.
    # alpha=0.25 from a converged +1.0: the ramp toward -1.0 is exactly
    # 1 - 0.25*2, 1 - 0.4375*2, ... i.e. 0.5, -0.25, -0.625.
    p = KeyboardTwistProvider(keyboard=_FakeKeyboard(["w"]), alpha=0.25)  # type: ignore[arg-type]
    for _ in range(40):  # converge to +1.0 (release window is wall-clock; 40 fast calls stay held)
        p.get_cmd()
    np.testing.assert_allclose(p.get_cmd()[0], 1.0, atol=1e-5)
    p._keyboard = _FakeKeyboard(["s"])  # type: ignore[attr-defined]
    v1 = p.get_cmd()[0]
    v2 = p.get_cmd()[0]
    v3 = p.get_cmd()[0]
    # v2/v3 stay within the release window (fast calls), so the target is
    # still -1.0 and the alpha=0.25 ramp from +1.0 continues monotonically.
    np.testing.assert_allclose(v1, 0.5, atol=1e-4)
    np.testing.assert_allclose(v2, 0.125, atol=1e-4)
    np.testing.assert_allclose(v3, -0.15625, atol=1e-4)


def test_keyboard_all_directions():
    # Remapped keys (2026-08-20): W/S fwd/back, J/L strafe left/right,
    # N/M turn left/right — none collide with session mode keys.
    for key, idx, sign in [("w", 0, 1), ("s", 0, -1), ("j", 1, 1), ("l", 1, -1), ("n", 5, 1), ("m", 5, -1)]:
        p = KeyboardTwistProvider(keyboard=_FakeKeyboard([key]), alpha=1.0)  # type: ignore[arg-type]
        cmd = p.get_cmd()
        expected = np.zeros(6)
        expected[idx] = sign * {0: 1.0, 1: 0.5, 5: 1.0}[idx]
        np.testing.assert_allclose(cmd, expected, atol=1e-6)


def test_keyboard_no_keyboard_returns_zeros():
    p = KeyboardTwistProvider(keyboard=None)
    np.testing.assert_allclose(p.get_cmd(), np.zeros(6))
    p.reset()
    p.close()  # must not raise


def test_command_provider_isinstance_runtime_checkable():
    p = KeyboardTwistProvider(keyboard=None)
    assert isinstance(p, CommandProvider)


class TestTerminalKeyboardReaderPlatforms:
    """Cross-platform reader contract: inactive without a tty, no-raise close."""

    def test_reader_inactive_without_tty(self):
        # pytest runs with piped stdin on CI — isatty() False everywhere,
        # and on Windows the msvcrt backend still requires a tty check first.
        from teleopit.runtime.terminal_keyboard import TerminalKeyboardReader
        reader = TerminalKeyboardReader()
        assert reader.active is False
        assert reader.poll() == ()
        reader.close()  # must not raise in either state
