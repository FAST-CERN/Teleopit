"""Factory: build the merged_bsi command provider (joystick primary, BSI secondary).

The single place that imports bsi_dds/cyclonedds — lazily, inside
``build_dds_reader`` — so the default pico_joystick/keyboard paths never touch
DDS. ``reader_factory`` is injectable so tests in the teleopit env (no
cyclonedds) can exercise the full assembly with a fake source.
"""
from __future__ import annotations

import time
from typing import Any, Callable

from teleopit.commands.bsi_dds_source import DdsIntentSource
from teleopit.commands.bsi_twist import BsiTwistProvider
from teleopit.commands.merged_twist import MergedTwistProvider


def build_dds_reader(bsi_cfg: dict[str, Any], clock: Callable[[], float]) -> DdsIntentSource:
    """Construct the real bsi_dds reader (lazy cyclonedds import — dds-probe env)."""
    from bsi_dds import DiscreteCommandSubscriber

    reader = DiscreteCommandSubscriber(
        domain_id=int(bsi_cfg.get("domain_id", 0)),
        interface=bsi_cfg.get("interface") or None,
    )
    return DdsIntentSource(reader, clock=clock)


def build_merged_bsi_provider(
    joystick_provider: Any,
    bsi_cfg: dict[str, Any],
    *,
    clock: Callable[[], float] = time.monotonic,
    reader_factory: Callable[[dict[str, Any], Callable[[], float]], DdsIntentSource] | None = None,
) -> MergedTwistProvider:
    """Assemble joystick(primary) + BSI(secondary) into one CommandProvider."""
    factory = reader_factory or build_dds_reader
    source = factory(bsi_cfg, clock)
    bsi = BsiTwistProvider(
        source,
        alpha=float(bsi_cfg.get("alpha", 0.3)),
        debounce_packets=int(bsi_cfg.get("debounce_packets", 3)),
        idle_debounce_packets=int(bsi_cfg.get("idle_debounce_packets", 2)),
        silence_timeout_s=float(bsi_cfg.get("silence_timeout_s", 1.0)),
        speeds=dict(bsi_cfg.get("speeds", {}) or {}) or None,
        clock=clock,
    )
    return MergedTwistProvider(joystick_provider, bsi)
