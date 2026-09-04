"""HMD + 2 motion trackers -> 24-joint upper-body synthesis (mocap map t05 design, t06 implementation).

Turns one pico_bridge frame (``head`` + ``trackers``) into a body-joints array
in the same raw format as PICO body tracking — Unity/flipped frame,
``[x, y, z, qx, qy, qz, qw]`` per joint — so the provider body path (dedup ->
coordinate transform -> ground alignment -> cache -> GMR/mink retarget) is
reused unchanged (t05 决议 1/4: 完整合成 body 等价帧, 零新变换).

Geometry (t05 决议 2/3):
- shoulder anchors: HMD pose + rigid constants (neck-shoulder drop, width, chest offset)
- elbow: midpoint(shoulder, wrist) + outward lateral offset (k, world-up cross arm dir)
- wrist: tracker pose minus mount offset rotated into the tracker frame
- lower body: standing template (root anchor only; the retarget takes arm idx 15-28)

Validity (t05 决议 5): one invalid tracker holds its last wrist pose for
``hold_s``; beyond the window (or never seen) the whole frame is invalid
(``None``) and the downstream starvation gates apply.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.spatial.transform import Rotation as Rot

from teleopit.inputs.pico_body_joints import BODY_JOINT_NAMES

_WORLD_UP = np.array([0.0, 1.0, 0.0])
_SIDE_SIGN = {"left": -1.0, "right": 1.0}

# Standing template for the non-arm joints (Unity frame, y up, meters).
# The retarget uses arm + torso tasks only; the lower body anchors the root
# and ground alignment lifts the skeleton onto the floor.
_TEMPLATE_POSITIONS: dict[str, tuple[float, float, float]] = {
    "Pelvis": (0.0, 0.95, 0.0),
    "Left_Hip": (-0.10, 0.92, 0.0),
    "Right_Hip": (0.10, 0.92, 0.0),
    "Spine1": (0.0, 1.05, 0.0),
    "Left_Knee": (-0.10, 0.50, 0.0),
    "Right_Knee": (0.10, 0.50, 0.0),
    "Spine2": (0.0, 1.15, 0.0),
    "Left_Ankle": (-0.10, 0.09, 0.0),
    "Right_Ankle": (0.10, 0.09, 0.0),
    "Spine3": (0.0, 1.28, 0.0),
    "Left_Foot": (-0.10, 0.02, 0.15),
    "Right_Foot": (0.10, 0.02, 0.15),
}

_NECK_DROP_M = 0.12  # Head -> Neck along the HMD down axis
_HAND_SEGMENT_M = 0.09  # Wrist -> Hand along the forearm direction


@dataclass(frozen=True)
class SynthConfig:
    """Rigid synthesis constants; measure once per operator (t05 决议 2/3)."""

    neck_shoulder_m: float = 0.28
    shoulder_width_m: float = 0.38
    chest_offset_m: tuple[float, float, float] = (0.0, 0.0, 0.03)
    elbow_lateral_m: float = 0.05
    tracker_offset: dict[str, tuple[float, float, float]] = field(
        default_factory=lambda: {"left": (0.0, 0.0, 0.0), "right": (0.0, 0.0, 0.0)}
    )
    hold_s: float = 0.3


class TrackerArmSynthesizer:
    """Pure pose-in/pose-out core plus the per-side hold state machine."""

    def __init__(self, config: SynthConfig) -> None:
        self._cfg = config
        self._held: dict[str, tuple[NDArray[np.float64], NDArray[np.float64], float] | None] = {
            "left": None,
            "right": None,
        }

    def synthesize(self, frame: Any) -> NDArray[np.float64] | None:
        """Eat a pico_bridge frame (head + trackers); return 24x7 body joints or None."""
        head = getattr(frame, "head", None)
        trackers = getattr(frame, "trackers", None)
        if head is None or trackers is None:
            return None

        head_position = getattr(head, "position", None)
        head_rotation = getattr(head, "rotation", None)
        if head_position is None or head_rotation is None:
            return None
        head_pos = np.asarray(head_position, dtype=np.float64).reshape(3)
        head_quat = _unit_quat_xyzw(np.asarray(head_rotation, dtype=np.float64).reshape(4))
        if head_quat is None:
            return None
        head_rot = Rot.from_quat(head_quat)

        now_s = float(getattr(frame, "receive_time_s", 0.0))
        wrists: dict[str, tuple[NDArray[np.float64], NDArray[np.float64]]] = {}
        for side in ("left", "right"):
            wrist = self._wrist_pose(side, getattr(trackers, side, None), now_s)
            if wrist is None:
                return None
            wrists[side] = wrist

        joints = np.zeros((len(BODY_JOINT_NAMES), 7), dtype=np.float64)
        identity = np.array([0.0, 0.0, 0.0, 1.0])
        for i in range(len(BODY_JOINT_NAMES)):
            joints[i, 3:7] = identity
        for name, position in _TEMPLATE_POSITIONS.items():
            joints[BODY_JOINT_NAMES.index(name), 0:3] = position

        neck_pos = head_pos + head_rot.apply(np.array([0.0, -_NECK_DROP_M, 0.0]))
        joints[BODY_JOINT_NAMES.index("Neck"), 0:3] = neck_pos
        joints[BODY_JOINT_NAMES.index("Neck"), 3:7] = head_quat
        joints[BODY_JOINT_NAMES.index("Head"), 0:3] = head_pos
        joints[BODY_JOINT_NAMES.index("Head"), 3:7] = head_quat

        chest = np.asarray(self._cfg.chest_offset_m, dtype=np.float64)
        half_width = 0.5 * float(self._cfg.shoulder_width_m)
        drop = float(self._cfg.neck_shoulder_m)

        for side in ("left", "right"):
            sign = _SIDE_SIGN[side]
            wrist_pos, wrist_quat = wrists[side]
            suffix = "Left" if side == "left" else "Right"

            shoulder_pos = head_pos + head_rot.apply(chest + np.array([sign * half_width, -drop, 0.0]))
            elbow_pos = _elbow_position(shoulder_pos, wrist_pos, sign, float(self._cfg.elbow_lateral_m))

            forearm_dir = wrist_pos - elbow_pos
            hand_pos = wrist_pos + forearm_dir * (_HAND_SEGMENT_M / max(float(np.linalg.norm(forearm_dir)), 1e-9))

            canonical = np.array([sign, 0.0, 0.0])  # T-pose arm direction per side
            for joint, position, direction in (
                ("Collar", 0.5 * (neck_pos + shoulder_pos), shoulder_pos - neck_pos),
                ("Shoulder", shoulder_pos, elbow_pos - shoulder_pos),
                ("Elbow", elbow_pos, forearm_dir),
            ):
                idx = BODY_JOINT_NAMES.index(f"{suffix}_{joint}")
                joints[idx, 0:3] = position
                joints[idx, 3:7] = _align_quat(canonical, direction)
            joints[BODY_JOINT_NAMES.index(f"{suffix}_Wrist"), 0:3] = wrist_pos
            joints[BODY_JOINT_NAMES.index(f"{suffix}_Wrist"), 3:7] = wrist_quat
            joints[BODY_JOINT_NAMES.index(f"{suffix}_Hand"), 0:3] = hand_pos
            joints[BODY_JOINT_NAMES.index(f"{suffix}_Hand"), 3:7] = wrist_quat

        return joints

    def _wrist_pose(
        self, side: str, state: Any, now_s: float
    ) -> tuple[NDArray[np.float64], NDArray[np.float64]] | None:
        pose = None if state is None else getattr(state, "pose", None)
        valid = state is not None and bool(getattr(state, "valid", False))
        if valid and pose is not None:
            position = getattr(pose, "position", None)
            rotation = getattr(pose, "rotation", None)
            quat = None if rotation is None else _unit_quat_xyzw(np.asarray(rotation, dtype=np.float64).reshape(-1))
            if position is not None and quat is not None:
                tracker_pos = np.asarray(position, dtype=np.float64).reshape(3)
                offset = np.asarray(self._cfg.tracker_offset.get(side, (0.0, 0.0, 0.0)), dtype=np.float64)
                wrist_pos = tracker_pos - Rot.from_quat(quat).apply(offset)
                self._held[side] = (wrist_pos, quat, now_s)
                return wrist_pos, quat

        held = self._held[side]
        if held is None:
            return None
        wrist_pos, wrist_quat, held_s = held
        if now_s - held_s > float(self._cfg.hold_s):
            return None
        return wrist_pos, wrist_quat


def _elbow_position(
    shoulder: NDArray[np.float64],
    wrist: NDArray[np.float64],
    side_sign: float,
    lateral_m: float,
) -> NDArray[np.float64]:
    """midpoint(shoulder, wrist) + outward lateral offset (t05 决议 2).

    The lateral hint uses ``cross(up, arm_dir) / |arm_dir|`` (magnitude
    ``k*sin(theta)`` from vertical) instead of a normalized direction: it fades
    smoothly to zero as the arm approaches vertical, so the elbow never jumps
    when the arm sweeps through the degenerate direction (IK-chased elbow
    flips seen in the t06 replay).
    """
    mid = 0.5 * (shoulder + wrist)
    arm_dir = wrist - shoulder
    arm_len = float(np.linalg.norm(arm_dir))
    if arm_len <= 1e-9:
        return mid
    return mid + side_sign * (np.cross(_WORLD_UP, arm_dir) / arm_len) * lateral_m


def _align_quat(canonical: NDArray[np.float64], direction: NDArray[np.float64]) -> NDArray[np.float64]:
    """Quaternion (xyzw) rotating the canonical bone axis onto ``direction``."""
    norm = float(np.linalg.norm(direction))
    if norm <= 1e-9:
        return np.array([0.0, 0.0, 0.0, 1.0])
    quat = Rot.align_vectors(np.asarray(canonical, dtype=np.float64).reshape(3), (direction / norm).reshape(3))[0].as_quat()
    return _unit_quat_xyzw(quat) if _unit_quat_xyzw(quat) is not None else np.array([0.0, 0.0, 0.0, 1.0])


def _unit_quat_xyzw(quat: NDArray[np.float64]) -> NDArray[np.float64] | None:
    norm = float(np.linalg.norm(quat))
    if norm <= 1e-9 or not np.all(np.isfinite(quat)):
        return None
    return np.asarray(quat / norm, dtype=np.float64)
