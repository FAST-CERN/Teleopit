---
id: bsi-dds-map
title: "BSI 脑控离散指令接入：DDS 接口 + BSI_DDSInterface handoff + 仿真同源"
labels: [wayfinder:map]
status: open
created: 2026-08-21
---

## Destination

仿真内端到端跑通 BSI 四态离散指令（前/左转/右转/idle）→ G1 行走：接入 **pico4 仿真状态机**（SimLoopSession 通路），与 Pico 摇杆/键盘同源融合（摇杆优先，急停渐0→STANDING）；同时交付 **BSI_DDSInterface 新仓库**（third_party 子模块，Python 包：指令协议 + 局域网 DDS 收发 + 通信进程管理，上位机/下位机双端复用），BSI 上位机团队可据此对接局域网。map 完成标志 = 协议/映射/急停/接线/验收六项决策锁定 + 仓库骨架落地；Teleopit 侧编码实现走后续 superpowers plan，真机验证不在本图。

## Notes

**领域**：BSI（脑机接口）离散运动指令 → Unitree G1 locomotion（cmd_vel 通道）仿真接入；DDS 局域网接口。**仅仿真**，真机（BSI 做 locomotion + Pico 遥操作上身）是下一张图。

**现状接缝**（charting 时已查实）：

- `teleopit/commands/base.py` — `CommandProvider` 6D twist seam，Phase A 起 DDS-future-proof 设计。
- `teleopit/commands/keyboard_cmd.py` — 键盘语义基线：hold-to-move、释放归零（0.2s）、指数平滑（alpha 0.3）、K 急零；键位 W/S/J/L/N/M/K（避开会话键 h q y v x a b r space p）。
- `teleopit/commands/pico_joystick.py` — `PicoJoystickProvider`：L 平移/R 转向、死区 0.15、stale 0.5s 归零。
- `teleopit/sim/velocity_session.py` + `velocity_step.py` — STANDING↔VELOCITY 状态机；V 进入（仅从 STANDING、has_frame 门控）、X 退出（yaw 保持 pose-B 缓动）；joint-vel 超限→STOP(damping)、tilt→STANDING。
- `third_party/unitree_sdk2_python` — DDS 栈在仓先例（cyclonedds + IDL，vendored 全量拷贝，非 submodule）。

**Charting 会话锁定的边界决策**（2026-08-21）：

1. **四态指令集**：前 / 左转 / 右转 / idle。idle 是显式类别（BSI 持续输出当前意图），不靠超时推断。
2. **融合规则**：BSI 与摇杆在 VELOCITY 模式内并联为 twist 源，**摇杆非零时摇杆优先**（人手抢夺脑控），摇杆零时 BSI 生效。状态机转换（V/X）仍由 Pico 侧驱动，BSI 不碰状态机。
3. **急停**：Pico 手柄 + 键盘都加急停键；语义 = cmd_vel **渐 0 → 切 STANDING**（非 damping）；joint-vel 超限/过速→damping 维持原行为。急停影响 keymap，键位设计单独成 ticket。
4. **BSI_DDSInterface 定位**：一个仓库，挂 third_party 子模块；主体 Python 包：指令协议（单一来源，Teleopit 不复制）+ 局域网 DDS 收发接口 + 通信进程管理；**上位机、下位机双端复用**。Teleopit import 该包实现订阅端 provider，CommandProvider seam 不变。
5. **Submodule 是本仓首例**：现有 third_party 均为 vendored 拷贝；submodule 的 git 行为（init/update/克隆流程）必须写文档。
6. **map 边界**：决策为主，唯一例外是「BSI_DDSInterface 仓库骨架」task ticket（协议产物要落库才有意义）。Teleopit 侧编码（provider/急停/接线实现）走后续 superpowers plan。

**Skills**：grilling 类 ticket 先 `/grilling` + `/domain-modeling`；需要实物反应时 `/prototype`。本图无 research ticket（无外部知识依赖）。

**Tracker 约定**（本地 markdown，同 zed-fpv）：

- Ticket = `tickets/NN-*.md`，frontmatter：`labels`（含 `wayfinder:<type>`）、`status: open|closed`、`assignee`（空为未认领）、`blocked-by`（ticket id 列表）。
- Frontier = status:open 且 blocked-by 全部 closed 且 assignee 为空的 ticket。
- Claim = 在 frontmatter `assignee` 填入驱动者标识。
- Resolve = 正文追加 `## Resolution` 章节、`status: closed`、并在本 map 的 Decisions so far 追加一行。
- 产物放本目录 `research/` 或指向 BSI_DDSInterface 仓库，ticket 内链接。

## Decisions so far

- [BSI 离散指令 DDS 协议设计](tickets/01-discrete-command-protocol.md) — domain 0 同域 + `bsi/cmd_discrete`；持续意图流 ≥10Hz；best-effort+deadline 0.5s；IDL 源+idlc 生成；schema = stamp_ns/seq/command/confidence，IDLE=0 故障安全；静默 1s 归 idle；点对点直连无中继。

## Not yet specified

- BSI 实测特性未知（误分类率、指令间隔、标签切换节奏）→ 映射 ticket 的防抖/缓冲策略可能需要实测回填后重校，届时或生「特性回填」ticket。（confidence 字段已进 schema，实测后可用于阈值策略）
- ~~BSI_DDSInterface「通信进程管理」的具体 API 面~~ — T1 已定形态：可选启动/健康检查工具集（非守护进程中继），API 面随骨架 task 细化。
- bvh/udp 通路要不要 BSI — 先只接 pico4 通路，视经验再议。
- 验收若暴露响应延迟/抖动问题 → 参数整定（平滑常数、防抖窗口）可能单出 ticket。

## Out of scope

- 真机 BSI/locomotion 验证（twist 通道真机化属 Phase B 下一张图；BSI 做 locomotion + Pico 遥操作上身的目标形态在那边拼装）。
- BSI 解码模型、EEG 采集、任何脑电信号处理（BSI 团队侧，进度图泳道 5 另两项）。
- 上位机侧应用代码（本图只交付库 + 协议 + 文档，怎么用是 BSI 团队自治）。
- Teleopit 内 provider/急停/仿真接线的编码实现（决策锁定后 superpowers plan 执行，不进本图）。
- bvh/udp 通路的 BSI 接入（先 pico4 通路）。
