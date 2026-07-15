from __future__ import annotations

import math
from types import ModuleType, SimpleNamespace

import numpy as np

from teleopit.inputs.pico4_provider import BODY_JOINT_NAMES, Pico4InputProvider
from teleopit.sim2real.neck.config import NeckConfig, parse_neck_config
from teleopit.sim2real.neck.mapper import HeadPoseMapper
from teleopit.sim2real.neck.openneck import DryRunNeckDevice, OpenNeckDevice
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


class FakeDevice:
    def __init__(self) -> None:
        self.moves: list[tuple[float, float]] = []
        self.center_calls = 0
        self.released = False
        self.closed = False

    def connect(self) -> None:
        return None

    def center(self) -> None:
        self.center_calls += 1

    def release_torque(self) -> None:
        self.released = True

    def move_deg(self, yaw_deg: float, pitch_deg: float) -> tuple[float, float]:
        self.moves.append((yaw_deg, pitch_deg))
        return max(-20.0, min(20.0, yaw_deg)), max(-10.0, min(10.0, pitch_deg))

    def close(self) -> None:
        self.closed = True


def test_head_pose_mapper_maps_fixed_pico_convention_to_openneck_degrees() -> None:
    mapper = HeadPoseMapper(NeckConfig(enabled=True, dead_zone_deg=0.0))

    command = mapper.map_frame(_frame(_quat_y(30.0), _quat_y(0.0)))
    assert command is not None
    assert command.yaw_deg == pytest_approx(-30.0)

    command = mapper.map_frame(_frame(_quat_y(0.0), _quat_y(0.0)))
    assert command is not None
    assert command.yaw_deg == pytest_approx(0.0)

    command = mapper.map_frame(_frame(_quat_x(15.0), _quat_x(0.0)))
    assert command is not None
    assert command.pitch_deg == pytest_approx(-15.0)


def test_head_pose_mapper_uses_body_relative_orientation() -> None:
    mapper = HeadPoseMapper(NeckConfig(enabled=True, dead_zone_deg=0.0))

    command = mapper.map_frame(_frame(_quat_y(40.0), _quat_y(10.0)))

    assert command is not None
    assert command.yaw_deg == pytest_approx(-30.0)


def test_head_pose_mapper_handles_converted_pico_neutral_and_yaw() -> None:
    body_poses = np.zeros((len(BODY_JOINT_NAMES), 7), dtype=np.float64)
    body_poses[:, 6] = 1.0
    mapper = HeadPoseMapper(NeckConfig(enabled=True, dead_zone_deg=0.0))

    neutral = mapper.map_frame(Pico4InputProvider._convert_body_joints_to_frame(body_poses))
    assert neutral is not None
    assert neutral.yaw_deg == pytest_approx(0.0)
    assert neutral.pitch_deg == pytest_approx(0.0)

    head_idx = BODY_JOINT_NAMES.index("Head")
    body_poses[head_idx, 4] = math.sin(math.radians(30.0) / 2.0)
    body_poses[head_idx, 6] = math.cos(math.radians(30.0) / 2.0)
    command = mapper.map_frame(Pico4InputProvider._convert_body_joints_to_frame(body_poses))
    assert command is not None
    assert command.yaw_deg == pytest_approx(-30.0)
    assert command.pitch_deg == pytest_approx(0.0)


def test_head_pose_mapper_requires_spine3_joint() -> None:
    mapper = HeadPoseMapper(NeckConfig(enabled=True))

    assert mapper.map_frame(_frame(_quat_y(30.0))) is None


def test_neck_runtime_sends_degrees_and_returns_applied_target() -> None:
    device = FakeDevice()
    cfg = NeckConfig(
        enabled=True,
        dead_zone_deg=0.0,
        center_on_start=True,
        center_on_shutdown=True,
    )
    runtime = NeckRuntime(cfg, device=device)

    runtime.start()
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
    assert command.yaw_deg == pytest_approx(-20.0)
    assert command.pitch_deg == pytest_approx(0.0)
    assert neutral_command is not None
    assert neutral_command.yaw_deg == pytest_approx(0.0)
    np.testing.assert_allclose(device.moves, [(-30.0, 0.0), (0.0, 0.0)], atol=1e-6)
    assert device.center_calls == 2
    assert device.closed is True


