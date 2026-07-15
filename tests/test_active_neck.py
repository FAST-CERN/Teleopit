from __future__ import annotations

import math
from types import ModuleType, SimpleNamespace

import numpy as np

from teleopit.inputs.pico4_provider import BODY_JOINT_NAMES, Pico4InputProvider
from teleopit.sim2real.neck.config import NeckConfig, parse_neck_config
from teleopit.sim2real.neck.mapper import HeadPoseMapper
from teleopit.sim2real.neck.openneck import OpenNeckDevice
from teleopit.sim2real.neck.worker import NeckRuntime, body_packet_frame


def _quat_y(deg: float) -> np.ndarray:
    rad = math.radians(deg)
    return np.array([math.cos(rad / 2.0), 0.0, math.sin(rad / 2.0), 0.0], dtype=np.float64)


def _quat_x(deg: float) -> np.ndarray:
    rad = math.radians(deg)
    return np.array([math.cos(rad / 2.0), math.sin(rad / 2.0), 0.0, 0.0], dtype=np.float64)


def _frame(head: np.ndarray, spine: np.ndarray | None = None):
    pos = np.zeros(3, dtype=np.float64)
    frame = {"Head": (pos, head)}
    if spine is not None:
        frame["Spine3"] = (pos, spine)
    return frame


def test_head_pose_mapper_maps_fixed_neutral_yaw_pitch_without_startup_calibration() -> None:
    cfg = NeckConfig(
        enabled=True,
        invert_yaw=False,
        invert_pitch=False,
        dead_zone_deg=0.0,
    )
    mapper = HeadPoseMapper(cfg)

    command = mapper.map_frame(_frame(_quat_y(30.0), _quat_y(0.0)))
    assert command is not None
    assert command.yaw_deg == pytest_approx(30.0)
    assert command.yaw == pytest_approx(30.0 / 90.0)

    command = mapper.map_frame(_frame(_quat_y(0.0), _quat_y(0.0)))
    assert command is not None
    assert command.yaw_deg == pytest_approx(0.0)
    assert command.yaw == pytest_approx(0.0)

    command = mapper.map_frame(_frame(_quat_x(15.0), _quat_x(0.0)))
    assert command is not None
    assert command.pitch_deg == pytest_approx(15.0)
    assert command.pitch == pytest_approx(15.0 / 60.0)


def test_head_pose_mapper_uses_body_relative_orientation() -> None:
    cfg = NeckConfig(
        enabled=True,
        invert_yaw=False,
        dead_zone_deg=0.0,
    )
    mapper = HeadPoseMapper(cfg)

    command = mapper.map_frame(_frame(_quat_y(40.0), _quat_y(10.0)))

    assert command is not None
    assert command.yaw_deg == pytest_approx(30.0)


def test_head_pose_mapper_handles_converted_pico_neutral_and_yaw() -> None:
    body_poses = np.zeros((len(BODY_JOINT_NAMES), 7), dtype=np.float64)
    body_poses[:, 6] = 1.0
    mapper = HeadPoseMapper(
        NeckConfig(
            enabled=True,
            invert_yaw=False,
            invert_pitch=False,
            dead_zone_deg=0.0,
        )
    )

    neutral = mapper.map_frame(Pico4InputProvider._convert_body_joints_to_frame(body_poses))
    assert neutral is not None
    assert neutral.yaw_deg == pytest_approx(0.0)
    assert neutral.pitch_deg == pytest_approx(0.0)

    head_idx = BODY_JOINT_NAMES.index("Head")
    body_poses[head_idx, 4] = math.sin(math.radians(30.0) / 2.0)
    body_poses[head_idx, 6] = math.cos(math.radians(30.0) / 2.0)
    command = mapper.map_frame(Pico4InputProvider._convert_body_joints_to_frame(body_poses))
    assert command is not None
    assert command.yaw_deg == pytest_approx(30.0)
    assert command.pitch_deg == pytest_approx(0.0)


def test_head_pose_mapper_requires_spine3_joint() -> None:
    mapper = HeadPoseMapper(NeckConfig(enabled=True))

    assert mapper.map_frame(_frame(_quat_y(30.0))) is None


