"""Tests for teleopit.runtime.factory — velocity (twist_cmd) dual-controller build.

RLPolicyController session loading is bypassed by monkeypatching the
module-level ``_open_onnx_session`` seam in ``teleopit.controllers.rl_policy``,
so the real input-signature analysis (single vs dual input, obs-dim checks)
stays under test without a real ONNX model.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from teleopit.runtime.factory import build_velocity_components

# Pose B — the velocity policy's neutral pose (teleopit/configs/controller/velocity.yaml).
_POSE_B = [
    -0.1, 0.0, 0.0, 0.3, -0.2, 0.0,
    -0.1, 0.0, 0.0, 0.3, -0.2, 0.0,
    0.0, 0.0, 0.0,
    0.35, 0.18, 0.0, 0.87, 0.0, 0.0, 0.0,
    0.35, -0.18, 0.0, 0.87, 0.0, 0.0, 0.0,
]
# Pose A — robot defaults; deliberately different at the asserted index.
_POSE_A = [0.0] * 29
_POSE_A[3] = 0.669


class _FakeOnnxInput:
    def __init__(self, name: str, shape: list[int]) -> None:
        self.name = name
        self.shape = shape


class _FakeSession:
    def __init__(self, inputs: list[_FakeOnnxInput], outputs: list[_FakeOnnxInput]) -> None:
        self._inputs = inputs
        self._outputs = outputs

    def get_inputs(self) -> list[_FakeOnnxInput]:
        return self._inputs

    def get_outputs(self) -> list[_FakeOnnxInput]:
        return self._outputs


def _dual_input_session() -> _FakeSession:
    """Mimic-style policy: 'obs' + 'obs_history' dual inputs, 167D."""
    return _FakeSession(
        [_FakeOnnxInput("obs", [1, 167]), _FakeOnnxInput("obs_history", [1, 50, 167])],
        [_FakeOnnxInput("actions", [1, 29])],
    )


def _single_input_session() -> _FakeSession:
    """Velocity-style policy: single 'obs' input, 98D."""
    return _FakeSession(
        [_FakeOnnxInput("obs", [1, 98])],
        [_FakeOnnxInput("actions", [1, 29])],
    )


def _patch_sessions(
    monkeypatch: pytest.MonkeyPatch,
    *,
    mimic: _FakeSession,
    velocity: _FakeSession,
) -> None:
    def fake_open_session(policy_path: Any, device: Any) -> _FakeSession:
        name = Path(str(policy_path)).name
        if name == "mimic.onnx":
            return mimic
        if name == "velocity.onnx":
            return velocity
        raise AssertionError(f"unexpected policy path: {policy_path}")

    monkeypatch.setattr(
        "teleopit.controllers.rl_policy._open_onnx_session",
        fake_open_session,
    )


class _DummyRobot:
    def __init__(self, cfg: object) -> None:
        self.cfg = cfg


class _DummyVelCmdBuilder:
    """Stands in for VelCmdObservationBuilder (which needs mujoco + real XML)."""

    total_obs_size = 167

    def __init__(self, cfg: object) -> None:
        self.cfg = cfg

    def reset(self) -> None:
        pass


def _base_cfg(tmp_path: Path) -> dict[str, Any]:
    mimic_onnx = tmp_path / "mimic.onnx"
    mimic_onnx.write_bytes(b"fake")
    velocity_onnx = tmp_path / "velocity.onnx"
    velocity_onnx.write_bytes(b"fake")
    xml_path = tmp_path / "robot.xml"
    xml_path.write_text("<mujoco model='dummy'/>", encoding="utf-8")
    return {
        "policy_hz": 50.0,
        "robot": {
            "num_actions": 29,
            "default_angles": list(_POSE_A),
            "action_scale": [0.25] * 29,
            "xml_path": str(xml_path),
            "anchor_body_name": "torso_link",
        },
        "controller": {  # legacy mimic section
            "policy_path": str(mimic_onnx),
            "observation_type": "velcmd_history",
        },
        "controllers": {
            "velocity": {
                "policy_path": str(velocity_onnx),
                "observation_type": "twist_cmd",
                "default_dof_pos": list(_POSE_B),
                "action_scale": [0.5] * 29,
                "clip_range": [-10.0, 10.0],
                "cmd_limits": {
                    "lin_vel_x": [-1.0, 2.0],
                    "lin_vel_y": [-0.5, 0.5],
                    "ang_vel_z": [-1.0, 1.0],
                },
                "gait_period_s": 0.6,
                "gait_zero_cmd_norm": 0.1,
            },
        },
        "command": {"provider": "keyboard"},
    }


def test_velocity_components_build_both_controllers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_sessions(monkeypatch, mimic=_dual_input_session(), velocity=_single_input_session())
    # Also proves the legacy monkeypatch point still flows through the registry.
    monkeypatch.setattr("teleopit.runtime.factory.VelCmdObservationBuilder", _DummyVelCmdBuilder)

    cfg = _base_cfg(tmp_path)
    components = build_velocity_components(cfg, tmp_path, robot_cls=_DummyRobot)

    # Velocity section: single-input ONNX accepted, real 98D twist builder.
    assert components.velocity_controller._multi_input is False
    assert components.velocity_obs_builder.total_obs_size == 98
    # Pose B intact: velocity defaults are the policy pose, not robot pose A.
    assert float(components.velocity_obs_builder.default_dof_pos[3]) == pytest.approx(0.3)
    assert float(components.velocity_obs_builder.default_dof_pos[3]) != pytest.approx(_POSE_A[3])
    # Mimic section still built through the legacy controller key.
    assert components.mimic_controller._multi_input is True
    assert components.mimic_obs_builder.total_obs_size == 167
    assert isinstance(components.mimic_obs_builder, _DummyVelCmdBuilder)
    assert components.mimic_obs_builder.cfg["num_actions"] == 29
    # Robot constructed from the same robot_cfg; command/sim cfgs passed through.
    assert isinstance(components.robot, _DummyRobot)
    assert components.robot.cfg is cfg["robot"]
    assert components.command_cfg == {"provider": "keyboard"}
    assert components.sim_cfg["policy_hz"] == pytest.approx(50.0)


def test_velocity_components_accepts_controllers_mimic_section(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_sessions(monkeypatch, mimic=_dual_input_session(), velocity=_single_input_session())
    monkeypatch.setattr("teleopit.runtime.factory.VelCmdObservationBuilder", _DummyVelCmdBuilder)

    cfg = _base_cfg(tmp_path)
    cfg["controllers"]["mimic"] = cfg.pop("controller")

    components = build_velocity_components(cfg, tmp_path, robot_cls=_DummyRobot)
    assert components.mimic_controller._multi_input is True
    assert components.mimic_obs_builder.total_obs_size == 167
    assert components.velocity_obs_builder.total_obs_size == 98


def test_velocity_components_rejects_single_input_mimic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_sessions(monkeypatch, mimic=_single_input_session(), velocity=_single_input_session())

    cfg = _base_cfg(tmp_path)
    with pytest.raises(ValueError, match="dual inputs"):
        build_velocity_components(cfg, tmp_path, robot_cls=_DummyRobot)


def test_velocity_components_requires_explicit_default_dof_pos(tmp_path: Path) -> None:
    cfg = _base_cfg(tmp_path)
    del cfg["controllers"]["velocity"]["default_dof_pos"]
    with pytest.raises(ValueError, match="controllers.velocity.default_dof_pos"):
        build_velocity_components(cfg, tmp_path, robot_cls=_DummyRobot)


def test_velocity_components_requires_velocity_section(tmp_path: Path) -> None:
    cfg = _base_cfg(tmp_path)
    del cfg["controllers"]
    with pytest.raises(ValueError, match="controllers.velocity"):
        build_velocity_components(cfg, tmp_path, robot_cls=_DummyRobot)


def test_build_obs_builder_rejects_unknown_observation_type() -> None:
    from teleopit.runtime.factory import _build_obs_builder

    with pytest.raises(ValueError, match="Unsupported controller.observation_type='wibble'"):
        _build_obs_builder({}, {"observation_type": "wibble"}, {})
