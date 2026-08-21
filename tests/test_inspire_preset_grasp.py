"""Pico 扳机 → Inspire 预制抓取：mapper toggle 状态机 + device 消息组装。"""
from __future__ import annotations

from types import SimpleNamespace

from teleopit.sim2real.hands.inspire_ftp import PresetToggleMapper

PRESETS = {
    "open": {"angles": [1000] * 6, "speed": [500] * 6, "force": [300] * 6},
    "grasp": {"angles": [0, 0, 0, 0, 300, 1000], "speed": [500] * 6, "force": [300] * 6},
}


def _snap(left_trigger: float = 0.0, right_trigger: float = 0.0, *, t: float = 100.0):
    def side(trigger: float) -> SimpleNamespace:
        return SimpleNamespace(trigger=trigger, present=True, timestamp_s=t, grip=0.0)

    return SimpleNamespace(left=side(left_trigger), right=side(right_trigger), timestamp_s=t)


def test_left_trigger_edge_toggles_left_hand_to_grasp_then_open() -> None:
    mapper = PresetToggleMapper(PRESETS, ["left", "right"])
    mapper.map(controller_snapshot=_snap(left_trigger=0.1), hand_snapshot=None, active=True, now_s=100.0)
    cmds = mapper.map(controller_snapshot=_snap(left_trigger=0.9), hand_snapshot=None, active=True, now_s=100.5)
    assert len(cmds) == 1 and cmds[0].side == "left"
    assert tuple(cmds[0].pose) == (0, 0, 0, 0, 300, 1000)
    assert cmds[0].reason == "preset:grasp"
    # 再扣（去抖后）回 open
    mapper.map(controller_snapshot=_snap(left_trigger=0.1), hand_snapshot=None, active=True, now_s=101.0)
    cmds = mapper.map(controller_snapshot=_snap(left_trigger=0.9), hand_snapshot=None, active=True, now_s=101.5)
    assert len(cmds) == 1 and tuple(cmds[0].pose) == (1000,) * 6
    assert cmds[0].reason == "preset:open"


def test_right_trigger_independent_of_left() -> None:
    mapper = PresetToggleMapper(PRESETS, ["left", "right"])
    first = mapper.map(controller_snapshot=_snap(right_trigger=0.9), hand_snapshot=None, active=True, now_s=100.0)
    second = mapper.map(controller_snapshot=_snap(right_trigger=0.9, left_trigger=0.9), hand_snapshot=None, active=True, now_s=100.5)
    assert [c.side for c in first] == ["right"]   # 右扳机先扣 → 右手 grasp
    assert [c.side for c in second] == ["left"]   # 左扳机后扣 → 左手 grasp；右手 held 无新边沿不重复发
    sides = sorted(c.side for c in list(first) + list(second))
    assert sides == ["left", "right"]  # 两侧各一条，互不影响对方状态


def test_debounce_suppresses_rapid_retrigger() -> None:
    mapper = PresetToggleMapper(PRESETS, ["left"])
    mapper.map(controller_snapshot=_snap(left_trigger=0.9), hand_snapshot=None, active=True, now_s=100.0)
    # 100.1s 松开、100.15s 再扣——去抖窗口内，无输出
    mapper.map(controller_snapshot=_snap(left_trigger=0.1), hand_snapshot=None, active=True, now_s=100.1)
    cmds = mapper.map(controller_snapshot=_snap(left_trigger=0.9), hand_snapshot=None, active=True, now_s=100.15)
    assert cmds == ()


def test_inactive_holds_and_emits_nothing() -> None:
    mapper = PresetToggleMapper(PRESETS, ["left"])
    assert mapper.map(controller_snapshot=_snap(left_trigger=0.9), hand_snapshot=None, active=False, now_s=100.0) == ()


def test_absent_controller_side_is_silent() -> None:
    mapper = PresetToggleMapper(PRESETS, ["left"])
    snap = SimpleNamespace(left=SimpleNamespace(trigger=0.9, present=False, timestamp_s=100.0), right=None, timestamp_s=100.0)
    assert mapper.map(controller_snapshot=snap, hand_snapshot=None, active=True, now_s=100.0) == ()


import pytest

from teleopit.sim2real.hands.inspire_ftp import (
    InspireCtrlMessage, InspireFtpDevice, MODE_BIT_ANGLE, MODE_BIT_FORCE, MODE_BIT_SPEED,
)

DEV_CFG = {
    "domain_id": 0,
    "ctrl_topic_prefix": "rt/inspire_hand/ctrl",
    "presets": {
        "open": {"angles": [1000] * 6, "speed": [500] * 6, "force": [300] * 6},
        "grasp": {"angles": [0, 0, 0, 0, 300, 800], "speed": [500] * 6, "force": [300] * 6},
    },
}


class FakeInspirePublisher:
    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg
        self.published: list[tuple[str, InspireCtrlMessage]] = []

    def publish(self, side: str, message: InspireCtrlMessage) -> None:
        self.published.append((side, message))

    def close(self) -> None:
        pass


