"""cmd_vel gait reference line (sonic-wbc t02 line 6).

The official walk clip (Bones-SEED retarget, converted once to plain npz
@50Hz by the operator) is replayed at a speed-scaled rate: playback_rate =
cmd_speed / native_speed, looping over the clip; root heading is stripped
(identity quats — the direct-feed obs normalizes relative orientation) with
an optional yaw-rate integration knob. Clip joints are MuJoCo-blocked
(statistical fit + policy_parameters.hpp "reference motions use MuJoCo
order"); the stream is exported in IsaacLab order.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from teleopit.policies.sonic.joint_order import to_isaaclab_order
from teleopit.sim.sonic_gait import build_gait_stream, load_gait_clip

_NPZ = Path("assets/policies/sonic/sample_data/walk_forward_50hz.npz")
requires_npz = pytest.mark.skipif(not _NPZ.exists(), reason="walk clip npz not converted")


def test_missing_npz_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_gait_clip(tmp_path / "nope.npz")


@requires_npz
class TestLoadGaitClip:
    def test_shapes_and_native_speed(self):
        clip = load_gait_clip(_NPZ)
        assert clip.joint_pos_mj.shape[1] == 29
        assert clip.joint_pos_mj.shape[0] > 1000
        assert clip.native_speed == pytest.approx(0.525, abs=0.05)
        # MuJoCo blocked order: knee col 3 is the clearly-positive joint.
        means = clip.joint_pos_mj.mean(axis=0)
        assert means[3] == pytest.approx(0.378, abs=0.05)
        assert means[15] == pytest.approx(means[22], abs=0.15)  # L/R shoulder pitch-ish


@requires_npz
class TestBuildGaitStream:
    def test_native_speed_keeps_clip_frames(self):
        clip = load_gait_clip(_NPZ)
        stream = build_gait_stream(clip, speed_mps=clip.native_speed, duration_s=2.0, policy_hz=50.0)
        assert stream.joint_pos_il.shape == (100, 29)
        np.testing.assert_allclose(stream.joint_pos_il[0], to_isaaclab_order(clip.joint_pos_mj[0]), atol=1e-9)
        np.testing.assert_allclose(stream.joint_pos_il[10], to_isaaclab_order(clip.joint_pos_mj[10]), atol=1e-9)

    def test_double_speed_advances_double_frames(self):
        clip = load_gait_clip(_NPZ)
        stream = build_gait_stream(clip, speed_mps=2.0 * clip.native_speed, duration_s=1.0, policy_hz=50.0)
        k = 20
        np.testing.assert_allclose(
            stream.joint_pos_il[k], to_isaaclab_order(clip.joint_pos_mj[2 * k]), atol=1e-6
        )

    def test_clip_loops_past_end(self):
        clip = load_gait_clip(_NPZ)
        stream = build_gait_stream(clip, speed_mps=clip.native_speed, duration_s=1.0, policy_hz=50.0)
        tail = clip.joint_pos_mj.shape[0] - 1
        # Last frames stay finite (wrap or clamp both acceptable, no NaN).
        assert np.all(np.isfinite(stream.joint_pos_il))

    def test_identity_root_quats_without_yaw(self):
        clip = load_gait_clip(_NPZ)
        stream = build_gait_stream(clip, speed_mps=clip.native_speed, duration_s=0.5, policy_hz=50.0)
        np.testing.assert_allclose(stream.root_quats_wxyz, np.tile([1.0, 0, 0, 0], (25, 1)), atol=1e-12)

    def test_yaw_rate_integrates_into_quats(self):
        clip = load_gait_clip(_NPZ)
        w = 0.5  # rad/s
        stream = build_gait_stream(clip, speed_mps=clip.native_speed, duration_s=2.0, policy_hz=50.0, yaw_rate=w)
        from scipy.spatial.transform import Rotation as Rot

        r = Rot.from_quat(stream.root_quats_wxyz[:, [1, 2, 3, 0]])
        yaw = r.as_euler("xyz")[:, 2]
        t = np.arange(100) / 50.0
        np.testing.assert_allclose(yaw, w * t, atol=1e-6)

    def test_upper_body_override_replaces_arms_only(self):
        clip = load_gait_clip(_NPZ)
        upper = np.tile(np.arange(29, dtype=np.float64), (25, 1))
        stream = build_gait_stream(
            clip, speed_mps=clip.native_speed, duration_s=0.5, policy_hz=50.0,
            upper_body_pos_il=upper,
        )
        arm_il = [11, 12, 15, 16, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28]
        np.testing.assert_allclose(stream.joint_pos_il[:, arm_il], upper[:, arm_il], atol=1e-12)
        # Everything else (legs + waist) stays the clip's own.
        leg_waist_il = [i for i in range(29) if i not in arm_il]
        expected = to_isaaclab_order(clip.joint_pos_mj[0])[leg_waist_il]
        np.testing.assert_allclose(stream.joint_pos_il[0, leg_waist_il], expected, atol=1e-9)
