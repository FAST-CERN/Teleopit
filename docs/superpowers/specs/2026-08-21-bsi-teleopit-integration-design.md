# BSI 脑控离散指令 Teleopit 仿真接入 — 设计文档（第一阶段）

日期：2026-08-21
状态：已批准（分节过审）
输入：wayfinder map `docs/wayfinder/2026-08-21-bsi-dds/`（七票全决，规格单一来源 = 各 ticket Resolution）

## 目的与范围

把 BSI 四态离散指令（前/左转/右转/idle）接入 Teleopit pico4 仿真 VELOCITY 模式，与摇杆同源融合。**本设计覆盖第一阶段（数据层闭环，无 DDS）**；第二阶段（接线+键位+真 DDS 联调）在新对话执行，handoff 缝见末节。

阶段划分（brainstorm 已锁）：

- **第一阶段**：BsiTwistProvider（防抖/平滑/静默/哑音，意图源抽象注入）+ MergedTwistProvider（整包互斥）+ EstopController（会话层锁存+渐0）+ 全部 pytest 指标门。**零 cyclonedds import，teleopit env 直跑。**
- **第二阶段**：`command.provider: merged_bsi` 配置分支、DDS 意图源（dds-probe env）、键位接线（E/C/menuButton/左手Y）、H 帮助文本、桌面 14 行 checklist（真 mock CLI 联调）。

第一阶段验收 = 07 票指标门全套 pytest 过 + `run_velocity_sim.py` headless 冒烟（steps=50）不红 + 现有 457 测试零新红。

## 组件

```
teleopit/commands/bsi_twist.py      # BsiTwistProvider + IntentSource 抽象
teleopit/commands/merged_twist.py   # MergedTwistProvider
teleopit/sim/estop.py               # EstopController（锁存+渐0）
tests/test_bsi_twist.py             # provider 指标门
tests/test_merged_twist.py          # 融合指标门
tests/test_estop.py                 # 急停指标门
```

### IntentSource（bsi_twist.py 内 Protocol）

`poll() -> DiscreteIntent | None`——返回当前意图枚举值（0..3 int）+ 收包单调时间戳；None = 无新包。第二阶段 DDS 订阅线程实现它；第一阶段 `ScriptedIntentSource`（脚本化序列+注入时钟）实现它。BsiTwistProvider 只依赖此抽象——provider 层零 DDS 依赖。未知枚举值由源层归 IDLE（fail-safe，同 bsi_dds.subscriber 惯例）。

### BsiTwistProvider（CommandProvider 实现）

管道（每 get_cmd 一次）：

1. `source.poll()` → 无包则沿用上次意图做包年龄判定
2. **静默**：最新收包时刻距今 >1.0s → 意图 IDLE（清防抖计数）
3. **防抖**：连续 N 包同新标签才切换意图；N=3（切换）/ N=2（进 IDLE，停优先）
4. **哑音**：`toggle_mute()` 强制意图 IDLE（订阅不断），`muted` 属性可查
5. **映射**：FORWARD→lin_x 0.6；TURN_LEFT→ang_z +0.6；TURN_RIGHT→ang_z −0.6（原地转）；IDLE→0
6. **平滑**：指数 `out += alpha*(target-out)`，alpha 0.3 独立参数，骨架同 KeyboardTwistProvider

时钟全部注入（`clock=` 构造参数，同 PicoJoystickProvider 惯例）。`reset()` 清防抖计数+平滑器（哑音保持——操作者状态）；`close()` 关意图源。

### MergedTwistProvider（CommandProvider 实现）

构造接任意两个 CommandProvider（主=摇杆、副=BSI，不绑 Pico input_provider——bvh 通路未来可复用）。`get_cmd`：主源 `get_cmd()` 非零向量 → 整包取主；否则整包取副。**不逐轴叠加**（避免脑控前进+手控转向复合意图）。无额外切换 ramp。`reset()`/`close()` 传递两子源。

### EstopController（teleopit/sim/estop.py）

会话级急停状态（票 03）：

