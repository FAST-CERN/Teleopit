# Pico 扳机预制 Inspire 抓取 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** hands worker 新增 `inspire_ftp` driver：左右手柄扳机各自独立边沿 toggle，驱动二态预制抓取（角度+力+速度，拇指转钉住不动），经 DDS `rt/inspire_hand/ctrl/l|r` 下发，由 Orin 上现成的 `driver_double_wlan0.py` 转发到双手 Modbus。

**Architecture:** 一切住在既有 hand worker 进程内——新 mapper（preset toggle 状态机）+ 新 device（lazy-import cyclonedds 的 ctrl 发布器，`publisher_factory` 注入假件测试）。Teleopit 只发 DDS ctrl，不碰 Modbus；模式门控（STANDING/MOCAP/ARMS 活跃、VELOCITY hold、IDLE/DAMPING 张开）补在 mp 侧 hand worker 循环，缺席配置时保持 linkerhand 旧行为（恒活跃）。

**Tech Stack:** Python / NumPy / cyclonedds-python（仅运行时 lazy import，测试一律注入）/ hydra yaml。

**Spec:** 2026-08-22 凌晨 grilling 共识（本 plan 头部"Locked decisions"节即全文）；Orin 侧 SDK 事实见"事实底座"。

## Locked decisions（grilling 定案，Q1-Q12）

| 决策 | 定案 |
|---|---|
| 扳机语义 | 边沿 toggle：扣一下→grasp 预设，再扣→open 预设；阈值 0.6、去抖 0.25s |
| 预设集 | 二态表 `{name: {angles, speed, force}}`，初值占位、执行会话从 PC manus server 实跑取数回填 |
| 左右映射 | 同侧直连：左手柄扳机→左手，右手柄扳机→右手，独立 toggle |
| 作用域 | trigger 活跃于 STANDING/MOCAP/ARMS；VELOCITY 禁用但 hold（可携带）；IDLE 不动作；DAMPING 强制张开 |
| 拇指转 | 关节序 index 5（thumb-rotation）**钉 1000 永不驱动**（防碰，参照 SDK `example/dds_publish.py` 拇指位保持做法） |
| 控制面 | 角度+力(+速度)：mode bit0=角度 bit2=力 bit3=速度 → 全给时 `0b1101`，无速度 `0b0101` |
| 架构 | Teleopit 发 DDS ctrl；`driver_double_wlan0.py`（Orin, inspire_test env）照常转发 Modbus（.210/.211:6000） |
| 配置 | hands 段开在 `pico4_sim2real_bsi.yaml` |
| 交接 | 本 plan + 记忆指针，新对话 executing-plans 执行 |

## Global Constraints

- **测试铁律**：teleopit PC env 无 cyclonedds——任何测试不得 import `cyclonedds` 或触发其加载；device 一律 `publisher_factory` 注入假件（bsi_dds 同款纪律）。
- **拇指转钉住**：所有下发（含 open_all）强制 `angle_set[5] = 1000`，单一 choke point 在 device。
- **mode 位**：常量 `ANGLE=0b0001, POSITION=0b0010, FORCE=0b0100, SPEED=0b1000`（SDK `example/dds_publish.py` 注释表）；本功能只用 ANGLE|FORCE|SPEED 组合。
- **idl 绑定出处**：从 `F:/Chufan_Rui/manus_haptic_rt/src/manus_haptic_rt/hand/dds_types.py` 移植 `InspireHandCtrl`（typename `inspire.inspire_hand_ctrl`），文件头注明出处与同步日期。
- **linkerhand 零回归**：`hands.trigger_modes` 缺席时 hand worker 行为与现状完全一致（恒活跃、无模式张开）。
- 提交信息 conventional commits，每任务一提交。

## 事实底座（执行者必读）

