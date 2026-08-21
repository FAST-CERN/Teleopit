# BSI 真机 VELOCITY 模式实现计划（bsi-realhw Phase B Teleopit 侧）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 mp 真机运行时（`_RobotControlWorker`）新增 `RobotMode.VELOCITY`：Pico 键控进出（X / 左 grip）、merged BSI+摇杆 twist 源、速度 ONNX 策略直驱，带 05 安全包络（阈值/damping 锁存/E 解锁）与 07 验收支撑（L2 限速、cmd jsonl 日志）。

**Architecture:** 一切住在 robot_control 进程内——订阅器、`MergedTwistProvider`、`EstopController`、velocity ONNX 栈全部随 `_RobotControlWorker` 构建（04/D2）；模式机以 STANDING 为枢纽，`TOGGLE_VELOCITY` 事件走既有 CONTROL_EVENTS_TOPIC 管线（04/D1）；安全阈值每 policy step 检查，任一 damping 入口都置 estop 锁存（05）；L2 限速 = provider 包装器 + yaml 预设（07）。

**Tech Stack:** Python / NumPy / ONNX（RLPolicyController）/ ZMQ IPC（mp 进程间）/ cyclonedds（仅运行时 lazy import，测试一律注入假 reader）。

**Spec:** `docs/wayfinder/2026-08-21-bsi-realhw/`（map + tickets 04/05/07 的 Resolution——本 plan 的全部需求来源，执行时两读）。

## Global Constraints

- **频率不变量**：policy_hz 50 / LowCmd 200Hz，两侧一致（04）。
- **安全阈值（05，票面原值）**：joint-vel 上限 **10.0 rad/s**（单一标量）→ 立即 damping；tilt 优雅线 **0.524 rad（30°）** → 0.3s 渐0 回 STANDING；tilt 跌倒线 **0.785 rad（45°）** → 立即 damping。仅 VELOCITY 模式查，每 policy step 一次。
- **锁存规则（05）**：凡进过 DAMPING（L1+R1 / joint-vel / tilt≥45°）→ estop 锁存，VELOCITY 拒入，**E 是唯一解锁键**（同键 toggle）；优雅路径不锁。
- **E 急停语义（照搬 sim，`teleopit/sim/estop.py`）**：0.3s 指数衰减→0 → 走退出路径进 STANDING；站立下按 = no-op。
- **进门规则（04/D1）**：仅 STANDING 可进 VELOCITY；estop 锁存期拒绝。
- **L2 限制（07）**：全通道（BSI+摇杆）仅 forward，lin_x ≤ **0.3 m/s**，lin_y / ang_z 一律 0；lin_x 负值（后退）也压 0。
- **键位（07）**：Pico **X = TOGGLE_VELOCITY**、**左 grip（模拟量阈值）= TOGGLE_ESTOP**、Y = mute、A/B 原功能；G1 遥控器 Y 进 mocap 加配置门 `mocap_entry_enabled`（BSI yaml 默认 **false**）。
- **测试环境铁律**：teleopit env 无 cyclonedds/bsi_dds——测试一律走 `reader_factory` 注入或 monkeypatch，**任何测试不得触发 `from bsi_dds import ...`**（bsi_factory 的 lazy-import 缝是既有锁定设计）。
- **VELOCITY 进程内构建（04/D2）**：`build_merged_bsi_provider` 顶层 import 安全（bsi_factory 顶层只 import teleopit.commands.*，cyclonedds 仅在 `build_dds_reader` 函数体内 lazy import）。
- 提交信息用 conventional commits（feat/test/docs），每任务一提交。

## 事实底座（执行者必读）

- `_RobotControlWorker`：`teleopit/sim2real/mp/runtime.py:1197`。主循环 `run()`（1373）先查遥控器 L1+R1 → `_enter_damping`（2341），再 `_handle_transitions`（1489），按 mode 分发 step。
- 事件管线：Pico 进程 `pop_control_events` → `ControlEventsPacket` 发布到 CONTROL_EVENTS_TOPIC（runtime.py:767-772）→ robot_control `_events_sub` → `_handle_mocap_control_events`（2419，现只处理 TOGGLE_ARMS/PAUSE，ESTOP/MUTE 被丢弃）。
- 摇杆数据：Pico 进程把 `provider.get_controller_snapshot()` 包成 `SnapshotPacket(snapshot, timestamp_s, seq)` 发 CONTROLLER_TOPIC（runtime.py:774-784）；`PicoJoystickProvider`（`teleopit/commands/pico_joystick.py`）读 `input_provider.get_controller_snapshot()` → `.left/.right.present/.axis_x/.axis_y` + `.timestamp_s`。
- `_run_pico_input_worker` 构造 `Pico4InputProvider`（runtime.py:635-652）**只传了 pause/arms 按钮**——estop/mute 参数存在但从未接线（这就是真机收不到 E/哑音的根因）。
- `Pico4InputProvider`（`teleopit/inputs/pico4_provider.py`）：`_poll_control_events`（558）逐按钮调 `_poll_button_control_event`（602，buttons 字典 + 边沿 + 去抖）；`_PAUSE_BUTTON_MAP`（109）只有 A/B/X/Y/axis_click/menu。**grip 是模拟量**（`axis["grip"]`，0..1，见 652），不在 buttons 字典里——左 grip 急停必须走模拟量阈值边沿检测。
- `_build_policy_and_obs`（runtime.py:1448）= mimic 栈构建先例（`_build_policy_components` + `_multi_input` 门）。velocity 侧用 `teleopit/runtime/factory.py:499` 的 `build_velocity_policy_components(cfg, project_root)` → `(velocity_controller, velocity_obs_builder)`，single_input_ok，无需 _multi_input 门。
- `_standing_step`（runtime.py:1978）= step 先例：`get_state → build_observation → policy.compute_action → policy.get_target_dof_pos → safety.clip_to_joint_limits → safety.send_positions`。
- `TwistCmdObservationBuilder.build(state, cmd, last_action) -> obs`（`teleopit/controllers/twist_observation.py:105`）——内部自带步态推进，与真机 `RobotState`（qpos[:29]/qvel[:29]/quat/ang_vel）完全兼容（04 已验）。tilt 数学：`_quat_rotate_inv_np(quat, [0,0,-1])` → `arccos(clip(-g_b[2]))`（`teleopit/sim/velocity_step.py:154-160`，纯 numpy 可复用）。
- `_enter_standing`（runtime.py:2199）：按 prev_mode 分支——"已在 debug 模式"集合（STANDING/MOCAP/ARMS/POLICY）、"退出时 ramp 参考+kp"集合（MOCAP/ARMS/POLICY）。VELOCITY 两个集合都要加入。
- `EstopController`（`teleopit/sim/estop.py`）：`toggle(in_velocity)` / `apply(cmd)` / `consume_exit_request()` / `on_standing()`；状态 INACTIVE/RAMPING/LATCHED。**没有 force-latch 方法，需新增 `latch()`**。
- `Sim2RealSafetyManager`（`teleopit/sim2real/safety.py`）：有 `check_joint_velocity_safety`（mp 路径今天未调用）但**无 tilt 检查**——本计划新增独立函数 `velocity_safety_verdict`，不复用该类。
- 测试惯例（`tests/test_sim2real_multiprocess.py`）：`object.__new__(_RobotControlWorker)` + `SimpleNamespace` 假件，单测方法不整体构造。
- 配置测试惯例（`tests/test_cli_entrypoints.py:48`）：hydra `initialize_config_dir` + `compose`。配置组 `controller/velocity.yaml` 已存在；`pico4_sim2real.yaml` 是真机基线（real_robot 段、runtime 段）。

## File Structure

