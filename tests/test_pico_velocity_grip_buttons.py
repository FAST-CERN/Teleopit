"""Pico 侧新键位：X=TOGGLE_VELOCITY（本文件 Task1）、左 grip=TOGGLE_ESTOP（Task2）。"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from teleopit.inputs.pico4_provider import Pico4InputProvider
from teleopit.inputs.realtime_packet import ControlEvent, ControlEventType


class _StubPicoBridge:
    """Stub bridge that satisfies Pico4InputProvider's contract without network I/O."""

    def __init__(self, **kwargs):  # noqa: ARG002
        self._started = False

    def start(self):
        self._started = True

    def stop(self):
        self._started = False


def _frame_with_buttons(side: str, buttons: dict[str, bool], *, timestamp: float = 100.0):
    controller = SimpleNamespace(buttons=buttons, axis={}, present=True, raw=False)
    controllers = SimpleNamespace(**{side: controller})
    return SimpleNamespace(controllers=controllers, timestamp_s=timestamp)


def test_velocity_button_x_emits_toggle_velocity_event() -> None:
    provider = Pico4InputProvider(
        velocity_button="X",
        velocity_debounce_s=0.25,
        bridge_cls=_StubPicoBridge,
    )
    frame_off = _frame_with_buttons("left", {"primaryButton": False})
    frame_on = _frame_with_buttons("left", {"primaryButton": True}, timestamp=101.0)

    provider._poll_control_events(frame_off, timestamp=100.0)
    provider._poll_control_events(frame_on, timestamp=101.0)

    events = provider.pop_control_events()
    assert any(e.event_type == ControlEventType.TOGGLE_VELOCITY for e in events)
    assert events[0].source == "pico4:X"


def _frame_with_grip(side: str, grip: float, *, timestamp: float = 100.0):
    controller = SimpleNamespace(buttons={}, axis={"grip": grip}, present=True, raw=False)
    controllers = SimpleNamespace(**{side: controller})
    return SimpleNamespace(controllers=controllers, timestamp_s=timestamp)


def test_left_grip_crossing_threshold_emits_toggle_estop() -> None:
    provider = Pico4InputProvider(
        estop_button="left_grip",
        estop_grip_threshold=0.6,
        bridge_cls=_StubPicoBridge,
    )
    provider._poll_control_events(_frame_with_grip("left", 0.1), timestamp=100.0)
    assert provider.pop_control_events() == ()

    provider._poll_control_events(_frame_with_grip("left", 0.9), timestamp=101.0)
    events = provider.pop_control_events()
    assert [e.event_type for e in events] == [ControlEventType.TOGGLE_ESTOP]
    assert events[0].source == "pico4:left_grip"


def test_left_grip_below_threshold_is_silent() -> None:
    provider = Pico4InputProvider(
        estop_button="left_grip",
        estop_grip_threshold=0.6,
        bridge_cls=_StubPicoBridge,
    )
    provider._poll_control_events(_frame_with_grip("left", 0.5), timestamp=100.0)
    assert provider.pop_control_events() == ()


def test_velocity_button_constructor_contract() -> None:
    """Test that velocity_button kwarg is accepted and resolved correctly."""
    provider = Pico4InputProvider(
        velocity_button="X",
        velocity_debounce_s=0.3,
        bridge_cls=_StubPicoBridge,
    )
    assert provider._velocity_button == "X"
    assert provider._velocity_debounce_s == 0.3
    assert provider._velocity_button_path == ("left", "primaryButton")
    assert provider._last_velocity_button_pressed is False
    assert provider._last_velocity_toggle_timestamp is None


def test_velocity_button_defaults() -> None:
    """Test that velocity_button defaults to None when omitted."""
    provider = Pico4InputProvider(bridge_cls=_StubPicoBridge)
    assert provider._velocity_button is None
    assert provider._velocity_debounce_s == 0.25  # default per brief
    assert provider._velocity_button_path is None


def test_grip_threshold_constructor_contract() -> None:
    """Test that estop_grip_threshold is accepted and grip detection is configured."""
    provider = Pico4InputProvider(
        estop_button="left_grip",
        estop_grip_threshold=0.7,
        bridge_cls=_StubPicoBridge,
    )
    assert provider._estop_grip_threshold == 0.7
    assert provider._estop_is_grip is True
    assert provider._estop_grip_side == "left"
    assert provider._last_grip_pressed is False


def test_grip_threshold_defaults() -> None:
    """Test that estop_grip_threshold defaults to 0.6 when omitted."""
    provider = Pico4InputProvider(estop_button="left_grip", bridge_cls=_StubPicoBridge)
    assert provider._estop_grip_threshold == 0.6  # default per brief