- **hands worker**：`teleopit/sim2real/hands/base.py` 定义 `HandPoseCommand(side, pose, force=False, reason="")`（frozen dataclass）、`HandDevice` Protocol（`connect/get_state(side)/send_pose(side, pose, *, force, reason)/open_all(*, force, reason)/close`）、`HandInputMapper` Protocol（`start/map(*, controller_snapshot, hand_snapshot, active, now_s)/close`）。`worker.py:115-126` `build_hand_runtime(cfg)` 按 `hands.driver` 分发（现只有 linkerhand_l6/o6），返回 `HandRuntime(device, mapper)`；`worker.py:43` `tick()` 调 mapper.map 后逐条 send_pose，异常→`_failed` + `open_all(force=True, reason="failure")`。
- **mp 侧**：`_run_hand_worker`（`teleopit/sim2real/mp/runtime.py:3307-3341`）spawn 独立进程，订阅 `hand_pub`/`controller_pub`(CONTROLLER_TOPIC)/`mode_pub`(MODE_TOPIC)/`command_pub`，`runtime.hand_worker_hz` 默认 120。模式门控缝：`_hand_worker_active_for_mode`（runtime.py:3302-3304）目前无条件 `return True`。执行 Task 4 前先读 runtime.py:3290-3420 记下 MODE_TOPIC 包的字段名再落码。
- **扳机数据已在流**：`teleopit/inputs/pico4_provider.py:58-67` `PicoControllerState(raw, grip, trigger, present, axis_x, axis_y)`——`trigger` 是桥原生模拟轴（0..1），快照 `snapshot.left.trigger` / `snapshot.right.trigger` 经 CONTROLLER_TOPIC 已到 hand worker，**无需新增事件管线**。
- **角度语义**：int16 0=闭合 1000=张开；关节序 `[pinky, ring, middle, index, thumb-bend, thumb-rotation]`。
- **Orin 运行位**：`~/eeg_humanoid/lib/inspire_hand_ws/inspire_hand_sdk/example/driver_double_wlan0.py`（inspire_test env，双手两进程，DDS 绑 wlan0，ModbusTCP 192.168.123.210/.211:6000）。DDS 与 BSI 同在 wlan0 domain 0，不同话题无冲突。
- **manus 取数参考**：`F:/Chufan_Rui/manus_haptic_rt/`（PC）——`src/manus_haptic_rt/hand/dds_backend.py` 是 ctrl 发布的完整参考；其 knowledge 文档有接口与安全调机记录。
- **配置模板**：`teleopit/configs/pico4_sim2real.yaml:71-106` hands 段结构；`hands.enabled=true` 要求 `input.provider=pico4`（runtime.py:386-388，bsi 配置已满足）。

## File Structure

- Modify `teleopit/sim2real/hands/base.py` — `HandPoseCommand` 加 `speed_set`/`force_set` 可选元组。
- Create `teleopit/sim2real/hands/inspire_dds_types.py` — `InspireHandCtrl` idl 绑定（cyclonedds-dependent，仅被 lazy import）。
- Create `teleopit/sim2real/hands/inspire_ftp.py` — `PresetToggleMapper` + `InspireCtrlMessage` + `InspireFtpDevice` + `build_inspire_ftp(cfg)`。
- Modify `teleopit/sim2real/hands/worker.py` — 工厂分发 `inspire_ftp`。
- Modify `teleopit/sim2real/mp/runtime.py` — `_hand_worker_active_for_mode` 配置化 + open-on-damping 转移。
- Modify `teleopit/configs/pico4_sim2real_bsi.yaml` — hands 段。
- Test: `tests/test_inspire_preset_grasp.py`（新建，本 plan 全部测试）；`tests/test_dexterous_hand.py` 追加 dataclass 扩展测。

---

### Task 1: `HandPoseCommand` 扩展 speed/force 数组

**Files:**
- Modify: `teleopit/sim2real/hands/base.py:10-15`
- Test: `tests/test_dexterous_hand.py`（追加）

**Interfaces:**
- Produces: `HandPoseCommand(side, pose, force=False, reason="", speed_set: tuple[int, ...] = (), force_set: tuple[int, ...] = ())`——Task 3 的 mapper 构造、Task 4 的 device 消费。

- [ ] **Step 1: 写失败测试（追加到 tests/test_dexterous_hand.py）**

```python
def test_hand_pose_command_optional_speed_force_default_empty() -> None:
    from teleopit.sim2real.hands.base import HandPoseCommand

    plain = HandPoseCommand(side="left", pose=(1, 2, 3, 4, 5, 6))
    assert plain.speed_set == () and plain.force_set == ()
    rich = HandPoseCommand(
        side="right", pose=(0, 0, 0, 0, 300, 1000),
        speed_set=(500,) * 6, force_set=(300,) * 6, reason="preset:grasp",
    )
    assert rich.speed_set == (500,) * 6 and rich.force_set == (300,) * 6
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_dexterous_hand.py -k hand_pose_command -v`
Expected: FAIL（`TypeError: unexpected keyword 'speed_set'`）

