"""BSI discrete-intent twist source: debounce -> map -> exponential smoothing.

The provider consumes an IntentSource (poll-based, injectable — a scripted
source in tests, the DDS subscriber thread in phase 2) and exposes the
CommandProvider seam. Locked parameters (wayfinder bsi-dds-02): forward
0.6 m/s, in-place turns ±0.6 rad/s, alpha-0.3 smoothing, 3-packet debounce
to switch intent / 2 packets to enter IDLE, 1.0 s silence -> IDLE.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Protocol

import numpy as np

# Intent enum ints — mirror bsi_dds.protocol (IDLE=0 fail-safe). Duplicated
# deliberately: phase 1 must not import bsi_dds (cyclonedds-free).
INTENT_IDLE = 0
INTENT_FORWARD = 1
INTENT_TURN_LEFT = 2
INTENT_TURN_RIGHT = 3

_DEFAULT_SPEEDS = {"forward": 0.6, "turn": 0.6}


@dataclass(frozen=True)
class DiscreteIntent:
    """One observed intent: the command value and when it was received."""

    command: int
    rx_time_s: float


class IntentSource(Protocol):
    """Yields newly arrived intents; None when nothing arrived since last poll."""

    def poll(self) -> DiscreteIntent | None: ...

    def close(self) -> None: ...


class ScriptedIntentSource:
    """Replays a (command, hold_seconds) script — the phase-1 test source.

    poll() returns the current segment's intent stamped with the segment
    start time, at most once per 1/rate_hz window (a packet generator, not a
    step function): repeated polls inside one window return None.
    """

    def __init__(
        self,
        script: list[tuple[int, float]],
        clock: Callable[[], float] = time.monotonic,
        *,
        rate_hz: float = 10.0,
    ) -> None:
        self._clock = clock
        self._period = 1.0 / float(rate_hz)
        self._segments: list[tuple[int, float, float]] = []  # (cmd, start, end)
        t = 0.0
        for command, hold in script:
            self._segments.append((int(command), t, t + float(hold)))
            t += float(hold)
        self._last_emit_t: float | None = None

    def poll(self) -> DiscreteIntent | None:
        now = self._clock()
        # Epsilon-tolerant rate limit: 0.1s float accumulation (0.1*3 ==
        # 0.30000000000000004) must not eat an emit slot.
        if (
            self._last_emit_t is not None
            and now - self._last_emit_t < self._period - 1e-9
        ):
            return None
        for command, start, end in self._segments:
            if start <= now < end:
                self._last_emit_t = now
                return DiscreteIntent(command=command, rx_time_s=now)
        # Past the script end: hold the last segment forever (tests rely on it).
        command, start, _end = self._segments[-1]
        self._last_emit_t = now
        return DiscreteIntent(command=command, rx_time_s=now)

    def close(self) -> None:
        return None


class BsiTwistProvider:
    """CommandProvider over a discrete-intent stream.

    Pipeline per get_cmd: poll -> silence check -> debounce -> mute -> map
    -> exponential smoothing. Clock is injectable; get_cmd never raises.
    """

    def __init__(
        self,
        source: IntentSource,
        *,
        alpha: float = 0.3,
        debounce_packets: int = 3,
        idle_debounce_packets: int = 2,
        silence_timeout_s: float = 1.0,
        speeds: dict[str, float] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not 0.0 < float(alpha) <= 1.0:
            raise ValueError(f"alpha must be in (0, 1], got {alpha}")
        self._source = source
        self._alpha = float(alpha)
        self._debounce = int(debounce_packets)
        self._idle_debounce = int(idle_debounce_packets)
        self._silence_timeout_s = float(silence_timeout_s)
        sp = dict(_DEFAULT_SPEEDS)
        if speeds:
            sp.update(speeds)
        self._forward = float(sp["forward"])
        self._turn = float(sp["turn"])
        self._clock = clock

        self._intent = INTENT_IDLE  # effective (debounced) intent
        self._streak_cmd: int | None = None  # command of current packet streak
        self._streak_len = 0
        self._last_rx_s: float | None = None
        self._muted = False
        self._smoothed = np.zeros(6, dtype=np.float32)

    # -- intent pipeline --------------------------------------------------

    def _poll_intent(self) -> None:
        now = self._clock()
        intent = self._source.poll()
        if intent is not None:
            self._last_rx_s = intent.rx_time_s
            # Packet streak -> debounce (asymmetric: IDLE enters faster).
            if intent.command == self._streak_cmd:
                self._streak_len += 1
            else:
                self._streak_cmd = intent.command
                self._streak_len = 1
            needed = self._idle_debounce if intent.command == INTENT_IDLE else self._debounce
            if self._streak_len >= needed and intent.command != self._intent:
                self._intent = intent.command
        # Silence: link lost -> IDLE (and clear the streak; silence is a
        # link event, not a label event).
        if (
            self._last_rx_s is None
            or now - self._last_rx_s > self._silence_timeout_s
        ):
            self._intent = INTENT_IDLE
            self._streak_cmd = None
            self._streak_len = 0

    def _target(self) -> np.ndarray:
        effective = INTENT_IDLE if self._muted else self._intent
        target = np.zeros(6, dtype=np.float32)
        if effective == INTENT_FORWARD:
            target[0] = np.float32(self._forward)
        elif effective == INTENT_TURN_LEFT:
            target[5] = np.float32(self._turn)
        elif effective == INTENT_TURN_RIGHT:
            target[5] = np.float32(-self._turn)
        return target

    # -- CommandProvider seam ----------------------------------------------

    def get_cmd(self) -> np.ndarray:
        self._poll_intent()
        target = self._target()
        self._smoothed = np.asarray(
            self._smoothed + self._alpha * (target - self._smoothed),
            dtype=np.float32,
        )
        return self._smoothed.copy()

    def reset(self) -> None:
        # Motion state clears; mute is operator state and survives.
        self._intent = INTENT_IDLE
        self._streak_cmd = None
        self._streak_len = 0
        self._last_rx_s = None
        self._smoothed = np.zeros(6, dtype=np.float32)

    def close(self) -> None:
        close = getattr(self._source, "close", None)
        if callable(close):
            close()

    # -- mute (wayfinder bsi-dds-05) ---------------------------------------

    def toggle_mute(self) -> bool:
        """Cut/uncut the brain source: muted forces IDLE, subscription lives."""
        self._muted = not self._muted
        return self._muted

    @property
    def muted(self) -> bool:
        return self._muted
