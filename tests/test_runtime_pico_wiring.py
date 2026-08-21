"""Test that the mp runtime correctly wires button configs to Pico4InputProvider."""
from __future__ import annotations

from types import SimpleNamespace

from teleopit.inputs.pico4_provider import Pico4InputProvider
from teleopit.sim2real.mp.runtime import _build_pico_input_provider


class _StubPicoBridge:
    """Stub bridge that satisfies Pico4InputProvider's contract without network I/O."""

    def __init__(self, **kwargs):  # noqa: ARG002
        self._started = False

    def start(self):
        self._started = True

    def stop(self):
        self._started = False


def _minimal_video_cfg():
    return SimpleNamespace(enabled=False, source=None, codec=None, bitrate=None, fps=None)


def test_mp_wires_estop_button_from_config() -> None:
    """Test that estop_button flows from config to provider."""
    input_cfg = {"estop_button": "left_grip"}
    provider = _build_pico_input_provider(input_cfg, _minimal_video_cfg(), bridge_cls=_StubPicoBridge)
    assert provider._estop_button == "left_grip"
    assert provider._estop_is_grip is True
    assert provider._estop_grip_side == "left"


def test_mp_wires_estop_grip_threshold_from_config() -> None:
    """Test that estop_grip_threshold flows from config to provider."""
    input_cfg = {"estop_button": "left_grip", "estop_grip_threshold": 0.8}
    provider = _build_pico_input_provider(input_cfg, _minimal_video_cfg(), bridge_cls=_StubPicoBridge)
    assert provider._estop_grip_threshold == 0.8


def test_mp_defaults_estop_grip_threshold_when_absent() -> None:
    """Test that estop_grip_threshold defaults to 0.6 when absent from config."""
    input_cfg = {"estop_button": "left_grip"}
    provider = _build_pico_input_provider(input_cfg, _minimal_video_cfg(), bridge_cls=_StubPicoBridge)
    assert provider._estop_grip_threshold == 0.6


def test_mp_wires_mute_button_from_config() -> None:
    """Test that mute_button flows from config to provider."""
    input_cfg = {"mute_button": "Y"}
    provider = _build_pico_input_provider(input_cfg, _minimal_video_cfg(), bridge_cls=_StubPicoBridge)
    assert provider._mute_button == "Y"


def test_mp_wires_velocity_button_from_config() -> None:
    """Test that velocity_button flows from config to provider."""
    input_cfg = {"velocity_button": "X"}
    provider = _build_pico_input_provider(input_cfg, _minimal_video_cfg(), bridge_cls=_StubPicoBridge)
    assert provider._velocity_button == "X"
    assert provider._velocity_button_path == ("left", "primaryButton")


def test_mp_wires_velocity_debounce_s_from_config() -> None:
    """Test that velocity_debounce_s flows from config to provider."""
    input_cfg = {"velocity_button": "X", "velocity_debounce_s": 0.4}
    provider = _build_pico_input_provider(input_cfg, _minimal_video_cfg(), bridge_cls=_StubPicoBridge)
    assert provider._velocity_debounce_s == 0.4


def test_mp_defaults_velocity_debounce_s_when_absent() -> None:
    """Test that velocity_debounce_s defaults to 0.25 when absent from config."""
    input_cfg = {"velocity_button": "X"}
    provider = _build_pico_input_provider(input_cfg, _minimal_video_cfg(), bridge_cls=_StubPicoBridge)
    assert provider._velocity_debounce_s == 0.25


def test_mp_wires_all_five_button_keys_together() -> None:
    """Test that all five button keys flow correctly from config to provider."""
    input_cfg = {
        "estop_button": "left_grip",
        "estop_grip_threshold": 0.7,
        "mute_button": "Y",
        "velocity_button": "X",
        "velocity_debounce_s": 0.3,
    }
    provider = _build_pico_input_provider(input_cfg, _minimal_video_cfg(), bridge_cls=_StubPicoBridge)
    assert provider._estop_button == "left_grip"
    assert provider._estop_grip_threshold == 0.7
    assert provider._mute_button == "Y"
    assert provider._velocity_button == "X"
    assert provider._velocity_debounce_s == 0.3