- [ ] **Step 3: 最小实现（base.py，dataclass 字段尾加两行）**

```python
@dataclass(frozen=True)
class HandPoseCommand:
    side: str
    pose: tuple[int, ...]
    force: bool = False
    reason: str = ""
    speed_set: tuple[int, ...] = ()
    force_set: tuple[int, ...] = ()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_dexterous_hand.py -q`
Expected: 全 PASS（既有构造点不传新字段，零破坏）

- [ ] **Step 5: 提交**

```bash
git add teleopit/sim2real/hands/base.py tests/test_dexterous_hand.py
git commit -m "feat(hands): HandPoseCommand optional speed_set/force_set arrays"
```

---

### Task 2: `PresetToggleMapper`（双扳机独立 toggle 状态机）

**Files:**
- Create: `teleopit/sim2real/hands/inspire_ftp.py`（本任务先建文件放 mapper；Task 3/4 同文件续写）
- Test: `tests/test_inspire_preset_grasp.py`（新建）

**Interfaces:**
- Consumes: Task 1 的 `HandPoseCommand`；既有快照形状（`snapshot.left/.right` 各带 `.trigger: float`、`.present: bool`、`.timestamp_s`）。
- Produces: `PresetToggleMapper(presets: dict, sides: list[str], *, trigger_threshold: float = 0.6, trigger_debounce_s: float = 0.25)`，`map(*, controller_snapshot, hand_snapshot, active, now_s) -> tuple[HandPoseCommand, ...]`。预设形状 `{name: {"angles": [6 int], "speed": [6 int] | None, "force": [6 int] | None}}`。Task 4 的 device 消费其输出。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_inspire_preset_grasp.py
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
    cmds = mapper.map(controller_snapshot=_snap(left_trigger=0.1), hand_snapshot=None, active=True, now_s=101.0)
    cmds = mapper.map(controller_snapshot=_snap(left_trigger=0.9), hand_snapshot=None, active=True, now_s=101.5)
    assert len(cmds) == 1 and tuple(cmds[0].pose) == (1000,) * 6
    assert cmds[0].reason == "preset:open"


def test_right_trigger_independent_of_left() -> None:
    mapper = PresetToggleMapper(PRESETS, ["left", "right"])
    mapper.map(controller_snapshot=_snap(right_trigger=0.9), hand_snapshot=None, active=True, now_s=100.0)
    cmds = mapper.map(controller_snapshot=_snap(right_trigger=0.9, left_trigger=0.9), hand_snapshot=None, active=True, now_s=100.5)
    sides = sorted(c.side for c in cmds)
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_inspire_preset_grasp.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 最小实现（teleopit/sim2real/hands/inspire_ftp.py 文件头 + mapper）**

