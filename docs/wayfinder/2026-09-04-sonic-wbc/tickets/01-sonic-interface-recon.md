---
id: 01-sonic-interface-recon
title: "SONIC 接口面侦察：ZMQ qpos 流契约 / checkpoint 选型 / 锁腰与腕颈处理"
labels: [wayfinder:research]
status: open
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
