---
id: 08-replay-viewer-rerun
title: "回放驱动的合成骨架 viewer + receiver Rerun side-first 补齐"
labels: [wayfinder:prototype]
status: open
assignee: claude
blocked-by: []
---

## Question

t06 主观轮与调参需要一个**不开 sim 全链**的可视化：录制 JSONL → 合成器 → 骨架 viewer，合成人体与机器人参考同框观察。同时 receiver 的 Rerun 可视化还欠 side-first 契约对齐（t04 定 side-first wire，Rerun 面仍按 tracker-id 组织）。

2026-09-04 21:22 grilling 定案（全部按推荐 settled）：

- **新工具** `scripts/run/replay_tracker_mocap.py`：读录制 JSONL（`{type,seq,recorded_at_ns,payload}` 信封，Motion 在 payload）→ 喂 `tracker_arm_synth` → 复用现有 `mocap_viewer_proc`（Mocap Input MuJoCo 骨架 viewer 子进程，`viewer_subprocess.py`/`runtime_components.py`）渲染合成 HumanFrame。
- **零接线确认**：tracker 模式合成帧经 `write_mocap` 的 HumanFrame 流自动点亮骨架 viewer——无需 sim 在场。
- **Rerun side-first**：pc_receiver Rerun 面改按 left/right 侧组织（对齐 t04 wire 契约），不再按 trackerid。
- **无 APK 改动**，纯双仓 Python。

验收：replay 工具对 `tracking_20260904_104418.jsonl`（坐标冒烟段）渲染出方向正确的合成骨架（三轴冒烟动作可辨）；Rerun 面显示 left/right 各自 valid/位姿。

序：本票先于 07（无 APK、无人工依赖），随后 07 → t06 主观轮 → map CLOSED。

## Resolution

（待填）
