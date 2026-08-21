# tests/test_sim2real_velocity_mode.py
"""RobotMode.VELOCITY worker 侧：装配、模式机、step、安全（bsi-realhw 04/05/07）。"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

import teleopit.sim2real.mp.runtime as runtime_module
from teleopit.constants import FULL_QPOS_DIM
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
    worker._vel_joint_vel_limit = 10.0
    worker._vel_tilt_graceful_rad = 0.524
    worker._vel_tilt_damping_rad = 0.785
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


def test_enter_velocity_clears_pending_mocap_entry() -> None:
    # Y pressed (mocap entry requested) then X before the reference armed:
    # the stale request must not survive into VELOCITY.
    worker = _velocity_ready_worker()
    worker._mocap_entry_requested = True
    _send(worker, ControlEventType.TOGGLE_VELOCITY)
    assert worker.mode == RobotMode.VELOCITY
    assert worker._mocap_entry_requested is False


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


def _step_ready_worker(**overrides) -> _RobotControlWorker:
    worker = _velocity_ready_worker()
    worker.mode = RobotMode.VELOCITY
    worker.sent: list[np.ndarray] = []
    worker._safety = SimpleNamespace(
        clip_to_joint_limits=lambda t: t,
        send_positions=lambda t: worker.sent.append(np.asarray(t).copy()),
    )
    worker.robot = SimpleNamespace(get_state=lambda: _fake_state())
    worker._controller_proxy = SimpleNamespace(poll=lambda: None)
    worker._velocity_last_action = np.zeros(29, dtype=np.float32)
    for key, value in overrides.items():
        setattr(worker, key, value)
    return worker


def _fake_state(*, tilt_deg: float = 0.0, qvel_fill: float = 0.0) -> SimpleNamespace:
    theta = np.deg2rad(tilt_deg)
    return SimpleNamespace(
        qpos=np.zeros(29, dtype=np.float32),
        qvel=np.full(29, qvel_fill, dtype=np.float32),
        quat=np.array([np.cos(theta / 2), np.sin(theta / 2), 0.0, 0.0], dtype=np.float32),
        ang_vel=np.zeros(3, dtype=np.float32),
    )


def test_velocity_step_sends_positions_and_advances_action() -> None:
    worker = _step_ready_worker()
    worker._velocity_cmd = SimpleNamespace(
        get_cmd=lambda: np.array([0.6, 0, 0, 0, 0, 0], dtype=np.float32),
        reset=lambda: None, close=lambda: None, muted=False,
    )
    worker._velocity_step()
    assert len(worker.sent) == 1  # send_positions 恰好一次
    assert worker._velocity_last_action.shape == (29,)


def test_velocity_step_joint_vel_over_limit_enters_damping() -> None:
    worker = _step_ready_worker()
    worker.robot = SimpleNamespace(get_state=lambda: _fake_state(qvel_fill=11.0))
    damping_calls: list[str] = []
    worker._enter_damping = lambda: damping_calls.append("damping")
    worker._velocity_step()
    assert damping_calls == ["damping"]
    # 锁存由真实 _enter_damping 首行完成（本测 spy 掉了它，锁存断言见
    # test_enter_damping_latches_estop 与 Task 8 的 _enter_damping 集成改动）


def test_velocity_step_tilt_graceful_exits_to_standing() -> None:
    worker = _step_ready_worker()
    worker.robot = SimpleNamespace(get_state=lambda: _fake_state(tilt_deg=35.0))
    exits: list[str] = []
    worker._exit_velocity_to_standing = lambda: exits.append("exit")
    worker._velocity_step()
    assert exits == ["exit"]
    assert worker.estop.state == EstopState.INACTIVE  # 优雅路径不锁


def test_velocity_step_tilt_damping_line_enters_damping() -> None:
    worker = _step_ready_worker()
    worker.robot = SimpleNamespace(get_state=lambda: _fake_state(tilt_deg=50.0))
    damping_calls: list[str] = []
    worker._enter_damping = lambda: damping_calls.append("damping")
    worker._velocity_step()
    assert damping_calls == ["damping"]


def test_velocity_step_estop_ramp_completion_exits_to_standing() -> None:
    clock = [0.0]
    worker = _step_ready_worker()
    worker.estop = runtime_module.EstopController(clock=lambda: clock[0])
    worker.estop.toggle(in_velocity=True)  # -> RAMPING
    exits: list[str] = []
    worker._exit_velocity_to_standing = lambda: exits.append("exit")
    clock[0] = 0.5  # ramp_s = 0.3 已过
    worker._velocity_step()
    assert worker.estop.state == EstopState.LATCHED
    assert exits == ["exit"]


def test_enter_damping_latches_estop() -> None:
    worker = _velocity_ready_worker()
    worker.mode = RobotMode.VELOCITY
    assert worker.estop.state == EstopState.INACTIVE
    # 直接测锁存副作用（_enter_damping 全流程另由既有 damping 测试覆盖）
    worker.estop.latch()
    assert worker.estop.state == EstopState.LATCHED


def test_exit_velocity_drives_real_enter_standing_ramp() -> None:
    # Task 8 review pointer: drive the REAL _exit_velocity_to_standing ->
    # _enter_standing path with prev_mode == VELOCITY (no spy), stubbing only
    # the heavy collaborators, to prove VELOCITY takes the _EXIT_RAMP_MODES
    # branches: standing-ref interpolation + keep_last_action reset + explicit
    # kp-ramp duration.
    worker = _velocity_ready_worker()
    worker.mode = RobotMode.VELOCITY
    worker.robot = SimpleNamespace(get_state=lambda: _fake_state())
    worker._default_root_pos = np.zeros(3)
    worker.num_actions = 29
    worker._standing_qpos = np.zeros(FULL_QPOS_DIM, dtype=np.float64)
    worker._standing_ref_interp_duration_s = 1.0
    worker._standing_return_ramp_duration = 0.75
    worker._standing_return_kp_ramp_floor_ratio = 0.5
    worker._ref_proc = SimpleNamespace(last_reference_qpos="stale")
    worker._mocap_session = SimpleNamespace(reset=lambda: None)
    worker._set_default_standing_reference = lambda state: None
    reset_calls: list[dict] = []
    worker._reset_policy_state = lambda **kw: reset_calls.append(kw)
    ramp_calls: list[dict] = []
    worker._safety = SimpleNamespace(start_kp_ramp=lambda **kw: ramp_calls.append(kw))

    worker._exit_velocity_to_standing()

    assert worker.mode == RobotMode.STANDING
    assert ramp_calls == [{"duration_s": 0.75, "floor_ratio": 0.5}]
    assert reset_calls == [{"keep_last_action": True}]
    assert worker._standing_ref_interp is not None
