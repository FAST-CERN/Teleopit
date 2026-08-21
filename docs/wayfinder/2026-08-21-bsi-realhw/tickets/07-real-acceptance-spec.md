---
id: bsi-realhw-07
title: "L1-L3 分级验收规格（真机 BSI locomotion）"
labels: [wayfinder:grilling]
status: open
assignee: ""
blocked-by: [bsi-realhw-04, bsi-realhw-05]
created: 2026-08-21
---

## Question

Q7 定分级安全门形态。待决细则：

1. **L1 静态站立安全门**：站立下 E 急停（渐0 + 锁存/解锁）、跌倒保护行为——观察行与通过线。
2. **L2 看护慢速门**：降速幅值（如 0.3 m/s 级？）、仅 forward/idle、看护配置——观察行与通过线。
3. **L3 自由四态门**：前/左/右/idle 穿场 + 摇杆抢夺/回零交还 + 静默 1s 站住——观察行与通过线。
4. **可日志测时序指标**（意图→速度响应、急停耗时）与记录方式；**失败处置**（退级重试规则）。

产出：三级验收规格表（真机执行在后续 plan/硬件会话，不在本图）。
