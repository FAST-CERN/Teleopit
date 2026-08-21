"""Inspire RH56 (FTP) preset-grasp driver: DDS ctrl publisher side (2026-08-22 grilling).

Teleopit only publishes rt/inspire_hand/ctrl/{l,r}; the Orin-side
driver_double_wlan0.py (inspire_test env) forwards to ModbusTCP
192.168.123.210/.211:6000. Thumb-rotation (angle index 5) is pinned open
(1000) at the device — never actuated (anti-collision, SDK dds_publish
precedent). Angle units: int16, 0=closed 1000=open, joint order
[pinky, ring, middle, index, thumb-bend, thumb-rotation].
"""
from __future__ import annotations

import time
from typing import Any

from teleopit.sim2real.hands.base import HandPoseCommand

MODE_BIT_ANGLE = 0b0001
MODE_BIT_POSITION = 0b0010
MODE_BIT_FORCE = 0b0100
MODE_BIT_SPEED = 0b1000
THUMB_ROTATION_HOLD = 1000


class PresetToggleMapper:
    """Per-side analog-trigger edge toggle between named presets.

    Same discipline as the mp estop grip seam (threshold + edge + debounce),
    but stateful per side: each toggle advances open <-> grasp. Inactive
    (mode-gated) emits nothing — the device holds its last pose.
    """

    def __init__(
        self,
        presets: dict[str, dict[str, Any]],
        sides: list[str],
        *,
        trigger_threshold: float = 0.6,
        trigger_debounce_s: float = 0.25,
        clock: Any = time.monotonic,
    ) -> None:
        if "open" not in presets or "grasp" not in presets:
            raise ValueError("presets must define at least 'open' and 'grasp'")
        self._presets = presets
        self._sides = list(sides)
        self._threshold = float(trigger_threshold)
        self._debounce_s = float(trigger_debounce_s)
        self._clock = clock
        self._current: dict[str, str] = {side: "open" for side in self._sides}
        self._pressed: dict[str, bool] = {side: False for side in self._sides}
        self._last_toggle: dict[str, float | None] = {side: None for side in self._sides}

    def start(self) -> None:
        pass

    def _toggle(self, side: str, now_s: float) -> HandPoseCommand:
        target = "grasp" if self._current[side] != "grasp" else "open"
        self._current[side] = target
        self._last_toggle[side] = now_s
        preset = self._presets[target]
        return HandPoseCommand(
            side=side,
            pose=tuple(int(v) for v in preset["angles"]),
            force=True,
            reason=f"preset:{target}",
            speed_set=tuple(int(v) for v in preset.get("speed") or ()),
            force_set=tuple(int(v) for v in preset.get("force") or ()),
        )

    def map(self, *, controller_snapshot, hand_snapshot, active: bool, now_s: float):
        if not active or controller_snapshot is None:
            return ()
        commands: list[HandPoseCommand] = []
        for side in self._sides:
            state = getattr(controller_snapshot, side, None)
            if state is None or not bool(getattr(state, "present", False)):
                self._pressed[side] = False
                continue
            pressed = float(getattr(state, "trigger", 0.0)) >= self._threshold
            fired = pressed and not self._pressed[side]
            self._pressed[side] = pressed
            if not fired:
                continue
            last = self._last_toggle[side]
            if last is not None and now_s - last < self._debounce_s:
                continue
            commands.append(self._toggle(side, now_s))
        return tuple(commands)

    def close(self) -> None:
        pass
