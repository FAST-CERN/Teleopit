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

## Progress

**2026-09-04 lines 1-3 落地（Teleopit `5156b74` + 后续 commit；45 测试全绿）**：

1. **策略适配层** `teleopit/policies/sonic/`：`joint_order`（映射数组 verbatim 自 policy_parameters.hpp:100-104；方向以 upper-body 交叉表裁决——变量名与注释相反，TDD 当场抓到一次方向反写）；`observation`（994D decoder + 1247D encoder 装配：块序、偏差坐标、oldest→newest、钳尾前瞻、6D=旋转矩阵前两列行展开、vr/smpl 支路置零=官方 v1 流对齐）；`params`（SONIC 自有 default/scale，hip_pitch 用新 7520_22 表与本地 g1.yaml 不同）；`runtime`（onnxruntime enc/dec 封装 + 加载期维度校验，checkpoint 落 `assets/policies/sonic/low_latency/` gitignored）。
2. **闭环** `teleopit/sim/sonic_session.py`：50Hz 策略 + 4×0.005 物理（pd_hz 200 不变量）+ 骨盆高度跌倒保护 + 上身跟踪/根高/action 量级指标。
3. **变体** `teleopit/sim/sonic_variants.py`：锁腰（三腰关节 range 0 0）+ RH56E2 配重（**改 `<inertial>`**：mass/CoM 平行轴精确/diaginertia 点档+0 盒档+m/12 项——本地 XML 腕 body 显式 inertial 使 geom 质量无效，research/01 §7"碰撞 geom 有质量"论断对本地 XML 不成立，已修正）。
4. **端到端冒烟（真 low_latency checkpoint）**：站姿参考 4s 三变体全稳——基线/锁腰 root_z≈0.765 平直、+0.5kg 盒 RMSE 0.0464（基线 0.0593）action 1.52（1.30）、锁腰+配重同稳。**对照实验：纯被动 PD 保持 1.5s 塌（plant 属性，策略必须主动平衡）——Python 复刻链数值正确性由此反证**。
5. **风险项消除一条**：low_latency 的 994/1247 obs 里无 root_z 字段（研究 §1.3 风险只适用于 default 变体 obs），root_z 恒 0 风险对本 checkpoint 不存在。

6. **2026-09-04 line 4 落地（`9e470aa`）**：合成挥臂源 `sonic_synthetic.py`（站姿模板+腰 0+双肘反相 ±0.6 rad/2s 周期+肩摆，差分速度，6 测试）+ 入口 `scripts/run/run_sonic_sim2sim.py`（变体选择/managed viewer/realtime pacing）。**20s 目视运行：1000 步零跌落，root_z 0.757-0.767 呈摆臂节律起伏，RMSE 0.062**。**主观目视结论：操作员 2026-09-04 确认"没问题"（方向/幅度/节律跟手）——line 4 过线。**

**剩余线（待续）**：真实输入源（JSONL 回放→tracker_arm_synth→GMR/mink 重定向→上身 qpos，依赖 mocap 图 t06 产出）；cmd_vel 步态线（恒值持尾前瞻的参考生成器 + BSI 映射）；腕力矩饱和率指标。
