---
id: bsi-realhw-05
title: "真机安全包络与分层急停落地"
labels: [wayfinder:grilling]
status: closed
assignee: "claude/main"
blocked-by: [bsi-realhw-04]
created: 2026-08-21
---

## Question

Q5 定两级：E 键 0.3s 渐0→站定（锁存照搬）+ 硬件层立即阻尼做底。待决：

1. **硬件层载体**：物理急停钮（有无、类型）/ Unitree 自带保护停 / `_enter_damping` 各自何时触发、谁操作、在哪里。
2. **阈值真机值**：joint-vel 12.0 / tilt 1.0 rad 是 sim 值——真机收紧到多少；超速/超限降级行为（STOP damping vs 回 STANDING）。
3. **跌倒应对**与恢复流程。

产出：安全参数表 + 行为规格（进 07 验收规格与后续 plan）。

## Resolution

**2026-08-21 grilling 两轮九问定案（Q1-Q9）**：

**安全参数表（真机）**

| 参数 | 真机值 | 触发行为 |
|---|---|---|
| joint-vel 上限 | 10.0 rad/s 单一标量（per-joint 数组留 plan 按 G1 限速表填，L3 前生效） | 立即 damping |
| tilt 优雅线 | 30°（0.524 rad） | 0.3s 渐0 → 回 STANDING |
| tilt 跌倒线 | 45°（0.785 rad） | 立即 damping |
| 检查装设 | mp VELOCITY 分支每 policy step（50Hz）查，仅 VELOCITY 模式（照 sim；STANDING 不查——mimic+kp ramp 自稳） | — |
| E 键急停 | `EstopController` 照搬：0.3s 指数渐0→STANDING、锁存、同键解锁、锁存期拒入 VELOCITY | 优雅层 |

**两级急停与角色分置**：优雅层 = E 键（Pico，操作员）；硬件层 = L1+R1（G1 遥控器，**看护人持有**）→ `_enter_damping`（`runtime.py:1387` 已接线，零改动）。G1 本体无其他物理急停钮。角色分置：G1 遥控器→看护人，Pico→操作员。

**统一锁存规则（核心决策）**：凡进过 DAMPING（L1+R1 / joint-vel 超限 / tilt≥45°），VELOCITY 一律上锁，**E 是唯一解锁键**；优雅路径（X 退出、tilt<45° 回站）不锁。实现 = damping 入口顺手置 estop 锁存位。

**跌倒应对**：检测 = tilt 双线（30°/45°）+ 看护人目视 + L1+R1；root-height 真机不可用（LowState 无 base_pos，04 已证），sim `min_root_height` 降为纯指标。跌倒中（≥45°）= damping 瘫软落地。恢复 SOP 五步：人工扶正 → 遥控器 START（`runtime.py:1692`，DAMPING→STANDING，kp ramp 2s）→ 操作员按 E 解锁 → TOGGLE_VELOCITY。

**喂 07**：L1 门 E 急停行为行、跌倒保护行为行可直接写；L2 看护配置 = 看护人持 G1 遥控器。**喂 plan**：TOGGLE_ESTOP 事件接通（与 TOGGLE_VELOCITY 同 CONTROL_EVENTS_TOPIC 管线）、`Sim2RealSafetyManager.check_joint_velocity_safety` 装进 mp VELOCITY 分支、tilt 检查新增（真机 RobotState 有 quat）、damping 入口置锁存位、per-joint 限速数组（L3 前）。
