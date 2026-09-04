---
id: 01-sonic-interface-recon
title: "SONIC 接口面侦察：ZMQ qpos 流契约 / checkpoint 选型 / 锁腰与腕颈处理"
labels: [wayfinder:research]
status: closed
assignee: claude
blocked-by: []
---

## Question

SONIC 接口面精确语义收齐（AFK 研究，产物进 `research/`），约束 02 试验台：

1. **输入通道定案**：ZMQ qpos 流的精确契约（消息 schema、频率、根位姿语义、坐标系）vs teleop 编码模式（未来速度 + VR 三点位姿）——我们链路是 合成帧→重定向→G1 上身 qpos 直灌（首选，免 FK）还是造三点位姿走编码模式；**cmd_vel 在所选通道如何注入**（速度通道在哪、单位/坐标系/前瞻语义）。
2. **checkpoint 三选一**：3 个 G1 29-DoF checkpoint（80ms lookahead 遥操作版 / v1.1 腕增强 / 基础）的观测/动作张量形状、onnx/jit 形态、推理依赖（torch 版本；**是否需 Isaac Lab 才能 inference**——希望不需要）。
3. **锁腰面**：qpos 输入腰值恒 0 是否被策略接受（腰在 obs 中的角色）；输出腰参考需否再钳；与实机 mode_machine 锁腰（unitree_rl_lab issue #6/#114 经验值 29dof≈6）的兼容。
4. **腕/颈面**：29-DoF 含双腕 3+3——策略腕输出与我们重定向腕目标的冲突处理（旁路 PD?）；OpenNeck 2dof 不在 G1 29 内，确认颈完全旁路。
5. **RH56E2 增重仿真法**：MuJoCo `g1_29dof.xml` 腕端加配重（~0.5kg/手）评估稳定性差的实验设计。
6. **sim2sim 最短路径**：SONIC 仓内有无 sim2sim/部署例程可借；与本地 `MuJoCoRobot`（pd_hz 200）桥接的对接面。

主要信源：本地克隆 `F:\tmp\wbc-groot`（代码级核实）+ HF checkpoint 页 + arXiv 论文；预研报告 `research/00-wbc-policy-candidates-bsi-upperbody.md` 作起点，**关键契约逐条重验**。

## Resolution

2026-09-04 闭，产物 `research/01-sonic-interface-semantics.md`。要点：

1. **输入通道**：`pose` topic 协议 v1 直灌可行且免 FK——joint_pos/joint_vel[N,29]+body_quat[N,4] wxyz+frame_index，单条 ZMQ 消息（5556，topic+1280B JSON 头+二进制），**IsaacLab 交错关节序**、绝对角；但 v1 **无速度槽位**（decoder obs 994D=token+历史），cmd_vel 官方面在 **planner 模式**（movement/facing/speed+`upper_body_position[17]`）。
2. **checkpoint**：low_latency（enc 45.9/dec 149.8MB，4 帧 80ms+step1）/ v1_1（腕增强+航向归一）/ default；decoder 994D→29D、encoder 1247D→64D token；**inference 不需 Isaac Lab**（onnxruntime 即可，sim venv 无 torch 无 isaaclab 验证）。
3. **锁腰**：腰=IsaacLab {2,5,8}，obs 偏差坐标恒 0+default=0 → 参考置 0+模型 weld 即可，无需钳输出；温和域差 sim2sim 定量。
4. **腕/颈**：腕直灌无冲突（参考即我们的腕目标，旁路降为备选；注意 ±5/±25Nm 腕力矩限幅）；**颈完全旁路实锤**（29 序无颈）。
5. **配重**：SONIC 橡胶手挂 wrist_yaw_link (0.0415,0.003,0)；本地 XML 加显式 mass geom，四档对照 0/0.25/0.5 点/0.5 分布，指标含腕力矩饱和率。
6. **sim2sim**：官方 run_sim_loop+C++ deploy 依赖 TensorRT（Windows 不可行）；**最短路径=Python harness+onnxruntime+MuJoCoRobot**（200Hz 物理+50Hz 策略，与 pd_hz 200 不变量同构）。

**决议（用户确认）**：上身线走 v1 直灌（关节序映射表进 harness 常量）；**速度线=BSI cmd_vel 直造前瞻张量（恒值持尾），不引官方 774MB planner**——真机契约对齐（速度来自 BSI 而非 VLM planner），planner 只留官方行为对照备选；checkpoint 主线 low_latency+对照 v1_1。两大待验项进 02：root_z 恒 0 风险、前瞻持尾行为。frontier→02。
