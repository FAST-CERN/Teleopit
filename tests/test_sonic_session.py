"""SonicSimSession sim2sim closed loop (sonic-wbc t02 TDD-4).

Drives MuJoCoRobot at the pd_hz-200 invariant (sim_dt 0.005, decimation 4,
50 Hz policy) through the SONIC obs/codec stack. Session-logic tests run
against a stub policy so the loop mechanics stay testable without the
checkpoint; one integration smoke exercises the real ONNX pair and asserts
only mechanical health (finite actions, loop completes) — stability lines
belong to ticket 03.
"""
from __future__ import annotations

import numpy as np
import pytest

from conftest import find_g1_xml_path, requires_mujoco

from teleopit.policies.sonic.joint_order import from_isaaclab_order, to_isaaclab_order
from teleopit.policies.sonic.observation import SonicReferenceStream
from teleopit.policies.sonic.params import SONIC_DEFAULT_ANGLES_MJ
from teleopit.policies.sonic.runtime import SONIC_CKPT_DIR
from teleopit.sim.sonic_session import SonicSimSession

_XML_PATH = find_g1_xml_path()
_skip_no_xml = pytest.mark.skipif(_XML_PATH is None, reason="Robot XML not found")

IDENTITY_QUAT = np.array([1.0, 0.0, 0.0, 0.0])
ARM_MJ = list(range(15, 29))


class StubPolicy:
    """Duck-typed SonicOnnxPolicy: validates dims, always outputs zeros."""

    encoder_input_dim = 1247
    decoder_input_dim = 994
    token_dim = 64
    action_dim = 29

    def encode(self, encoder_obs):
        assert np.asarray(encoder_obs).reshape(-1).shape[0] == 1247
        return np.zeros(64)

    def decode(self, decoder_obs):
        assert np.asarray(decoder_obs).reshape(-1).shape[0] == 994
        return np.zeros(29)


def _make_robot():
    from omegaconf import OmegaConf
    from teleopit.robots.mujoco_robot import MuJoCoRobot

    cfg = OmegaConf.load("teleopit/configs/robot/g1.yaml")
    cfg.xml_path = str(_XML_PATH)
    return MuJoCoRobot(cfg)


def _standing_stream(arm_offset_il=None, frames=600):
    pos_il = np.tile(to_isaaclab_order(SONIC_DEFAULT_ANGLES_MJ), (frames, 1))
    if arm_offset_il is not None:
        pos_il = pos_il.copy()
        pos_il[:, arm_offset_il] += 0.25
    return SonicReferenceStream(
        joint_pos_il=pos_il,
        joint_vel_il=np.zeros((frames, 29)),
        root_quats_wxyz=np.tile(IDENTITY_QUAT, (frames, 1)),
    )


@requires_mujoco
@_skip_no_xml
class TestSessionLoop:
    def test_standing_reference_with_stub_policy_holds(self):
        # Passive PD-hold of the default pose collapses on this plant after
        # ~1.4 s (measured; the mimic policy balances actively), so the stub
        # test stays inside that horizon and checks loop mechanics + metrics,
        # not balance.
        session = SonicSimSession(robot=_make_robot(), policy=StubPolicy())
        session.attach_reference(_standing_stream())
        summary = session.run(50)
        assert summary["steps"] == 50
        assert summary["fell"] is False
        assert summary["min_root_height_m"] > 0.5
        assert summary["upper_track_rmse_rad"] < 0.08
        assert summary["upper_track_max_rad"] < 0.2

    def test_upper_track_metric_reacts_to_reference_offset(self):
        # Stub policy holds the default pose; reference asks for elbow +0.25
        # (il 21). The tracking metric must see it (max over arm-14 joints).
        session = SonicSimSession(robot=_make_robot(), policy=StubPolicy())
        session.attach_reference(_standing_stream(arm_offset_il=21))
        summary = session.run(50)
        assert summary["fell"] is False
        assert summary["upper_track_max_rad"] == pytest.approx(0.25, abs=0.03)
        # RMSE over 14 arm joints with a single 0.25 offset.
        assert summary["upper_track_rmse_rad"] == pytest.approx(0.25 / np.sqrt(14), abs=0.02)

    def test_reference_stream_advances_with_steps_and_clamps(self):
        stream = _standing_stream(frames=60)
        session = SonicSimSession(robot=_make_robot(), policy=StubPolicy())
        session.attach_reference(stream)
        session.run(80)
        assert stream.playhead == 59  # clamped at last frame (hold-tail)

    def test_fall_guard_threshold(self):
        session = SonicSimSession(robot=_make_robot(), policy=StubPolicy())
        assert session._is_fallen({"base_pos": np.array([0.0, 0.0, 0.30])}) is True
        assert session._is_fallen({"base_pos": np.array([0.0, 0.0, 0.72])}) is False

    def test_missing_reference_stream_raises(self):
        session = SonicSimSession(robot=_make_robot(), policy=StubPolicy())
        with pytest.raises(RuntimeError, match="reference"):
            session.run(10)


@requires_mujoco
@_skip_no_xml
@pytest.mark.skipif(
    not (SONIC_CKPT_DIR / "model_encoder.onnx").exists()
    or not (SONIC_CKPT_DIR / "model_decoder.onnx").exists(),
    reason="SONIC low_latency checkpoints not downloaded",
)
class TestRealPolicyIntegrationSmoke:
    def test_runs_finite_actions_over_50_steps(self):
        from teleopit.policies.sonic.runtime import SonicOnnxPolicy

        session = SonicSimSession(robot=_make_robot(), policy=SonicOnnxPolicy())
        session.attach_reference(_standing_stream())
        summary = session.run(50)
        assert summary["steps"] == 50
        assert np.isfinite(summary["max_abs_action"])
        assert summary["max_abs_action"] > 0.0  # real policy, not the stub
        assert "min_root_height_m" in summary
