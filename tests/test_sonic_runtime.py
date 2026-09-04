"""SONIC onnxruntime session wrapper (sonic-wbc t02 TDD-3).

Runs the real low_latency checkpoint pair downloaded to
``assets/policies/sonic/low_latency`` (hf-mirror). IO contract verified
against the models themselves (2026-09-04):

- encoder: ``obs_dict [1,1247] f32`` -> ``encoded_tokens [1,64]``
- decoder: ``obs_dict [1,994] f32`` -> ``action [1,29]``

Skipped when the checkpoints are not on disk (assets are gitignored).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from teleopit.policies.sonic.observation import SonicObsBuilder, SonicReferenceStream
from teleopit.policies.sonic.params import SONIC_DEFAULT_ANGLES_MJ
from teleopit.policies.sonic.runtime import SONIC_CKPT_DIR, SonicOnnxPolicy

requires_ckpt = pytest.mark.skipif(
    not (SONIC_CKPT_DIR / "model_encoder.onnx").exists()
    or not (SONIC_CKPT_DIR / "model_decoder.onnx").exists(),
    reason="SONIC low_latency checkpoints not downloaded (assets/policies/sonic)",
)

IDENTITY_QUAT = np.array([1.0, 0.0, 0.0, 0.0])


def make_state(qpos_mj):
    return {
        "qpos": np.asarray(qpos_mj, dtype=np.float64),
        "qvel": np.zeros(29),
        "ang_vel": np.zeros(3),
        "quat": IDENTITY_QUAT.copy(),
    }


class TestLoadAndValidate:
    @requires_ckpt
    def test_loads_and_reports_dims(self):
        policy = SonicOnnxPolicy()
        assert policy.encoder_input_dim == 1247
        assert policy.decoder_input_dim == 994
        assert policy.token_dim == 64
        assert policy.action_dim == 29

    def test_missing_dir_raises_with_hint(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="GEAR-SONIC"):
            SonicOnnxPolicy(ckpt_dir=tmp_path)

    @requires_ckpt
    def test_wrong_input_dim_raises(self):
        policy = SonicOnnxPolicy()
        with pytest.raises(ValueError, match="1247"):
            policy.encode(np.zeros(999))
        with pytest.raises(ValueError, match="994"):
            policy.decode(np.zeros(999))


@requires_ckpt
class TestInferenceSmoke:
    def test_zeros_obs_produces_finite_outputs(self):
        policy = SonicOnnxPolicy()
        token = policy.encode(np.zeros(1247))
        assert token.shape == (64,)
        assert np.all(np.isfinite(token))
        action = policy.decode(np.zeros(994))
        assert action.shape == (29,)
        assert np.all(np.isfinite(action))
        assert np.max(np.abs(action)) < 50.0

    def test_full_codec_round_trip_with_obs_builder(self):
        """encoder obs -> token -> decoder obs (token block) -> action."""
        policy = SonicOnnxPolicy()
        builder = SonicObsBuilder()
        builder.push_history(make_state(SONIC_DEFAULT_ANGLES_MJ), last_action_il=np.zeros(29))
        stream = SonicReferenceStream(
            joint_pos_il=np.tile(to_il_default(), (16, 1)),
            joint_vel_il=np.zeros((16, 29)),
            root_quats_wxyz=np.tile(IDENTITY_QUAT, (16, 1)),
        )
        enc_obs = builder.build_encoder_obs(base_quat_wxyz=IDENTITY_QUAT, stream=stream)
        token = policy.encode(enc_obs)
        dec_obs = builder.build_decoder_obs(token)
        action = policy.decode(dec_obs)
        assert action.shape == (29,)
        assert np.all(np.isfinite(action))


def to_il_default():
    from teleopit.policies.sonic.joint_order import to_isaaclab_order

    return to_isaaclab_order(SONIC_DEFAULT_ANGLES_MJ)