- **锁存标志** + **渐0 状态机**：`toggle()` 触发 → 0.3s 指数收敛到零 → 请求 exit_velocity（一次性）
- 会话钩子：`estop.apply(cmd)` 在 merged get_cmd 之后调用——锁存时覆盖为零、渐0 期返回衰减值、未启用纯 passthrough（与 master 逐 bit 一致）
- 解锁：同键再按 `toggle()`；回 STANDING 自动解锁
- STANDING 下触发：无操作（反馈 ignored，防死锁）
- 渐0 期拦截 X 重复触发；与 Esc/STOP（damping）并存，两者都触发时 STOP 优先

## 数据流（VELOCITY 步进，50Hz）

```
pico4 bridge ──► PicoJoystickProvider.get_cmd ──┐
                                                ├─► MergedTwistProvider.get_cmd
IntentSource.poll ─► BsiTwistProvider.get_cmd ──┘         │
（静默→防抖→哑音→映射→平滑）                              ▼
                                              EstopController.apply(cmd)   ← 会话钩子
                                                           │ 非急停原样通过
                                                           ▼
                                              velocity_step（既有，零改动）
```

第一阶段无线程（ScriptedIntentSource 同步 poll）；第二阶段 DDS 源才起后台线程（reader callback → 缓存最新意图+时间戳，get_cmd 读缓存）。

## 配置 schema（第二阶段接线用，一阶段先定形）

```yaml
command:
  provider: merged_bsi
  joystick: {...}          # 照旧
  bsi:
    silence_timeout_s: 1.0
    debounce_packets: 3       # 切换门槛；IDLE 进入 = max(2, N-1)
    alpha: 0.3
    speeds: {forward: 0.6, turn: 0.6}
    domain_id: 0
```

不配 `merged_bsi` → 不 import bsi_dds、不建 BSI provider（默认路径零变化）。

## 错误处理与边界

| 故障 | 行为 | 依据 |
|---|---|---|
| 无包/静默 >1s | IDLE → twist 0；恢复自动恢复 | 票 01/02 |
| 未知枚举值 | 源层归 IDLE | 票 01 |
| 误标签孤包 | 防抖滤除 | 票 02 |
| 哑音中 FORWARD | 强制 IDLE，解除下周期恢复 | 票 05 |
| 急停锁存中任何源 | 会话层覆盖为零 | 票 03 |
| cyclonedds/bsi_dds 缺失 | 仅 merged_bsi 分支 import 报错（指路 dds-probe env）；默认路径零 import | 票 04 |

边界：防抖计数跨静默清零（静默是链路事件非标签事件）；哑音+静默叠加归同一定义无需特判；provider 契约同步无异常（读失败返回零，同摇杆/键盘惯例）。

## 测试（pytest 指标门 = 票 07 表自动化）

`test_bsi_twist.py`：响应≤1.0s 到半幅（防抖 0.3s+平滑收敛）；自然减速 ≤1.5s（→<0.1 m/s）；静默 1s 开始衰减/1.5s 全零；孤包滤除；IDLE 2 包切换；哑音即时生效/解除恢复；四态映射精确断言；未知值 fail-safe。

`test_merged_twist.py`：整包互斥（摇杆非零取主、零取副）；抢夺 ≤2 get_cmd 周期。

`test_estop.py`：急停减速 ≤0.8s；锁存抑制全源；同键 toggle 解锁；STANDING 触发无操作；渐0 期拦截 X、完成请求 exit 一次。急停测试在 EstopController 单元级测（不建完整会话）——会话钩子的端到端（键位→estop→exit_velocity）在第二阶段集成测覆盖。

回归：现有 457 测试零触碰（新文件+会话最小缝），快套无新红；headless 冒烟 steps=50；estop 未启用纯 passthrough。

## Handoff 边界（第二阶段输入）

spec + 第一阶段 plan 完成后新对话接手：merged_bsi 配置分支、DDS 意图源实现 IntentSource（dds-probe env：`C:/Users/user/.conda/envs/dds-probe/python.exe`）、键位接线（键盘 E/C + pico 右 menuButton/左手Y）、H 帮助、桌面 14 行 checklist（mock CLI 联调）。一阶段的 IntentSource 抽象与 estop 钩子即 handoff 缝——二阶段零返工点。