def test_neck_runtime_sends_relative_command_on_first_active_frame() -> None:
    class FakeDevice:
        def __init__(self) -> None:
            self.moves: list[tuple[float, float]] = []
            self.center_calls = 0
            self.closed = False

        def connect(self) -> None:
            return None

        def center(self) -> None:
            self.center_calls += 1

        def release(self) -> None:
            return None

        def move_norm(self, yaw: float, pitch: float) -> None:
            self.moves.append((yaw, pitch))

        def close(self) -> None:
            self.closed = True

    device = FakeDevice()
    cfg = NeckConfig(
        enabled=True,
        invert_yaw=False,
        dead_zone_deg=0.0,
        center_on_start=True,
        center_on_shutdown=True,
    )
    runtime = NeckRuntime(cfg, device=device)

    runtime.start()
    assert device.center_calls == 1
    command = runtime.tick(
        frame=_frame(_quat_y(30.0), _quat_y(0.0)),
        frame_timestamp_s=1.0,
        active=True,
        now_s=1.01,
    )
    neutral_command = runtime.tick(
        frame=_frame(_quat_y(0.0), _quat_y(0.0)),
        frame_timestamp_s=1.02,
        active=True,
        now_s=1.03,
    )
    runtime.close()

    assert command is not None
    assert command.yaw == pytest_approx(30.0 / 90.0)
    assert command.pitch == pytest_approx(0.0)
    assert neutral_command is not None
    assert neutral_command.yaw == pytest_approx(0.0)
    assert device.moves == [(30.0 / 90.0, 0.0), (0.0, 0.0)]
    assert device.center_calls == 2
    assert device.closed is True


def test_neck_runtime_releases_on_shutdown_when_enabled() -> None:
    class FakeDevice:
        def __init__(self) -> None:
            self.released = False
            self.closed = False

        def connect(self) -> None:
            return None

        def center(self) -> None:
            return None

        def release(self) -> None:
            self.released = True

        def move_norm(self, yaw: float, pitch: float) -> None:
            del yaw, pitch

        def close(self) -> None:
            self.closed = True

    device = FakeDevice()
    runtime = NeckRuntime(
        NeckConfig(enabled=True, center_on_start=False, center_on_shutdown=False, release_on_shutdown=True),
        device=device,
    )

    runtime.close()

    assert device.released is True
    assert device.closed is True


def test_neck_shutdown_defaults_to_close_only() -> None:
    class FakeDevice:
        def __init__(self) -> None:
            self.center_calls = 0
            self.released = False
            self.closed = False

        def connect(self) -> None:
            return None

        def center(self) -> None:
            self.center_calls += 1

        def release(self) -> None:
            self.released = True

        def move_norm(self, yaw: float, pitch: float) -> None:
            del yaw, pitch

        def close(self) -> None:
            self.closed = True

    device = FakeDevice()
    runtime = NeckRuntime(NeckConfig(enabled=True, center_on_start=False), device=device)

    runtime.close()

    assert device.center_calls == 0
    assert device.released is False
    assert device.closed is True


def test_neck_runtime_closes_after_shutdown_center_failure() -> None:
    class FakeDevice:
        def __init__(self) -> None:
            self.closed = False

        def connect(self) -> None:
            return None

        def center(self) -> None:
            raise RuntimeError("neck center failed")

        def release(self) -> None:
            return None

        def move_norm(self, yaw: float, pitch: float) -> None:
            del yaw, pitch

        def close(self) -> None:
            self.closed = True

    device = FakeDevice()
    runtime = NeckRuntime(
        NeckConfig(enabled=True, center_on_start=False, center_on_shutdown=True),
        device=device,
    )

    runtime.close()

    assert device.closed is True


def test_body_packet_frame_ignores_incomplete_packets() -> None:
    assert body_packet_frame(None) == (None, None, -1)
    assert body_packet_frame(SimpleNamespace(frame=_frame(_quat_y(0.0)))) == (None, None, -1)
    assert body_packet_frame(SimpleNamespace(frame=_frame(_quat_y(0.0)), timestamp_s="bad", seq=1)) == (None, None, -1)


def test_openneck_device_closes_context_manager(monkeypatch) -> None:
    calls: list[str] = []

    class FakeEnteredController:
        port = "/dev/entered"

        def center(self, *, wait_s: float) -> None:
            calls.append(f"entered-center-{wait_s}")

        def move_norm(self, yaw: float, pitch: float) -> None:
            calls.append(f"entered-move-{yaw}-{pitch}")

    class FakeOpenNeckController:
        port = "/dev/fake"

        def __init__(self, *, config: object, port: object, enable_torque_on_connect: bool) -> None:
            del config, port, enable_torque_on_connect
            self.entered = FakeEnteredController()

        def __enter__(self):
            calls.append("enter")
            return self.entered

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            del exc_type, exc, tb
            calls.append("exit")

        def close(self) -> None:
            calls.append("close")

    module = ModuleType("openneck")
    module.OpenNeckController = FakeOpenNeckController  # type: ignore[attr-defined]
    monkeypatch.setitem(__import__("sys").modules, "openneck", module)

    device = OpenNeckDevice(NeckConfig(enabled=True))
    device.connect()
    device.center()
    device.move_norm(0.25, -0.5)
    device.close()

    assert calls == ["enter", "entered-center-0.5", "entered-move-0.25--0.5", "exit"]


