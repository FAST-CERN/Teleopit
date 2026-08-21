---
id: bsi-dds-07
title: "验收演示场景：mock BSI 序列驱动的量化指标与行为 checklist"
labels: [wayfinder:grilling]
status: open
assignee: ""
blocked-by: [bsi-dds-02, bsi-dds-04]
created: 2026-08-21
---

## Question

「仿真内跑通 BSI→G1 行走」的验收标准是什么？

- **场景脚本**：mock 发布器发一段指令序列（如 idle→前→左转→前→idle + 中途摇杆抢夺 + 急停触发），MuJoCo 观察行为正确性 checklist（类似 task #6 的 12 项 HMD gate，但这里是桌面仿真 gate）。
- **量化指标**（pytest 可测）：指令→速度响应时间（收到 FORWARD 到 lin_x 达 0.5×目标的耗时）；idle/急停的减速时间；摇杆抢夺延迟（摇杆非零到 BSI 被压制的帧数）；误标签注入后的行为（防抖生效，不切换意图）。
- **通过线**：参考 Phase A 验收（跟踪误差 0.35 m/s、hand-off 跳变 0.25 rad）与 task #6 gate 的宽严程度定。
- **mock 序列可复用性**：同一脚本将来真机 Phase B 回放（BSI 录制数据重放）要不要预留格式。

产出：验收 checklist + 指标表（进 ticket resolution），演示在后续 plan 实现完成后执行。
