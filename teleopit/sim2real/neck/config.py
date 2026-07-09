from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from teleopit.runtime.common import cfg_get

VALID_NECK_ACTIVE_MODES = frozenset(("standing", "mocap", "arms", "pause"))


@dataclass(frozen=True)
class NeckConfig:
    enabled: bool = False
    driver: str = "openneck"
    config_path: str | None = None
    port: str | None = None
    rate_hz: float = 60.0
    frame_timeout_s: float = 0.2
    active_modes: tuple[str, ...] = ("standing", "mocap", "arms", "pause")
    head_joint: str = "Head"
    body_reference_joint: str = "Spine3"
    use_body_reference: bool = True
    dead_zone_deg: float = 0.5
    smoothing_alpha: float = 0.35
    yaw_range_deg: float = 90.0
    pitch_range_deg: float = 60.0
    invert_yaw: bool = True
    invert_pitch: bool = True
    center_on_start: bool = True
    center_on_shutdown: bool = False
    release_on_shutdown: bool = False
    dry_run: bool = False


def parse_neck_config(cfg: Any) -> NeckConfig:
    neck_cfg = cfg_get(cfg, "neck", {}) or {}
    active_modes = _parse_active_modes(cfg_get(neck_cfg, "active_modes", ["standing", "mocap", "arms", "pause"]))
    rate_hz = float(cfg_get(neck_cfg, "rate_hz", 60.0))
    if rate_hz <= 0:
        raise ValueError("neck.rate_hz must be > 0")
    frame_timeout_s = float(cfg_get(neck_cfg, "frame_timeout_s", 0.2))
    if frame_timeout_s <= 0:
        raise ValueError("neck.frame_timeout_s must be > 0")
    smoothing_alpha = float(cfg_get(neck_cfg, "smoothing_alpha", 0.35))
    if not 0.0 < smoothing_alpha <= 1.0:
        raise ValueError("neck.smoothing_alpha must be in (0, 1]")
    dead_zone_deg = float(cfg_get(neck_cfg, "dead_zone_deg", 0.5))
    if dead_zone_deg < 0:
        raise ValueError("neck.dead_zone_deg must be >= 0")
    yaw_range_deg = float(cfg_get(neck_cfg, "yaw_range_deg", 90.0))
    pitch_range_deg = float(cfg_get(neck_cfg, "pitch_range_deg", 60.0))
    if yaw_range_deg <= 0:
        raise ValueError("neck.yaw_range_deg must be > 0")
    if pitch_range_deg <= 0:
        raise ValueError("neck.pitch_range_deg must be > 0")
    config_path = cfg_get(neck_cfg, "config_path", None)
    if config_path in ("", "null"):
        config_path = None
    elif config_path is not None:
        config_path = str(Path(str(config_path)).expanduser())
    port = cfg_get(neck_cfg, "port", None)
    if port in ("", "null"):
        port = None
    return NeckConfig(
        enabled=bool(cfg_get(neck_cfg, "enabled", False)),
        driver=str(cfg_get(neck_cfg, "driver", "openneck")).strip().lower(),
        config_path=config_path,
        port=None if port is None else str(port),
        rate_hz=rate_hz,
        frame_timeout_s=frame_timeout_s,
        active_modes=active_modes,
        head_joint=str(cfg_get(neck_cfg, "head_joint", "Head")),
        body_reference_joint=str(cfg_get(neck_cfg, "body_reference_joint", "Spine3")),
        use_body_reference=bool(cfg_get(neck_cfg, "use_body_reference", True)),
        dead_zone_deg=dead_zone_deg,
        smoothing_alpha=smoothing_alpha,
        yaw_range_deg=yaw_range_deg,
        pitch_range_deg=pitch_range_deg,
        invert_yaw=bool(cfg_get(neck_cfg, "invert_yaw", True)),
        invert_pitch=bool(cfg_get(neck_cfg, "invert_pitch", True)),
        center_on_start=bool(cfg_get(neck_cfg, "center_on_start", True)),
        center_on_shutdown=bool(cfg_get(neck_cfg, "center_on_shutdown", False)),
        release_on_shutdown=bool(cfg_get(neck_cfg, "release_on_shutdown", False)),
        dry_run=bool(cfg_get(neck_cfg, "dry_run", False)),
    )


def _parse_active_modes(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        modes = (value.strip().lower(),)
    elif isinstance(value, Iterable):
        modes = tuple(str(mode).strip().lower() for mode in value)
    else:
        raise ValueError("neck.active_modes must be a mode string or a list of modes")
    modes = tuple(mode for mode in modes if mode)
    if not modes:
        raise ValueError("neck.active_modes must contain at least one mode")
    unsupported = sorted(set(modes).difference(VALID_NECK_ACTIVE_MODES))
    if unsupported:
        raise ValueError(
            "neck.active_modes contains unsupported modes "
            f"{unsupported}; supported modes: {sorted(VALID_NECK_ACTIVE_MODES)}"
        )
    return modes