- Modify `teleopit/inputs/realtime_packet.py` — `ControlEventType` 加 `TOGGLE_VELOCITY`（1 行）。
- Modify `teleopit/inputs/pico4_provider.py` — `velocity_button` 数字键 + `left_grip` 模拟量急停。
- Modify `teleopit/sim2real/mp/runtime.py` — 主体：RobotMode.VELOCITY、velocity 栈构建、事件处理、`_velocity_step`、damping 锁存、Y 门、pico worker 按钮接线。
- Modify `teleopit/sim/estop.py` — 加 `latch()`。
- Modify `teleopit/sim2real/safety.py` — 加 `velocity_safety_verdict()`。
- Create `teleopit/commands/forward_only.py` — `ForwardOnlyCapProvider`（L2）。
- Create `teleopit/sim2real/mp/cmd_log.py` — `VelocityCmdLogger`（jsonl）。
- Create `teleopit/configs/pico4_sim2real_bsi.yaml` — BSI 真机主配置（L3/自由）。
- Create `teleopit/configs/pico4_sim2real_bsi_l2.yaml` — L2 看护慢速预设。
- Test: `tests/test_pico_velocity_grip_buttons.py`、`tests/test_sim2real_velocity_mode.py`、`tests/test_sim2real_velocity_safety.py`、`tests/test_forward_only_provider.py`、`tests/test_velocity_cmd_log.py`；`tests/test_velocity_session.py` 与 `tests/test_cli_entrypoints.py` 追加。

---

### Task 1: `TOGGLE_VELOCITY` 事件类型 + Pico X 数字键

**Files:**
- Modify: `teleopit/inputs/realtime_packet.py:17-21`
- Modify: `teleopit/inputs/pico4_provider.py`（`__init__` 217-320、`_poll_control_events` 558-600）
- Test: `tests/test_pico_velocity_grip_buttons.py`（新建）

**Interfaces:**
- Produces: `ControlEventType.TOGGLE_VELOCITY = "toggle_velocity"`；`Pico4InputProvider.__init__(..., velocity_button: str | None = None, velocity_debounce_s: float | None = None, ...)`。按钮名走 `_PAUSE_BUTTON_MAP`（"X" → ("left", "primaryButton")）。Task 2/8 依赖此事件类型与参数名。

- [x] **Step 1: 写失败测试**

```python
# tests/test_pico_velocity_grip_buttons.py
"""Pico 侧新键位：X=TOGGLE_VELOCITY（本文件 Task1）、左 grip=TOGGLE_ESTOP（Task2）。"""
from __future__ import annotations

from types import SimpleNamespace

from teleopit.inputs.pico4_provider import Pico4InputProvider
from teleopit.inputs.realtime_packet import ControlEvent, ControlEventType


def _frame_with_buttons(side: str, buttons: dict[str, bool], *, timestamp: float = 100.0):
    controller = SimpleNamespace(buttons=buttons, axis={}, present=True, raw=False)
    controllers = SimpleNamespace(**{side: controller})
    return SimpleNamespace(controllers=controllers, timestamp_s=timestamp)


def test_velocity_button_x_emits_toggle_velocity_event() -> None:
    provider = Pico4InputProvider(velocity_button="X", velocity_debounce_s=0.25)
    # Pico4InputProvider 后台线程需要 bridge；这里直连私有轮询（单测惯例）。
    frame_off = _frame_with_buttons("left", {"primaryButton": False})
    frame_on = _frame_with_buttons("left", {"primaryButton": True}, timestamp=101.0)

    provider._poll_control_events(frame_off, timestamp=100.0)
    events: tuple[ControlEvent, ...] = ()
    for _ in range(2):
        events = provider.pop_control_events()
        if events:
            break
        provider._poll_control_events(frame_on, timestamp=101.0)

    assert any(e.event_type == ControlEventType.TOGGLE_VELOCITY for e in events)
    assert events[0].source == "pico4:X"
```

- [x] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_pico_velocity_grip_buttons.py -v`
Expected: FAIL（`TypeError: unexpected keyword 'velocity_button'`）

- [x] **Step 3: 最小实现**

`teleopit/inputs/realtime_packet.py`：

```python
class ControlEventType(str, Enum):
    TOGGLE_PAUSE = "toggle_pause"
    TOGGLE_ARMS = "toggle_arms"
    TOGGLE_ESTOP = "toggle_estop"
    TOGGLE_MUTE = "toggle_mute"
    TOGGLE_VELOCITY = "toggle_velocity"
```

`teleopit/inputs/pico4_provider.py` `__init__` 签名在 `arms_debounce_s` 之后加两个参数并在体末解析 path（与 estop/mute 同款）：

```python
        velocity_button: str | None = None,
        velocity_debounce_s: float | None = None,
```

```python
        self._velocity_button = velocity_button
        self._velocity_debounce_s = (
            float(velocity_debounce_s)
            if velocity_debounce_s is not None
            else 0.25
        )
        self._velocity_button_path = self._resolve_button_path(velocity_button)
        self._last_velocity_button_pressed = False
        self._last_velocity_toggle_timestamp: float | None = None
```

`_poll_control_events` 在 mute 块后追加（完全镜像 estop 块）：

```python
        emitted = self._poll_button_control_event(
            frame,
            timestamp=timestamp,
            button_path=self._velocity_button_path,
            button_label=self._velocity_button,
            event_type=ControlEventType.TOGGLE_VELOCITY,
            last_pressed_attr="_last_velocity_button_pressed",
            last_toggle_attr="_last_velocity_toggle_timestamp",
            debounce_s=self._velocity_debounce_s,
        ) or emitted
```

- [x] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_pico_velocity_grip_buttons.py -v`
Expected: PASS

- [x] **Step 5: 回归 + 提交**

Run: `python -m pytest tests/ -k "pico" -q`
Expected: 全 PASS（既有 pico 测试不受影响）

```bash
git add teleopit/inputs/realtime_packet.py teleopit/inputs/pico4_provider.py tests/test_pico_velocity_grip_buttons.py
git commit -m "feat(pico): TOGGLE_VELOCITY control event + X button polling"
```

---

### Task 2: 左 grip 模拟量急停 + mp worker 按钮接线

**Files:**
- Modify: `teleopit/inputs/pico4_provider.py`（`__init__`、新 `_poll_grip_control_event`、`_poll_control_events`）
- Modify: `teleopit/sim2real/mp/runtime.py:635-652`（`_run_pico_input_worker` 构造）
- Test: `tests/test_pico_velocity_grip_buttons.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `TOGGLE_ESTOP` 既有事件类型。
- Produces: `estop_button: "left_grip"` 走模拟量阈值；参数 `estop_grip_threshold: float = 0.6`。mp 构造传递 `estop_button / estop_grip_threshold / mute_button / velocity_button` 四个 input 配置键（Task 8 的 yaml 依赖这些键名）。

**背景**：grip 不在 buttons 字典（数字量缺失），但 `controller.axis["grip"]`（0..1 模拟量）保证存在（`_read_controller_state` 652 行在读）。阈值 + 边沿检测 = 数字键等价行为，无需改 Unity 桥。

- [x] **Step 1: 写失败测试（追加到 tests/test_pico_velocity_grip_buttons.py）**

```python
def _frame_with_grip(side: str, grip: float, *, timestamp: float = 100.0):
    controller = SimpleNamespace(buttons={}, axis={"grip": grip}, present=True, raw=False)
    controllers = SimpleNamespace(**{side: controller})
    return SimpleNamespace(controllers=controllers, timestamp_s=timestamp)


def test_left_grip_crossing_threshold_emits_toggle_estop() -> None:
    provider = Pico4InputProvider(estop_button="left_grip", estop_grip_threshold=0.6)
    provider._poll_control_events(_frame_with_grip("left", 0.1), timestamp=100.0)
    assert provider.pop_control_events() == ()

    provider._poll_control_events(_frame_with_grip("left", 0.9), timestamp=101.0)
    events = provider.pop_control_events()
    assert [e.event_type for e in events] == [ControlEventType.TOGGLE_ESTOP]
    assert events[0].source == "pico4:left_grip"


