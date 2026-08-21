---
id: bsi-realhw-04
title: "真机 VELOCITY 模式接线设计（ONNX 速度策略 sim2real）"
labels: [wayfinder:grilling]
status: open
assignee: ""
blocked-by: [bsi-realhw-01, bsi-realhw-02, bsi-realhw-03]
created: 2026-08-21
---

## Question

Q8=A 定架：mp 运行时（`teleopit/sim2real/mp/runtime.py` `_RobotControlWorker`）新增 `RobotMode.VELOCITY` 分支，复用 sim 的 twist→ONNX→关节目标栈。待决设计点：

1. **状态机映射**：sim `VelocitySimSession` 的 V/X、E 急停锁存、STANDING↔VELOCITY 语义如何落到真机 RobotMode 机（现有 STANDING/MOCAP/POLICY）；estop latch 的真机等价物。
2. **指令源接入**：`MergedTwistProvider`（Pico 摇杆优先 + BSI，Q4 语义）+ `DdsIntentSource` 在 mp 运行时的构建位置（哪个进程、哪台机器）。
3. **策略复用与校验**：`build_velocity_policy_components` 直接复用的差异面（obs builder 输入改自 `UnitreeG1Robot.get_state()`）；`_multi_input` sim2real 校验门；pd_hz 200 / policy_hz 50 不变量。
4. **配置与入口**：真机 velocity yaml（自 pico4_sim_bsi 派生）+ `run_*` 入口脚本形态。

边界：locomotion-only，无上身并发（Q9）。产出：设计决策——后续 superpowers plan 的直接输入。