def test_openneck_device_direct_close_after_context_exit_failure(monkeypatch) -> None:
    calls: list[str] = []

    class FakeOpenNeckController:
        port = "/dev/fake"

        def __init__(self, *, config: object, port: object, enable_torque_on_connect: bool) -> None:
            del config, port, enable_torque_on_connect

        def __enter__(self):
            calls.append("enter")
            return self

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            del exc_type, exc, tb
            calls.append("exit")
            raise RuntimeError("context exit failed")

        def close(self) -> None:
            calls.append("close")

    module = ModuleType("openneck")
    module.OpenNeckController = FakeOpenNeckController  # type: ignore[attr-defined]
    monkeypatch.setitem(__import__("sys").modules, "openneck", module)

    device = OpenNeckDevice(NeckConfig(enabled=True))
    device.connect()
    try:
        device.close()
    except RuntimeError as exc:
        assert "context exit failed" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")

    assert calls == ["enter", "exit", "close"]


def test_openneck_device_direct_closes_context_when_entered_proxy_lacks_close(monkeypatch) -> None:
    calls: list[str] = []

    class FakeEnteredController:
        port = "/dev/entered"

    class FakeOpenNeckController:
        port = "/dev/fake"

        def __init__(self, *, config: object, port: object, enable_torque_on_connect: bool) -> None:
            del config, port, enable_torque_on_connect
            self.entered = FakeEnteredController()

        def __enter__(self):
            calls.append("enter")
            return self.entered

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            del exc_type, exc, tb
            calls.append("exit")
            raise RuntimeError("context exit failed")

        def close(self) -> None:
            calls.append("context-close")

    module = ModuleType("openneck")
    module.OpenNeckController = FakeOpenNeckController  # type: ignore[attr-defined]
    monkeypatch.setitem(__import__("sys").modules, "openneck", module)

    device = OpenNeckDevice(NeckConfig(enabled=True))
    device.connect()
    try:
        device.close()
    except RuntimeError as exc:
        assert "context exit failed" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")

    assert calls == ["enter", "exit", "context-close"]


def test_openneck_device_attempts_all_direct_close_targets(monkeypatch) -> None:
    calls: list[str] = []

    class FakeEnteredController:
        port = "/dev/entered"

        def close(self) -> None:
            calls.append("entered-close")
            raise RuntimeError("entered close failed")

    class FakeOpenNeckController:
        port = "/dev/fake"

        def __init__(self, *, config: object, port: object, enable_torque_on_connect: bool) -> None:
            del config, port, enable_torque_on_connect
            self.entered = FakeEnteredController()

        def __enter__(self):
            calls.append("enter")
            return self.entered

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            del exc_type, exc, tb
            calls.append("exit")
            raise RuntimeError("context exit failed")

        def close(self) -> None:
            calls.append("context-close")

    module = ModuleType("openneck")
    module.OpenNeckController = FakeOpenNeckController  # type: ignore[attr-defined]
    monkeypatch.setitem(__import__("sys").modules, "openneck", module)

    device = OpenNeckDevice(NeckConfig(enabled=True))
    device.connect()
    try:
        device.close()
    except RuntimeError as exc:
        assert "context exit failed" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")

    assert calls == ["enter", "exit", "entered-close", "context-close"]


def test_parse_neck_config_validates_rate() -> None:
    try:
        parse_neck_config({"neck": {"enabled": True, "rate_hz": 0}})
    except ValueError as exc:
        assert "neck.rate_hz" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_parse_neck_config_accepts_scalar_active_mode() -> None:
    cfg = parse_neck_config({"neck": {"enabled": True, "active_modes": "mocap"}})

    assert cfg.active_modes == ("mocap",)


def test_parse_neck_config_rejects_unknown_active_mode() -> None:
    try:
        parse_neck_config({"neck": {"enabled": True, "active_modes": ["mocap", "idle"]}})
    except ValueError as exc:
        assert "neck.active_modes" in str(exc)
        assert "idle" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def pytest_approx(value: float):
    import pytest

    return pytest.approx(value, abs=1e-6)
