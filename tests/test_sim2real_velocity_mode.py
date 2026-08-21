# tests/test_sim2real_velocity_mode.py
"""RobotMode.VELOCITY worker 侧：装配、模式机、step、安全（bsi-realhw 04/05/07）。"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

import teleopit.sim2real.mp.runtime as runtime_module
from teleopit.inputs.realtime_packet import ControlEvent, ControlEventType
from teleopit.sim.estop import EstopState
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
    worker._mocap_entry_requested = False
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


def _velocity_ready_worker(**overrides) -> _RobotControlWorker:
    worker = _make_worker(**overrides)
    worker.mode = RobotMode.STANDING
    worker._velocity_policy = _FakePolicy()
    worker._velocity_obs_builder = _FakeObsBuilder()
    worker._velocity_cmd = SimpleNamespace(
        get_cmd=lambda: np.zeros(6, dtype=np.float32),
        reset=lambda: None,
        close=lambda: None,
        toggle_mute=lambda: True,
        muted=False,
    )
    worker.estop = runtime_module.EstopController()
    return worker


def _send(worker: _RobotControlWorker, event_type: ControlEventType) -> None:
    worker._handle_mocap_control_events(
        (ControlEvent(event_type=event_type, source="pico4:test", timestamp_s=1.0),)
    )


def test_toggle_velocity_enters_from_standing() -> None:
    worker = _velocity_ready_worker()
    _send(worker, ControlEventType.TOGGLE_VELOCITY)
    assert worker.mode == RobotMode.VELOCITY


def test_toggle_velocity_refused_when_estop_latched() -> None:
    worker = _velocity_ready_worker()
    worker.estop.latch()
    _send(worker, ControlEventType.TOGGLE_VELOCITY)
    assert worker.mode == RobotMode.STANDING


def test_toggle_velocity_ignored_without_stack() -> None:
    worker = _make_worker()  # _velocity_policy None
    worker.mode = RobotMode.STANDING
    _send(worker, ControlEventType.TOGGLE_VELOCITY)
    assert worker.mode == RobotMode.STANDING


def test_toggle_velocity_exits_back_to_standing() -> None:
    worker = _velocity_ready_worker()
    _send(worker, ControlEventType.TOGGLE_VELOCITY)
    exits: list[str] = []
    worker._exit_velocity_to_standing = lambda: exits.append("exit")  # spy
    _send(worker, ControlEventType.TOGGLE_VELOCITY)
    assert exits == ["exit"]


def test_toggle_estop_in_velocity_engages_ramp() -> None:
    worker = _velocity_ready_worker()
    _send(worker, ControlEventType.TOGGLE_VELOCITY)
    _send(worker, ControlEventType.TOGGLE_ESTOP)
    assert worker.estop.state == EstopState.RAMPING


def test_toggle_estop_in_standing_is_noop() -> None:
    worker = _velocity_ready_worker()
    _send(worker, ControlEventType.TOGGLE_ESTOP)
    assert worker.estop.state == EstopState.INACTIVE
    assert worker.mode == RobotMode.STANDING


def test_toggle_mute_delegates_to_provider() -> None:
    worker = _velocity_ready_worker()
    mute_calls: list[bool] = []

    def _mute() -> bool:
        mute_calls.append(True)
        return True

    worker._velocity_cmd = SimpleNamespace(
        get_cmd=lambda: np.zeros(6, dtype=np.float32),
        reset=lambda: None, close=lambda: None, toggle_mute=_mute, muted=False,
    )
    _send(worker, ControlEventType.TOGGLE_MUTE)
    assert mute_calls == [True]


def test_mocap_entry_gate_blocks_remote_y_when_disabled() -> None:
    worker = _velocity_ready_worker()
    worker._mocap_entry_enabled = False
    worker.remote = SimpleNamespace(
        Y=SimpleNamespace(on_pressed=True, pressed=False),
    )
    worker._mocap_reentry_armed = False
    # STANDING 分支只触 Y 检查：无其它 remote 属性也必须不炸
    worker._handle_transitions()
    assert worker._mocap_entry_requested is False
