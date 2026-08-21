---
id: bsi-realhw-05
title: "真机安全包络与分层急停落地"
labels: [wayfinder:grilling]
status: open
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
