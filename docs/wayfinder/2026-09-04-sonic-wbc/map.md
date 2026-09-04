---
id: sonic-wbc-map
title: "G1 全身策略接入 GEAR-SONIC：BSI 指令 + 上半身动捕 → sim2sim 过线"
labels: [wayfinder:map]
status: open
created: 2026-09-04
---

## Destination

统一 policy 第一段：**GEAR-SONIC 全身策略在本地 sim2sim 吃我们的契约输入**——BSI cmd_vel 速度指令 + 上半身动捕合成参考（mocap→重定向→G1 上身 qpos）——经 ZMQ/onnx 接入，锁腰钳 0、RH56E2 腕端增重等 gap 全部仿真落地，**四线验收（指令跟踪 / 上身跟随 / 稳定裕度含失效安全 / 主观）过线**即达。

真机 Onboard 部署与验收、复训线另议（见 Out of scope）。

## Notes

**领域**：统一 policy 图，承接 upperbody-mocap 图 Out-of-scope 条目「统一 policy 训练/接入」。策略输出面 = G1 29-DoF 全身（含腕）；**手指不在输出面**（Inspire RH56E2 走既有 Modbus preset grasp 链）；颈（OpenNeck 2dof）旁路直发 PD。

**本图携带执行**（同前图惯例）：终点 = sim2sim 试验台合入 + 四线过线。

**开图定案**（2026-09-04 会话与用户对齐）：

1. **模型选型 = GEAR-SONIC**（`NVlabs/GR00T-WholeBodyControl`，Top1；依据 `research/00-wbc-policy-candidates-bsi-upperbody.md` 排名）；AMO（Top2）留作对照/受阻 fallback；unitree_rl_lab 自训线为颈/手特化需求强时的回退。
2. **输入契约** = BSI cmd_vel + 上半身动捕合成参考；**无变高/蹲起需求**，锁腰可接受。
3. **灵巧手 = Inspire RH56E2**（非 Dex-3/LEAP；每手 ~0.5kg 腕端增重，仿真评估）。
4. **先 sim2sim**（MuJoCo `g1_29dof.xml`，本机）；真机另议。

**术语**：「SONIC」= NVIDIA GEAR-SONIC 全身控制策略；「teleop 编码模式」= SONIC 输入 = 未来速度指令 + VR 三点（头+双手）位姿的编码方式；「ZMQ qpos 流」= SONIC 备用输入接口，直接吃 G1 全身 qpos 流（官方注明 No PICO hardware needed）；「锁腰钳 0」= 腰关节输入/输出参考恒 0 的处理；「sim2sim」= 策略推理 + MuJoCo 闭环，无真机。

**硬事实（开图侦察定案，来源：两份预研报告 `research/00-*.md`——`reference/` 本地副本在 .gitignore 内，入库以 research/ 为准，代码级引用在档）**：

- SONIC 仓 push 2026-09-03；**3 个 G1 29-DoF checkpoint 在 HF**（含 80ms lookahead 低延迟遥操作版、v1.1 腕增强版）；代码 Apache-2.0、权重 NVIDIA Open Model License（**非 NC**）；训练面 Isaac Lab 2.3.2 + Bones-SEED 288h + finetune 配方；官方部署路径 G1 板载 Orin/JetPack6。克隆在 `F:\tmp\wbc-groot`（预研留档）。
- **已知 gap（预研报告 §4，全部须仿真落地）**：① 腰可动假设 → 锁腰钳 0 + sim2sim 验证；② 上身通道形态待定（teleop 编码走 FK vs qpos 流直灌——01 票定）；③ 腕/颈旁路直发 PD；④ 手零质量假设 → RH56E2 增重配重仿真。
- 本地可复用：`MuJoCoRobot` + `VelocitySimSession`（twist Phase A `3162807` 模式，**pd_hz 200 不变量**）；mocap 图 t06 正实装 `tracker_arm_synth`（本图吃其合成帧或直接回放 JSONL `pc_receiver/pico_bridge_recordings/tracking_20260904_104418.jsonl` 25.9MB，含坐标冒烟段）；现有 GMR/mink 重定向产 G1 上身 14 关节（idx 15–28）。
- 淘汰名单与理由（HumanPlus/OmniH2O 系/OpenWBC/HDMI 等）在 `research/00-wbc-policy-candidates-bsi-upperbody.md`；OpenHomie 否决案在 `research/00-openhomie-integration-feasibility.md`。

**部署/环境**：本机 teleopit conda env（3.10）跑 sim2sim 与测试；无真机面、无停机窗口。

**Tracker 约定**（同前图）：Ticket = `tickets/NN-*.md`（frontmatter labels/status/assignee/blocked-by）；Frontier = open 且依赖全闭且未认领；Resolve = 正文追加 `## Resolution` + status: closed + 本 map Decisions 追加一行；研究产物放 `research/`。

## Decisions so far

- 2026-09-04 开图：选型 GEAR-SONIC（Top1）+ AMO fallback + unitree_rl_lab 自训回退（预研排名，用户确认）；sim2sim 先行、真机另议。
- 2026-09-04 t01 闭（research/01）：直灌可行免 FK（`pose` topic v1，ZMQ 5556，IsaacLab 交错序，映射表进 harness 常量）；checkpoint 主线 **low_latency**+对照 v1_1，**inference 无需 Isaac Lab**（onnxruntime）；锁腰=参考置 0 无需钳输出；腕直灌、颈旁路实锤；RH56E2 四档配重对照设计在档；sim2sim=Python+onnxruntime+MuJoCoRobot（200/50Hz 同构 pd_hz 200）。**速度线用户定案：cmd_vel 直造前瞻（恒值持尾），不引官方 planner**。frontier→t02。

## Not yet specified

- 四线数值线（03 票内定稿）
- ~~checkpoint 三选一~~——t01 已决：主线 low_latency+对照 v1_1
- AMO 对照线是否开票（SONIC sim2sim 受阻时）；官方 planner 对照线（用户已定主线不引，留备选）
- 真机 Onboard 部署/验收、模式机整合（本图闭后另议或另图）
- Isaac Lab 复训线是否启用（仅 sim2sim 不过线时评估）

## Out of scope

- 真机部署与验收（Onboard JetPack6、estop、模式机改动、VELOCITY 臂覆盖层）
- 训练/finetune（Isaac Lab 2.3.2 复训、Bones-SEED 数据）
- 手指链路（RH56E2 Modbus 既有链零改动）
- FPV 视频链路、颈增强（既有出图）
- HOMIE/OpenHomie 代码接入（预研已否决，报告在档）
