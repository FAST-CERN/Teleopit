"""Pico 侧新键位：X=TOGGLE_VELOCITY（本文件 Task1）、左 grip=TOGGLE_ESTOP（Task2）。"""
from __future__ import annotations

from types import SimpleNamespace

from teleopit.inputs.pico4_provider import Pico4InputProvider
from teleopit.inputs.realtime_packet import ControlEvent, ControlEventType


def _frame_with_buttons(side: str, buttons: dict[str, bool], *, timestamp: float = 100.0):
    controller = SimpleNamespace(buttons=buttons, axis={}, present=True, raw=False)
    controllers = SimpleNamespace(**{side: controller})
    return SimpleNamespace(controllers=controllers, timestamp_s=timestamp)


def test_velocity_button_x_emits_toggle_velocity_event() -> None:
    provider = Pico4InputProvider(velocity_button="X", velocity_debounce_s=0.25)
    # Pico4InputProvider 后台线程需要 bridge；这里直连私有轮询（单测惯例）。
    frame_off = _frame_with_buttons("left", {"primaryButton": False})
    frame_on = _frame_with_buttons("left", {"primaryButton": True}, timestamp=101.0)

    provider._poll_control_events(frame_off, timestamp=100.0)
    events: tuple[ControlEvent, ...] = ()
    for _ in range(2):
        events = provider.pop_control_events()
        if events:
            break
        provider._poll_control_events(frame_on, timestamp=101.0)

    assert any(e.event_type == ControlEventType.TOGGLE_VELOCITY for e in events)
    assert events[0].source == "pico4:X"
