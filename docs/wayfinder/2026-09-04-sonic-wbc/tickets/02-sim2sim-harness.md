---
id: 02-sim2sim-harness
title: "sim2sim 试验台：回放→合成→重定向→SONIC→MuJoCo 闭环"
labels: [wayfinder:prototype]
status: open
assignee: claude
blocked-by: ["01-sonic-interface-recon"]
---

## Question

按 01 定案实装 sim2sim 试验台（TDD）：

- **SONIC 推理进程**：按 01 选型落地（ZMQ 服务或 onnx 直载），锁腰钳 0，腕/颈按 01 处理；
- **输入源**：`pc_receiver/pico_bridge_recordings/tracking_20260904_104418.jsonl` 回放 → `tracker_arm_synth` 合成（依赖 mocap 图 t06 产出；未闭时按其 research/05 设计先行最小子集）→ 现有 GMR/mink 重定向 → G1 上身 qpos；cmd_vel 注入（步行段脚本化）；
- **仿真闭环**：复用 `MuJoCoRobot` + `VelocitySimSession` 模式（**pd_hz 200 不变量**），`g1_29dof.xml` 基线 + RH56E2 腕端配重变体；
- **指标采集**：指令/上身跟踪误差、稳定时长、端到端延迟（日志法）；
- 契约测试 + 冒烟（回放坐标冒烟段，viewer 观察）。
