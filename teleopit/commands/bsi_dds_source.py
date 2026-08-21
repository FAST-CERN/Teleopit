"""DDS-backed IntentSource: adapt a BSI subscriber reader to the intent seam.

Cyclonedds-free: the reader is injected (duck-typed ``.drain() -> list`` of
samples each exposing ``.command.value``, plus ``.close()``). The real reader
is ``bsi_dds.DiscreteCommandSubscriber``, constructed lazily in
``bsi_factory.build_dds_reader`` so importing THIS module never pulls in
cyclonedds — the teleopit env tests inject a fake reader.

``poll()`` returns None on an empty drain (the provider's own 1.0 s silence
check resolves link loss) and maps the newest sample's enum to an int intent
otherwise; unknown values fail safe to IDLE (mirrors bsi_dds.subscriber).
"""
from __future__ import annotations

import time
from typing import Any, Callable

from teleopit.commands.bsi_twist import (
    INTENT_FORWARD,
    INTENT_IDLE,
    INTENT_TURN_LEFT,
    INTENT_TURN_RIGHT,
    DiscreteIntent,
)

_VALID_COMMANDS = {INTENT_IDLE, INTENT_FORWARD, INTENT_TURN_LEFT, INTENT_TURN_RIGHT}


class DdsIntentSource:
    """IntentSource over a raw BSI DDS reader."""

    def __init__(self, reader: Any, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._reader = reader
        self._clock = clock

    def poll(self) -> DiscreteIntent | None:
        drain = getattr(self._reader, "drain", None)
        samples = [] if not callable(drain) else list(drain())
        if not samples:
            return None
        newest = samples[-1]
        try:
            command = int(newest.command.value)
        except (AttributeError, ValueError):
            command = INTENT_IDLE  # unknown on the wire -> fail safe
        if command not in _VALID_COMMANDS:
            command = INTENT_IDLE
        return DiscreteIntent(command=command, rx_time_s=self._clock())

    def close(self) -> None:
        close = getattr(self._reader, "close", None)
        if callable(close):
            close()