def test_left_grip_below_threshold_is_silent() -> None:
    provider = Pico4InputProvider(estop_button="left_grip", estop_grip_threshold=0.6)
    provider._poll_control_events(_frame_with_grip("left", 0.5), timestamp=100.0)
    assert provider.pop_control_events() == ()
```

- [x] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_pico_velocity_grip_buttons.py -v`
Expected: 新增两测 FAIL（`left_grip` 不在 `_PAUSE_BUTTON_MAP`，path 为 None → 无事件）

- [x] **Step 3: 最小实现**

`teleopit/inputs/pico4_provider.py` `__init__` 加参数 `estop_grip_threshold: float = 0.6` 与状态位：

```python
        self._estop_grip_threshold = float(estop_grip_threshold)
        self._estop_is_grip = estop_button in ("left_grip", "right_grip")
        self._estop_grip_side = "left" if estop_button == "left_grip" else "right"
        self._last_grip_pressed = False
```

新方法（放在 `_poll_button_control_event` 之后）：

```python
    def _poll_grip_control_event(self, frame: Any, *, timestamp: float) -> bool:
        """Analog grip edge detector: threshold crossing == button press.

        The bridge reports grip only as an analog axis (0..1), never in the
        buttons dict, so the estop seam maps the threshold crossing onto the
        same edge+debounce discipline as digital buttons.
        """
        controllers = getattr(frame, "controllers", None)
        controller = None if controllers is None else getattr(controllers, self._estop_grip_side, None)
        axis = {} if controller is None else getattr(controller, "axis", {}) or {}
        pressed = float(axis.get("grip", 0.0)) >= self._estop_grip_threshold
        last_pressed = self._last_grip_pressed
        emitted = False
        if pressed and not last_pressed:
            last_toggle = self._last_estop_toggle_timestamp
            if last_toggle is None or timestamp - float(last_toggle) >= self._estop_debounce_s - 1e-9:
                with self._lock:
                    self._pending_control_events.append(
                        ControlEvent(
                            event_type=ControlEventType.TOGGLE_ESTOP,
                            source="pico4:left_grip" if self._estop_grip_side == "left" else "pico4:right_grip",
                            timestamp_s=float(timestamp),
                        )
                    )
                logger.info("Pico control event: toggle_estop from grip (side=%s)", self._estop_grip_side)
                setattr(self, "_last_estop_toggle_timestamp", float(timestamp))
                emitted = True
        self._last_grip_pressed = pressed
        return emitted
```

`_poll_control_events` 的 estop 块改为二选一：

```python
        if self._estop_is_grip:
            emitted = self._poll_grip_control_event(frame, timestamp=timestamp) or emitted
        else:
            emitted = self._poll_button_control_event(
                frame,
                timestamp=timestamp,
                button_path=self._estop_button_path,
                button_label=self._estop_button,
                event_type=ControlEventType.TOGGLE_ESTOP,
                last_pressed_attr="_last_estop_button_pressed",
                last_toggle_attr="_last_estop_toggle_timestamp",
                debounce_s=self._estop_debounce_s,
            ) or emitted
```

`teleopit/sim2real/mp/runtime.py` `_run_pico_input_worker` 构造（635-652）在 `arms_debounce_s` 行后补四行（**根因修复：estop/mute 从未接线到 mp 真机**）：

```python
            estop_button=cfg_get(input_cfg, "estop_button", None),
            estop_grip_threshold=float(cfg_get(input_cfg, "estop_grip_threshold", 0.6)),
            mute_button=cfg_get(input_cfg, "mute_button", None),
            velocity_button=cfg_get(input_cfg, "velocity_button", None),
            velocity_debounce_s=float(cfg_get(input_cfg, "velocity_debounce_s", 0.25)),
```

- [x] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_pico_velocity_grip_buttons.py -v`
Expected: PASS（3 测）

- [x] **Step 5: 回归 + 提交**

Run: `python -m pytest tests/ -k "pico or realtime" -q`
Expected: 全 PASS

```bash
git add teleopit/inputs/pico4_provider.py teleopit/sim2real/mp/runtime.py tests/test_pico_velocity_grip_buttons.py
git commit -m "feat(pico): analog left-grip estop edge detect + wire estop/mute/velocity buttons into mp pico worker"
```

---

### Task 3: `EstopController.latch()`

**Files:**
- Modify: `teleopit/sim/estop.py`（类尾追加）
- Test: `tests/test_velocity_session.py`（追加——estop 既有测试在此）

**Interfaces:**
- Produces: `EstopController.latch() -> None`——任意状态强制 LATCHED 且**不**置 exit 请求（damping 场景不需要渐0 退出，只要锁）；随后 `toggle()` 照常释放。Task 8/9 的「凡进 DAMPING 必锁」依赖它。

- [x] **Step 1: 写失败测试（追加到 tests/test_velocity_session.py，numpy/np 已有导入）**

```python
def test_estop_latch_forces_latched_and_releases_by_toggle() -> None:
    from teleopit.sim.estop import EstopState

    clock = [0.0]
    estop = EstopController(clock=lambda: clock[0])

    estop.latch()
    assert estop.state == EstopState.LATCHED
    np.testing.assert_allclose(estop.apply(np.ones(6, dtype=np.float32)), np.zeros(6, dtype=np.float32))
    # latch 不产生退出请求（damping 场景无需渐0 退出路径）
    assert estop.consume_exit_request() is False
    # 同键 toggle 解锁
    assert estop.toggle(in_velocity=False) == "released"
    assert estop.state == EstopState.INACTIVE
```

- [x] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_velocity_session.py::test_estop_latch_forces_latched_and_releases_by_toggle -v`
Expected: FAIL（`AttributeError: 'EstopController' object has no attribute 'latch'`）

- [x] **Step 3: 最小实现（teleopit/sim/estop.py，`consume_exit_request` 之后）**

```python
    def latch(self) -> None:
        """Force LATCHED without an exit request (damping entry, bsi-realhw-05).

        Any DAMPING entry locks VELOCITY re-entry until the operator's E
        toggle releases it. No ramp/exit semantics: the caller has already
        left VELOCITY by harder means.
        """
        self._state = EstopState.LATCHED
        self._ramp_start = None
        self._exit_requested = False
        self._exit_consumed = True
```