def test_neck_runtime_releases_torque_on_shutdown_when_enabled() -> None:
    device = FakeDevice()
    runtime = NeckRuntime(
        NeckConfig(enabled=True, center_on_start=False, release_on_shutdown=True),
        device=device,
    )

    runtime.close()

    assert device.released is True
    assert device.closed is True


def test_neck_shutdown_defaults_to_close_only() -> None:
    device = FakeDevice()
    runtime = NeckRuntime(NeckConfig(enabled=True, center_on_start=False), device=device)

    runtime.close()

    assert device.center_calls == 0
    assert device.released is False
    assert device.closed is True


def test_neck_runtime_closes_after_shutdown_center_failure() -> None:
    class CenterFailingDevice(FakeDevice):
        def center(self) -> None:
            raise RuntimeError("neck center failed")

    device = CenterFailingDevice()
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


def test_openneck_device_uses_angle_api_and_returns_applied_target(monkeypatch) -> None:
    calls: list[str] = []

    class FakeOpenNeckController:
        port = "/dev/fake"

        def __init__(self, *, config: object, port: object) -> None:
            calls.append(f"init-{config}-{port}")

        def connect(self) -> None:
            calls.append("connect")

        def center(self) -> None:
            calls.append("center")

        def move_deg(self, yaw_deg: float, pitch_deg: float) -> SimpleNamespace:
            calls.append(f"move-{yaw_deg}-{pitch_deg}")
            return SimpleNamespace(yaw_deg=-20.0, pitch_deg=10.0)

        def release_torque(self) -> None:
            calls.append("release-torque")

        def close(self) -> None:
            calls.append("close")

    module = ModuleType("openneck")
    module.OpenNeckController = FakeOpenNeckController  # type: ignore[attr-defined]
    monkeypatch.setitem(__import__("sys").modules, "openneck", module)

    device = OpenNeckDevice(
        NeckConfig(enabled=True, config_path="neck.json", port="/dev/ttyACM0")
    )
    device.connect()
    device.center()
    applied = device.move_deg(-25.0, 15.0)
    device.release_torque()
    device.close()

    assert applied == (-20.0, 10.0)
    assert calls == [
        "init-neck.json-/dev/ttyACM0",
        "connect",
        "center",
        "move--25.0-15.0",
        "release-torque",
        "close",
    ]


def test_dry_run_neck_device_reuses_openneck_calibration_clamp(monkeypatch) -> None:
    calls: list[str] = []

    class FakeOpenNeckController:
        def __init__(self, *, config: object, port: object) -> None:
            calls.append(f"init-{config}-{port}")

        def move_deg(self, yaw_deg: float, pitch_deg: float) -> None:
            del yaw_deg, pitch_deg
            raise AssertionError("dry-run must not send a hardware command")

        def _angle_to_step(self, axis: str, angle_deg: float) -> int:
            calls.append(f"angle-to-step-{axis}-{angle_deg}")
            low, high = (-20.0, 20.0) if axis == "yaw" else (-10.0, 10.0)
            return round(max(low, min(high, angle_deg)))

        def _step_to_angle(self, axis: str, step: int) -> float:
            calls.append(f"step-to-angle-{axis}-{step}")
            return float(step)

    module = ModuleType("openneck")
    module.OpenNeckController = FakeOpenNeckController  # type: ignore[attr-defined]
    monkeypatch.setitem(__import__("sys").modules, "openneck", module)

    device = DryRunNeckDevice(
        NeckConfig(
            enabled=True,
            config_path="neck.json",
            port="/dev/ttyACM0",
            dry_run=True,
        )
    )
    device.connect()
    applied = device.move_deg(25.0, -15.0)
    device.close()

    assert applied == (20.0, -10.0)
    assert calls == [
        "init-neck.json-/dev/ttyACM0",
        "angle-to-step-yaw-25.0",
        "angle-to-step-pitch--15.0",
        "step-to-angle-yaw-20",
        "step-to-angle-pitch--10",
    ]


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


def test_parse_neck_config_rejects_removed_normalized_fields() -> None:
    try:
        parse_neck_config({"neck": {"enabled": True, "yaw_range_deg": 90.0}})
    except ValueError as exc:
        assert "Removed normalized OpenNeck config" in str(exc)
        assert "angles in degrees" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def pytest_approx(value: float):
    import pytest

    return pytest.approx(value, abs=1e-6)
