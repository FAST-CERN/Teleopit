---
id: bsi-dds-01
title: "BSI 离散指令 DDS 协议设计（topic/QoS/schema/四态枚举）"
labels: [wayfinder:grilling]
status: closed
assignee: "claude/main"
blocked-by: []
created: 2026-08-21
---

## Question

BSI 上位机 → Teleopit 的指令契约长什么样？需要锁定：

- **Topic 命名**与域（domain id）、参与者命名——与 unitree SDK 的 DDS 域共存策略（同域不同 topic，还是独立域）。
- **消息 schema**：四态枚举（FORWARD / TURN_LEFT / TURN_RIGHT / IDLE）+ 时间戳 + 序列号 + 是否要版本字段/心跳字段/置信度字段（BSI 解码可能带概率输出，传不传？）。
- **QoS**：reliability（best-effort vs reliable）、durability、deadline——BSI 是持续意图流（类似 LowState 高频流）还是离散事件流？频率预期？
- **IDL 形态**：CycloneDDS IDL 生成（unitree 惯例）还是 cyclonedds-python 原生动态类型？
- 断连/静默语义：多久没收到指令算通信丢失，provider 侧归 idle 还是保持最后指令？

产出：协议文档落 BSI_DDSInterface 仓库（`docs/protocol.md` 或 IDL 文件本体），BSI 团队对接的唯一契约。

### 依赖

无阻塞。是 T5（仓库骨架）的协议输入、T2（映射）的数据来源。

## Resolution

**2026-08-21 grilling 锁定（8 项子决策，逐项过问）**：

1. **域共存**：domain 0 同域共存（与 unitree SDK 一致），topic 用 `bsi/` 前缀隔离；domain id 暴露为库的可选参数（默认 0），备将来隔离。
2. **流形态**：**持续意图流**——发送端固定频率重发当前意图（含 idle 期间），跳帧无害；写入协议为必选要求。不采用离散事件流（静默歧义 + 需可靠传输）。
3. **QoS**：best-effort + deadline 0.5s + liveliness automatic（与 unitree SDK 默认 QoS 风格一致；新意图覆盖旧意图，重传无意义）。
4. **IDL 形态**：OMG IDL 源文件为契约单一来源，CycloneDDS idlc 生成 Python 绑定（v0.11 后端，unitree 惯例）；生成产物落库（Python 用户免装 idlc）；C++/其他栈上位机可直接复用同一份 IDL。
5. **Schema（4 字段）**：`stamp_ns`(i64，发送端单调时钟，静默检测+延迟测量) + `seq`(u32，仅诊断/统计) + `command`(u8 枚举) + `confidence`(f32，不用则恒 1.0)。
6. **枚举值（零值故障安全）**：**IDLE=0, FORWARD=1, TURN_LEFT=2, TURN_RIGHT=3**——零值/未初始化/未知值一律落在 idle（不动）。
7. **Topic 命名**：`bsi/cmd_discrete`。
8. **静默语义**：订阅端 **1s** 无新包 → 判通信丢失，BSI 源归 idle（twist 渐 0 停步），恢复通信自动恢复。比摇杆 stale 0.5s 宽（10Hz 下需连丢 10 包）。频率要求 **≥10Hz** 锁进协议（deadline 0.5s = 2 倍容限）。
9. **包序策略**：到达序即生效（best-effort 局域网内乱序罕见），seq 不做拒旧处理；DDS reader 按到达序出包，provider 取「最新到达」意图。
10. **进程拓扑**：点对点直连（上位机进程直接用 `bsi_dds` 包发布，仿真进程内订阅），无中继守护进程；「通信进程管理」= 可选启动/健康检查工具集。

**兼容性策略**：枚举只增不改；breaking 变更 = 换 topic 名（version 字段不进 schema）。

**环境事实依据**（查证于本仓）：unitree SDK `ChannelFactoryInitialize(id=0)` 单例 participant、QoS 全传 None（DDS 默认 best-effort/volatile）；IDL 为 idlc v0.11.0 生成 dataclass 惯例；Teleopit 运行时目前零 DDS 依赖，`CommandProvider` seam（`teleopit/commands/base.py`）干净。

**产物去向**：协议文档（`docs/protocol.md` + IDL 源）落 BSI_DDSInterface 仓库（ticket 06 骨架的输入）；映射参数（T2）与静默阈值 1s 在 Teleopit 侧 provider 复用本决议。