- [x] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_velocity_session.py -v`
Expected: 全 PASS（既有 estop 测试不受影响）

- [x] **Step 5: 提交**

```bash
git add teleopit/sim/estop.py tests/test_velocity_session.py
git commit -m "feat(estop): latch() for damping-entry lock (bsi-realhw-05)"
```

---

### Task 4: `velocity_safety_verdict` 真机阈值判定

**Files:**
- Modify: `teleopit/sim2real/safety.py`（模块级函数，文件尾追加）
- Test: `tests/test_sim2real_velocity_safety.py`（新建）

**Interfaces:**
- Produces: `velocity_safety_verdict(state, *, joint_vel_limit: float, tilt_graceful_rad: float, tilt_damping_rad: float) -> str | None`，返回 `"damping" | "standing" | None`。joint-vel 超 → "damping"；tilt ≥ 跌倒线 → "damping"；tilt ≥ 优雅线 → "standing"。tilt 数学复用 `teleopit.controllers.twist_observation._quat_rotate_inv_np`（纯 numpy，无 mujoco 依赖）。Task 9 的 `_velocity_step` 消费。

- [x] **Step 1: 写失败测试**

```python
# tests/test_sim2real_velocity_safety.py
"""bsi-realhw-05 真机阈值：joint-vel 10.0 / tilt 30° 优雅 / 45° damping。"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from teleopit.sim2real.safety import velocity_safety_verdict

LIMITS = dict(joint_vel_limit=10.0, tilt_graceful_rad=0.524, tilt_damping_rad=0.785)


def _state(*, tilt_deg: float = 0.0, qvel_fill: float = 0.0) -> SimpleNamespace:
    theta = np.deg2rad(tilt_deg)
    quat = np.array(
        [np.cos(theta / 2.0), np.sin(theta / 2.0), 0.0, 0.0], dtype=np.float32
    )
    return SimpleNamespace(
        qpos=np.zeros(29, dtype=np.float32),
        qvel=np.full(29, qvel_fill, dtype=np.float32),
        quat=quat,
        ang_vel=np.zeros(3, dtype=np.float32),
    )


def test_normal_walking_state_is_clean() -> None:
    assert velocity_safety_verdict(_state(tilt_deg=5.0, qvel_fill=3.0), **LIMITS) is None


def test_joint_vel_over_limit_demands_damping() -> None:
    assert velocity_safety_verdict(_state(qvel_fill=11.0), **LIMITS) == "damping"


def test_tilt_over_graceful_line_demands_standing() -> None:
    assert velocity_safety_verdict(_state(tilt_deg=35.0), **LIMITS) == "standing"


def test_tilt_over_damping_line_demands_damping() -> None:
    assert velocity_safety_verdict(_state(tilt_deg=50.0), **LIMITS) == "damping"


def test_joint_vel_wins_over_tilt_when_both_exceeded() -> None:
    assert (
        velocity_safety_verdict(_state(tilt_deg=50.0, qvel_fill=11.0), **LIMITS)
        == "damping"
    )
```

- [x] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_sim2real_velocity_safety.py -v`
Expected: FAIL（ImportError：函数不存在）

- [x] **Step 3: 最小实现（teleopit/sim2real/safety.py 文件尾）**

```python
def velocity_safety_verdict(
    state: Any,
    *,
    joint_vel_limit: float,
    tilt_graceful_rad: float,
    tilt_damping_rad: float,
) -> str | None:
    """bsi-realhw-05 envelope check for the real-robot VELOCITY mode.

    Returns "damping" (overspeed or falling: enter DAMPING now), "standing"
    (recoverable tilt: graceful 0.3s-ramp exit to STANDING), or None.
    Checked once per policy step, VELOCITY mode only — same discipline as the
    sim's VelocityStepController.check_safety, with the real dual tilt lines.
    """
    import numpy as np

    from teleopit.controllers.twist_observation import _quat_rotate_inv_np

    max_vel = float(np.max(np.abs(np.asarray(state.qvel, dtype=np.float64))))
    if max_vel > float(joint_vel_limit):
        logger.error(
            "SAFETY: joint velocity %.2f rad/s exceeds %.2f -> DAMPING", max_vel, joint_vel_limit
        )
        return "damping"
    quat = np.asarray(state.quat, dtype=np.float32)
    gravity_b = _quat_rotate_inv_np(quat, np.array([0.0, 0.0, -1.0], dtype=np.float32))
    tilt = float(np.arccos(np.clip(-gravity_b[2], -1.0, 1.0)))
    if tilt > float(tilt_damping_rad):
        logger.error("SAFETY: tilt %.2f rad over %.2f -> DAMPING", tilt, tilt_damping_rad)
        return "damping"
    if tilt > float(tilt_graceful_rad):
        logger.error("SAFETY: tilt %.2f rad over %.2f -> STANDING", tilt, tilt_graceful_rad)
        return "standing"
    return None
```

- [x] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_sim2real_velocity_safety.py -v`
Expected: PASS（5 测）

- [x] **Step 5: 提交**

```bash
git add teleopit/sim2real/safety.py tests/test_sim2real_velocity_safety.py
git commit -m "feat(safety): velocity_safety_verdict — real dual tilt lines + joint-vel gate (bsi-realhw-05)"
```

---

### Task 5: `ForwardOnlyCapProvider`（L2 限速压制）

**Files:**
- Create: `teleopit/commands/forward_only.py`
- Test: `tests/test_forward_only_provider.py`（新建）

**Interfaces:**
- Consumes: 任意 `CommandProvider`（`get_cmd/reset/close`）。
- Produces: `ForwardOnlyCapProvider(inner, *, max_lin_x: float)`——`get_cmd()` 返回 6D：`out[0] = clip(cmd[0], 0.0, max_lin_x)`（负值=后退也压 0），`out[1] = 0.0`，`out[5] = 0.0`，其余照抄；`reset()/close()` 委托。Task 7 的 restrict 装配消费。

- [x] **Step 1: 写失败测试**

```python
# tests/test_forward_only_provider.py
"""L2 看护慢速门：全通道仅 forward ≤ max_lin_x，侧向/转向一律 0（bsi-realhw-07）。"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from teleopit.commands.forward_only import ForwardOnlyCapProvider


def _provider(cmd: np.ndarray) -> SimpleNamespace:
    return SimpleNamespace(
        get_cmd=lambda: np.asarray(cmd, dtype=np.float32).copy(),
        reset=lambda: None,
        close=lambda: None,
    )


def test_forward_clamped_to_cap() -> None:
    capped = ForwardOnlyCapProvider(_provider(np.array([0.6, 0, 0, 0, 0, 0])), max_lin_x=0.3)
    np.testing.assert_allclose(capped.get_cmd(), np.array([0.3, 0, 0, 0, 0, 0], dtype=np.float32))


def test_backward_and_lateral_and_turn_are_zeroed() -> None:
    capped = ForwardOnlyCapProvider(
        _provider(np.array([-0.4, 0.5, 0, 0, 0, -0.8])), max_lin_x=0.3
    )
    np.testing.assert_allclose(capped.get_cmd(), np.array([0.0, 0, 0, 0, 0, 0], dtype=np.float32))


def test_zero_command_passes_through() -> None:
    capped = ForwardOnlyCapProvider(_provider(np.zeros(6)), max_lin_x=0.3)
    np.testing.assert_allclose(capped.get_cmd(), np.zeros(6, dtype=np.float32))
```

- [x] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_forward_only_provider.py -v`
Expected: FAIL（ModuleNotFoundError）

- [x] **Step 3: 最小实现**

```python
# teleopit/commands/forward_only.py
"""L2 caretaker gate: whole-channel forward-only cap (wayfinder bsi-realhw-07).

Applied above the merged provider so BOTH halves (BSI intents and Pico
joystick) obey the same envelope: lin_x clamped to [0, max_lin_x] (reverse
squelched too), lin_y and ang_z forced to zero. L3 runs without this wrapper.
"""
from __future__ import annotations

from typing import Any

import numpy as np


class ForwardOnlyCapProvider:
    """Wrap a CommandProvider with the L2 forward-only envelope."""

    def __init__(self, inner: Any, *, max_lin_x: float) -> None:
        if float(max_lin_x) <= 0.0:
            raise ValueError(f"max_lin_x must be > 0, got {max_lin_x}")
        self._inner = inner
        self._max_lin_x = float(max_lin_x)

    def get_cmd(self) -> np.ndarray:
        cmd = np.asarray(self._inner.get_cmd(), dtype=np.float32).reshape(-1).copy()
        if cmd.shape[0] < 6:
            return cmd
        cmd[0] = np.clip(cmd[0], 0.0, self._max_lin_x)
        cmd[1] = 0.0
        cmd[5] = 0.0
        return cmd

    def reset(self) -> None:
        self._inner.reset()

    def close(self) -> None:
        self._inner.close()

    @property
    def muted(self) -> bool:
        return bool(getattr(self._inner, "muted", False))

    def toggle_mute(self) -> bool | None:
        """Delegate BSI mute through the cap so TOGGLE_MUTE survives wrapping."""
        toggle = getattr(self._inner, "toggle_mute", None)
        return bool(toggle()) if callable(toggle) else None
```

