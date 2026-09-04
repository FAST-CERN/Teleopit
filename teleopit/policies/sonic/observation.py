"""SONIC low_latency observation assembly + action decode (sonic-wbc t02).

Python port of the C++ observation gatherers in ``g1_deploy_onnx_ref.cpp``
(clone HEAD 087f9ac) for the low_latency checkpoint
(``observation_config_low_latency.yaml``):

- decoder obs 994 = token(64) + his ang_vel(10x3) + his q-default(10x29) +
  his dq(10x29) + his last_action(10x29) + his gravity(10x3). Blocks are
  per-quantity, frames oldest->newest, joints in IsaacLab order, positions
  in deviation coordinates (q - default; the C++ state logger stores them
  pre-subtracted).
- encoder obs 1247 = encoder_mode_4(4) + motion q(10x29) + motion dq(10x29) +
  anchor 6D(10x6) + anchor 6D(6) + lower-body q(10x12) + lower-body dq(10x12)
  + vr 3point pos(9) + orn(12) + smpl joints(4x72) + smpl anchor(4x6) +
  wrists(4x6). Lookahead frames are playhead + k*step clamped to the last
  frame (the "hold-tail" of a live stream). In g1 mode (encoder_mode_4 zeros)
  the vr/smpl branches stay zero — matching what the official v1 streamed
  path yields with no VR/smpl data.

apply_delta_heading is kept as identity here: our reference stream carries
world-identity root quaternions, so the heading-rebasing the C++ does at
stream start degenerates. If sim2sim shows heading sensitivity, promote it
to a knob (ComputeApplyDeltaHeading analogue).
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.spatial.transform import Rotation as Rot

from teleopit.policies.sonic.joint_order import (
    LOWER12_MUJOCO_ORDER_IN_ISAACLAB,
    WRIST6_ISAACLAB,
    from_isaaclab_order,
    to_isaaclab_order,
)
from teleopit.policies.sonic.params import (
    SONIC_ACTION_SCALE_MJ,
    SONIC_DEFAULT_ANGLES_MJ,
)

_DEFAULT_IL = to_isaaclab_order(SONIC_DEFAULT_ANGLES_MJ)


def _field(state: Any, name: str) -> np.ndarray:
    value = getattr(state, name, None)
    if value is None and isinstance(state, dict):
        value = state.get(name)
    if value is None:
        raise ValueError(f"state is missing field {name!r}")
    return np.asarray(value, dtype=np.float64)


def quat_to_6d(quat_wxyz: np.ndarray) -> np.ndarray:
    """First two rotation-matrix columns, flattened row-wise (C++ layout)."""
    r = Rot.from_quat(np.asarray(quat_wxyz, dtype=np.float64)[[1, 2, 3, 0]])
    m = r.as_matrix()
    return np.array([m[0, 0], m[0, 1], m[1, 0], m[1, 1], m[2, 0], m[2, 1]])


def _relative_6d(base_quat_wxyz: np.ndarray, ref_quat_wxyz: np.ndarray) -> np.ndarray:
    """6D of inv(base) * ref (apply_delta_heading held at identity)."""
    base = Rot.from_quat(np.asarray(base_quat_wxyz)[[1, 2, 3, 0]])
    ref = Rot.from_quat(np.asarray(ref_quat_wxyz)[[1, 2, 3, 0]])
    rel = base.inv() * ref
    m = rel.as_matrix()
    return np.array([m[0, 0], m[0, 1], m[1, 0], m[1, 1], m[2, 0], m[2, 1]])


def _gravity_b(quat_wxyz: np.ndarray) -> np.ndarray:
    """Body-frame projected gravity: inv(q) * (0, 0, -1)."""
    rot = Rot.from_quat(np.asarray(quat_wxyz)[[1, 2, 3, 0]])
    return rot.inv().apply(np.array([0.0, 0.0, -1.0]))


class SonicHistory:
    """Ring of robot proprioception frames feeding the decoder's his_* blocks."""

    def __init__(self, num_frames: int = 10) -> None:
        self._num_frames = num_frames
        self._ring: deque[tuple[np.ndarray, ...]] = deque(maxlen=num_frames)

    def push(self, *, state: Any, last_action_il: np.ndarray) -> None:
        qpos_dev_il = to_isaaclab_order(_field(state, "qpos")) - _DEFAULT_IL
        self._ring.append(
            (
                _field(state, "ang_vel").reshape(3).copy(),
                qpos_dev_il,
                to_isaaclab_order(_field(state, "qvel")),
                np.asarray(last_action_il, dtype=np.float64).reshape(29).copy(),
                _gravity_b(_field(state, "quat").reshape(4)),
            )
        )

    def blocks(self) -> dict[str, np.ndarray]:
        """(num_frames, dim) arrays per quantity; warm-up repeats the oldest."""
        names = ("ang_vel", "joint_pos_dev", "joint_vel", "last_action", "gravity")
        dims = (3, 29, 29, 29, 3)
        out = {n: np.zeros((self._num_frames, d)) for n, d in zip(names, dims)}
        if not self._ring:
            return out
        frames = list(self._ring)
        pad = self._num_frames - len(frames)
        frames = [frames[0]] * pad + frames
        for i, frame in enumerate(frames):
            for name, values in zip(names, frame):
                out[name][i] = values
        return out

    def reset(self) -> None:
        self._ring.clear()