```python
"""Inspire RH56 (FTP) preset-grasp driver: DDS ctrl publisher side (2026-08-22 grilling).

Teleopit only publishes rt/inspire_hand/ctrl/{l,r}; the Orin-side
driver_double_wlan0.py (inspire_test env) forwards to ModbusTCP
192.168.123.210/.211:6000. Thumb-rotation (angle index 5) is pinned open
(1000) at the device — never actuated (anti-collision, SDK dds_publish
precedent). Angle units: int16, 0=closed 1000=open, joint order
[pinky, ring, middle, index, thumb-bend, thumb-rotation].
"""
from __future__ import annotations

import time
from typing import Any

from teleopit.sim2real.hands.base import HandPoseCommand

MODE_BIT_ANGLE = 0b0001
MODE_BIT_POSITION = 0b0010
MODE_BIT_FORCE = 0b0100
MODE_BIT_SPEED = 0b1000
THUMB_ROTATION_HOLD = 1000


class PresetToggleMapper:
    """Per-side analog-trigger edge toggle between named presets.

    Same discipline as the mp estop grip seam (threshold + edge + debounce),
    but stateful per side: each toggle advances open <-> grasp. Inactive
    (mode-gated) emits nothing — the device holds its last pose.
    """

    def __init__(
        self,
        presets: dict[str, dict[str, Any]],
        sides: list[str],
        *,
        trigger_threshold: float = 0.6,
        trigger_debounce_s: float = 0.25,
        clock: Any = time.monotonic,
    ) -> None:
        if "open" not in presets or "grasp" not in presets:
            raise ValueError("presets must define at least 'open' and 'grasp'")
        self._presets = presets
        self._sides = list(sides)
        self._threshold = float(trigger_threshold)
        self._debounce_s = float(trigger_debounce_s)
        self._clock = clock
        self._current: dict[str, str] = {side: "open" for side in self._sides}
        self._pressed: dict[str, bool] = {side: False for side in self._sides}
        self._last_toggle: dict[str, float | None] = {side: None for side in self._sides}

    def _toggle(self, side: str, now_s: float) -> HandPoseCommand:
        target = "grasp" if self._current[side] != "grasp" else "open"
        self._current[side] = target
        self._last_toggle[side] = now_s
        preset = self._presets[target]
        return HandPoseCommand(
            side=side,
            pose=tuple(int(v) for v in preset["angles"]),
            force=True,
            reason=f"preset:{target}",
            speed_set=tuple(int(v) for v in preset.get("speed") or ()),
            force_set=tuple(int(v) for v in preset.get("force") or ()),
        )

    def map(self, *, controller_snapshot, hand_snapshot, active: bool, now_s: float):
        if not active or controller_snapshot is None:
            return ()
        commands: list[HandPoseCommand] = []
        for side in self._sides:
            state = getattr(controller_snapshot, side, None)
            if state is None or not bool(getattr(state, "present", False)):
                self._pressed[side] = False
                continue
            pressed = float(getattr(state, "trigger", 0.0)) >= self._threshold
            fired = pressed and not self._pressed[side]
            self._pressed[side] = pressed
            if not fired:
                continue
            last = self._last_toggle[side]
            if last is not None and now_s - last < self._debounce_s:
                continue
            commands.append(self._toggle(side, now_s))
        return tuple(commands)
```

（`start/close` 空实现照 `HandInputMapper` Protocol 补上。）

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_inspire_preset_grasp.py -v`
Expected: PASS（5 测）

- [ ] **Step 5: 提交**

```bash
git add teleopit/sim2real/hands/inspire_ftp.py tests/test_inspire_preset_grasp.py
git commit -m "feat(hands): PresetToggleMapper — per-side trigger edge toggle (grilling 2026-08-22)"
```

---

### Task 3: `InspireFtpDevice`（消息组装 + publisher 注入缝）

**Files:**
- Modify: `teleopit/sim2real/hands/inspire_ftp.py`（续写）
- Create: `teleopit/sim2real/hands/inspire_dds_types.py`
- Test: `tests/test_inspire_preset_grasp.py`（追加）

**Interfaces:**
- Consumes: Task 2 常量与 mapper 输出；`HandDevice` Protocol。
- Produces: `InspireCtrlMessage(angle_set, speed_set, force_set, mode)`（纯 dataclass，无 cyclonedds）；`FakeInspirePublisher`（测试假件，记录 `(side, message)`）；`InspireFtpDevice(cfg: dict, *, publisher_factory=None)`；`build_inspire_ftp(cfg) -> HandRuntime`（Task 5 工厂消费）。真 publisher 构造：`_RealInspirePublisher(cfg)` lazy import cyclonedds + 本仓 `inspire_dds_types.InspireHandCtrl`，按 side 发 `rt/inspire_hand/ctrl/{l|r}`。

- [ ] **Step 1: 写失败测试（追加）**

```python
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
    assert tuple(msg.angle_set) == (0, 0, 0, 0, 300, 800)
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_inspire_preset_grasp.py -v`
Expected: 新增 6 测 FAIL（ImportError：名字不存在）

- [ ] **Step 3: 最小实现**

`teleopit/sim2real/hands/inspire_dds_types.py`（cyclonedds-dependent，只被 lazy import）：

```python
"""Inspire hand ctrl DDS idl binding — ported from manus_haptic_rt
(src/manus_haptic_rt/hand/dds_types.py, 2026-08-22). Imported ONLY inside
the real publisher path; the teleopit test env has no cyclonedds.
"""
from dataclasses import dataclass

