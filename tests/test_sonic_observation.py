"""SONIC low_latency obs assembly + action decode (sonic-wbc t02 TDD-2).

Layouts verified against the C++ gatherers in
``gear_sonic_deploy/src/g1/g1_deploy_onnx_ref/src/g1_deploy_onnx_ref.cpp``
(registry ~1700-1810, gatherers 616-900 / 1454-1650) and
``policy/release/observation_config_low_latency.yaml`` (clone HEAD 087f9ac):

- decoder obs 994 = token(64) + ang_vel(10x3) + q-default(10x29) +
  dq(10x29) + last_action(10x29) + gravity(10x3), block-per-quantity,
  frames oldest->newest, IsaacLab joint order.
- encoder obs 1247 = mode_4(4) + motion_q(10x29) + motion_dq(10x29) +
  anchor6d(10x6) + anchor6d(6) + lower_q(10x12) + lower_dq(10x12) +
  vr_pos(9, zeros) + vr_orn(12, zeros) + smpl(288, zeros) +
  smpl_anchor(24, zeros) + wrists(4x6).
- action decode: q_target[mj] = default[mj] + action[il] * scale[mj]
  (policy_parameters.hpp:29, constants in MuJoCo blocked order).
"""
from __future__ import annotations

import numpy as np
import pytest

from teleopit.policies.sonic.joint_order import (
    LOWER12_MUJOCO_ORDER_IN_ISAACLAB,
    WRIST6_ISAACLAB,
    to_isaaclab_order,
)
from teleopit.policies.sonic.observation import (
    SonicHistory,
    SonicObsBuilder,
    SonicReferenceStream,
    decode_action,
    quat_to_6d,
)
from teleopit.policies.sonic.params import (
    SONIC_ACTION_SCALE_MJ,
    SONIC_DEFAULT_ANGLES_MJ,
)

IDENTITY_QUAT = np.array([1.0, 0.0, 0.0, 0.0])


def make_state(qpos_mj, qvel_mj=None, ang_vel=None, quat=None):
    """Minimal duck-typed RobotState for the history push."""
    return {
        "qpos": np.asarray(qpos_mj, dtype=np.float64),
        "qvel": np.zeros(29) if qvel_mj is None else np.asarray(qvel_mj, dtype=np.float64),
        "ang_vel": np.zeros(3) if ang_vel is None else np.asarray(ang_vel, dtype=np.float64),
        "quat": IDENTITY_QUAT.copy() if quat is None else np.asarray(quat, dtype=np.float64),
    }


class TestParams:
    def test_default_angles_match_policy_parameters_hpp(self):
        # policy_parameters.hpp:210-240, MuJoCo blocked order.
        expected = np.array([
            -0.312, 0.0, 0.0, 0.669, -0.363, 0.0,
            -0.312, 0.0, 0.0, 0.669, -0.363, 0.0,
            0.0, 0.0, 0.0,
            0.2, 0.2, 0.0, 0.6, 0.0, 0.0, 0.0,
            0.2, -0.2, 0.0, 0.6, 0.0, 0.0, 0.0,
        ])
        np.testing.assert_allclose(SONIC_DEFAULT_ANGLES_MJ, expected, atol=1e-12)

    def test_action_scale_from_motor_constants(self):
        # scale = 0.25 * effort / stiffness (policy_parameters.hpp:27, 106-139).
        # 7520_22: 139N/99.10 -> hip_pitch/roll/knee; 7520_14: 88N/40.18 ->
        # hip_yaw & waist_yaw; 5020: 25N/14.25; 4010: 5N/16.78 -> wrist pitch/yaw.
        assert SONIC_ACTION_SCALE_MJ.shape == (29,)
        assert SONIC_ACTION_SCALE_MJ[0] == pytest.approx(0.3507, abs=2e-4)   # L hip_pitch
        assert SONIC_ACTION_SCALE_MJ[1] == pytest.approx(0.3507, abs=2e-4)   # L hip_roll
        assert SONIC_ACTION_SCALE_MJ[2] == pytest.approx(0.5475, abs=2e-4)   # L hip_yaw
        assert SONIC_ACTION_SCALE_MJ[3] == pytest.approx(0.3507, abs=2e-4)   # L knee
        assert SONIC_ACTION_SCALE_MJ[4] == pytest.approx(0.4386, abs=2e-4)   # L ankle_pitch
        assert SONIC_ACTION_SCALE_MJ[12] == pytest.approx(0.5475, abs=2e-4)  # waist_yaw
        assert SONIC_ACTION_SCALE_MJ[15] == pytest.approx(0.4386, abs=2e-4)  # L shoulder_pitch
        assert SONIC_ACTION_SCALE_MJ[18] == pytest.approx(0.4386, abs=2e-4)  # L elbow
        assert SONIC_ACTION_SCALE_MJ[20] == pytest.approx(0.0746, abs=2e-4)  # L wrist_pitch
        assert SONIC_ACTION_SCALE_MJ[28] == pytest.approx(0.0746, abs=2e-4)  # R wrist_yaw


