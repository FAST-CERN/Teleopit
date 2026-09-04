"""Tests for the HMD+2-tracker upper-body synthesizer (mocap map t06, t05 design).

The synthesizer turns one pico_bridge frame (head + trackers) into a 24x7
body-joints array in the same raw format as PICO body tracking (Unity/flipped
frame, [x, y, z, qx, qy, qz, qw]) so the provider body path (dedup ->
_convert -> ground alignment -> cache -> GMR/mink retarget) is reused unchanged.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from teleopit.inputs.pico4_provider import BODY_JOINT_NAMES
from teleopit.inputs.tracker_arm_synth import SynthConfig, TrackerArmSynthesizer


CONFIG = SynthConfig(
    neck_shoulder_m=0.28,
    shoulder_width_m=0.38,
    chest_offset_m=(0.0, 0.0, 0.03),
    elbow_lateral_m=0.05,
    tracker_offset={"left": (0.0, 0.0, 0.0), "right": (0.0, 0.0, 0.0)},
    hold_s=0.3,
)

HEAD_POS = np.array([0.0, 1.7, 0.0])
IDENTITY_QUAT = np.array([0.0, 0.0, 0.0, 1.0])  # xyzw


def _tracker(pos, valid=True, quat=None) -> SimpleNamespace:
    """Mirror pico_bridge TrackerState: pose fields live under .pose (xyzw)."""
    return SimpleNamespace(
        sn=1,
        valid=valid,
        pose=SimpleNamespace(
            position=np.asarray(pos, dtype=np.float64),
            rotation=IDENTITY_QUAT if quat is None else np.asarray(quat, dtype=np.float64),
        ),
    )


def _frame(
    *,
    seq: int = 1,
    t: float = 100.0,
    left=_tracker((-0.4, 1.4, 0.3)),
    right=_tracker((0.4, 1.4, 0.3), quat=None),
    head_pos=HEAD_POS,
    head_quat=IDENTITY_QUAT,
) -> SimpleNamespace:
    right = _tracker((0.4, 1.4, 0.3)) if right is None else right
    return SimpleNamespace(
        seq=seq,
        receive_time_s=t,
        head=SimpleNamespace(position=np.asarray(head_pos, dtype=np.float64), rotation=np.asarray(head_quat, dtype=np.float64)),
        trackers=SimpleNamespace(left=left, right=right),
    )


def test_synthesize_valid_frame_returns_24x7_body_joints() -> None:
    synth = TrackerArmSynthesizer(CONFIG)

    joints = synth.synthesize(_frame())

    assert joints is not None
    assert joints.shape == (len(BODY_JOINT_NAMES), 7)
    assert np.all(np.isfinite(joints))
    quat_norms = np.linalg.norm(joints[:, 3:7], axis=1)
    np.testing.assert_allclose(quat_norms, 1.0, rtol=1e-9)


def test_wrist_pose_comes_from_tracker_minus_rotated_offset() -> None:
    config = SynthConfig(
        neck_shoulder_m=0.28,
        shoulder_width_m=0.38,
        chest_offset_m=(0.0, 0.0, 0.03),
        elbow_lateral_m=0.05,
        tracker_offset={"left": (0.0, 0.02, 0.05), "right": (0.0, 0.0, 0.0)},
        hold_s=0.3,
    )
    synth = TrackerArmSynthesizer(config)

    joints = synth.synthesize(_frame())

    left_idx = BODY_JOINT_NAMES.index("Left_Wrist")
    # zero tracker offset -> right wrist equals tracker position exactly
    right_idx = BODY_JOINT_NAMES.index("Right_Wrist")
    np.testing.assert_allclose(joints[right_idx, 0:3], [0.4, 1.4, 0.3], atol=1e-12)
    # identity tracker rotation, offset (0, 0.02, 0.05) -> wrist = tracker - offset
    np.testing.assert_allclose(joints[left_idx, 0:3], [-0.4, 1.38, 0.25], atol=1e-9)
    # wrist orientation = tracker quaternion (xyzw)
    np.testing.assert_allclose(joints[right_idx, 3:7], IDENTITY_QUAT, atol=1e-9)


def test_shoulder_anchor_from_head_and_elbow_at_midpoint_plus_lateral() -> None:
    synth = TrackerArmSynthesizer(CONFIG)

    joints = synth.synthesize(_frame())

    head_idx = BODY_JOINT_NAMES.index("Head")
    neck_idx = BODY_JOINT_NAMES.index("Neck")
    ls_idx = BODY_JOINT_NAMES.index("Left_Shoulder")
    le_idx = BODY_JOINT_NAMES.index("Left_Elbow")
    lw_idx = BODY_JOINT_NAMES.index("Left_Wrist")
    rs_idx = BODY_JOINT_NAMES.index("Right_Shoulder")

    # identity head rotation: shoulder = head + chest_offset + (+/- width/2, -neck_shoulder, 0)
    expected_left_shoulder = np.array([0.0 - 0.19, 1.7 - 0.28, 0.0 + 0.03])
    expected_right_shoulder = np.array([0.0 + 0.19, 1.7 - 0.28, 0.0 + 0.03])
    np.testing.assert_allclose(joints[ls_idx, 0:3], expected_left_shoulder, atol=1e-9)
    np.testing.assert_allclose(joints[rs_idx, 0:3], expected_right_shoulder, atol=1e-9)

    # elbow = midpoint(shoulder, wrist) + k * outward_lateral (world-up cross arm dir, signed per side)
    shoulder = joints[ls_idx, 0:3]
    wrist = joints[lw_idx, 0:3]
    mid = 0.5 * (shoulder + wrist)
    arm_dir = wrist - shoulder
    up = np.array([0.0, 1.0, 0.0])
    cross = np.cross(up, arm_dir)
    lateral = -cross / np.linalg.norm(cross) * CONFIG.elbow_lateral_m  # left side sign
    np.testing.assert_allclose(joints[le_idx, 0:3], mid + lateral, atol=1e-9)

    # head/neck ride the HMD pose
    np.testing.assert_allclose(joints[head_idx, 0:3], HEAD_POS, atol=1e-9)


def test_missing_head_or_trackers_returns_none() -> None:
    synth = TrackerArmSynthesizer(CONFIG)

    no_head = _frame()
    no_head.head = None
    assert synth.synthesize(no_head) is None

    no_trackers = _frame()
    no_trackers.trackers = None
    assert synth.synthesize(no_trackers) is None

    one_side = _frame(left=None)
    assert synth.synthesize(one_side) is None


def test_invalid_within_hold_keeps_last_wrist_beyond_hold_returns_none() -> None:
    synth = TrackerArmSynthesizer(CONFIG)

    ok = synth.synthesize(_frame(t=100.0))
    assert ok is not None

    # invalid 0.1s later -> frame still produced with the held wrist pose
    held = synth.synthesize(_frame(t=100.1, left=_tracker((-9.9, 9.9, 9.9), valid=False)))
    assert held is not None
    lw = BODY_JOINT_NAMES.index("Left_Wrist")
    np.testing.assert_allclose(held[lw, 0:3], ok[lw, 0:3], atol=1e-12)

    # invalid 0.5s later (> hold_s=0.3) -> whole frame invalid
    assert synth.synthesize(_frame(t=100.5, left=_tracker((-9.9, 9.9, 9.9), valid=False))) is None

    # recovery: valid again -> fresh pose streams again
    recovered = synth.synthesize(_frame(t=100.6, left=_tracker((-0.5, 1.2, 0.4))))
    assert recovered is not None
    np.testing.assert_allclose(recovered[lw, 0:3], [-0.5, 1.2, 0.4], atol=1e-9)


def test_provider_accepts_synth_frame_when_body_inactive_and_arm_source_tracker() -> None:
    import threading
    from collections import deque

    from teleopit.inputs.pico4_provider import Pico4InputProvider
    from teleopit.inputs.realtime_frame_cache import RealtimeFrameCache

    def _provider_with(arm_synth):
        provider = object.__new__(Pico4InputProvider)
        provider._lock = threading.Lock()
        provider._frame_ready = threading.Event()
        provider._frame_cache = RealtimeFrameCache(buffer_size=8, fps_window=30)
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
        provider._arm_synth = arm_synth
        return provider

    frame = SimpleNamespace(
        seq=7,
        receive_time_s=200.0,
        head=SimpleNamespace(position=HEAD_POS.copy(), rotation=IDENTITY_QUAT.copy()),
        body=SimpleNamespace(active=False, joints=None),
        trackers=SimpleNamespace(left=_tracker((-0.4, 1.4, 0.3)), right=_tracker((0.4, 1.4, 0.3))),
        controllers=SimpleNamespace(left=SimpleNamespace(buttons={}), right=SimpleNamespace(buttons={})),
    )

    # default (no synth): body inactive -> rejected, as today
    plain = _provider_with(None)
    assert plain._accept_pico_frame(frame) is False
    assert not plain.has_frame()

    # arm_source=tracker: synthesized body flows through the body path
    armed = _provider_with(TrackerArmSynthesizer(CONFIG))
    assert armed._accept_pico_frame(frame) is True
    assert armed.has_frame()