from cyclonedds import idl, types


@dataclass
@idl.final
@idl.autoid("sequential")
class InspireHandCtrl(idl.IdlStruct, typename="inspire.inspire_hand_ctrl"):
    pos_set: types.sequence[types.int16, 6]
    angle_set: types.sequence[types.int16, 6]
    force_set: types.sequence[types.int16, 6]
    speed_set: types.sequence[types.int16, 6]
    mode: types.int8
```

`inspire_ftp.py` 追加（模块级不 import cyclonedds）：

```python
import dataclasses


@dataclasses.dataclass(frozen=True)
class InspireCtrlMessage:
    angle_set: tuple[int, ...]
    speed_set: tuple[int, ...]
    force_set: tuple[int, ...]
    mode: int


class _RealInspirePublisher:
    """cyclonedds ctrl publisher — created only via the default factory."""

    def __init__(self, cfg: dict) -> None:
        from cyclonedds.domain import DomainParticipant
        from cyclonedds.pub import DataWriter
        from cyclonedds.topic import Topic

        from teleopit.sim2real.hands.inspire_dds_types import InspireHandCtrl

        self._idl = InspireHandCtrl
        domain = int(cfg.get("domain_id", 0))
        prefix = str(cfg.get("ctrl_topic_prefix", "rt/inspire_hand/ctrl"))
        self._participant = DomainParticipant(domain)
        self._writers = {
            "left": DataWriter(Topic(self._participant, f"{prefix}/l", InspireHandCtrl)),
            "right": DataWriter(Topic(self._participant, f"{prefix}/r", InspireHandCtrl)),
        }

    def publish(self, side: str, message: InspireCtrlMessage) -> None:
        self._writers[side].write(self._idl(
            pos_set=[0] * 6,
            angle_set=[int(v) for v in message.angle_set],
            force_set=[int(v) for v in message.force_set],
            speed_set=[int(v) for v in message.speed_set],
            mode=int(message.mode),
        ))

    def close(self) -> None:
        self._writers = {}


class InspireFtpDevice:
    """HandDevice publishing preset ctrl messages; thumb-rotation pinned here."""

    def __init__(self, cfg: dict, *, publisher_factory=None) -> None:
        self._cfg = cfg
        self._presets = cfg["presets"]
        self._publisher = None
        self._factory = publisher_factory or _RealInspirePublisher
        self._last_pose: dict[str, tuple[int, ...]] = {}

    def connect(self) -> None:
        if self._publisher is None:
            self._publisher = self._factory(self._cfg)

    def get_state(self, side: str) -> tuple[float, ...]:
        return ()  # v1 write-only; state topic subscription is future work

    def _compose(self, pose, speed_set, force_set) -> InspireCtrlMessage:
        angles = [THUMB_ROTATION_HOLD if i == 5 else int(v) for i, v in enumerate(pose[:6])]
        mode = MODE_BIT_ANGLE
        if force_set:
            mode |= MODE_BIT_FORCE
        if speed_set:
            mode |= MODE_BIT_SPEED
        return InspireCtrlMessage(tuple(angles), tuple(speed_set), tuple(force_set), mode)

    def send_pose(self, side, pose, *, force=False, reason="", speed_set=(), force_set=()) -> None:
        pose_t = tuple(int(v) for v in pose[:6])
        if not force and self._last_pose.get(side) == (pose_t, tuple(speed_set), tuple(force_set)):
            return
        self._last_pose[side] = (pose_t, tuple(speed_set), tuple(force_set))
        self.connect()
        self._publisher.publish(side, self._compose(pose_t, speed_set, force_set))

    def open_all(self, *, force=False, reason="") -> None:
        open_preset = self._presets["open"]
        for side in ("left", "right"):
            self.send_pose(
                side, open_preset["angles"], force=True, reason=reason or "open_all",
                speed_set=tuple(open_preset.get("speed") or ()),
                force_set=tuple(open_preset.get("force") or ()),
            )

    def close(self) -> None:
        if self._publisher is not None:
            self._publisher.close()
            self._publisher = None
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_inspire_preset_grasp.py -v`
Expected: PASS（11 测）

- [ ] **Step 5: 提交**

```bash
git add teleopit/sim2real/hands/inspire_ftp.py teleopit/sim2real/hands/inspire_dds_types.py tests/test_inspire_preset_grasp.py
git commit -m "feat(hands): InspireFtpDevice — ctrl message compose (angle+force+speed 0b1101) + injected publisher seam + thumb pin"
```

---

### Task 4: 模式门控（trigger_modes / open_modes，linkerhand 零回归）

**Files:**
- Modify: `teleopit/sim2real/mp/runtime.py:3302-3304`（`_hand_worker_active_for_mode`）+ `_run_hand_worker` 循环（3307-3341）
- Test: `tests/test_inspire_preset_grasp.py`（追加）

**Interfaces:**
- Consumes: 无（读 `hands.trigger_modes: [standing, mocap, arms]` / `hands.open_modes: [idle, damping]` 配置；两键均缺席 = 旧行为）。
- Produces: 门控语义供 Task 5 的 yaml 消费。**执行前先读 runtime.py:3290-3420**，记下 MODE_TOPIC 包里模式值的字段名/取值（`RobotMode.value` 字符串），下面代码按 `mode_value: str` 写，落码时对齐真实字段。

- [ ] **Step 1: 写失败测试（追加；纯函数级测门控判定）**

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_inspire_preset_grasp.py -k mode_gate -v`
Expected: FAIL（签名/函数不存在）

