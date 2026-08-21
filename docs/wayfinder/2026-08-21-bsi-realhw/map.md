---
id: bsi-realhw-map
title: "BSI 过渡：mock 仿真收口 → 真实解码器驱动仿真 → 真机 G1 行走"
labels: [wayfinder:map]
status: open
created: 2026-08-21
---

## Destination

仿真 mock 收口作门（14 行目视验收跑毕 + BSI 真实解码器接入仿真 + 真实流采数复校参数），门后真机 Phase B 四决策锁定：VELOCITY 模式设计（sim 速度 ONNX 策略 sim2real 复用接线）/ 真机安全包络 / 真机运行拓扑 / L1-L3 分级验收规格。实现与真机验收执行交后续 superpowers plan 与硬件会话；上身并轨（Pico 手臂 + BSI 腿同场）不进本图。

## Notes

**领域**：BSI（脑机接口）四态离散指令 → Unitree G1 locomotion。本图 = 从「mock 跑通仿真」过渡到「真实解码器驱动仿真」，再门控「真机 G1 行走（locomotion-only，复现仿真效果）」。上张图 [bsi-dds]（2026-08-21，七票全决，closed）交付协议/映射/急停/keymap/架构/BSI_DDSInterface 仓库/验收规格；其 Teleopit 侧编码（Phase 1/2）已 merge 至 master 17e8190，仿真 mock 跑通、差目视验收。

**现状接缝**（charting 会话两份 survey 已查实，2026-08-21）：

- 订阅端已真：`bsi_factory.build_dds_reader` → `DiscreteCommandSubscriber`（domain 0）；「mock」在发布端（`bsi_dds.cli mock`，dds-probe env）。配置开关 `command.provider: merged_bsi`（pico4_sim_bsi.yaml）。Teleopit 侧无 mock/real 代码开关——真实解码器只要向 domain 0 发布，仿真零改动即被活信号驱动。
- sim 栈：`MergedTwistProvider`（整包摇杆优先 + BSI 次源）→ `VelocitySimSession`（V/X、E 急停 0.3s 渐0→STANDING 带锁存、C/Y 哑音）→ ONNX 速度策略 → MuJoCo。
- 真机栈：`Sim2RealRuntime`/`HighLevelPolicySim2RealRuntime`（mp 多进程）恒进 debug 模式，本地 mimic ONNX → `UnitreeG1Robot.send_positions` → `g1_bridge_sdk` LowCmd 200Hz；输入为 50D 动作包（根位姿+29 关节+手+颈），**无 twist/velocity 接缝**；ai 模式（Unitree LocoClient）仅 damping/关机安全态使用；`g1_bridge_sdk` 无 velocity API（驱动 LocoClient 须扩 C++ 桥）。
- 真实接缝（Q8=A 选定）：mp 运行时新增 `RobotMode.VELOCITY` 分支，复用 `build_velocity_policy_components` + `MergedTwistProvider` + `UnitreeG1Robot.send_positions`；mimic ONNX 已在真机跑（`runtime.py:1448-1461`，`_multi_input` 双输入校验门）为先例。
- 14 行桌面 checklist 已写未跑（`docs/knowledge/research/2026-08-21-bsi-desktop-checklist.md`）；phase-2 唯一显式遗留即此手动门。

**Charting 会话锁定的边界决策**（2026-08-21，grilling 九问）：

1. **分段图**（Q1c）：仿真收口门（验收 + 真实解码器接入 + 复校）→ 真机 Phase B 主体；仿真票 blocker 真机票。
2. **目视验收**（Q2c）：14 行 checklist 单跑一遍闭环；bug 视作 cosmetic/低优先，暴露即各自成 fix ticket，但不阻塞门。
3. **解码器就绪**（Q3a）：BSI 解码已能稳定出意图——全图按活信号联调规划，无回放数据兜底路径。
4. **真机腿覆盖**（Q4）：Pico 摇杆做腿（手部追踪做上身是另一通道，摇杆空闲）；非零压制 BSI、回零交还——sim merged 语义原样上真机，融合层零改动。
5. **分层两级急停**（Q5）：E 键 0.3s 渐0→站定（锁存照搬）+ 硬件物理钮/Unitree 保护停立即阻尼做安全底。
6. **采数后再校**（Q6）：借仿真收口的活信号 echo 抓包量化（延迟/误分类/置信度）→ 据此定参数再上真机。
7. **分级安全门验收**（Q7）：L1 静态站立安全 → L2 看护慢速（仅 forward/idle、降速）→ L3 自由四态穿场；行为 checklist 贯穿 + 可日志测时序指标。
8. **ONNX 速度策略 sim2real**（Q8A）：不碰 C++ 桥；LocoClient 路线弃选留备选。
9. **不并轨**（Q9）：真机只复现仿真效果（BSI locomotion 单独）；上身并轨涉及新控制策略，另图。

