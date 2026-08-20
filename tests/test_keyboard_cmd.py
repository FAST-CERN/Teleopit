from __future__ import annotations

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


def test_keyboard_w_then_x():
    p = KeyboardTwistProvider(keyboard=_FakeKeyboard(["w"]))  # type: ignore[arg-type]
    np.testing.assert_allclose(p.get_cmd()[0], 1.0, atol=1e-6)
    np.testing.assert_allclose(p.get_cmd()[2], 0.0, atol=1e-6)  # holds
    p = KeyboardTwistProvider(keyboard=_FakeKeyboard(["w", "x"]))  # type: ignore[arg-type]
    p.get_cmd()
    np.testing.assert_allclose(p.get_cmd(), np.zeros(6), atol=1e-6)


def test_keyboard_all_directions():
    for key, idx, sign in [("w", 0, 1), ("s", 0, -1), ("a", 1, 1), ("d", 1, -1), ("q", 5, 1), ("e", 5, -1)]:
        p = KeyboardTwistProvider(keyboard=_FakeKeyboard([key]))  # type: ignore[arg-type]
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
