"""Pico button -> estop/mute control-event mapping (config plumbing, no bridge)."""
from __future__ import annotations

import pytest

from teleopit.inputs.pico4_provider import Pico4InputProvider
from teleopit.inputs.realtime_packet import ControlEventType


def test_new_control_event_types():
    assert ControlEventType.TOGGLE_ESTOP.value == "toggle_estop"
    assert ControlEventType.TOGGLE_MUTE.value == "toggle_mute"


def test_button_path_resolution_for_estop_and_mute():
    # right menuButton = estop; left secondaryButton (Y) = mute (ticket 05).
    assert Pico4InputProvider._resolve_button_path("right_menu_button") == ("right", "menuButton")
    assert Pico4InputProvider._resolve_button_path("Y") == ("left", "secondaryButton")
    assert Pico4InputProvider._resolve_button_path("left_menu_button") == ("left", "menuButton")
    assert Pico4InputProvider._resolve_button_path(None) is None
