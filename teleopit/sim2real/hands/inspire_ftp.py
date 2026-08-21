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


import dataclasses


@dataclasses.dataclass(frozen=True)
class InspireCtrlMessage:
    angle_set: tuple[int, ...]
    speed_set: tuple[int, ...]
    force_set: tuple[int, ...]
    mode: int


class _RealInspirePublisher:
    """cyclonedds ctrl publisher — created only via the default factory."""

    def __init__(self, cfg: dict) -> None:
        from cyclonedds.domain import DomainParticipant
        from cyclonedds.pub import DataWriter
        from cyclonedds.topic import Topic

        from teleopit.sim2real.hands.inspire_dds_types import InspireHandCtrl

        self._idl = InspireHandCtrl
        domain = int(cfg.get("domain_id", 0))
        prefix = str(cfg.get("ctrl_topic_prefix", "rt/inspire_hand/ctrl"))
        self._participant = DomainParticipant(domain)
        self._writers = {
            "left": DataWriter(self._participant, Topic(self._participant, f"{prefix}/l", InspireHandCtrl)),
            "right": DataWriter(self._participant, Topic(self._participant, f"{prefix}/r", InspireHandCtrl)),
        }

    def publish(self, side: str, message: InspireCtrlMessage) -> None:
        self._writers[side].write(self._idl(
            pos_set=[0] * 6,
            angle_set=[int(v) for v in message.angle_set],
            force_set=[int(v) for v in message.force_set],
            speed_set=[int(v) for v in message.speed_set],
            mode=int(message.mode),
        ))

    def close(self) -> None:
        self._writers = {}


class InspireFtpDevice:
    """HandDevice publishing preset ctrl messages; thumb-rotation pinned here."""

    def __init__(self, cfg: dict, *, publisher_factory=None) -> None:
        self._cfg = cfg
        self._presets = cfg["presets"]
        self._publisher = None
        self._factory = publisher_factory or _RealInspirePublisher
        self._last_pose: dict[str, tuple[int, ...]] = {}

    def connect(self) -> None:
        if self._publisher is None:
            self._publisher = self._factory(self._cfg)

    def get_state(self, side: str) -> tuple[float, ...]:
        return ()  # v1 write-only; state topic subscription is future work

    def _compose(self, pose, speed_set, force_set) -> InspireCtrlMessage:
        angles = [THUMB_ROTATION_HOLD if i == 5 else int(v) for i, v in enumerate(pose[:6])]
        mode = MODE_BIT_ANGLE
        if force_set:
            mode |= MODE_BIT_FORCE
        if speed_set:
            mode |= MODE_BIT_SPEED
        return InspireCtrlMessage(tuple(angles), tuple(speed_set), tuple(force_set), mode)

    def send_pose(self, side, pose, *, force=False, reason="", speed_set=(), force_set=()) -> None:
        pose_t = tuple(int(v) for v in pose[:6])
        if not force and self._last_pose.get(side) == (pose_t, tuple(speed_set), tuple(force_set)):
            return
        self._last_pose[side] = (pose_t, tuple(speed_set), tuple(force_set))
        self.connect()
        self._publisher.publish(side, self._compose(pose_t, speed_set, force_set))

    def open_all(self, *, force=False, reason="") -> None:
        open_preset = self._presets["open"]
        for side in ("left", "right"):
            self.send_pose(
                side, open_preset["angles"], force=True, reason=reason or "open_all",
                speed_set=tuple(open_preset.get("speed") or ()),
                force_set=tuple(open_preset.get("force") or ()),
            )

    def close(self) -> None:
        if self._publisher is not None:
            self._publisher.close()
            self._publisher = None


def build_inspire_ftp(cfg: Any):
    from teleopit.sim2real.hands.worker import HandRuntime

    hands_cfg = cfg.get("hands", {}) if isinstance(cfg, dict) else getattr(cfg, "hands", {})
    dev_cfg = dict(hands_cfg.get("inspire_ftp", {}) or {})
    dev_cfg.setdefault("presets", {
        "open": {"angles": [1000] * 6, "speed": None, "force": None},
        "grasp": {"angles": [0, 0, 0, 0, 300, 1000], "speed": None, "force": None},
    })
    device = InspireFtpDevice(dev_cfg)
    mapper = PresetToggleMapper(
        dev_cfg["presets"], list(hands_cfg.get("sides", ["left", "right"])),
        trigger_threshold=float(dev_cfg.get("trigger_threshold", 0.6)),
        trigger_debounce_s=float(dev_cfg.get("trigger_debounce_s", 0.25)),
    )
    return HandRuntime(device=device, mapper=mapper)