- [ ] **Step 3: 最小实现（runtime.py，`_hand_worker_active_for_mode` 处重写为模块级纯函数 + 循环接线）**

```python
def _hand_worker_active_for_mode(mode_value: str, cfg: Any) -> bool:
    """trigger 活跃门（grilling 2026-08-22）：配置缺席时保持旧行为恒活跃。"""
    hands_cfg = cfg_get(cfg_get(cfg, "hands", {}) or {}, "trigger_modes", None) if hasattr(cfg, "get") or isinstance(cfg, dict) else None
    trigger_modes = cfg_get(cfg_get(cfg, "hands", {}), "trigger_modes", None)
    if trigger_modes is None:
        return True
    return str(mode_value) in [str(m) for m in trigger_modes]


def _hand_worker_open_on_mode(mode_value: str, cfg: Any) -> bool:
    """进入即张开兜底（idle/damping）；velocity 是 hold 不在列。"""
    open_modes = cfg_get(cfg_get(cfg, "hands", {}), "open_modes", None)
    if open_modes is None:
        return False
    return str(mode_value) in [str(m) for m in open_modes]
```

（第一行 hands_cfg 冗余变量删除，只留 return 链。）`_run_hand_worker` 循环内：拿 MODE_TOPIC 最新包处，把现有 `_hand_worker_active_for_mode(<现参>)` 调用改为传 mode 值 + cfg；并新增转移检测——记 `last_mode_value`，当 `_hand_worker_open_on_mode(new_mode, cfg) and new_mode != last_mode_value` 时调 `runtime.open_all(force=True, reason=f"mode:{new_mode}")`。具体变量名对齐该循环现有代码。

- [ ] **Step 4: 跑测试确认通过 + mp 回归**

Run: `python -m pytest tests/test_inspire_preset_grasp.py tests/test_sim2real_multiprocess.py -q`
Expected: 全 PASS（multiprocess 既有测不破——门控纯函数化不改变缺席配置路径）

- [ ] **Step 5: 提交**

```bash
git add teleopit/sim2real/mp/runtime.py tests/test_inspire_preset_grasp.py
git commit -m "feat(mp): hand-worker mode gating — trigger_modes active gate + open_modes safety open (linkerhand legacy preserved)"
```

---

### Task 5: 工厂分发 + `pico4_sim2real_bsi.yaml` hands 段

**Files:**
- Modify: `teleopit/sim2real/hands/worker.py:115-126`（`build_hand_runtime` 分发）
- Modify: `teleopit/configs/pico4_sim2real_bsi.yaml`
- Test: `tests/test_inspire_preset_grasp.py`（追加装配测）+ `tests/test_cli_entrypoints.py`（追加配置合同测）