@dataclass(frozen=True)
class LookaheadFrames:
    joint_pos: np.ndarray  # (F, 29) IsaacLab order, absolute
    joint_vel: np.ndarray  # (F, 29)
    root_quats_wxyz: np.ndarray  # (F, 4)


class SonicReferenceStream:
    """Reference motion at 50 Hz with a playhead and clamped lookahead."""

    def __init__(
        self,
        *,
        joint_pos_il: np.ndarray,
        joint_vel_il: np.ndarray,
        root_quats_wxyz: np.ndarray,
    ) -> None:
        self.joint_pos_il = np.asarray(joint_pos_il, dtype=np.float64).reshape(-1, 29)
        self.joint_vel_il = np.asarray(joint_vel_il, dtype=np.float64).reshape(-1, 29)
        self.root_quats_wxyz = np.asarray(root_quats_wxyz, dtype=np.float64).reshape(-1, 4)
        if not (self.joint_pos_il.shape[0] == self.joint_vel_il.shape[0] == self.root_quats_wxyz.shape[0]):
            raise ValueError("reference stream arrays must share one time axis")
        if self.joint_pos_il.shape[0] == 0:
            raise ValueError("reference stream needs at least one frame")
        self._playhead = 0

    @property
    def playhead(self) -> int:
        return self._playhead

    def advance(self, n: int = 1) -> None:
        last = self.joint_pos_il.shape[0] - 1
        self._playhead = min(self._playhead + n, last)

    def lookahead(self, num_frames: int, step: int) -> LookaheadFrames:
        """Frames at playhead + k*step, clamped to the last frame (hold-tail)."""
        last = self.joint_pos_il.shape[0] - 1
        idx = np.minimum(self._playhead + np.arange(num_frames) * step, last)
        return LookaheadFrames(
            joint_pos=self.joint_pos_il[idx],
            joint_vel=self.joint_vel_il[idx],
            root_quats_wxyz=self.root_quats_wxyz[idx],
        )


class SonicObsBuilder:
    """Assembles the 994D decoder and 1247D encoder inputs for low_latency."""

    HISTORY_FRAMES = 10
    LOOKAHEAD_FRAMES = 10
    WRIST_FRAMES = 4

    def __init__(self) -> None:
        self.history = SonicHistory(num_frames=self.HISTORY_FRAMES)

    def push_history(self, state: Any, last_action_il: np.ndarray) -> None:
        self.history.push(state=state, last_action_il=last_action_il)

    def build_decoder_obs(self, token: np.ndarray) -> np.ndarray:
        token = np.asarray(token, dtype=np.float64).reshape(-1)
        if token.shape[0] != 64:
            raise ValueError(f"token has {token.shape[0]} entries, expected 64")
        blocks = self.history.blocks()
        return np.concatenate([
            token,
            blocks["ang_vel"].reshape(-1),
            blocks["joint_pos_dev"].reshape(-1),
            blocks["joint_vel"].reshape(-1),
            blocks["last_action"].reshape(-1),
            blocks["gravity"].reshape(-1),
        ])

    def build_encoder_obs(self, *, base_quat_wxyz: np.ndarray, stream: SonicReferenceStream) -> np.ndarray:
        base = np.asarray(base_quat_wxyz, dtype=np.float64).reshape(4)
        look = stream.lookahead(self.LOOKAHEAD_FRAMES, step=1)
        wrists = look.joint_pos[: self.WRIST_FRAMES][:, list(WRIST6_ISAACLAB)]
        anchors = np.stack([_relative_6d(base, q) for q in look.root_quats_wxyz])
        lower_idx = list(LOWER12_MUJOCO_ORDER_IN_ISAACLAB)
        return np.concatenate([
            np.zeros(4),                                   # encoder_mode_4: g1 mode 0
            look.joint_pos.reshape(-1),                    # motion q 10x29
            look.joint_vel.reshape(-1),                    # motion dq 10x29
            anchors.reshape(-1),                           # anchor 6D 10x6
            anchors[0],                                    # single-frame anchor
            look.joint_pos[:, lower_idx].reshape(-1),      # lower q 10x12
            look.joint_vel[:, lower_idx].reshape(-1),      # lower dq 10x12
            np.zeros(9),                                   # vr_3point_local_target
            np.zeros(12),                                  # vr_3point_local_orn_target
            np.zeros(288),                                 # smpl_joints 4x72
            np.zeros(24),                                  # smpl_anchor 4x6
            wrists.reshape(-1),                            # wrists 4x6
        ])


def decode_action(action_il: np.ndarray) -> np.ndarray:
    """q_target[mj] = default[mj] + action[il] * scale[mj] (blocked order out)."""
    action = np.asarray(action_il, dtype=np.float64).reshape(-1)
    if action.shape[0] != 29:
        raise ValueError(f"action has {action.shape[0]} entries, expected 29")
    return SONIC_DEFAULT_ANGLES_MJ + from_isaaclab_order(action) * SONIC_ACTION_SCALE_MJ
