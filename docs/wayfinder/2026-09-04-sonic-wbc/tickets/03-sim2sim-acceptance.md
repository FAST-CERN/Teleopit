---
id: 03-sim2sim-acceptance
title: "sim2sim 四线验收：指令跟踪 / 上身跟随 / 稳定裕度 / 主观"
labels: [wayfinder:prototype]
status: open
assignee: claude
blocked-by: ["02-sim2sim-harness"]
---

## Question

终点票：四线验收（数值线本票定稿）：

1. **指令跟踪**：cmd_vel（含斜向/原地转向）跟随误差线；
2. **上身跟随**：合成参考跟踪无发散/NaN/振荡，肘欠定不抖；
3. **稳定裕度**：锁腰 + RH56E2 配重下站立+行走 N 分钟不倒；失效注入（参考超龄/丢 tracker → hold 语义）后恢复无跳变；
4. **主观**：回放坐标冒烟段，MuJoCo viewer 中方向/幅度/手感可用。

过线 → 本图 CLOSED，产出 SONIC 接入快照（输入构造器 + 钳位 + 配置 + 指标基线）移交真机图。