- [x] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_forward_only_provider.py -v`
Expected: PASS（4 测）

补第四测（与 Step 1 一起写）：

```python
def test_mute_delegates_through_the_cap() -> None:
    calls: list[bool] = []

    def _mute() -> bool:
        calls.append(True)
        return True

    inner = SimpleNamespace(
        get_cmd=lambda: np.zeros(6), reset=lambda: None, close=lambda: None,
        toggle_mute=_mute, muted=False,
    )
    capped = ForwardOnlyCapProvider(inner, max_lin_x=0.3)
    assert capped.toggle_mute() is True
    assert calls == [True]
    assert capped.muted is False
```

- [x] **Step 5: 提交**

```bash
git add teleopit/commands/forward_only.py tests/test_forward_only_provider.py
git commit -m "feat(commands): ForwardOnlyCapProvider — L2 forward-only envelope (bsi-realhw-07)"
```

---

### Task 6: `VelocityCmdLogger`（jsonl 指标日志）

**Files:**
- Create: `teleopit/sim2real/mp/cmd_log.py`
- Test: `tests/test_velocity_cmd_log.py`（新建）

**Interfaces:**
- Produces: `VelocityCmdLogger(path: str | None)`——`log(*, cmd, estop_state: str, mode: str, muted: bool) -> None` 追加一行 JSON（`{"t": <monotonic 秒>, "cmd": [6 floats], "estop": ..., "mode": ..., "muted": ...}`）；`path=None` 为空操作（默认不开日志）；`close()` 关文件。07 的时序指标表（意图→cmd ≤1.0s、E→cmd0 ≤0.8s、抢夺 ≤2 周期）全部由此文件事后分析。

- [x] **Step 1: 写失败测试**

```python
# tests/test_velocity_cmd_log.py
import json

import numpy as np

from teleopit.sim2real.mp.cmd_log import VelocityCmdLogger


def test_log_writes_jsonl_lines(tmp_path) -> None:
    path = tmp_path / "cmd.jsonl"
    logger = VelocityCmdLogger(str(path))
    logger.log(cmd=np.array([0.6, 0, 0, 0, 0, 0.0]), estop_state="inactive", mode="velocity", muted=False)
    logger.log(cmd=np.zeros(6), estop_state="latched", mode="velocity", muted=True)
    logger.close()

    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 2
    assert lines[0]["cmd"] == [0.6, 0.0, 0.0, 0.0, 0.0, 0.0]
    assert lines[0]["estop"] == "inactive"
    assert lines[1]["muted"] is True


def test_none_path_is_a_noop() -> None:
    logger = VelocityCmdLogger(None)
    logger.log(cmd=np.zeros(6), estop_state="inactive", mode="velocity", muted=False)
    logger.close()  # 不抛即过
```

- [x] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_velocity_cmd_log.py -v`
Expected: FAIL（ModuleNotFoundError）

- [x] **Step 3: 最小实现**

```python
# teleopit/sim2real/mp/cmd_log.py
"""Per-step jsonl command log for the real VELOCITY mode (bsi-realhw-07).

The acceptance timing table (intent->cmd, E->cmd0, joystick-preemption
cycles) is derived offline from this file; LowState has no base_lin_vel, so
the merged cmd stream is the authoritative observable.
"""
from __future__ import annotations

import json
import time
from typing import Any

import numpy as np


class VelocityCmdLogger:
    """Append one JSON line per policy step; disabled when path is None."""

    def __init__(self, path: str | None) -> None:
        self._path = path
        self._fh: Any = None
        if path:
            self._fh = open(path, "a", encoding="utf-8")

    def log(self, *, cmd: np.ndarray, estop_state: str, mode: str, muted: bool) -> None:
        if self._fh is None:
            return
        record = {
            "t": time.monotonic(),
            "cmd": [float(v) for v in np.asarray(cmd, dtype=np.float32).reshape(-1)[:6]],
            "estop": str(estop_state),
            "mode": str(mode),
            "muted": bool(muted),
        }
        self._fh.write(json.dumps(record) + "\n")
        self._fh.flush()

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None
```

- [x] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_velocity_cmd_log.py -v`
Expected: PASS（2 测）

- [x] **Step 5: 提交**

```bash
git add teleopit/sim2real/mp/cmd_log.py tests/test_velocity_cmd_log.py
git commit -m "feat(mp): VelocityCmdLogger jsonl per-step command log (bsi-realhw-07)"
```

---

### Task 7: worker velocity 栈装配（RobotMode.VELOCITY + 指令源）

**Files:**
- Modify: `teleopit/sim2real/mp/runtime.py`：`RobotMode`（145-151）、模块 import 区、`_RobotControlWorker.__init__`（1265 后插段）、新方法 `_build_velocity_stack`、新模块级 `_ControllerSnapshotProxy`
- Test: `tests/test_sim2real_velocity_mode.py`（新建）

**Interfaces:**
- Consumes: Task 5 `ForwardOnlyCapProvider`、Task 6 `VelocityCmdLogger`、既有 `build_velocity_policy_components(cfg, project_root)` / `build_merged_bsi_provider(joystick, bsi_cfg, *, reader_factory=None)` / `PicoJoystickProvider(input_provider, *, deadzone, max_stick_scale, max_age_s)` / `LatestSubscriber(endpoint, topic)` / `SnapshotPacket`。
- Produces（Task 8/9 依赖的 worker 属性与方法签名）：
  - `RobotMode.VELOCITY = "velocity"`
  - `self.estop: EstopController`、`self._velocity_policy`、`self._velocity_obs_builder`、`self._velocity_cmd`（None = 栈未配置）、`self._velocity_last_action: np.ndarray`
  - `self._vel_joint_vel_limit: float`、`self._vel_tilt_graceful_rad: float`、`self._vel_tilt_damping_rad: float`、`self._mocap_entry_enabled: bool`、`self._velocity_cmd_logger: VelocityCmdLogger`、`self._controller_proxy`
  - `_build_velocity_stack(command_cfg: dict, *, reader_factory=None) -> None`
  - 配置键：`command.provider == "merged_bsi"` 触发构建；`safety.joint_vel_limit/tilt_graceful_rad/tilt_damping_rad`；`mocap_entry_enabled`；`velocity_cmd_log.path`；`command.restrict.forward_only.max_lin_x`。

- [x] **Step 1: 写失败测试**

```python
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
```

- [x] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_sim2real_velocity_mode.py -v`
Expected: FAIL（`RobotMode.VELOCITY` 不存在 + `_build_velocity_stack` 缺失）

- [x] **Step 3: 最小实现（runtime.py 四处）**

(a) `RobotMode` 加成员：

```python
class RobotMode(Enum):
    IDLE = "idle"
    STANDING = "standing"
    MOCAP = "mocap"
    ARMS = "arms"
    POLICY = "policy"
    VELOCITY = "velocity"
    DAMPING = "damping"
```

(b) 模块 import 区（与既有 `from teleopit.sim2real.safety import Sim2RealSafetyManager` 同区）加：

```python
from teleopit.commands.bsi_factory import build_merged_bsi_provider
from teleopit.commands.forward_only import ForwardOnlyCapProvider
from teleopit.commands.pico_joystick import PicoJoystickProvider
from teleopit.runtime.factory import build_velocity_policy_components
from teleopit.sim.estop import EstopController, EstopState
from teleopit.sim2real.mp.cmd_log import VelocityCmdLogger
```

(`EstopState` 若与现有 import 冲突则并入既有行。)

(c) 模块级（`_HandSnapshotProxy` 旁）加：

```python
class _ControllerSnapshotProxy:
    """Feed PicoJoystickProvider from the CONTROLLER_TOPIC ZMQ stream.

    The pico worker publishes SnapshotPacket(snapshot=<controller snapshot>);
    PicoJoystickProvider only needs get_controller_snapshot() returning the
    latest snapshot object (.left/.right/.timestamp_s), mirroring the sim-side
    direct-provider access (bsi-realhw-04 D2).
    """

    def __init__(self, sub: LatestSubscriber) -> None:
        self._sub = sub
        self._snapshot: Any = None

    def poll(self) -> None:
        packet = self._sub.recv_latest()
        if isinstance(packet, SnapshotPacket):
            self._snapshot = packet.snapshot

    def get_controller_snapshot(self) -> Any | None:
        return self._snapshot
```

