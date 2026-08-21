# tests/test_forward_only_provider.py
"""L2 看护慢速门：全通道仅 forward ≤ max_lin_x，侧向/转向一律 0（bsi-realhw-07）。"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from teleopit.commands.forward_only import ForwardOnlyCapProvider


def _provider(cmd: np.ndarray) -> SimpleNamespace:
    return SimpleNamespace(
        get_cmd=lambda: np.asarray(cmd, dtype=np.float32).copy(),
        reset=lambda: None,
        close=lambda: None,
    )


def test_forward_clamped_to_cap() -> None:
    capped = ForwardOnlyCapProvider(_provider(np.array([0.6, 0, 0, 0, 0, 0])), max_lin_x=0.3)
    np.testing.assert_allclose(capped.get_cmd(), np.array([0.3, 0, 0, 0, 0, 0], dtype=np.float32))


def test_backward_and_lateral_and_turn_are_zeroed() -> None:
    capped = ForwardOnlyCapProvider(
        _provider(np.array([-0.4, 0.5, 0, 0, 0, -0.8])), max_lin_x=0.3
    )
    np.testing.assert_allclose(capped.get_cmd(), np.array([0.0, 0, 0, 0, 0, 0], dtype=np.float32))


def test_zero_command_passes_through() -> None:
    capped = ForwardOnlyCapProvider(_provider(np.zeros(6)), max_lin_x=0.3)
    np.testing.assert_allclose(capped.get_cmd(), np.zeros(6, dtype=np.float32))


def test_mute_delegates_through_the_cap() -> None:
    calls: list[bool] = []

    def _mute() -> bool:
        calls.append(True)
        return True

    inner = SimpleNamespace(
        get_cmd=lambda: np.zeros(6), reset=lambda: None, close=lambda: None,
        toggle_mute=_mute, muted=False,
    )
    capped = ForwardOnlyCapProvider(inner, max_lin_x=0.3)
    assert capped.toggle_mute() is True
    assert calls == [True]
    assert capped.muted is False
