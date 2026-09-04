"""Tracker recording replay: envelope parsing + paced replay bridge (mocap map t08).

The replay bridge lets a recorded tracking JSONL (the t03/t04 receiver
recording format) drive the unmodified Pico4InputProvider body path —
synthesis, coordinate transform, ground alignment, frame cache — exactly
like a live device, so ``scripts/run/replay_tracker_mocap.py`` renders the
synthesized skeleton through the same code the sim loop uses.
"""

from __future__ import annotations

import json
import time
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from teleopit.inputs.tracker_replay import (
    TrackerReplayBridge,
    frame_from_record,
    iter_tracking_records,
)


def _record(
    seq: int,
    recorded_s: float,
    *,
    head: str = "0,1.7,0,0,0,0,1",
    left: str = "-0.2,1.4,0.1,0,0,0,1",
    right: str = "0.2,1.4,0.1,0,0,0,1",
    valid: bool = True,
    type_: str = "tracking",
) -> dict[str, Any]:
    return {
        "type": type_,
        "seq": seq,
        "recorded_at_ns": int(recorded_s * 1e9),
        "payload": {
            "timeStampNs": int(recorded_s * 1e9),
            "Head": {"pose": head, "status": 3},
            "Motion": {
                "poseSpace": "pico_tracker_local",
                "left": {"sn": 1, "p": left, "valid": valid},
                "right": {"sn": 2, "p": right, "valid": valid},
            },
        },
    }


def _write_recording(path: Path, records: list[dict[str, Any]]) -> Path:
    with open(path, "w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")
    return path


@pytest.fixture()
def recording(tmp_path: Path) -> Path:
    records = [
        _record(10, 100.0),
        _record(11, 100.02),
        _record(12, 100.04),
        _record(13, 100.06),
        _record(14, 100.08),
    ]
    return _write_recording(tmp_path / "replay.jsonl", records)


class TestIterTrackingRecords:
    def test_filters_to_tracking_records(self, recording: Path) -> None:
        noisy = recording.parent / "noisy.jsonl"
        records = [json.loads(line) for line in open(recording, encoding="utf-8")]
        records.insert(2, {"type": "video", "seq": 99, "recorded_at_ns": 1, "payload": {}})
        records.append({"type": "tracking", "seq": 15, "recorded_at_ns": int(100.1e9), "payload": {}})
        _write_recording(noisy, records)
        assert [r["seq"] for r in iter_tracking_records(noisy)] == [10, 11, 12, 13, 14, 15]

    def test_empty_recording_raises(self, tmp_path: Path) -> None:
        empty = _write_recording(tmp_path / "empty.jsonl", [])
        with pytest.raises(ValueError, match="tracking"):
            list(iter_tracking_records(empty))


class TestFrameFromRecord:
    def test_parses_envelope_and_motion_side_first(self) -> None:
        record = _record(42, 100.0, left="-0.16,1.42,0.13,0.15,0.6,0.78,0.05", valid=True)
        frame = frame_from_record(record)

        assert frame.seq == 42
        assert frame.receive_time_s == pytest.approx(100.0)
        assert frame.head.position == pytest.approx([0.0, 1.7, 0.0])
        assert frame.trackers.left.sn == 1
        assert frame.trackers.left.valid is True
        assert frame.trackers.left.pose.position == pytest.approx([-0.16, 1.42, 0.13])
        assert frame.trackers.left.pose.rotation == pytest.approx([0.15, 0.6, 0.78, 0.05])
        assert frame.trackers.right.sn == 2
        assert frame.body.active is False

    def test_head_defaults_when_missing(self) -> None:
        record = _record(1, 1.0)
        del record["payload"]["Head"]
        frame = frame_from_record(record)
        assert frame.head.position == pytest.approx([0.0, 1.7, 0.0])
        assert frame.head.rotation == pytest.approx([0.0, 0.0, 0.0, 1.0])

    def test_missing_motion_side_yields_none_tracker(self) -> None:
        record = _record(1, 1.0)
        del record["payload"]["Motion"]["left"]
        frame = frame_from_record(record)
        assert frame.trackers.left is None
        assert frame.trackers.right is not None

    def test_explicit_receive_time_override(self) -> None:
        frame = frame_from_record(_record(1, 1.0), receive_time_s=7.5)
        assert frame.receive_time_s == 7.5