(d) `__init__` 在 `self._mocap_session = MocapSessionManager()` 之后插：

```python
        # BSI velocity stack (wayfinder bsi-realhw-04): assembled only when the
        # config carries a merged_bsi command section; without it the worker
        # behaves exactly as before.
        self.estop = EstopController()
        self._velocity_policy = None
        self._velocity_obs_builder = None
        self._velocity_cmd = None
        self._controller_proxy = None
        self._velocity_last_action = np.zeros(self.num_actions, dtype=np.float32)
        self._mocap_entry_enabled = bool(cfg_get(cfg, "mocap_entry_enabled", True))
        velocity_safety_cfg = cfg_get(cfg, "safety", {}) or {}
        self._vel_joint_vel_limit = float(
            cfg_get(velocity_safety_cfg, "joint_vel_limit", cfg_get(cfg, "joint_vel_limit", 10.0))
        )
        self._vel_tilt_graceful_rad = float(cfg_get(velocity_safety_cfg, "tilt_graceful_rad", 0.524))
        self._vel_tilt_damping_rad = float(cfg_get(velocity_safety_cfg, "tilt_damping_rad", 0.785))
        cmd_log_cfg = cfg_get(cfg, "velocity_cmd_log", {}) or {}
        self._velocity_cmd_logger = VelocityCmdLogger(cfg_get(cmd_log_cfg, "path", None))
        command_cfg = cfg_get(cfg, "command", None)
        if isinstance(command_cfg, dict) and str(command_cfg.get("provider", "")) == "merged_bsi":
            self._build_velocity_stack(dict(command_cfg))
```

(e) 新方法（`_build_policy_and_obs` 之后）：

```python
    def _build_velocity_stack(self, command_cfg: dict[str, Any]) -> None:
        """Assemble the in-process velocity command + policy stack (bsi-realhw-04 D2).

        Joystick half reads CONTROLLER_TOPIC; BSI half subscribes domain-0 DDS
        via the lazy bsi_dds import. All of it lives in THIS robot_control
        process — DDS silence decays to IDLE inside the merged provider, so no
        process isolation is needed.
        """
        self._velocity_policy, self._velocity_obs_builder = build_velocity_policy_components(
            self.cfg, PROJECT_ROOT
        )
        self._controller_proxy = _ControllerSnapshotProxy(
            LatestSubscriber(self.endpoints.controller_pub, CONTROLLER_TOPIC)
        )
        joystick_cfg = dict(command_cfg.get("joystick", {}) or {})
        joystick = PicoJoystickProvider(
            self._controller_proxy,
            deadzone=float(joystick_cfg.get("deadzone", 0.15)),
            max_stick_scale=dict(joystick_cfg.get("max_stick_scale", {}) or {}) or None,
            max_age_s=float(joystick_cfg.get("max_age_s", 0.5)),
        )
        self._velocity_cmd = build_merged_bsi_provider(
            joystick, dict(command_cfg.get("bsi", {}) or {})
        )
        restrict_cfg = command_cfg.get("restrict", None)
        if isinstance(restrict_cfg, dict) and "forward_only" in restrict_cfg:
            forward_cfg = dict(restrict_cfg["forward_only"] or {})
            self._velocity_cmd = ForwardOnlyCapProvider(
                self._velocity_cmd, max_lin_x=float(forward_cfg.get("max_lin_x", 0.3))
            )
```

注意：`__init__` 里 `self.estop` 也可被既有代码占用名——若重名改用 `self.velocity_estop`（当前代码无 estop 属性，可直接用）。

- [x] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_sim2real_velocity_mode.py -v`
Expected: PASS（3 测）

- [x] **Step 5: 回归（worker 全套）+ 提交**

Run: `python -m pytest tests/test_sim2real_multiprocess.py -q`
Expected: 全 PASS（`__init__` 新增段不破坏既有构造路径——无 command 段时零副作用）

```bash
git add teleopit/sim2real/mp/runtime.py tests/test_sim2real_velocity_mode.py
git commit -m "feat(mp): assemble in-process velocity stack — RobotMode.VELOCITY, merged_bsi provider, controller-topic joystick (bsi-realhw-04)"
```

---

### Task 8: 模式机——TOGGLE_VELOCITY/ESTOP/MUTE 事件 + 进出门 + Y 门

**Files:**
- Modify: `teleopit/sim2real/mp/runtime.py`：`_handle_mocap_control_events`（2419）、`_handle_transitions` STANDING 分支（1497-1507）、`_enter_standing`（2199，模式集合常量化）、新方法 `_enter_velocity` / `_exit_velocity_to_standing`、`shutdown`（1416）
- Test: `tests/test_sim2real_velocity_mode.py`（追加）

**Interfaces:**
- Consumes: Task 1 `TOGGLE_VELOCITY` 事件、Task 3 `EstopController.latch/toggle`、Task 7 worker 属性。
- Produces（Task 9 依赖）：`_enter_velocity()`（仅 STANDING 且未锁存且栈已配置；reset 栈 + 播种 last_action）、`_exit_velocity_to_standing()`（= X 语义，走 `_enter_standing`）；模块常量 `_EXIT_RAMP_MODES = (MOCAP, ARMS, POLICY, VELOCITY)`、`_DEBUG_MODES = (STANDING, MOCAP, ARMS, POLICY, VELOCITY)`。

- [x] **Step 1: 写失败测试（追加）**

```python
from teleopit.inputs.realtime_packet import ControlEvent, ControlEventType
from teleopit.sim.estop import EstopState


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
```

（`_handle_transitions` STANDING 分支还会走 `self.remote.start`？不会——start 仅 IDLE/DAMPING 分支读。STANDING 只读 Y 与 reentry。）

- [x] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_sim2real_velocity_mode.py -v`
Expected: 新增 8 测 FAIL（事件被丢弃 / 方法缺失）

- [x] **Step 3: 最小实现（runtime.py 五处）**

(a) `_handle_mocap_control_events` 加三个分支（TOGGLE_ARMS 块之前）：

```python
            if event.event_type == ControlEventType.TOGGLE_VELOCITY:
                if self.mode == RobotMode.VELOCITY:
                    self._exit_velocity_to_standing()
                else:
                    self._enter_velocity()
                continue
            if event.event_type == ControlEventType.TOGGLE_ESTOP:
                result = self.estop.toggle(in_velocity=(self.mode == RobotMode.VELOCITY))
                operator_logger.info("Pico estop toggle: %s", result)
                continue
            if event.event_type == ControlEventType.TOGGLE_MUTE:
                if self._velocity_cmd is not None:
                    muted = self._velocity_cmd.toggle_mute()
                    if muted is not None:
                        operator_logger.info("BSI mute: %s", "muted" if muted else "live")
                continue
```

(b) 新方法（`_build_velocity_stack` 之后）：

```python
    def _enter_velocity(self) -> None:
        """STANDING -> VELOCITY (Pico X, bsi-realhw-04 D1).

        Entry gate mirrors the sim V key: only from STANDING, refused while
        the estop latch holds (05: E is the only release key — damping
        entries latch it), and needs the velocity stack configured.
        """
        if self._velocity_policy is None:
            operator_logger.warning("TOGGLE_VELOCITY ignored: velocity stack not configured")
            return
        if self.mode != RobotMode.STANDING:
            operator_logger.warning(
                "TOGGLE_VELOCITY ignored: entry only from STANDING (now %s)", self.mode.value
            )
            return
        if self.estop.state != EstopState.INACTIVE:
            operator_logger.warning(
                "TOGGLE_VELOCITY refused: estop latched — press E (left grip) to release"
            )
            return
        self._velocity_obs_builder.reset()
        self._velocity_policy.reset()
        self._velocity_cmd.reset()
        # Action-continuity seeding (sim begin_velocity_handoff semantics):
        # the first velocity observation must not see a zero action jump.
        self._velocity_last_action = self._last_action.copy()
        self.mode = RobotMode.VELOCITY
        operator_logger.info("mode -> VELOCITY")

    def _exit_velocity_to_standing(self) -> None:
        """VELOCITY -> STANDING via the standing-return ramp (sim X semantics)."""
        operator_logger.info("velocity exit -> STANDING (ramp)")
        self._enter_standing()
```