class TestQuat6D:
    def test_identity(self):
        np.testing.assert_allclose(quat_to_6d(IDENTITY_QUAT), [1, 0, 0, 1, 0, 0], atol=1e-12)

    def test_yaw_90(self):
        half = np.sqrt(0.5)
        quat = np.array([half, 0.0, 0.0, half])  # +90 deg about z, wxyz
        np.testing.assert_allclose(quat_to_6d(quat), [0, -1, 1, 0, 0, 0], atol=1e-12)


class TestHistory:
    def test_push_two_frames_and_read_deviation_blocks(self):
        h = SonicHistory(num_frames=10)
        q0 = SONIC_DEFAULT_ANGLES_MJ.copy()
        q1 = SONIC_DEFAULT_ANGLES_MJ.copy()
        q1[18] += 0.25  # left elbow +0.25 rad
        h.push(state=make_state(q0), last_action_il=np.zeros(29))
        h.push(state=make_state(q1, qvel_mj=np.full(29, 0.5), ang_vel=np.array([0.1, 0.2, 0.3])), last_action_il=np.ones(29))

        blocks = h.blocks()
        assert set(blocks) == {"ang_vel", "joint_pos_dev", "joint_vel", "last_action", "gravity"}
        assert blocks["ang_vel"].shape == (10, 3)
        assert blocks["joint_pos_dev"].shape == (10, 29)
        # Warm-up: oldest entries repeat the first push (frame 0 == frame 1...8).
        assert np.all(blocks["ang_vel"][:9] == 0.0)
        np.testing.assert_allclose(blocks["ang_vel"][9], [0.1, 0.2, 0.3])
        # Deviation coords, IsaacLab order: left_elbow mj18 -> il21.
        np.testing.assert_allclose(blocks["joint_pos_dev"][8, 21], 0.0, atol=1e-12)
        np.testing.assert_allclose(blocks["joint_pos_dev"][9, 21], 0.25, atol=1e-12)
        np.testing.assert_allclose(blocks["joint_vel"][9, 21], 0.5, atol=1e-12)
        np.testing.assert_allclose(blocks["last_action"][9], np.ones(29))
        # Gravity with identity quat: inv(q) * (0,0,-1) = (0,0,-1).
        np.testing.assert_allclose(blocks["gravity"][9], [0, 0, -1], atol=1e-12)

    def test_joint_pos_dev_equals_permuted_difference(self):
        h = SonicHistory(num_frames=10)
        rng = np.random.default_rng(7)
        q = rng.normal(size=29)
        h.push(state=make_state(q), last_action_il=rng.normal(size=29))
        got = h.blocks()["joint_pos_dev"][9]
        np.testing.assert_allclose(got, to_isaaclab_order(q) - to_isaaclab_order(SONIC_DEFAULT_ANGLES_MJ), atol=1e-12)


class TestReferenceStream:
    def _stream(self, n=30):
        rng = np.random.default_rng(3)
        pos = rng.normal(size=(n, 29))
        vel = rng.normal(size=(n, 29)) * 0.1
        quats = np.tile(IDENTITY_QUAT, (n, 1))
        return SonicReferenceStream(joint_pos_il=pos, joint_vel_il=vel, root_quats_wxyz=quats), pos, vel

    def test_lookahead_from_playhead_then_advance(self):
        s, pos, _ = self._stream()
        frames = s.lookahead(num_frames=4, step=1)
        assert frames.joint_pos.shape == (4, 29)
        np.testing.assert_allclose(frames.joint_pos[0], pos[0])
        np.testing.assert_allclose(frames.joint_pos[3], pos[3])
        s.advance()
        frames = s.lookahead(num_frames=4, step=1)
        np.testing.assert_allclose(frames.joint_pos[0], pos[1])

    def test_lookahead_clamps_to_last_frame(self):
        s, pos, _ = self._stream(n=5)
        s.advance(4)  # playhead at last frame
        frames = s.lookahead(num_frames=10, step=1)
        np.testing.assert_allclose(frames.joint_pos[0], pos[4])
        np.testing.assert_allclose(frames.joint_pos[9], pos[4])
        np.testing.assert_allclose(frames.joint_vel[9], s.joint_vel_il[4])

    def test_advance_clamps_at_end(self):
        s, _, _ = self._stream(n=3)
        s.advance(100)
        assert s.playhead == 2