**Interfaces:**
- Consumes: Task 2/3 的 `PresetToggleMapper`、`InspireFtpDevice`；Task 4 门控配置键。
- Produces: `build_hand_runtime` 认 `hands.driver: inspire_ftp`；`build_inspire_ftp(cfg) -> HandRuntime`；可用配置 `pico4_sim2real_bsi`（hands.enabled=true）。

- [ ] **Step 1: 写失败测试（追加）**

```python
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
```

`tests/test_cli_entrypoints.py` 追加：

```python
def test_pico4_sim2real_bsi_hands_section_loads() -> None:
    from hydra import compose, initialize_config_dir

    with initialize_config_dir(config_dir=str(_CONFIG_DIR), version_base=None):
        cfg = compose(config_name="pico4_sim2real_bsi")
    assert bool(cfg.hands.enabled) is True
    assert str(cfg.hands.driver) == "inspire_ftp"
    assert str(cfg.hands.mode) == "preset_toggle"
    assert [str(s) for s in cfg.hands.sides] == ["left", "right"]
    assert [str(m) for m in cfg.hands.trigger_modes] == ["standing", "mocap", "arms"]
    assert [str(m) for m in cfg.hands.open_modes] == ["idle", "damping"]
    assert float(cfg.hands.inspire_ftp.trigger_threshold) == 0.6
    assert [int(v) for v in cfg.hands.inspire_ftp.presets.grasp.angles] == [0, 0, 0, 0, 300, 1000]
    assert cfg.hands.inspire_ftp.presets.grasp.angles[5] == 1000  # thumb-rotation held
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_inspire_preset_grasp.py tests/test_cli_entrypoints.py -k "inspire or bsi_hands" -v`
Expected: FAIL（driver 不认识 / hands 段不存在）

- [ ] **Step 3: 最小实现**

`worker.py` 分发（115-126 处，linkerhand 分支后加）：

```python
    elif driver == "inspire_ftp":
        from teleopit.sim2real.hands.inspire_ftp import (
            InspireFtpDevice, PresetToggleMapper, build_inspire_ftp,
        )
        return build_inspire_ftp(cfg)
```

`inspire_ftp.py` 文件尾：

```python
def build_inspire_ftp(cfg: dict):
    from teleopit.sim2real.hands.worker import HandRuntime

    hands_cfg = cfg_get_hands(cfg)
    dev_cfg = dict(hands_cfg.get("inspire_ftp", {}) or {})
    dev_cfg.setdefault("presets", {
        "open": {"angles": [1000] * 6, "speed": None, "force": None},
        "grasp": {"angles": [0, 0, 0, 0, 300, 1000], "speed": None, "force": None},
    })
    device = InspireFtpDevice(dev_cfg)
    mapper = PresetToggleMapper(
        dev_cfg["presets"], list(hands_cfg.get("sides", ["left", "right"])),
        trigger_threshold=float(dev_cfg.get("trigger_threshold", 0.6)),
        trigger_debounce_s=float(dev_cfg.get("trigger_debounce_s", 0.25)),
    )
    return HandRuntime(device=device, mapper=mapper)
```

（`cfg_get_hands` 若 worker.py 无现成取法，就 `cfg.get("hands", {}) if isinstance(cfg, dict) else getattr(cfg, "hands", {})` 内联。）

`pico4_sim2real_bsi.yaml` 追加：

```yaml
# ── Inspire 预制抓取（grilling 2026-08-22；Orin 侧需先起 driver_double_wlan0）──
hands:
  enabled: true
  driver: inspire_ftp
  mode: preset_toggle
  sides: [left, right]
  trigger_modes: [standing, mocap, arms]   # 扳机活跃域；velocity=hold，其余见 open_modes
  open_modes: [idle, damping]               # 进入即张开兜底
  inspire_ftp:
    domain_id: 0
    ctrl_topic_prefix: rt/inspire_hand/ctrl
    trigger_threshold: 0.6
    trigger_debounce_s: 0.25
    presets:                                # 数值为占位——执行会话从 manus server 实跑取数回填
      open:   {angles: [1000, 1000, 1000, 1000, 1000, 1000], speed: [500, 500, 500, 500, 500, 500], force: [300, 300, 300, 300, 300, 300]}
      grasp:  {angles: [0, 0, 0, 0, 300, 1000], speed: [500, 500, 500, 500, 500, 500], force: [300, 300, 300, 300, 300, 300]}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_inspire_preset_grasp.py tests/test_cli_entrypoints.py -q`