def _device() -> tuple[InspireFtpDevice, FakeInspirePublisher]:
    fake = FakeInspirePublisher(DEV_CFG)
    device = InspireFtpDevice(DEV_CFG, publisher_factory=lambda cfg: fake)
    device.connect()
    return device, fake


def test_send_pose_composes_angle_force_speed_mode() -> None:
    device, fake = _device()
    device.send_pose("left", (0, 0, 0, 0, 300, 800), force=True, reason="preset:grasp",
                     speed_set=(500,) * 6, force_set=(300,) * 6)
    side, msg = fake.published[-1]
    assert side == "left"
    assert tuple(msg.angle_set) == (0, 0, 0, 0, 300, 1000)  # index 5 pinned per thumb-rotation hold
    assert msg.mode == MODE_BIT_ANGLE | MODE_BIT_FORCE | MODE_BIT_SPEED  # 0b1101


def test_mode_drops_speed_bit_without_speed_array() -> None:
    device, fake = _device()
    device.send_pose("right", (1000,) * 6, force=True, reason="preset:open",
                     speed_set=(), force_set=(300,) * 6)
    assert fake.published[-1][1].mode == MODE_BIT_ANGLE | MODE_BIT_FORCE  # 0b0101


def test_thumb_rotation_pinned_open_on_every_send() -> None:
    device, fake = _device()
    device.send_pose("left", (0, 0, 0, 0, 0, 0), force=True, reason="preset:grasp",
                     speed_set=(), force_set=())
    assert fake.published[-1][1].angle_set[5] == 1000


def test_open_all_uses_open_preset_for_all_sides() -> None:
    device, fake = _device()
    device.open_all(force=True, reason="damping")
    sides = sorted(side for side, _ in fake.published[-2:])
    assert sides == ["left", "right"]
    assert all(tuple(m.angle_set) == (1000,) * 6 for _, m in fake.published[-2:])


def test_duplicate_pose_skipped_without_force() -> None:
    device, fake = _device()
    device.send_pose("left", (1000,) * 6, force=True, reason="preset:open")
    n = len(fake.published)
    device.send_pose("left", (1000,) * 6, force=False, reason="dup")
    assert len(fake.published) == n


def test_module_imports_without_cyclonedds() -> None:
    import subprocess, sys
    code = "import teleopit.sim2real.hands.inspire_ftp; import teleopit.sim2real.hands.worker"
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0


def test_active_mode_gate_membership() -> None:
    from teleopit.sim2real.mp.runtime import _hand_worker_active_for_mode

    class _Cfg(dict):
        pass

    cfg = _Cfg(hands={"trigger_modes": ["standing", "mocap", "arms"], "open_modes": ["idle", "damping"]})
    assert _hand_worker_active_for_mode("standing", cfg) is True
    assert _hand_worker_active_for_mode("mocap", cfg) is True
    assert _hand_worker_active_for_mode("velocity", cfg) is False   # hold
    assert _hand_worker_active_for_mode("damping", cfg) is False
    legacy = _Cfg(hands={})
    assert _hand_worker_active_for_mode("velocity", legacy) is True  # 缺席=旧行为恒活跃


def test_open_modes_membership() -> None:
    from teleopit.sim2real.mp.runtime import _hand_worker_open_on_mode

    cfg = {"hands": {"open_modes": ["idle", "damping"]}}
    assert _hand_worker_open_on_mode("damping", cfg) is True
    assert _hand_worker_open_on_mode("velocity", cfg) is False       # hold 不是 open
    assert _hand_worker_open_on_mode("damping", {"hands": {}}) is False  # 缺席不开


def test_hand_runtime_open_all_delegates_to_device() -> None:
    from teleopit.sim2real.hands.worker import HandRuntime

    calls = []

    class _Dev:
        def connect(self): pass
        def get_state(self, side): return ()
        def send_pose(self, side, pose, *, force=False, reason=""): pass
        def open_all(self, *, force=False, reason=""): calls.append((force, reason))
        def close(self): pass

    class _Map:
        def start(self): pass
        def map(self, **kwargs): return ()
        def close(self): pass

    runtime = HandRuntime(_Dev(), _Map())
    runtime.open_all(force=True, reason="mode:damping")
    assert calls == [(True, "mode:damping")]


def test_build_hand_runtime_dispatches_inspire_ftp(monkeypatch) -> None:
    import teleopit.sim2real.hands.inspire_ftp as inspire_module
    from teleopit.sim2real.hands.worker import build_hand_runtime

    made: dict = {}
    monkeypatch.setattr(
        inspire_module, "InspireFtpDevice",
        lambda cfg, publisher_factory=None: made.setdefault("device", FakeInspirePublisher(cfg)) and made["device"],
    )
    cfg = {
        "hands": {
            "enabled": True, "driver": "inspire_ftp", "mode": "preset_toggle",
            "sides": ["left", "right"],
            "inspire_ftp": dict(DEV_CFG),
        }
    }
    runtime = build_hand_runtime(cfg)
    assert "device" in made and runtime is not None
