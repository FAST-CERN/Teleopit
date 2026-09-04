"""Replay a recorded pico_bridge tracking JSONL through the live provider path (mocap map t08).

The receiver recording format is a JSONL envelope per line::

    {"type": "tracking", "seq": N, "recorded_at_ns": ..., "payload": {...}}

with the motion-tracker data inside ``payload["Motion"]`` (side-first:
``left``/``right`` each ``{sn, p, valid}``, pose as a comma string
``x,y,z,qx,qy,qz,qw`` in ``pico_tracker_local``).  :class:`TrackerReplayBridge`
turns such a file into a bridge the unmodified ``Pico4InputProvider`` poll
loop can consume, paced by the recorded timeline so hold-window and
timestamp-gap-reset semantics behave like a live device.  This is the engine
behind ``scripts/run/replay_tracker_mocap.py`` (skeleton viewer without sim).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator

_DEFAULT_HEAD_POSE = "0,1.7,0,0,0,0,1"


def iter_tracking_records(path: str | Path) -> Iterator[dict[str, Any]]:
    """Yield parsed tracking envelopes from a receiver recording, in file order."""
    path = Path(path)
    found = False
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("type") != "tracking":
                continue
            found = True
            yield record
    if not found:
        raise ValueError(f"no tracking records in recording: {path}")


def _pose(raw: dict[str, Any] | None) -> SimpleNamespace | None:
    if raw is None:
        return None
    values = [float(v) for v in str(raw["p"]).split(",")]
    return SimpleNamespace(
        position=values[0:3],
        rotation=values[3:7],
    )


def frame_from_record(
    record: dict[str, Any],
    *,
    receive_time_s: float | None = None,
    seq: int | None = None,
) -> SimpleNamespace:
    """Build a pico_bridge-shaped frame from one recording envelope.

    Mirrors what the live ``PicoBridge`` receiver hands the provider: head
    pose (default standing pose when the payload has none), side-first
    motion trackers, inactive body, empty controllers.
    """
    payload = record["payload"]
    head_raw = payload.get("Head", {})
    head_pose = _pose({"p": head_raw.get("pose", _DEFAULT_HEAD_POSE)} if head_raw else None)
    if head_pose is None:
        head_pose = _pose({"p": _DEFAULT_HEAD_POSE})
    motion = payload.get("Motion", {})

    # Device-uptime timeStampNs is the default receive timeline (matches the
    # live receiver frames the hold-window logic was tuned against); fall back
    # to the envelope's receiver wall clock for recordings that lack it.
    timestamp_ns = payload.get("timeStampNs")
    if timestamp_ns is None:
        timestamp_ns = record.get("recorded_at_ns", 0)

    return SimpleNamespace(
        seq=int(record["seq"] if seq is None else seq),
        receive_time_s=float(timestamp_ns / 1e9) if receive_time_s is None else float(receive_time_s),
        head=head_pose,
        body=SimpleNamespace(active=False, joints=None),
        trackers=SimpleNamespace(
            left=None if "left" not in motion else SimpleNamespace(
                sn=int(motion["left"].get("sn", 0)),
                valid=bool(motion["left"].get("valid")),
                pose=_pose(motion["left"]),
            ),
            right=None if "right" not in motion else SimpleNamespace(
                sn=int(motion["right"].get("sn", 0)),
                valid=bool(motion["right"].get("valid")),
                pose=_pose(motion["right"]),
            ),
        ),
        controllers=SimpleNamespace(
            left=SimpleNamespace(buttons={}),
            right=SimpleNamespace(buttons={}),
        ),
    )


class TrackerReplayBridge:
    """Drop-in bridge replaying a recording through ``Pico4InputProvider``.

    ``wait_frame`` paces delivery against the recorded ``recorded_at_ns``
    timeline (scaled by ``speed``).  With ``loop=True`` the recording replays
    periodically: sequence numbers and receive timestamps continue monotonically
    across the seam so the provider's after_seq / gap-reset bookkeeping never
    rewinds.  Constructor swallows the provider's bridge kwargs (host, port,
    video, ...) — there is no network.
    """

    def __init__(
        self,
        *,
        path: str | Path,
        speed: float = 1.0,
        loop: bool = True,
        **provider_kwargs: Any,
    ) -> None:
        if speed <= 0.0:
            raise ValueError(f"speed must be > 0, got {speed}")
        self._path = Path(path)
        self._speed = float(speed)
        self._loop = bool(loop)
        self._records = list(iter_tracking_records(self._path))
        self._rel_s: list[float] = self._relative_timeline(self._records)
        # One playback period: recording span plus the first inter-frame gap,
        # so the seam advances time like any other frame interval.
        first_dt = self._rel_s[1] - self._rel_s[0] if len(self._rel_s) > 1 else 0.02
        self._iteration_s = (self._rel_s[-1] + first_dt) if self._rel_s else 0.0
        base_ns = self._records[0].get("recorded_at_ns")
        self._base_receive_s = float((base_ns if base_ns is not None else 0) / 1e9)
        seqs = [int(r["seq"]) for r in self._records]
        self._seq_span = max(seqs) - min(seqs) + 1
        self._started = False
        self._closed = False
        self._t0: float | None = None  # wall-clock anchor of the first wait_frame
        self._iteration = 0
        self._cursor = 0
        self._emitted = 0

    @staticmethod
    def _relative_timeline(records: list[dict[str, Any]]) -> list[float]:
        base_ns = records[0].get("recorded_at_ns")
        base_ns = base_ns if base_ns is not None else records[0]["payload"].get("timeStampNs", 0)
        rel = []
        for record in records:
            ns = record.get("recorded_at_ns")
            if ns is None:
                ns = record["payload"].get("timeStampNs", 0)
            rel.append(max(0.0, (ns - base_ns) / 1e9))
        return rel

    def start(self) -> None:
        self._started = True

    def close(self) -> None:
        self._closed = True

    def __len__(self) -> int:
        return len(self._records)

    @property
    def iteration(self) -> int:
        """Playback iteration count (0 until the first seam)."""
        return self._iteration

    def wait_frame(self, timeout: float = 1.0, after_seq: int | None = None) -> SimpleNamespace:
        """Return the next paced frame, or raise ``TimeoutError``.

        Raises ``TimeoutError`` when the next frame is further out than
        ``timeout`` (the provider poll loop retries), when the recording is
        exhausted with ``loop=False``, or when the bridge is closed.
        """
        if not self._started or self._closed:
            raise TimeoutError("replay bridge is not running")
        if self._t0 is None:
            self._t0 = time.monotonic()

        while True:
            if self._cursor >= len(self._records):
                if not self._loop:
                    raise TimeoutError("recording exhausted")
                self._iteration += 1
                self._cursor = 0

            idx = self._cursor
            playhead_s = self._iteration * self._iteration_s + self._rel_s[idx]
            remaining = self._t0 + playhead_s / self._speed - time.monotonic()
            if remaining > 0.0:
                if remaining > timeout:
                    raise TimeoutError(f"next replay frame in {remaining:.3f}s")
                time.sleep(remaining)

            record = self._records[idx]
            self._cursor += 1
            seq = int(record["seq"]) + self._iteration * self._seq_span
            receive_s = self._base_receive_s + self._iteration * self._iteration_s + self._rel_s[idx]
            frame = frame_from_record(record, receive_time_s=receive_s, seq=seq)
            self._emitted += 1
            if after_seq is not None and frame.seq <= int(after_seq):
                continue
            return frame
