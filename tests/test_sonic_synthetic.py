"""Synthetic upper-body reference source for SONIC sim2sim (sonic-wbc t02).

Standing template + zero waist + alternating elbow flexion (anti-phase L/R)
+ shoulder-pitch swing, in IsaacLab order — a visually distinctive motion
for eyeballing upper-body tracking in the MuJoCo viewer before the replay
input line (mocap-map t06) lands.
"""
from __future__ import annotations

import numpy as np

from teleopit.policies.sonic.joint_order import to_isaaclab_order
from teleopit.policies.sonic.observation import SonicReferenceStream
from teleopit.policies.sonic.params import SONIC_DEFAULT_ANGLES_MJ
from teleopit.sim.sonic_synthetic import make_synthetic_upperbody_stream

IL_L_ELBOW = 21
IL_R_ELBOW = 22
IL_L_SHOULDER_PITCH = 11
IL_R_SHOULDER_PITCH = 12


class TestSyntheticStream:
    def test_frame_count_and_shapes(self):
        stream = make_synthetic_upperbody_stream(duration_s=4.0, policy_hz=50.0)
        assert stream.joint_pos_il.shape == (200, 29)
        assert stream.joint_vel_il.shape == (200, 29)
        assert stream.root_quats_wxyz.shape == (200, 4)

    def test_t_zero_is_default_pose(self):
        stream = make_synthetic_upperbody_stream()
        np.testing.assert_allclose(stream.joint_pos_il[0], to_isaaclab_order(SONIC_DEFAULT_ANGLES_MJ), atol=1e-12)

    def test_quarter_period_hits_amplitude_peaks(self):
        amp, period, hz = 0.6, 2.0, 50.0
        stream = make_synthetic_upperbody_stream(
            duration_s=2.0, policy_hz=hz, elbow_amplitude_rad=amp, period_s=period,
            shoulder_amplitude_rad=0.0,
        )
        default_il = to_isaaclab_order(SONIC_DEFAULT_ANGLES_MJ)
        k = int(round(period / 4 * hz))  # phase = pi/2
        np.testing.assert_allclose(stream.joint_pos_il[k, IL_L_ELBOW], default_il[IL_L_ELBOW] + amp, atol=1e-9)
        np.testing.assert_allclose(stream.joint_pos_il[k, IL_R_ELBOW], default_il[IL_R_ELBOW] - amp, atol=1e-9)

    def test_waist_and_legs_stay_at_template(self):
        stream = make_synthetic_upperbody_stream()
        default_il = to_isaaclab_order(SONIC_DEFAULT_ANGLES_MJ)
        leg_waist = [i for i in range(29) if i not in (IL_L_ELBOW, IL_R_ELBOW, IL_L_SHOULDER_PITCH, IL_R_SHOULDER_PITCH)]
        expected = np.tile(default_il[leg_waist], (stream.joint_pos_il.shape[0], 1))
        np.testing.assert_allclose(stream.joint_pos_il[:, leg_waist], expected, atol=1e-12)

    def test_velocities_are_finite_differences(self):
        hz = 50.0
        stream = make_synthetic_upperbody_stream(duration_s=2.0, policy_hz=hz)
        pos = stream.joint_pos_il
        expected0 = (pos[1] - pos[0]) * hz
        np.testing.assert_allclose(stream.joint_vel_il[0], expected0, atol=1e-9)
        expected_mid = (pos[6] - pos[4]) * (hz / 2.0)
        np.testing.assert_allclose(stream.joint_vel_il[5], expected_mid, atol=1e-9)

    def test_identity_root_quats(self):
        stream = make_synthetic_upperbody_stream()
        np.testing.assert_allclose(stream.root_quats_wxyz, np.tile([1.0, 0.0, 0.0, 0.0], (stream.joint_pos_il.shape[0], 1)))
