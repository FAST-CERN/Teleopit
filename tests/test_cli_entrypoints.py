from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


def _run_cli(project_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/run/run_sim.py", *args],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )


def test_run_sim_help_uses_hydra_cli(project_root: Path) -> None:
    result = _run_cli(project_root, "--help")

    assert result.returncode == 0, result.stderr
    assert "Powered by Hydra" in result.stdout


def test_run_sim_hydra_help_lists_hydra_flags(project_root: Path) -> None:
    result = _run_cli(project_root, "--hydra-help")

    assert result.returncode == 0, result.stderr
    assert "--cfg" in result.stdout
    assert "--multirun" in result.stdout


def test_run_sim_cfg_job_uses_hydra_cli(project_root: Path) -> None:
    result = _run_cli(project_root, "--cfg", "job")

    assert result.returncode == 0, result.stderr
    assert "controller:" in result.stdout
    assert "input:" in result.stdout


# ── pico4_sim_velocity.yaml launch config (task #6 VELOCITY mode) ──────────

_CONFIG_DIR = Path(__file__).resolve().parents[1] / "teleopit" / "configs"


def test_pico4_sim_velocity_config_loads_with_velocity_section() -> None:
    from hydra import compose, initialize_config_dir

    with initialize_config_dir(
        config_dir=str(_CONFIG_DIR), version_base=None
    ):
        cfg = compose(config_name="pico4_sim_velocity")
    assert str(cfg.input.provider) == "pico4"
    assert bool(cfg.keyboard.enabled) is True
    assert cfg.controllers.velocity.policy_path is not None
    assert str(cfg.command.provider) == "pico_joystick"
    assert float(cfg.safety.joint_vel_limit) == 12.0


def test_select_cmd_provider_kind_by_input() -> None:
    from teleopit.pipeline import _select_cmd_provider_kind

    assert _select_cmd_provider_kind("pico4") == "pico_joystick"
    assert _select_cmd_provider_kind("bvh") == "keyboard"
    assert _select_cmd_provider_kind("udp_bvh") == "keyboard"


def test_velocity_components_wrapper_builds_single_input_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """build_velocity_policy_components: only the velocity pair, pose B kept.

    Adapts tests/test_factory_velocity.py's _FakeSession monkeypatch of
    teleopit.controllers.rl_policy._open_onnx_session to a 98D single-input
    policy; the wrapper must not propagate robot defaults (pose A) into the
    twist builder's default_dof_pos (pose B).
    """
    from teleopit.runtime.factory import build_velocity_policy_components

    pose_b = [
        -0.1, 0.0, 0.0, 0.3, -0.2, 0.0,
        -0.1, 0.0, 0.0, 0.3, -0.2, 0.0,
        0.0, 0.0, 0.0,
        0.35, 0.18, 0.0, 0.87, 0.0, 0.0, 0.0,
        0.35, -0.18, 0.0, 0.87, 0.0, 0.0, 0.0,
    ]
    pose_a = [0.0] * 29
    pose_a[3] = 0.669

    class _FakeOnnxInput:
        def __init__(self, name: str, shape: list[int]) -> None:
            self.name = name
            self.shape = shape

    class _FakeSession:
        def __init__(self) -> None:
            self._inputs = [_FakeOnnxInput("obs", [1, 98])]
            self._outputs = [_FakeOnnxInput("actions", [1, 29])]

        def get_inputs(self):
            return self._inputs

        def get_outputs(self):
            return self._outputs

    monkeypatch.setattr(
        "teleopit.controllers.rl_policy._open_onnx_session",
        lambda policy_path, device: _FakeSession(),
    )

    velocity_onnx = tmp_path / "velocity.onnx"
    velocity_onnx.write_bytes(b"fake")
    xml_path = tmp_path / "robot.xml"
    xml_path.write_text("<mujoco model='dummy'/>", encoding="utf-8")
    cfg = {
        "policy_hz": 50.0,
        "robot": {
            "num_actions": 29,
            "default_angles": list(pose_a),
            "xml_path": str(xml_path),
            "anchor_body_name": "torso_link",
        },
        "controllers": {
            "velocity": {
                "policy_path": str(velocity_onnx),
                "observation_type": "twist_cmd",
                "default_dof_pos": list(pose_b),
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
    }

    controller, obs_builder = build_velocity_policy_components(cfg, tmp_path)

    assert controller._multi_input is False  # single-input ONNX accepted
    assert obs_builder.total_obs_size == 98
    assert float(obs_builder.default_dof_pos[3]) == pytest.approx(0.3)
    assert float(obs_builder.default_dof_pos[3]) != pytest.approx(pose_a[3])


# ── pico4_sim2real_bsi.yaml (bsi-realhw Phase B real VELOCITY mode) ────────


def test_pico4_sim2real_bsi_config_loads() -> None:
    from hydra import compose, initialize_config_dir

    with initialize_config_dir(config_dir=str(_CONFIG_DIR), version_base=None):
        cfg = compose(config_name="pico4_sim2real_bsi")
    assert str(cfg.command.provider) == "merged_bsi"
    assert str(cfg.input.velocity_button) == "X"
    assert str(cfg.input.estop_button) == "left_grip"
    assert str(cfg.input.mute_button) == "Y"
    assert float(cfg.input.estop_grip_threshold) == 0.6
    assert float(cfg.safety.joint_vel_limit) == 10.0
    assert float(cfg.safety.tilt_graceful_rad) == 0.524
    assert float(cfg.safety.tilt_damping_rad) == 0.785
    # flipped 2026-08-22 for mixed walk->mocap sessions; entry stays STANDING-only
    assert bool(cfg.mocap_entry_enabled) is True
    assert cfg.controllers.velocity.policy_path is not None
    assert float(cfg.real_robot.kp_real[0]) == 40.2  # 继承自 pico4_sim2real 基线
    assert float(cfg.command.joystick.deadzone) == 0.15
    assert float(cfg.command.joystick.max_age_s) == 0.5
    # L3 field finding 2026-08-22: unified with the BSI envelope — forward
    # 0.3*2.0=0.6 m/s; ang_z/lin_y now explicitly capped (were unscaled).
    assert float(cfg.command.joystick.max_stick_scale.lin_vel_x) == 0.3
    assert float(cfg.command.joystick.max_stick_scale.lin_vel_y) == 0.4
    assert float(cfg.command.joystick.max_stick_scale.ang_vel_z) == 0.4
    assert int(cfg.command.bsi.domain_id) == 0
    assert float(cfg.command.bsi.silence_timeout_s) == 1.0
    assert int(cfg.command.bsi.debounce_packets) == 3
    assert int(cfg.command.bsi.idle_debounce_packets) == 2
    assert float(cfg.command.bsi.alpha) == 0.3
    assert float(cfg.command.bsi.speeds.forward) == 0.6
    assert float(cfg.command.bsi.speeds.turn) == 0.6
    assert str(cfg.velocity_cmd_log.path) == "data/velocity_cmd.jsonl"


def test_pico4_sim2real_bsi_l2_config_restricts_forward() -> None:
    from hydra import compose, initialize_config_dir

    with initialize_config_dir(config_dir=str(_CONFIG_DIR), version_base=None):
        cfg = compose(config_name="pico4_sim2real_bsi_l2")
    assert float(cfg.command.restrict.forward_only.max_lin_x) == 0.3
    assert float(cfg.command.bsi.speeds.forward) == 0.3
    assert float(cfg.command.bsi.speeds.turn) == 0.3
    assert str(cfg.velocity_cmd_log.path) == "data/velocity_cmd_l2.jsonl"