(c) `_handle_transitions` STANDING 分支 Y 门：

```python
        elif self.mode == RobotMode.STANDING:
            reentry_request = self._mocap_reentry_armed and self.remote.Y.pressed
            if self._mocap_entry_enabled and (self.remote.Y.on_pressed or reentry_request):
                self._mocap_entry_requested = True
```

（后续 `if self._mocap_entry_requested:` 块不动——门关时 request 永不置位。）

(d) `_enter_standing` 模式集合常量化（行为等价重构 + 纳入 VELOCITY）。模块级常量（`RobotMode` 类之后）：

```python
# Modes already inside the local-ONNX debug loop; entering STANDING from one
# of these needs no debug-mode re-entry or joint locking.
_DEBUG_MODES = (RobotMode.STANDING, RobotMode.MOCAP, RobotMode.ARMS, RobotMode.POLICY, RobotMode.VELOCITY)
# Active modes whose exit ramps the standing reference and kp gains.
_EXIT_RAMP_MODES = (RobotMode.MOCAP, RobotMode.ARMS, RobotMode.POLICY, RobotMode.VELOCITY)
```

`_enter_standing` 内四个元组逐一替换：`already_in_debug = self.mode in _DEBUG_MODES`；lock 分支 `if prev_mode not in _DEBUG_MODES:`；两处 `prev_mode in (RobotMode.MOCAP, RobotMode.ARMS, RobotMode.POLICY)` → `prev_mode in _EXIT_RAMP_MODES`。

(e) `shutdown()` 的模式元组（1416 行）加 `RobotMode.VELOCITY`：

```python
        if self.mode in (
            RobotMode.STANDING, RobotMode.MOCAP, RobotMode.ARMS, RobotMode.POLICY, RobotMode.VELOCITY
        ):
```

- [x] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_sim2real_velocity_mode.py tests/test_sim2real_multiprocess.py -v`
Expected: 全 PASS（`_enter_standing` 重构不改变既有模式行为）

- [x] **Step 5: 提交**

```bash
git add teleopit/sim2real/mp/runtime.py tests/test_sim2real_velocity_mode.py
git commit -m "feat(mp): VELOCITY mode machine — X/grip event handling, latch-gated entry, mocap Y gate, exit ramp (bsi-realhw-04/05/07)"
```

---

### Task 9: `_velocity_step` + 安全判定接线 + damping 锁存

**Files:**
- Modify: `teleopit/sim2real/mp/runtime.py`：主循环 `run()` 模式分发（1394-1399）、新方法 `_velocity_step`、`_enter_damping`（2341，首行加锁存）
- Test: `tests/test_sim2real_velocity_mode.py`（追加）

**Interfaces:**
- Consumes: Task 4 `velocity_safety_verdict`、Task 3 `estop.apply/consume_exit_request/latch`、Task 7 栈属性、Task 8 `_exit_velocity_to_standing`。
- Produces: `_velocity_step() -> None`——每 policy step：`proxy.poll() → get_cmd → estop.apply → 安全判定（damping/standing 分岔）→ obs.build(state, cmd, velocity_last_action) → compute_action → clip → safety.send_positions → cmd 日志`。estop 渐0 完成后自动走退出路径。

- [x] **Step 1: 写失败测试（追加）**

```python
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
```

- [x] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_sim2real_velocity_mode.py -v`
Expected: 新增 6 测 FAIL（`_velocity_step` 不存在）

- [x] **Step 3: 最小实现（runtime.py 三处）**

(a) 主循环分发（1394-1399 的 elif 链）加一行：

```python
                else:
                    self._handle_transitions()
                    if self.mode == RobotMode.STANDING:
                        self._standing_step()
                    elif self.mode in (RobotMode.MOCAP, RobotMode.ARMS):
                        self._mocap_step()
                    elif self.mode == RobotMode.POLICY:
                        self._high_level_policy_step()
                    elif self.mode == RobotMode.VELOCITY:
                        self._velocity_step()
```

（保持原有结构，仅在 POLICY 分支后追加 VELOCITY 分支。）

(b) 新方法（`_exit_velocity_to_standing` 之后）：

```python
    def _velocity_step(self) -> None:
        """One policy step of real-robot VELOCITY mode (bsi-realhw-04/05).

        Order matches the sim step: merged cmd -> estop suppression -> safety
        verdict -> ONNX -> LowCmd. The estop's 0.3s exponential decay runs
        inside apply(); when the ramp completes, consume_exit_request drives
        the X-exit path into STANDING (NOT damping — bsi-dds-03 semantics).
        """
        if self._controller_proxy is not None:
            self._controller_proxy.poll()
        state = self.robot.get_state()
        cmd = np.asarray(self._velocity_cmd.get_cmd(), dtype=np.float32).reshape(-1)
        cmd = self.estop.apply(cmd)

        verdict = velocity_safety_verdict(
            state,
            joint_vel_limit=self._vel_joint_vel_limit,
            tilt_graceful_rad=self._vel_tilt_graceful_rad,
            tilt_damping_rad=self._vel_tilt_damping_rad,
        )
        if verdict == "damping":
            self._enter_damping()
            return
        if verdict == "standing":
            self._exit_velocity_to_standing()
            return
        if self.estop.consume_exit_request():
            self._exit_velocity_to_standing()
            return

        obs = self._velocity_obs_builder.build(state, cmd, self._velocity_last_action)
        action = self._velocity_policy.compute_action(obs)
        target_dof_pos = self._safety.clip_to_joint_limits(
            self._velocity_policy.get_target_dof_pos(action)
        )
        self._safety.send_positions(target_dof_pos)
        self._velocity_last_action = np.asarray(action, dtype=np.float32).reshape(-1)
        self._velocity_cmd_logger.log(
            cmd=cmd,
            estop_state=self.estop.state.value,
            mode=self.mode.value,
            muted=bool(getattr(self._velocity_cmd, "muted", False)),
        )
```

import 区补：`from teleopit.sim2real.safety import Sim2RealSafetyManager, velocity_safety_verdict`（并入既有行）。

(c) `_enter_damping` 首段（`_stop_high_level_policy_session` 调用之前）加锁存（05 统一规则）：

```python
    def _enter_damping(self) -> None:
        # bsi-realhw-05: any DAMPING entry (L1+R1 / joint-vel / tilt fall line)
        # locks VELOCITY re-entry; E (Pico left grip) is the only release key.
        self.estop.latch()
        if bool(getattr(self, "high_level_policy_enabled", False)) and (
```

