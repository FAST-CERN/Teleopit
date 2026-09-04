---
id: 08-replay-viewer-rerun
title: "回放驱动的合成骨架 viewer + receiver Rerun side-first 补齐"
labels: [wayfinder:prototype]
status: closed
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

代码面全落地（2026-09-04 晚，Teleopit `5c2bbc7` + pico-bridge `d1df51f`）：

- **回放引擎** `teleopit/inputs/tracker_replay.py`：信封解析（side-first Motion 在 payload）→ pico_bridge 形帧；`TrackerReplayBridge` 按 `recorded_at_ns` 时间线节奏供帧（`speed` 缩放），loop 时 seq/receive_time 跨接缝单调递增（after_seq/gap-reset 语义保真）；14 项新单测。e2e 测试改与工具共享 `frame_from_record`（单一解析源，wire 变更两处同爆）。
- **viewer 工具** `scripts/run/replay_tracker_mocap.py`：`PYTHONPATH=. python scripts/run/replay_tracker_mocap.py <recording.jsonl> [--speed S] [--no-loop] [--synth-yaml offsets.yaml] [--max-duration S]`——驱动未改动的 provider body 路径（合成→坐标变换→贴地）再喂 `mocap_viewer_proc` 骨架窗，无设备无 sim。冒烟：120 帧切片 1x 回放 provider 50.5Hz、渲染/退出干净；teleopit env 相关套件 59/59，全量=基线（4 预置败+11 收集错）。
- **Rerun side-first**（pico-bridge `d1df51f`）：`_log_motion` 从 t01 数组形草稿改为 side-first——`world/motion/{left,right}` 位姿 puck、分侧配色、invalid=末位姿半透明 ghost、Track-L/Track-R 徽章、跟随相机 bounds 收编 tracker；pc_receiver 113 过（+4 新，1 预置 aiortc 败）。

**剩余**：~~视觉确认轮（人工）~~：① MuJoCo 骨架窗冒烟——用户 2026-09-04 21:49 确认过线（`replay_tracker_mocap.py` 渲染方向正确可辨）；② Rerun 面留待 t07 真机轮顺带验证（本机无 rerun viewer 二进制；届时装 viewer 或 `--connect`）。票闭。
