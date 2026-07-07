from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
from numpy.typing import NDArray

from teleopit.inputs.realtime_packet import HumanFrame
from teleopit.sim2real.neck.config import NeckConfig


FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class NeckCommand:
    yaw: float
    pitch: float
    yaw_deg: float
    pitch_deg: float
    roll_deg: float


class HeadPoseMapper:
    """Map Teleopit Pico body frames to normalized active-neck yaw/pitch commands."""

    def __init__(self, config: NeckConfig) -> None:
        self._cfg = config
        self._offset = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)
        self._calibrated = False
        self._smooth_yaw = 0.0
        self._smooth_pitch = 0.0

    @property
    def calibrated(self) -> bool:
        return self._calibrated

    def reset(self) -> None:
        self._offset = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)
        self._calibrated = False
        self._smooth_yaw = 0.0
        self._smooth_pitch = 0.0

    def map_frame(self, frame: HumanFrame) -> NeckCommand | None:
        q_head = _joint_quat(frame, self._cfg.head_joint)
        if q_head is None:
            return None
        q_body = _joint_quat(frame, self._cfg.body_reference_joint) if self._cfg.use_body_reference else None
        relative = self._relative(q_head, q_body)
        if not self._calibrated:
            self._offset = relative
            self._calibrated = True
            return None

        q_cmd = _qmul(relative, _qconj(self._offset))
        yaw_deg, pitch_deg, roll_deg = _openneck_yaw_pitch_roll_deg(q_cmd)
        if self._cfg.invert_yaw:
            yaw_deg = -yaw_deg
        if self._cfg.invert_pitch:
            pitch_deg = -pitch_deg
        if abs(yaw_deg) < self._cfg.dead_zone_deg:
            yaw_deg = 0.0
        if abs(pitch_deg) < self._cfg.dead_zone_deg:
            pitch_deg = 0.0

        yaw = yaw_deg / self._cfg.yaw_range_deg
        pitch = pitch_deg / self._cfg.pitch_range_deg
        alpha = self._cfg.smoothing_alpha
        self._smooth_yaw += alpha * (yaw - self._smooth_yaw)
        self._smooth_pitch += alpha * (pitch - self._smooth_pitch)
        return NeckCommand(
            yaw=float(np.clip(self._smooth_yaw, -1.0, 1.0)),
            pitch=float(np.clip(self._smooth_pitch, -1.0, 1.0)),
            yaw_deg=float(yaw_deg),
            pitch_deg=float(pitch_deg),
            roll_deg=float(roll_deg),
        )

    def _relative(self, q_head: FloatArray, q_body: FloatArray | None) -> FloatArray:
        if q_body is not None:
            return _qmul(_qconj(q_body), q_head)
        return q_head


def _joint_quat(frame: HumanFrame, joint_name: str) -> FloatArray | None:
    item = frame.get(joint_name)
    if item is None:
        return None
    quat = np.asarray(item[1], dtype=np.float64).reshape(-1)
    if quat.shape[0] != 4 or not np.all(np.isfinite(quat)):
        return None
    norm = float(np.linalg.norm(quat))
    if norm <= 1e-9:
        return None
    return quat / norm


def _qconj(q: FloatArray) -> FloatArray:
    return np.array([q[0], -q[1], -q[2], -q[3]], dtype=np.float64)


def _qmul(a: FloatArray, b: FloatArray) -> FloatArray:
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b
    return np.array(
        [
            w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
            w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
            w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
        ],
        dtype=np.float64,
    )


def _openneck_yaw_pitch_roll_deg(q_wxyz: FloatArray) -> tuple[float, float, float]:
    w, x, y, z = q_wxyz
    yaw = math.degrees(math.atan2(2.0 * (x * z + w * y), 1.0 - 2.0 * (y * y + z * z)))
    pitch = math.degrees(math.asin(float(np.clip(-2.0 * (y * z - w * x), -1.0, 1.0))))
    roll = math.degrees(math.atan2(2.0 * (x * y + w * z), 1.0 - 2.0 * (x * x + z * z)))
    return yaw, pitch, roll
