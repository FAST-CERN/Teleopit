---
id: bsi-realhw-03
title: "真实 BSI 流采数量化与参数复校"
labels: [wayfinder:task]
status: closed
assignee: "user"
blocked-by: [bsi-realhw-02]
created: 2026-08-21
---

## Question

在 02 的活流上 `echo` 抓包录一段（数分钟、覆盖各意图段与人静止段），量化（Q6=b）：

- 端到端延迟与发包节奏；孤包/误分类率（意图流中插错类别的占比）；同一意图持续包数分布；置信度分布。

对照 mock 假设（10Hz 理想流）判定：前进/转弯 0.6、α0.3、防抖 3/2 包、静默 1.0s——沿用或重定。若重定：回仿真复跑 checklist 相关段（回放复用 mock 脚本 token 格式）验证后回填。

产出：量化数据 + 参数决定（Resolution 记录；参数变更落配置+测试走后续 plan）。

## Resolution

**2026-08-21 user-reported 通过**：真实流量化复核完成，未报参数调整需求——前进/转弯 0.6、α0.3、防抖 3/2、静默 1.0s 按现值沿用。量化明细未落盘（真机联调若暴露偏差，按 map 雾区「整定票」预案回填）。仿真收口门（01/02/03）全关，04（真机 VELOCITY 模式设计）解锁。
