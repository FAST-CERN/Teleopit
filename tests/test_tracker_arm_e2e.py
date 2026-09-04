"""End-to-end acceptance vehicle for the tracker-arm synthesis chain (mocap map t06).

Replays a real recorded tracker stream (tests/data/tracker_replay_slice.jsonl,
captured on device 2026-09-04) through the full provider body path
(arm_source=tracker) into the real GMR/mink retargeter, then checks the four
acceptance lines that can be measured headless:

1. 采集质量 — recorded stream rate + per-frame synth->retarget processing time
2. 跟随稳定 — qpos finite throughout, bounded per-step joint deltas, real range of motion
3. 断连安全 — dropout beyond the hold window starves the provider; recovery resumes

Line 4 (主观, operator in headset) runs live, not here.
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from teleopit.inputs.pico4_provider import Pico4InputProvider
from teleopit.inputs.realtime_frame_cache import RealtimeFrameCache
from teleopit.inputs.tracker_arm_synth import SynthConfig, TrackerArmSynthesizer

SLICE_PATH = Path(__file__).parent / "data" / "tracker_replay_slice.jsonl"
ARM_JOINT_SLICE = slice(7 + 15, 7 + 29)  # qpos arm joints (robot side, idx 15-28)
PROCESSING_BUDGET_S = 10e-3  # per-frame synth+retarget budget
WARMSTART_TRANSITIONS = 5  # IK warm-start settling after a fresh/reset retargeter
# (the sim loop covers this via retargeter.reset() on MOCAP entry + the
# 10-consecutive-valid-frame gate); steady state bound below catches IK
# branch flips / oscillation-class jumps (real fast arm swings measure ~0.49).
MAX_STEP_DELTA_RAD = 0.6  # oscillation guard per arm joint per frame, steady state
MIN_RANGE_RAD = 0.3  # arms must actually move across the slice


def _provider() -> Pico4InputProvider:
    provider = object.__new__(Pico4InputProvider)
    provider._lock = threading.Lock()
    provider._frame_ready = threading.Event()
    provider._frame_cache = RealtimeFrameCache(buffer_size=256, fps_window=30)
    provider._timeout = 1.0
    provider._timestamp_gap_reset_s = 0.15
    provider._pending_control_events = deque()
    provider._pause_button = None
    provider._arms_button = None
    provider._pause_button_path = None
    provider._arms_button_path = None
    provider._pause_debounce_s = 0.0
    provider._arms_debounce_s = 0.0
    provider._last_pause_button_pressed = False
    provider._last_arms_button_pressed = False
    provider._last_pause_toggle_timestamp = None
    provider._last_arms_toggle_timestamp = None
    provider._estop_button = None
    provider._mute_button = None
    provider._estop_button_path = None
    provider._mute_button_path = None
    provider._estop_debounce_s = 0.0
    provider._mute_debounce_s = 0.0
    provider._last_estop_button_pressed = False
    provider._last_mute_button_pressed = False
    provider._last_estop_toggle_timestamp = None
    provider._last_mute_toggle_timestamp = None
    provider._velocity_button = None
    provider._velocity_button_path = None
    provider._velocity_debounce_s = 0.25
    provider._last_velocity_button_pressed = False
    provider._last_velocity_toggle_timestamp = None
    provider._estop_grip_threshold = 0.6
    provider._estop_is_grip = False
    provider._estop_grip_side = "right"
    provider._last_grip_pressed = False
    provider._last_raw_body_joints = None
    provider._last_frame_timestamp = None
    provider._last_source_seq = None
    provider._ground_alignment_offset = None
    provider._controller_snapshot = None
    provider._hand_snapshot = None
    provider._head_pose_snapshot = None
    provider._tracker_snapshot = None
    provider._closed = False
    provider._arm_synth = TrackerArmSynthesizer(SynthConfig())
    return provider


def _pose(raw: dict[str, Any] | None) -> SimpleNamespace | None:
    if raw is None:
        return None
    values = [float(v) for v in str(raw["p"]).split(",")]
    return SimpleNamespace(
        position=np.asarray(values[0:3], dtype=np.float64),
        rotation=np.asarray(values[3:7], dtype=np.float64),
    )


def _replay_frame(payload: dict[str, Any], *, receive_time_s: float | None = None) -> SimpleNamespace:
    head_raw = payload.get("Head", {})
    head_pose = _pose({"p": head_raw.get("pose", "0,1.7,0,0,0,0,1")} if head_raw else None)
    motion = payload.get("Motion", {})
    return SimpleNamespace(
        seq=int(payload.get("seq", 0)),
        receive_time_s=float(payload["timeStampNs"] / 1e9) if receive_time_s is None else receive_time_s,
        head=head_pose,
        body=SimpleNamespace(active=False, joints=None),
        trackers=SimpleNamespace(
            left=None
            if "left" not in motion
            else SimpleNamespace(sn=int(motion["left"].get("sn", 0)), valid=bool(motion["left"].get("valid")), pose=_pose(motion["left"])),
            right=None
            if "right" not in motion
            else SimpleNamespace(sn=int(motion["right"].get("sn", 0)), valid=bool(motion["right"].get("valid")), pose=_pose(motion["right"])),
        ),
        controllers=SimpleNamespace(left=SimpleNamespace(buttons={}), right=SimpleNamespace(buttons={})),
    )


def _load_slice() -> list[dict[str, Any]]:
    records = []
    with open(SLICE_PATH, encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            if record.get("type") == "tracking":
                records.append(record)
    assert len(records) >= 60
    return records


@pytest.fixture(scope="module")
def retargeter():
    from teleopit.retargeting.core import RetargetingModule

    return RetargetingModule(robot_name="unitree_g1", human_format="pico_bridge", actual_human_height=1.75)


@pytest.fixture(scope="module")
def replay_results(retargeter):
    """Replay the recorded slice through provider -> retargeter once; share results."""
    records = _load_slice()
    provider = _provider()
    accepted = 0
    qposes: list[np.ndarray] = []
    processing_s: list[float] = []

    for record in records:
        payload = record["payload"]
        frame = _replay_frame(payload)
        start = time.perf_counter()
        ok = provider._accept_pico_frame(frame)
        human = provider.get_frame() if ok else None
        qpos = retargeter.retarget(human) if human is not None else None
        processing_s.append(time.perf_counter() - start)
        if ok and qpos is not None:
            accepted += 1
            qposes.append(qpos)

    return {
        "records": records,
        "accepted": accepted,
        "qposes": np.asarray(qposes),
        "processing_s": np.asarray(processing_s),
    }


def test_replay_slice_stream_rate_meets_line() -> None:
    """采集质量 (rate): device timestamps in the slice sustain >= 60 Hz median."""
    records = _load_slice()
    stamps = [r["payload"]["timeStampNs"] for r in records]
    dts = np.diff(np.asarray(stamps, dtype=np.float64)) / 1e9
    dts = dts[(dts > 0) & (dts < 1.0)]
    median_hz = 1.0 / float(np.median(dts))
    assert median_hz >= 60.0, f"stream rate too low: {median_hz:.1f} Hz"


def test_replay_all_frames_accepted_and_retargeted(replay_results) -> None:
    assert replay_results["accepted"] >= int(0.9 * len(replay_results["records"]))
    assert replay_results["qposes"].shape[1] == 36


def test_replay_processing_time_within_budget(replay_results) -> None:
    """采集质量 (latency): synth->retarget per frame stays under budget."""
    mean_s = float(np.mean(replay_results["processing_s"]))
    assert mean_s < PROCESSING_BUDGET_S, f"mean processing {mean_s*1e3:.1f} ms > {PROCESSING_BUDGET_S*1e3:.0f} ms"


def test_replay_arm_tracking_stable_and_alive(replay_results) -> None:
    """跟随稳定: finite qpos, bounded steady-state steps, real range of motion."""
    qposes = replay_results["qposes"]
    assert np.all(np.isfinite(qposes)), "non-finite qpos during replay"

    steps = np.abs(np.diff(qposes[:, ARM_JOINT_SLICE], axis=0))[WARMSTART_TRANSITIONS:]
    assert float(steps.max()) < MAX_STEP_DELTA_RAD, f"steady-state arm jump {steps.max():.2f} rad"

    motion_range = float(np.ptp(qposes[:, ARM_JOINT_SLICE], axis=0).max())
    assert motion_range > MIN_RANGE_RAD, f"arm range of motion {motion_range:.2f} rad — arms not following"


def test_dropout_beyond_hold_starves_then_recovers(retargeter) -> None:
    """断连安全: invalid past the hold window stops body frames; recovery resumes."""
    records = _load_slice()
    provider = _provider()

    warmup = _replay_frame(records[0]["payload"])
    assert provider._accept_pico_frame(warmup) is True

    # invalidate both trackers with time running past the hold window
    base_s = float(records[0]["payload"]["timeStampNs"] / 1e9)
    invalid_frame = _replay_frame(records[1]["payload"], receive_time_s=base_s + 0.1)
    for side in (invalid_frame.trackers.left, invalid_frame.trackers.right):
        side.valid = False
    assert provider._accept_pico_frame(invalid_frame) is True  # still inside hold

    expired_frame = _replay_frame(records[2]["payload"], receive_time_s=base_s + 0.5)
    for side in (expired_frame.trackers.left, expired_frame.trackers.right):
        side.valid = False
    assert provider._accept_pico_frame(expired_frame) is False  # whole frame invalid

    recovered_frame = _replay_frame(records[3]["payload"], receive_time_s=base_s + 0.6)
    assert provider._accept_pico_frame(recovered_frame) is True
    qpos = retargeter.retarget(provider.get_frame())
    assert np.all(np.isfinite(qpos))
