---
id: bsi-dds-02
title: "四态指令 → cmd_vel 目标映射与平滑/防抖策略"
labels: [wayfinder:grilling]
status: open
assignee: ""
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
