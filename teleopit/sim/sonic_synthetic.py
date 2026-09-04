"""Synthetic upper-body reference for SONIC sim2sim eyeballing (sonic-wbc t02).

Standing template everywhere (legs at default, waist locked at zero) with an
anti-phase left/right arm swing: elbow flexion ±amplitude around the 0.6 rad
default and an optional shoulder-pitch swing in phase with each side's
elbow. Root quaternions stay identity — the harness's heading face is inert
for direct-feed references. Velocities are finite differences matching the
50 Hz frame cadence, so the encoder's motion-dq blocks see a coherent
signal.

This stands in for the replay→tracker_arm_synth→retarget line until the
mocap map's t06 lands its producer; the stream shape is identical.
"""
from __future__ import annotations

import numpy as np

from teleopit.policies.sonic.joint_order import to_isaaclab_order
from teleopit.policies.sonic.observation import SonicReferenceStream
from teleopit.policies.sonic.params import SONIC_DEFAULT_ANGLES_MJ

# IsaacLab indices (see joint_order.py: upper-body cross table).
IL_L_ELBOW = 21
IL_R_ELBOW = 22
IL_L_SHOULDER_PITCH = 11
IL_R_SHOULDER_PITCH = 12


def make_synthetic_upperbody_stream(
    *,
    duration_s: float = 10.0,
    policy_hz: float = 50.0,
    elbow_amplitude_rad: float = 0.6,
    period_s: float = 2.0,
    shoulder_amplitude_rad: float = 0.2,
) -> SonicReferenceStream:
    """Anti-phase arm-swing reference on the standing template."""
    if duration_s <= 0 or policy_hz <= 0 or period_s <= 0:
        raise ValueError("duration_s, policy_hz and period_s must be positive")

    n = int(round(duration_s * policy_hz))
    t = np.arange(n) / policy_hz
    phase = 2.0 * np.pi * t / period_s
    swing = np.sin(phase)

    default_il = to_isaaclab_order(SONIC_DEFAULT_ANGLES_MJ)
    pos = np.tile(default_il, (n, 1))
    pos[:, IL_L_ELBOW] += elbow_amplitude_rad * swing
    pos[:, IL_R_ELBOW] -= elbow_amplitude_rad * swing
    pos[:, IL_L_SHOULDER_PITCH] += shoulder_amplitude_rad * swing
    pos[:, IL_R_SHOULDER_PITCH] -= shoulder_amplitude_rad * swing

    # Finite differences: forward at the head, backward at the tail,
    # central in between (matches dt spacing of the frame cadence).
    vel = np.zeros_like(pos)
    vel[0] = (pos[1] - pos[0]) * policy_hz
    vel[-1] = (pos[-1] - pos[-2]) * policy_hz
    if n > 2:
        vel[1:-1] = (pos[2:] - pos[:-2]) * (policy_hz / 2.0)

    quats = np.tile(np.array([1.0, 0.0, 0.0, 0.0]), (n, 1))
    return SonicReferenceStream(joint_pos_il=pos, joint_vel_il=vel, root_quats_wxyz=quats)
