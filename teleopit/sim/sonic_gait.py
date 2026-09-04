"""cmd_vel gait reference for SONIC sim2sim (sonic-wbc t02 line 6).

Replays the official walk clip (converted to a plain numpy ``.npz`` once —
the raw pkl is joblib/pickle and stays operator-run by design) at a
speed-scaled rate and wraps it into a :class:`SonicReferenceStream`:

- playback_rate = cmd_speed / clip.native_speed; frames are interpolated at
  fractional indices and the clip loops past its end;
- the clip's global heading is stripped — root quaternions are identity, the
  same inert-heading choice the standing/synthetic lines validated — with an
  optional ``yaw_rate`` whose integral becomes the reference heading (the
  ω face of cmd_vel);
- ``upper_body_pos_il`` overrides the arm columns (IsaacLab order) so the
  mocap/synthetic upper body composes with the gait legs.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation as Rot

from teleopit.policies.sonic.joint_order import MUJOCO_TO_ISAACLAB, UPPER17_ISAACLAB, to_isaaclab_order
from teleopit.policies.sonic.observation import SonicReferenceStream
from teleopit.policies.sonic.params import SONIC_DEFAULT_ANGLES_MJ

# IsaacLab order interleaves arms and legs: the arm-14 set is the upper-17
# minus the waist trio (2, 5, 8). A contiguous 11..28 slice would clobber
# ankle pitch/roll (il 13, 14, 17, 18).
_ARM_IL = np.array(sorted(set(UPPER17_ISAACLAB) - {2, 5, 8}), dtype=int)
_PERM_TO_IL = np.array(list(MUJOCO_TO_ISAACLAB), dtype=int)


@dataclass(frozen=True)
class GaitClip:
    joint_pos_mj: np.ndarray  # (T, 29) MuJoCo blocked order
    native_speed: float  # m/s


def load_gait_clip(npz_path: Path | str) -> GaitClip:
    path = Path(npz_path)
    if not path.exists():
        raise FileNotFoundError(
            f"walk clip npz not found: {path}. Convert the official pkl once via "
            "tmp_convert_walk.py (the joblib touch is operator-run by design)."
        )
    data = np.load(path)
    return GaitClip(
        joint_pos_mj=np.asarray(data["dof"], dtype=np.float64),
        native_speed=float(data["native_speed"]),
    )


def phase_aligned_period(src: np.ndarray, min_frames: int = 40) -> int:
    """Frame index whose pose best matches frame 0 — the natural loop point.

    A raw modulo loop wraps mid-stride (measured 1.22 rad seam vs 0.22 rad
    max inner step on the walk clip — the mid-run stumble in the operator's
    visual round). Repeating over the phase-matched period keeps the seam
    inside the gait's own step-to-step envelope. ``min_frames`` floors the
    search below one gait cycle.
    """
    src = np.asarray(src)
    if src.shape[0] <= min_frames + 1:
        return max(src.shape[0] - 1, 1)
    dists = np.linalg.norm(src[min_frames:] - src[0], axis=1)
    return int(np.argmin(dists)) + min_frames


def build_gait_stream(
    clip: GaitClip,
    *,
    speed_mps: float,
    duration_s: float,
    policy_hz: float = 50.0,
    yaw_rate: float = 0.0,
    upper_body_pos_il: np.ndarray | None = None,
    blend_in_s: float = 0.0,
) -> SonicReferenceStream:
    if speed_mps <= 0 or duration_s <= 0 or policy_hz <= 0:
        raise ValueError("speed_mps, duration_s and policy_hz must be positive")
    if blend_in_s < 0:
        raise ValueError("blend_in_s must be non-negative")

    n = int(round(duration_s * policy_hz))
    t = np.arange(n) / policy_hz
    src = clip.joint_pos_mj
    loop_len = phase_aligned_period(src)
    index = (t * speed_mps / clip.native_speed * policy_hz) % loop_len

    pos_mj = np.stack(
        [np.interp(index, np.arange(src.shape[0]), src[:, k]) for k in range(29)], axis=1
    )
    pos_il = pos_mj[:, _PERM_TO_IL]

    if blend_in_s > 0:
        # Smoothstep blend from the standing default into the gait so the
        # robot (initialized at the default pose, zero velocity) starts
        # walking instead of lurching into a mid-stride reference.
        n_blend = min(int(round(blend_in_s * policy_hz)), n - 1)
        w = np.ones(n)
        s = np.arange(n_blend) / max(n_blend - 1, 1)
        w[:n_blend] = 3 * s**2 - 2 * s**3
        default_il = to_isaaclab_order(SONIC_DEFAULT_ANGLES_MJ)
        pos_il = (1.0 - w)[:, None] * default_il[None, :] + w[:, None] * pos_il

    if upper_body_pos_il is not None:
        override = np.asarray(upper_body_pos_il, dtype=np.float64).reshape(-1, 29)
        if override.shape[0] not in (1, n):
            raise ValueError(f"upper_body_pos_il must have 1 or {n} rows, got {override.shape[0]}")
        if override.shape[0] == 1:
            override = np.tile(override, (n, 1))
        pos_il[:, _ARM_IL] = override[:, _ARM_IL]

    vel = np.zeros_like(pos_il)
    vel[0] = (pos_il[1] - pos_il[0]) * policy_hz
    vel[-1] = (pos_il[-1] - pos_il[-2]) * policy_hz
    if n > 2:
        vel[1:-1] = (pos_il[2:] - pos_il[:-2]) * (policy_hz / 2.0)

    if yaw_rate == 0.0:
        quats = np.tile(np.array([1.0, 0.0, 0.0, 0.0]), (n, 1))
    else:
        yaw = yaw_rate * t
        quats = Rot.from_euler("z", yaw).as_quat()[:, [3, 0, 1, 2]]  # xyzw -> wxyz

    return SonicReferenceStream(joint_pos_il=pos_il, joint_vel_il=vel, root_quats_wxyz=quats)
