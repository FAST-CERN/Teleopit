# tests/test_sim2real_velocity_mode.py
"""RobotMode.VELOCITY worker 侧：装配、模式机、step、安全（bsi-realhw 04/05/07）。"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

import teleopit.sim2real.mp.runtime as runtime_module
from teleopit.sim2real.mp.runtime import RobotMode, _RobotControlWorker


def test_robot_mode_has_velocity() -> None:
    assert RobotMode.VELOCITY.value == "velocity"


class _FakePolicy:
    def reset(self) -> None:
        pass

    def compute_action(self, obs) -> np.ndarray:
        return np.zeros(29, dtype=np.float32)

    def get_target_dof_pos(self, action) -> np.ndarray:
        return np.zeros(29, dtype=np.float32)


class _FakeObsBuilder:
    def reset(self) -> None:
        pass

    def build(self, state, cmd, last_action) -> np.ndarray:
        return np.zeros(10, dtype=np.float32)


def _make_worker(**overrides) -> _RobotControlWorker:
    worker = object.__new__(_RobotControlWorker)
    worker.cfg = {"policy_hz": 50.0}
    worker.endpoints = SimpleNamespace(controller_pub="tcp://127.0.0.1:39999")
    worker.mode = RobotMode.IDLE
    worker.estop = runtime_module.EstopController()
    worker._velocity_policy = None
    worker._velocity_obs_builder = None
    worker._velocity_cmd = None
    worker._velocity_last_action = np.zeros(29, dtype=np.float32)
    worker._last_action = np.zeros(29, dtype=np.float32)
    worker._mocap_entry_enabled = True
    worker._velocity_cmd_logger = runtime_module.VelocityCmdLogger(None)
    for key, value in overrides.items():
        setattr(worker, key, value)
    return worker


def test_build_velocity_stack_assembles_merged_provider(
    monkeypatch, tmp_path
) -> None:
    captured: dict = {}

    def fake_policy_build(cfg, project_root):
        return _FakePolicy(), _FakeObsBuilder()

    def fake_provider_build(joystick, bsi_cfg, *, clock=None, reader_factory=None):
        captured["joystick"] = joystick
        captured["bsi_cfg"] = bsi_cfg
        return SimpleNamespace(
            get_cmd=lambda: np.zeros(6, dtype=np.float32),
            reset=lambda: None,
            close=lambda: None,
            toggle_mute=lambda: True,
            muted=False,
        )

    class _FakeSub:
        def __init__(self, endpoint, topic) -> None:
            captured["topic"] = topic

        def recv_latest(self):
            return None

    monkeypatch.setattr(runtime_module, "build_velocity_policy_components", fake_policy_build)
    monkeypatch.setattr(runtime_module, "build_merged_bsi_provider", fake_provider_build)
    monkeypatch.setattr(runtime_module, "LatestSubscriber", _FakeSub)

    worker = _make_worker()
    command_cfg = {
        "provider": "merged_bsi",
        "joystick": {"deadzone": 0.15, "max_stick_scale": {"lin_vel_x": 0.5}},
        "bsi": {"domain_id": 0, "silence_timeout_s": 1.0, "speeds": {"forward": 0.6, "turn": 0.6}},
        "restrict": {"forward_only": {"max_lin_x": 0.3}},
    }
    worker._build_velocity_stack(command_cfg)

    assert isinstance(worker._velocity_policy, _FakePolicy)
    assert captured["topic"] == "controller"
    assert captured["bsi_cfg"]["domain_id"] == 0
    assert isinstance(worker._velocity_cmd, runtime_module.ForwardOnlyCapProvider)
    capped = worker._velocity_cmd.get_cmd()
    np.testing.assert_allclose(capped, np.zeros(6, dtype=np.float32))


def test_build_velocity_stack_without_restrict_keeps_plain_provider(monkeypatch) -> None:
    monkeypatch.setattr(
        runtime_module, "build_velocity_policy_components",
        lambda cfg, root: (_FakePolicy(), _FakeObsBuilder()),
    )
    monkeypatch.setattr(
        runtime_module, "build_merged_bsi_provider",
        lambda joystick, bsi_cfg, *, clock=None, reader_factory=None: SimpleNamespace(
            get_cmd=lambda: np.zeros(6, dtype=np.float32),
            reset=lambda: None, close=lambda: None,
        ),
    )
    monkeypatch.setattr(
        runtime_module, "LatestSubscriber",
        lambda endpoint, topic: SimpleNamespace(recv_latest=lambda: None),
    )

    worker = _make_worker()
    worker._build_velocity_stack({"provider": "merged_bsi"})
    assert not isinstance(worker._velocity_cmd, runtime_module.ForwardOnlyCapProvider)
