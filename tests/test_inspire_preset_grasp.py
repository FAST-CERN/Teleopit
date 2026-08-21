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
