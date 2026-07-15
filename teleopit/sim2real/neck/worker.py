from __future__ import annotations

import logging
import time
from typing import Any

from teleopit.inputs.realtime_packet import HumanFrame
from teleopit.sim2real.neck.config import NeckConfig, parse_neck_config
from teleopit.sim2real.neck.mapper import HeadPoseMapper, NeckCommand
from teleopit.sim2real.neck.openneck import NeckDevice, build_neck_device

logger = logging.getLogger(__name__)


class NeckRuntime:
    def __init__(self, config: NeckConfig, device: NeckDevice | None = None) -> None:
        self._cfg = config
        self._device = device or build_neck_device(config)
        self._mapper = HeadPoseMapper(config)

    def start(self) -> None:
        self._device.connect()
        if self._cfg.center_on_start:
            self._device.center()

    def tick(
        self,
        *,
        frame: HumanFrame | None,
        frame_timestamp_s: float | None,
        active: bool,
        now_s: float | None = None,
    ) -> NeckCommand | None:
        now = time.monotonic() if now_s is None else float(now_s)
        if not active or frame is None or frame_timestamp_s is None:
            return None
        if now - float(frame_timestamp_s) > self._cfg.frame_timeout_s:
            return None
        command = self._mapper.map_frame(frame)
        if command is None:
            return None
        applied_yaw_deg, applied_pitch_deg = self._device.move_deg(
            command.yaw_deg,
            command.pitch_deg,
        )
        return NeckCommand(
            yaw_deg=applied_yaw_deg,
            pitch_deg=applied_pitch_deg,
            roll_deg=command.roll_deg,
        )

    def close(self) -> None:
        try:
            if self._cfg.center_on_shutdown:
                try:
                    self._device.center()
                except Exception:
                    logger.exception("Failed to center OpenNeck on shutdown; closing device")
            if self._cfg.release_on_shutdown:
                try:
                    self._device.release_torque()
                except Exception:
                    logger.exception("Failed to release OpenNeck torque on shutdown; closing device")
        finally:
            self._device.close()


class DisabledNeckRuntime:
    def start(self) -> None:
        return None

    def tick(
        self,
        *,
        frame: HumanFrame | None,
        frame_timestamp_s: float | None,
        active: bool,
        now_s: float | None = None,
    ) -> None:
        del frame, frame_timestamp_s, active, now_s
        return None

    def close(self) -> None:
        return None


def build_neck_runtime(cfg: Any | NeckConfig, device: NeckDevice | None = None) -> NeckRuntime | DisabledNeckRuntime:
    neck_cfg = cfg if isinstance(cfg, NeckConfig) else parse_neck_config(cfg)
    if not neck_cfg.enabled:
        return DisabledNeckRuntime()
    return NeckRuntime(neck_cfg, device=device)


def mode_packet_active(mode_packet: object | None, config: NeckConfig) -> bool:
    if mode_packet is None:
        return False
    mode = "pause" if bool(getattr(mode_packet, "mocap_paused", False)) else str(getattr(mode_packet, "mode", "")).strip().lower()
    return mode in config.active_modes


def body_packet_frame(packet: object | None) -> tuple[HumanFrame | None, float | None, int]:
    if packet is None or not all(hasattr(packet, attr) for attr in ("frame", "timestamp_s", "seq")):
        return None, None, -1
    try:
        return getattr(packet, "frame"), float(getattr(packet, "timestamp_s")), int(getattr(packet, "seq"))
    except (TypeError, ValueError):
        return None, None, -1