class TestTrackerReplayBridge:
    def _bridge(self, path: Path, *, speed: float = 1000.0, **kwargs: Any) -> TrackerReplayBridge:
        bridge = TrackerReplayBridge(path=path, speed=speed, loop=False, **kwargs)
        bridge.start()
        return bridge

    def test_yields_frames_in_order_and_honors_after_seq(self, recording: Path) -> None:
        bridge = self._bridge(recording)
        first = bridge.wait_frame(timeout=1.0)
        assert first.seq == 10
        second = bridge.wait_frame(timeout=1.0, after_seq=12)  # skips 11 and 12
        assert second.seq == 13
        bridge.close()

    def test_timeout_when_exhausted_without_loop(self, recording: Path) -> None:
        bridge = self._bridge(recording)
        for _ in range(5):
            bridge.wait_frame(timeout=1.0)
        with pytest.raises(TimeoutError):
            bridge.wait_frame(timeout=0.05)
        bridge.close()

    def test_pacing_follows_recorded_timeline(self, tmp_path: Path) -> None:
        spaced = _write_recording(
            tmp_path / "spaced.jsonl",
            [_record(1, 0.0), _record(2, 0.4)],
        )
        bridge = self._bridge(spaced, speed=1.0)
        started = time.monotonic()
        bridge.wait_frame(timeout=1.0)
        bridge.wait_frame(timeout=1.0)
        elapsed = time.monotonic() - started
        assert elapsed >= 0.3, f"second frame arrived after only {elapsed:.3f}s — pacing ignored"
        bridge.close()

    def test_timeout_raised_when_next_frame_beyond_deadline(self, tmp_path: Path) -> None:
        spaced = _write_recording(
            tmp_path / "spaced.jsonl",
            [_record(1, 0.0), _record(2, 5.0)],
        )
        bridge = self._bridge(spaced, speed=1.0)
        bridge.wait_frame(timeout=1.0)
        with pytest.raises(TimeoutError):
            bridge.wait_frame(timeout=0.1)  # next frame is 5s out
        bridge.close()

    def test_loop_continues_with_monotonic_seq_and_time(self, recording: Path) -> None:
        bridge = TrackerReplayBridge(path=recording, speed=1000.0, loop=True)
        bridge.start()
        seqs = [bridge.wait_frame(timeout=1.0).seq for _ in range(7)]
        assert seqs == [10, 11, 12, 13, 14, 15, 16], "loop restart must continue the seq series"
        bridge.close()

    def test_loop_receive_time_is_monotonic_across_seam(self, recording: Path) -> None:
        bridge = TrackerReplayBridge(path=recording, speed=1000.0, loop=True)
        bridge.start()
        times = [bridge.wait_frame(timeout=1.0).receive_time_s for _ in range(7)]
        assert all(b > a for a, b in zip(times, times[1:])), f"receive_time went backwards: {times}"
        assert times[5] > times[4], "seam frame must not rewind time"
        bridge.close()

    def test_ignores_provider_constructor_kwargs(self, recording: Path) -> None:
        bridge = TrackerReplayBridge(
            path=recording,
            speed=1000.0,
            loop=False,
            host="0.0.0.0",
            port=63901,
            discovery=True,
            advertise_ip=None,
            video=None,
            video_enabled=False,
            motion_enabled=True,
            history_size=120,
            start_timeout=10.0,
        )
        bridge.start()
        assert bridge.wait_frame(timeout=1.0).seq == 10
        bridge.close()


class TestProviderReplayEndToEnd:
    def test_provider_synthesizes_from_replay_bridge(self, recording: Path) -> None:
        from teleopit.inputs.pico4_provider import Pico4InputProvider

        provider = Pico4InputProvider(
            arm_source="tracker",
            timeout=2.0,
            pause_button=None,
            arms_button=None,
            bridge_cls=partial(TrackerReplayBridge, path=recording, speed=1000.0, loop=True),
        )
        try:
            deadline = time.monotonic() + 5.0
            while not provider.has_frame():
                if time.monotonic() > deadline:
                    pytest.fail("provider never produced a frame from the replay bridge")
                time.sleep(0.05)
            frame = provider.get_frame()
            assert "Left_Wrist" in frame and "Right_Wrist" in frame
            positions = [frame[name][0] for name in provider.bone_names]
            assert all(len(p) == 3 for p in positions)
            assert frame["Left_Wrist"][0][0] < frame["Right_Wrist"][0][0], "left wrist must sit left of right"
        finally:
            provider.close()
