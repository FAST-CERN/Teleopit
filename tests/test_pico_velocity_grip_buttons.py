"""Pico 侧新键位：X=TOGGLE_VELOCITY（本文件 Task1）、左 grip=TOGGLE_ESTOP（Task2）。"""
from __future__ import annotations

import threading
from collections import deque
from types import SimpleNamespace

from teleopit.inputs.pico4_provider import Pico4InputProvider
from teleopit.inputs.realtime_frame_cache import RealtimeFrameCache
from teleopit.inputs.realtime_packet import ControlEvent, ControlEventType


def _make_provider(
    *,
    estop_button: str | None = None,
    estop_grip_threshold: float = 0.6,
    velocity_button: str | None = None,
    velocity_debounce_s: float = 0.25,
) -> Pico4InputProvider:
    """Create a provider without starting the bridge (for unit testing)."""
    provider = object.__new__(Pico4InputProvider)
    provider._lock = threading.Lock()
    provider._frame_ready = threading.Event()
    provider._frame_cache = RealtimeFrameCache(buffer_size=8, fps_window=30)
    provider._timeout = 1.0
    provider._timestamp_gap_reset_s = 0.15
    provider._pending_control_events = deque()
    provider._pause_button = None
    provider._arms_button = None
    provider._pause_debounce_s = 0.25
    provider._arms_debounce_s = 0.25
    provider._pause_button_path = None
    provider._arms_button_path = None
    provider._last_pause_button_pressed = False
    provider._last_arms_button_pressed = False
    provider._last_pause_toggle_timestamp = None
    provider._last_arms_toggle_timestamp = None
    provider._estop_button = estop_button
    provider._mute_button = None
    provider._estop_debounce_s = 0.25
    provider._mute_debounce_s = 0.25
    provider._estop_button_path = provider._resolve_button_path(estop_button)
    provider._mute_button_path = None
    provider._last_estop_button_pressed = False
    provider._last_mute_button_pressed = False
    provider._last_estop_toggle_timestamp = None
    provider._last_mute_toggle_timestamp = None
    provider._velocity_button = velocity_button
    provider._velocity_debounce_s = velocity_debounce_s
    provider._velocity_button_path = provider._resolve_button_path(velocity_button)
    provider._last_velocity_button_pressed = False
    provider._last_velocity_toggle_timestamp = None
    provider._estop_grip_threshold = estop_grip_threshold
    provider._estop_is_grip = estop_button in ("left_grip", "right_grip")
    provider._estop_grip_side = "left" if estop_button == "left_grip" else "right"
    provider._last_grip_pressed = False
    provider._last_raw_body_joints = None
    provider._last_frame_timestamp = None
    provider._last_source_seq = None
    provider._ground_alignment_offset = None
    provider._controller_snapshot = None
    provider._hand_snapshot = None
    provider._head_pose_snapshot = None
    return provider


def _frame_with_buttons(side: str, buttons: dict[str, bool], *, timestamp: float = 100.0):
    controller = SimpleNamespace(buttons=buttons, axis={}, present=True, raw=False)
    controllers = SimpleNamespace(**{side: controller})
    return SimpleNamespace(controllers=controllers, timestamp_s=timestamp)


def test_velocity_button_x_emits_toggle_velocity_event() -> None:
    provider = _make_provider(velocity_button="X", velocity_debounce_s=0.25)
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


def _frame_with_grip(side: str, grip: float, *, timestamp: float = 100.0):
    controller = SimpleNamespace(buttons={}, axis={"grip": grip}, present=True, raw=False)
    controllers = SimpleNamespace(**{side: controller})
    return SimpleNamespace(controllers=controllers, timestamp_s=timestamp)


def test_left_grip_crossing_threshold_emits_toggle_estop() -> None:
    provider = _make_provider(estop_button="left_grip", estop_grip_threshold=0.6)
    provider._poll_control_events(_frame_with_grip("left", 0.1), timestamp=100.0)
    assert provider.pop_control_events() == ()

    provider._poll_control_events(_frame_with_grip("left", 0.9), timestamp=101.0)
    events = provider.pop_control_events()
    assert [e.event_type for e in events] == [ControlEventType.TOGGLE_ESTOP]
    assert events[0].source == "pico4:left_grip"


def test_left_grip_below_threshold_is_silent() -> None:
    provider = _make_provider(estop_button="left_grip", estop_grip_threshold=0.6)
    provider._poll_control_events(_frame_with_grip("left", 0.5), timestamp=100.0)
    assert provider.pop_control_events() == ()

