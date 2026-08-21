---
id: bsi-dds-02
title: "四态指令 → cmd_vel 目标映射与平滑/防抖策略"
labels: [wayfinder:grilling]
status: closed
assignee: "claude/main"
blocked-by: [bsi-dds-01]
created: 2026-08-21
---

## Question

四态标签流如何变成 VELOCITY 模式的目标 twist？

- **幅值**：前 = lin_x 多少（摇杆封顶 1.0 m/s 已有标定，BSI 前进用满还是更保守）？左/右转 = ang_z 多少？转的时候带不带 lin_x（弧线行走 vs 原地转）？
- **平滑**：复用键盘 provider 的指数平滑骨架（alpha 0.3）还是独立参数？指令切换（前→左转）的目标跳变处理。
- **防抖**：BSI 误分类缓冲——连续 N 帧同标签才切换意图？窗口多长？idle 的进入/退出是否更宽松（安全侧）？
- **idle 语义**：目标 twist 渐 0 后 gait 归零（<0.1 范数）自然停步——确认这条链路即可，还是要显式停步信号？
- **超时**：超过多久没有新标签按 idle 处理（与 T1 的通信静默语义对齐）？

产出：映射表 + 平滑/防抖参数表，成为 Teleopit 侧 BsiTwistProvider 的规格（实现走后续 plan）。

## Resolution

**2026-08-21 grilling 锁定**：

**映射表**

| 意图 | lin_x | lin_y | ang_z | 说明 |
|---|---|---|---|---|
| IDLE (0) | 0 | 0 | 0 | 渐 0 → gait 范数 <0.1 自然停步（既有归零链路，无显式停步信号） |
| FORWARD (1) | 0.6 m/s | 0 | 0 | 恒速（脑控无幅值控制）；首次接入保守值（摇杆满推 1.0、策略上限 2.0），实测后可提 |
| TURN_LEFT (2) | 0 | 0 | +0.6 rad/s | 原地转（CCW，沿用 ang_z>0=左转符号约定） |
| TURN_RIGHT (3) | 0 | 0 | −0.6 rad/s | 原地转 |

四态互斥（同一时刻一个标签），转弯不带 lin_x——语义最干净、行为可预测、验收好写。

**平滑**：BSI provider 内置指数平滑，骨架同 `KeyboardTwistProvider`（alpha 0.3 起步、每 get_cmd 步进），参数独立可调，BSI 实测后单独整定。

**防抖**：意图切换需连续 **3 包**同新标签（10Hz 下 300ms 窗口）；**IDLE 进入只需 2 包**（安全侧不对称——停优先）；单包误分类被滤掉不动。参数可调；BSI 实测误分类率回填后重校（map 雾区「特性回填」预案）。

**超时**：静默 **1s** 归 idle——与 T1 协议静默语义同参数同源；实现为 provider 层判最新包年龄（get_cmd 时看时钟，不依赖 DDS deadline 回调），可注入时钟单测（同 PicoJoystickProvider 的 max_age_s 模式）。

**验收衔接**：0.6 > 0.5 记录线（velocity_session `_record_metrics`），跟踪误差 metric 门槛可直接复用；T7 验收 ticket 的响应时间指标以此表为目标。

**实现归属**：本表是 Teleopit 侧 `BsiTwistProvider` 的规格；编码走后续 superpowers plan（T4 接线架构定 provider 挂载位置）。