**Skills**：grilling 类 ticket 先 /grilling + /domain-modeling；需要实物反应时 /prototype。本图无 research 票（两份 survey 已在 charting 会话完成并摘录于上）。

**Tracker 约定**（本地 markdown，同 bsi-dds 图）：

- Ticket = `tickets/NN-*.md`，frontmatter：`labels`（含 `wayfinder:<type>`）、`status: open|closed`、`assignee`（空为未认领）、`blocked-by`（ticket id 列表）。
- Frontier = status:open 且 blocked-by 全部 closed 且 assignee 为空的 ticket。
- Claim = frontmatter `assignee` 填驱动者标识。
- Resolve = 正文追加 `## Resolution`、`status: closed`、并在本 map 的 Decisions so far 追加一行。
- 产物放本目录 `research/` 或链接既有 `docs/knowledge/research/` 文档。

## Decisions so far

- [仿真 14 行桌面 checklist 目视验收](tickets/01-sim-desktop-checklist.md) — user-reported 通过（目视 + 活信号复核），无 fix ticket；量化细节由 03 承接。
- [BSI 真实解码器接入仿真（活信号联调）](tickets/02-live-decoder-sim-hookup.md) — user-reported 通过：解码器→domain 0，仿真零改动被活信号驱动；流率/拓扑量化留 03/06。
- [真实 BSI 流采数量化与参数复校](tickets/03-bsi-stream-capture-retune.md) — user-reported 通过：真实流复核未报调整，参数按现值沿用；仿真收口门全关，Phase B（04）解锁。
- [真机 VELOCITY 模式接线设计](tickets/04-real-velocity-mode-design.md) — Sim2RealRuntime 内加 VELOCITY 模式；Pico TOGGLE_VELOCITY 键（仅 STANDING 进、锁存期拒入）；订阅器 + MergedTwistProvider 住 robot_control 进程（CONTROLLER_TOPIC 供摇杆半边）；速度 ONNX 策略与真机状态完全兼容直接复用（single_input_ok，无需 _multi_input 门）；新 pico4_sim2real_bsi.yaml + run_sim2real.py 入口。附带事实喂 05：joint_vel_limit mp 路径未执行、TOGGLE_ESTOP/MUTE 被丢弃（90% 现成急停缝）、L1+R1 遥控器 damping 即硬件级安全底。
- [真机运行拓扑确认](tickets/06-real-network-topology.md) — 板载 Orin（仓库惯例 + eth0 机器人总线 + Orin cyclonedds 0.10.5 实测 OK）；三机两总线拓扑定稿；5 步上真机验证清单（解码器机对齐 0.10.x 防 XTypes hash 静默丢包 → doctor → 跨机 echo → Orin 起 mp 栈 → 同进程双 DDS 共存）；run_velocity_sim.py 硬编码键盘 provider 系设计（键盘验证入口），不开 fix ticket。

## Not yet specified

- L2 慢速门的具体降速幅值与 L3 场地布置（并入 07 规格时定）。
- 真机联调暴露的整定票（同上张图「特性回填」预案）。

## Out of scope

- 上身并轨：Pico 手臂遥操与 BSI 腿同场并发（新控制策略，Q9 明确排除，目标形态另图拼装）。
- Teleopit 侧编码实现与真机验收执行（04/05/06/07 锁定后走 superpowers plan 与硬件会话）。
- BSI 解码模型、EEG 采集（BSI 团队侧，同上张图）。
- `g1_bridge_sdk` C++ 桥扩展（LocoClient velocity API；Q8 弃选，未来要厂商行走再启新图）。
- bvh/udp 通路 BSI 接入（同上张图）。
