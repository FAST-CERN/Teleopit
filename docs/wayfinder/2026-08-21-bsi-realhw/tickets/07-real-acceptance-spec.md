---
id: bsi-realhw-07
title: "L1-L3 分级验收规格（真机 BSI locomotion）"
labels: [wayfinder:grilling]
status: closed
assignee: "claude/main"
blocked-by: [bsi-realhw-04, bsi-realhw-05]
created: 2026-08-21
---

## Question

Q7 定分级安全门形态。待决细则：

1. **L1 静态站立安全门**：站立下 E 急停（渐0 + 锁存/解锁）、跌倒保护行为——观察行与通过线。
2. **L2 看护慢速门**：降速幅值（如 0.3 m/s 级？）、仅 forward/idle、看护配置——观察行与通过线。
3. **L3 自由四态门**：前/左/右/idle 穿场 + 摇杆抢夺/回零交还 + 静默 1s 站住——观察行与通过线。
4. **可日志测时序指标**（意图→速度响应、急停耗时）与记录方式；**失败处置**（退级重试规则）。

产出：三级验收规格表（真机执行在后续 plan/硬件会话，不在本图）。

## Resolution

**2026-08-21 grilling 定案（Q1-Q7 + mocap 键位澄清）**。前置门 = 06 的 5 步上真机验证清单（已另立，不重复）。

**模式机与键位（参照 sim，STANDING 枢纽）**——两遥控器分工：

| 键 | G1 遥控器（看护人） | Pico（操作员） |
|---|---|---|
| START | IDLE→STANDING 起立 / DAMPING→STANDING 恢复 | — |
| L1+R1 | 任意→DAMPING 硬急停 | — |
| Y | STANDING→MOCAP 进手臂域（**BSI yaml 配置门默认关**，防劫持） | TOGGLE_MUTE 哑音 |
| X | 手臂域→STANDING 回站 | **TOGGLE_VELOCITY 进/出**（仅 STANDING 进、E 锁存拒入；新钉，`velocity_button` 现成参数） |
| B | 手臂域暂停/恢复 playback | TOGGLE_ARMS 域内互切（域外 no-op，`runtime.py:2315` 既有守卫） |
| A | — | TOGGLE_PAUSE（域外跳过） |
| 左 grip | — | **TOGGLE_ESTOP** 优雅急停（新钉，`estop_button` 现成参数；中指扣、拇指不离摇杆） |
| 左摇杆 | — | 腿部 twist（Q4） |

mocap（手臂遥操）保留为运行时能力，与 BSI 腿互斥不同场（Q9 边界不变）。

**L1 静态站立安全门**（悬吊可挂）：① 上电 STANDING（kp ramp 2s）站立 60s 无漂移/零 threshold；② no-op 三连：站立按 E（Pico grip）、按 B（域外守卫）、按遥控器 Y（配置门）均无副作用；③ damping 演练 L1+R1→瘫→扶正→START→回站，全程 VELOCITY 锁定、E 解锁后 X 才可进。

**L2 看护慢速门**（挂悬吊；全通道限 forward ≤0.3 m/s、侧向/转向一律 0）：① X 起步；② BSI forward 直行 ≥5m 目视 ~0.3 m/s；③ 摇杆抢夺/回零交还（≤2 周期）；④ BSI left/right → idle 压制不动；行进中误按 B 无副作用；⑤ 静默 1s 站住；⑥ 行进中 E：0.3s 渐0 站定+锁存+拒入+解锁恢复；⑦ 推搡测试（悬吊兜底）：站住或 30° 优雅回站，不倒地。

**L3 自由四态门**（摘悬吊；≥5m×5m 平地清障；3 人=看护/操作/记录兼报幕）：看护口头报幕驱动，节奏照 sim 场景脚本 idle→前→左→前→右→idle→前（中途抢夺+E 急停+解锁）→idle。行为行：四态各正确且切换平滑、抢夺/交还、E 急停+解锁、静默站住；**总通过线 = 全程零 threshold 触发**（joint-vel/tilt 门不响）→ 复现仿真效果，全图验收。

**时序指标表**（日志测；实际速度响应降目视——真机无 base_lin_vel）：意图→融合 cmd ≤1.0s；E→cmd0 ≤0.8s；摇杆抢夺 ≤2 get_cmd 周期；误标签孤包不切换；静默 ≤1s 开始衰减。记录 = runtime 日志 + 06 echo 抓包，结果回填 `docs/knowledge/research/`；结构化 per-step cmd 日志（jsonl）列入 plan 要求。

**失败处置**：行级失败当场重试 1 次（第 2 次过算 pass 记录在案）；级失败退一级重走；threshold 触发的 damping（非人为）= 当日停机排查不重试；L1+R1 人为演练不算。

**喂 plan**：velocity_button/estop_button 配置接线、TOGGLE_ESTOP 事件处理（现被丢弃）、遥控器 Y mocap 进入配置门、L2 限速与指令集压制配置、05 的 threshold 监控装设、结构化 cmd 日志、per-joint 限速数组（L3 前）。
