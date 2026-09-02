---
id: 04-receiver-motion-parse
title: "pico_bridge 接收端：Motion 字段解析 + frame.trackers 暴露 + 录制扩展"
labels: [wayfinder:task]
status: open
assignee: ""
blocked-by: ["03-unity-motion-collection"]
---

## Question

`pc_receiver`（pico-bridge 仓库 Python 包，Teleopit 以 `pip install -e '.[pico4]'` 内嵌）跟上 03 定稿的 `Motion` 字段（AFK，TDD，本机 teleopit conda env）：

1. `protocol.py` 解析 `Motion` → 帧 attribute `trackers`（left/right：位姿+状态+SN+时间戳），沿用现有字段版本兼容策略（老 app 无 Motion 不炸）；
2. `pico4_provider.py` 暴露 `get_tracker_snapshot()`（对齐 `get_head_pose_snapshot()` 风格）；
3. 追踪录制（recorder）扩展 `Motion` 字段，回放路径同样可用；
4. 版本 bump 0.2.1→0.2.2（`_installed_pico_bridge_version` 门槛是否抬到 0.2.2 一并定）。

验收：mock 帧单测 + 03 装机后真机流回放解析通过。
