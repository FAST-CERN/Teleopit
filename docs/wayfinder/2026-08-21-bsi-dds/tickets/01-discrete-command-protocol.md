---
id: bsi-dds-01
title: "BSI 离散指令 DDS 协议设计（topic/QoS/schema/四态枚举）"
labels: [wayfinder:grilling]
status: open
assignee: ""
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
