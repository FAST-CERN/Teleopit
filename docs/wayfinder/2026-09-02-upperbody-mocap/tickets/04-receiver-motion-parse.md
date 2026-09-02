---
id: 04-receiver-motion-parse
title: "pico_bridge 接收端：Motion 字段解析 + frame.trackers 暴露 + 录制扩展"
labels: [wayfinder:task]
status: closed
assignee: claude
blocked-by: ["03-unity-motion-collection"]
---

## Question

`pc_receiver`（pico-bridge 仓库 Python 包，Teleopit 以 `pip install -e '.[pico4]'` 内嵌）跟上 03 定稿的 `Motion` 字段（AFK，TDD，本机 teleopit conda env）：

1. `protocol.py` 解析 `Motion` → 帧 attribute `trackers`（left/right：位姿+状态+SN+时间戳），沿用现有字段版本兼容策略（老 app 无 Motion 不炸）；
2. `pico4_provider.py` 暴露 `get_tracker_snapshot()`（对齐 `get_head_pose_snapshot()` 风格）；
3. 追踪录制（recorder）扩展 `Motion` 字段，回放路径同样可用；
4. 版本 bump 0.2.1→0.2.2（`_installed_pico_bridge_version` 门槛是否抬到 0.2.2 一并定）。

验收：mock 帧单测 + 03 装机后真机流回放解析通过。

## Resolution

2026-09-02 闭（TDD，mock 侧全绿；真机回放项挂 03 装机后补验——已回写 03 票面）。pico-bridge 仓 commit `7e83469`（0.2.2）+ Teleopit commit `71e3588`。

1. **wire 契约定稿**（细化 research/01 §8，side-first）：`"Motion":{"poseSpace":"pico_tracker_local","left":{"sn":<long>,"p":"x,y,z,qx,qy,qz,qw","valid":<0|1>},"right":{…}}`；03 按此上行（绑定结果在 app 侧，接收端哑）。
2. `frames.py`：`PicoFrame.trackers: MotionFrame{active,left,right}`，`TrackerState{sn,pose,valid}`；`_parse_motion` 容错（老 app 无 Motion=inactive、占位 `{joints:[],len:0}`=inactive、畸形单侧容忍）。RED→GREEN 4 测。
3. `recording.py` **零生产改动**：payload 原样透写，回放（JSONL→`from_tracking_payload`）天然携带 Motion——往返测试锁契约（RED 于 trackers 缺失时）。
4. `pico4_provider.get_tracker_snapshot()`：`PicoTrackerSnapshot{left,right,timestamp_s,seq}`/`PicoTrackerState{sn,valid,position,rotation_xyzw}`，**pico_native xyzw 原样透传**（合成器在原始系工作，t05 §1）；快照在 body 拒帧时照常捕获（head+motion-only 模式有粮）。真 `PicoFrame` 冒烟过。
5. 版本：pyproject 0.2.1→**0.2.2**（CHANGELOG 补条），teleopit env 已重装；provider 门槛**抬到 (0,2,2)**（gate 测试改为 monkeypatch 版本函数——原测试传 bridge_cls 绕过闸的缺陷一并修正）。
6. 回归：pc_receiver 108 过（1 deselect=预置 aiortc 欠账）；Teleopit 589 过，4 失败+11 收集错均为预置（干净树复验：dataset_v2/sim2real_multiprocess、mjlab/viser 缺包）。
