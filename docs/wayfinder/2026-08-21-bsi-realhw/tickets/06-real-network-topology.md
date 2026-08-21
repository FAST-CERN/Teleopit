---
id: bsi-realhw-06
title: "真机运行拓扑确认（运行位置 / DDS 网络 / 接口绑定）"
labels: [wayfinder:task]
status: open
assignee: ""
blocked-by: []
created: 2026-08-21
---

## Question

桌面/网络工作，不碰机器人本体：

1. **运行位置**：mp 运行时跑哪——机载 Orin vs 拖链 PC（核查现有 sim2real 部署惯例 + 决定 BSI 场景的运行位；BSI 订阅进程跟随运行位）。
2. **DDS/网络拓扑**：解码器机器 →（domain 0）→ 控制机；`g1_bridge_sdk` 走机器人自身总线——画清谁在哪发/订什么。
3. **接口绑定验证**：在目标机器上复用 `--interface` / `CYCLONEDDS_URI` 经验验证组播加入。

产出：拓扑图/文 + 验证记录（供 04 设计与后续 plan 引用）。