class TestDecoderObs:
    def test_layout_and_dims(self):
        b = SonicObsBuilder()
        b.push_history(make_state(SONIC_DEFAULT_ANGLES_MJ), last_action_il=np.zeros(29))
        token = np.arange(64, dtype=np.float64) * 0.01
        obs = b.build_decoder_obs(token)
        assert obs.shape == (994,)
        np.testing.assert_allclose(obs[:64], token)
        # ang_vel block at 64 (10x3), all zeros here
        np.testing.assert_allclose(obs[64:94], 0.0)
        # q-dev block at 94 (10x29) zeros (state == default)
        np.testing.assert_allclose(obs[94:384], 0.0)
        # gravity block at 964: identity quat -> (0,0,-1) x10
        np.testing.assert_allclose(obs[964:994].reshape(10, 3), np.tile([0, 0, -1], (10, 1)), atol=1e-12)


class TestEncoderObs:
    def _stream(self, n=30):
        rng = np.random.default_rng(11)
        pos = rng.normal(size=(n, 29))
        vel = rng.normal(size=(n, 29)) * 0.1
        quats = np.tile(IDENTITY_QUAT, (n, 1))
        return SonicReferenceStream(joint_pos_il=pos, joint_vel_il=vel, root_quats_wxyz=quats), pos, vel

    def test_layout_offsets_and_values(self):
        b = SonicObsBuilder()
        s, pos, vel = self._stream()
        obs = b.build_encoder_obs(base_quat_wxyz=IDENTITY_QUAT, stream=s)
        assert obs.shape == (1247,)
        # encoder_mode_4: g1 mode_id 0 -> zeros (GatherEncoderMode fill_zeros).
        np.testing.assert_allclose(obs[0:4], 0.0)
        # motion joint positions 10x29 at offset 4, playhead-relative, oldest first.
        np.testing.assert_allclose(obs[4:4 + 290].reshape(10, 29), pos[:10], atol=1e-12)
        # motion joint velocities at 294.
        np.testing.assert_allclose(obs[294:584].reshape(10, 29), vel[:10], atol=1e-12)
        # anchor 6D at 584: identity robot + identity ref -> identity 6D x10.
        np.testing.assert_allclose(obs[584:644].reshape(10, 6), np.tile([1, 0, 0, 1, 0, 0], (10, 1)), atol=1e-12)
        # single-frame anchor at 644.
        np.testing.assert_allclose(obs[644:650], [1, 0, 0, 1, 0, 0], atol=1e-12)
        # lower body pos at 650: 10x12, lower12 isaaclab indices.
        np.testing.assert_allclose(obs[650:770].reshape(10, 12), pos[:10][:, list(LOWER12_MUJOCO_ORDER_IN_ISAACLAB)], atol=1e-12)
        # lower body vel at 770.
        np.testing.assert_allclose(obs[770:890].reshape(10, 12), vel[:10][:, list(LOWER12_MUJOCO_ORDER_IN_ISAACLAB)], atol=1e-12)
        # vr + smpl branches zero (v1-stream parity).
        np.testing.assert_allclose(obs[890:1223], 0.0)
        # wrists 4x6 at 1223 from reference joints il 23..28.
        np.testing.assert_allclose(obs[1223:1247].reshape(4, 6), pos[:4][:, list(WRIST6_ISAACLAB)], atol=1e-12)

    def test_yaw_reference_anchor_block(self):
        b = SonicObsBuilder()
        half = np.sqrt(0.5)
        yaw_quat = np.array([half, 0.0, 0.0, half])
        s = SonicReferenceStream(
            joint_pos_il=np.zeros((10, 29)),
            joint_vel_il=np.zeros((10, 29)),
            root_quats_wxyz=np.tile(yaw_quat, (10, 1)),
        )
        obs = b.build_encoder_obs(base_quat_wxyz=IDENTITY_QUAT, stream=s)
        np.testing.assert_allclose(obs[584:590], [0, -1, 1, 0, 0, 0], atol=1e-12)


class TestDecodeAction:
    def test_zero_action_gives_default(self):
        q = decode_action(np.zeros(29))
        np.testing.assert_allclose(q, SONIC_DEFAULT_ANGLES_MJ, atol=1e-12)

    def test_unit_action_at_left_elbow(self):
        action = np.zeros(29)
        action[21] = 1.0  # il 21 = left_elbow (mj 18)
        q = decode_action(action)
        expected = SONIC_DEFAULT_ANGLES_MJ.copy()
        expected[18] += SONIC_ACTION_SCALE_MJ[18]
        np.testing.assert_allclose(q, expected, atol=1e-12)

    def test_rejects_wrong_length(self):
        with pytest.raises(ValueError):
            decode_action(np.zeros(28))