- [x] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_sim2real_velocity_mode.py -v`
Expected: 全 PASS（含 Task 7/8 的 11 测）

- [x] **Step 5: 全量回归 + 提交**

Run: `python -m pytest tests/ -q`
Expected: 全 PASS（457+ 新增）

```bash
git add teleopit/sim2real/mp/runtime.py tests/test_sim2real_velocity_mode.py
git commit -m "feat(mp): _velocity_step — merged cmd + estop decay + dual-tilt/joint-vel verdicts + damping-latch (bsi-realhw-05)"
```

---

### Task 10: 配置——`pico4_sim2real_bsi.yaml`（L3）与 `_l2` 预设

**Files:**
- Create: `teleopit/configs/pico4_sim2real_bsi.yaml`
- Create: `teleopit/configs/pico4_sim2real_bsi_l2.yaml`
- Test: `tests/test_cli_entrypoints.py`（追加两测）

**Interfaces:**
- Consumes: Task 1/2 的 input 键（velocity_button/estop_button/estop_grip_threshold/mute_button）、Task 7 的 command/safety/mocap_entry_enabled/velocity_cmd_log 键、既有组 `controller@controllers.velocity: velocity`、基线 `pico4_sim2real`。
- Produces: 两个可用 `--config-name`。L2 相对主配置仅三处覆盖：restrict 段、bsi speeds forward 降 0.3、velocity_cmd_log 文件名带 `_l2`。

- [x] **Step 1: 写失败测试（追加到 tests/test_cli_entrypoints.py，复用 `_CONFIG_DIR`）**

```python
# ── pico4_sim2real_bsi.yaml (bsi-realhw Phase B real VELOCITY mode) ────────


def test_pico4_sim2real_bsi_config_loads() -> None:
    from hydra import compose, initialize_config_dir

    with initialize_config_dir(config_dir=str(_CONFIG_DIR), version_base=None):
        cfg = compose(config_name="pico4_sim2real_bsi")
    assert str(cfg.command.provider) == "merged_bsi"
    assert str(cfg.input.velocity_button) == "X"
    assert str(cfg.input.estop_button) == "left_grip"
    assert float(cfg.safety.joint_vel_limit) == 10.0
    assert float(cfg.safety.tilt_graceful_rad) == 0.524
    assert float(cfg.safety.tilt_damping_rad) == 0.785
    assert bool(cfg.mocap_entry_enabled) is False
    assert cfg.controllers.velocity.policy_path is not None
    assert float(cfg.real_robot.kp_real[0]) == 40.2  # 继承自 pico4_sim2real 基线


def test_pico4_sim2real_bsi_l2_config_restricts_forward() -> None:
    from hydra import compose, initialize_config_dir

    with initialize_config_dir(config_dir=str(_CONFIG_DIR), version_base=None):
        cfg = compose(config_name="pico4_sim2real_bsi_l2")
    assert float(cfg.command.restrict.forward_only.max_lin_x) == 0.3
    assert float(cfg.command.bsi.speeds.forward) == 0.3
```

- [x] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_cli_entrypoints.py -k bsi_sim2real -v`（匹配名 `test_pico4_sim2real_bsi*`）
Expected: FAIL（config 不存在，compose 报错）

- [x] **Step 3: 写配置**

`teleopit/configs/pico4_sim2real_bsi.yaml`：

```yaml
# BSI real-hardware VELOCITY mode (wayfinder bsi-realhw 04/05/07).
# Launch (dds-probe env on the robot-control machine, e.g. onboard Orin):
#   python scripts/run/run_sim2real.py --config-name pico4_sim2real_bsi
# Optional bench publisher (another terminal, dds-probe env):
#   python -m bsi_dds.cli mock --script "idle:3,forward:5,left:3,idle:3"
# Keys: Pico X=enter/exit VELOCITY, left grip=estop, Y=mute;
#       G1 remote (caretaker) L1+R1=damping, START=recover, Y=mocap (gated OFF here).
defaults:
  - pico4_sim2real
  - controller@controllers.velocity: velocity
  - _self_

viewers: "none"

input:
  velocity_button: X          # STANDING -> VELOCITY -> STANDING (operator)
  estop_button: left_grip     # analog threshold estop (operator, thumb stays on stick)
  estop_grip_threshold: 0.6
  mute_button: Y              # BSI mute (source control)

# bsi-realhw-07: caretaker holds the G1 remote; Y must not hijack a BSI walk.
mocap_entry_enabled: false

safety:
  joint_vel_limit: 10.0       # bsi-realhw-05 scalar; per-joint array before L3
  tilt_graceful_rad: 0.524    # 30 deg -> graceful 0.3s ramp back to STANDING
  tilt_damping_rad: 0.785     # 45 deg -> immediate damping

velocity_cmd_log:
  path: data/velocity_cmd.jsonl   # 07 timing-metrics source; null to disable

command:
  provider: merged_bsi
  joystick:
    deadzone: 0.15
    max_age_s: 0.5
    max_stick_scale: {lin_vel_x: 0.5}   # 1.0 m/s cap (Phase A envelope)
  bsi:
    domain_id: 0
    silence_timeout_s: 1.0
    debounce_packets: 3
    idle_debounce_packets: 2
    alpha: 0.3
    speeds: {forward: 0.6, turn: 0.6}
```

`teleopit/configs/pico4_sim2real_bsi_l2.yaml`：

```yaml
# L2 caretaker slow gate (bsi-realhw-07): hoist on, all channels forward-only
# <=0.3 m/s, lateral/turn forced zero (BSI left/right intents suppressed).
defaults:
  - pico4_sim2real_bsi
  - _self_

velocity_cmd_log:
  path: data/velocity_cmd_l2.jsonl

command:
  restrict:
    forward_only:
      max_lin_x: 0.3
  bsi:
    speeds: {forward: 0.3, turn: 0.3}
```

- [x] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_cli_entrypoints.py -v`
Expected: 全 PASS（含既有配置测试——defaults 链不破坏 `pico4_sim2real` 本身）

- [x] **Step 5: 全量回归 + 提交**

Run: `python -m pytest tests/ -q`
Expected: 全 PASS

```bash
git add teleopit/configs/pico4_sim2real_bsi.yaml teleopit/configs/pico4_sim2real_bsi_l2.yaml tests/test_cli_entrypoints.py
git commit -m "feat(configs): pico4_sim2real_bsi + L2 preset — real BSI walk config (bsi-realhw-05/07)"
```

---

### Task 11: 收尾——全量验证 + plan 勾选归档

**Files:**
- Modify: 本 plan 文件（勾选执行完的步骤框）

- [x] **Step 1: 全量测试**

Run: `python -m pytest tests/ -q`
Expected: 全 PASS，零 skip 新增（cyclonedds 相关零导入）

- [x] **Step 2: 冒烟检查 import 面（teleopit env 无 DDS 泄漏）**

Run: `python -c "import teleopit.sim2real.mp.runtime"`
Expected: 无 ImportError（若 `build_merged_bsi_provider` 顶层 import 触发 bsi_dds，回到 Task 7 修 import——bsi_factory 顶层只 import teleopit.commands.*，不应发生）

- [x] **Step 3: 提交 plan 勾选**

```bash
git add docs/superpowers/plans/2026-08-21-bsi-realhw-velocity-mode.md
git commit -m "docs(plan): check off bsi-realhw velocity-mode implementation"
```

---

## Self-Review 结论

- **Spec 覆盖**：04（D1 模式键→Task 1/8；D2 进程内指令源→Task 7；D3 配置/入口→Task 10；策略复用→Task 7 `build_velocity_policy_components`）；05（阈值→Task 4/9；两级急停→Task 2/3/9；锁存规则→Task 3/8/9；恢复 SOP 是运行时既有能力 START→STANDING，无代码需求）；07（L2 限制→Task 5/10；cmd 日志→Task 6/9；键位→Task 1/2/10；Y 门→Task 8/10）。per-joint 限速数组明确**不在本计划**（05 票面：L3 前另行交付）。
- **占位符**：无 TBD/「适当处理」类步骤；所有代码块完整可写。
- **类型一致性**：`velocity_safety_verdict` 签名 Task 4 定义 = Task 9 调用；`_build_velocity_stack` 属性名 = Task 8/9 消费；`ForwardOnlyCapProvider(inner, *, max_lin_x)` = Task 7 装配；`VelocityCmdLogger.log(*, cmd, estop_state, mode, muted)` = Task 9 调用；`estop_button`/`velocity_button` 配置键 = Task 2 接线 = Task 10 yaml。