Expected: 全 PASS

- [ ] **Step 5: 全量回归 + 提交**

Run: `python -m pytest tests/ -q --ignore=tests/test_train_script.py`（train 系缺依赖模块按既有惯例 ignore）
Expected: 除既有 3 个 HDF5 recorder 旧失败外全 PASS

```bash
git add teleopit/sim2real/hands/worker.py teleopit/sim2real/hands/inspire_ftp.py teleopit/configs/pico4_sim2real_bsi.yaml tests/test_inspire_preset_grasp.py tests/test_cli_entrypoints.py
git commit -m "feat(hands): inspire_ftp wiring — factory dispatch + pico4_sim2real_bsi hands section"
```

---

### Task 6: 收尾——冒烟 + plan 勾选 + Orin 部署清单

**Files:**
- Modify: 本 plan 文件（勾选）

- [ ] **Step 1: import 面冒烟**

Run: `python -c "import teleopit.sim2real.hands.inspire_ftp, teleopit.sim2real.hands.worker, teleopit.sim2real.mp.runtime"`
Expected: 无 ImportError（cyclonedds 零泄漏）

- [ ] **Step 2: 提交 plan 勾选**

```bash
git add docs/superpowers/plans/2026-08-22-inspire-preset-grasp.md
git commit -m "docs(plan): check off inspire preset-grasp implementation"
```

- [ ] **Step 3: Orin 部署（pull 或 patch，同 2026-08-22 惯例）+ 起栈顺序**

```bash
# Orin, tmux 窗口 A（手驱动，先起）:
conda activate inspire_test
python ~/eeg_humanoid/lib/inspire_hand_ws/inspire_hand_sdk/example/driver_double_wlan0.py
# 窗口 B（主栈）:
cd ~/eeg_humanoid/teleop/Teleopit && conda activate teleopit
export CYCLONEDDS_URI=file:///home/unitree/cyclonedds_orin.xml
python scripts/run/run_sim2real.py --config-name pico4_sim2real_bsi controller.policy_path=ckpt/track_g1.onnx
```

---

### Task 7（真机会话）: manus 取数回填 + 验收行

- [ ] **Step 1: PC manus server 实跑取数**：起 `manus_haptic_rt`（macos/PC 配置，参考其 docs/knowledge），操作者做张开/抓握各一次，录 `rt/inspire_hand/ctrl/l|r` 的 `angle_set/speed_set/force_set/mode`（其 doctor/echo 工具或 `dds-probe` echo），取稳定段均值回填 `hands.inspire_ftp.presets`（拇指转位保持 1000）。
- [ ] **Step 2: 真机验收三行**：① STANDING 扣左/右扳机→对应手 grasp，再扣→open，拇指转全程不动；② 行走中（VELOCITY）扣扳机无响应、手保持（hold）；③ L1+R1→DAMPING→双手张开。全过 = 功能验收。
- [ ] **Step 3: 结果回填** docs/knowledge/research/ 一篇记录。

---

## Self-Review 结论

- **Spec 覆盖**：Q1 toggle→Task 2；Q2 二态表→Task 2/5（占位值+Task 7 回填）；Q3/Q10 作用域与 hold/open→Task 4；Q7 DDS 架构→Task 3 真发布器 + Task 6 起栈顺序；Q8 manus 取数→Task 7；Q9/Q12 同侧独立→Task 2（per-side 状态）；拇指转钉住→Task 3 `_compose` 单点；mode 0b1101/0b0101→Task 3 测试钉死；Q11 配置→Task 5；Q6 交接→本 plan + 记忆。
- **占位符**：Task 4 Step 3 首段代码块含一行待删冗余（已注明），其余无 TBD；预设数值为**有意的占位数据**，回填路径明确（Task 7）。
- **类型一致性**：`HandPoseCommand(speed_set/force_set)` Task 1 定义 = Task 2 构造 = Task 3 消费；`InspireCtrlMessage` 字段 = `_RealInspirePublisher.publish` 消费；`build_inspire_ftp(cfg)` Task 3 产出 = Task 5 工厂调用；`trigger_modes/open_modes` 键名 Task 4 = Task 5 yaml = Task 5 合同测。
