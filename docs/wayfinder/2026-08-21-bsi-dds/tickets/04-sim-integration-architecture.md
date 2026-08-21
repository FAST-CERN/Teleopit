---
id: bsi-dds-04
title: "pico4 仿真接线架构：BSI 与摇杆并联的融合层选择"
labels: [wayfinder:grilling]
status: open
assignee: ""
blocked-by: [bsi-dds-02]
created: 2026-08-21
---

## Question

BSI provider 与 Pico 摇杆「摇杆非零优先、摇杆零时 BSI 生效」的融合，在哪一层实现？

- **方案 A：provider 层组合**——新建 `MergedTwistProvider(joystick, bsi)`，对 session 仍是单个 CommandProvider，pipeline 自动选择逻辑不动。
- **方案 B：会话层多 provider**——SimLoopSession/VelocityStepController 感知多个指令源，融合逻辑进会话。
- 权衡：A 改动面最小、可单测、seam 干净；B 会话能看到指令来源（UI/日志可区分脑控 vs 手控），但动核心循环。
- 附带决定：BSI provider 的构造与配置挂在哪（`command:` 配置节的形状——`command.provider: merged` + 子配置？）；bvh/udp 键盘 fallback 通路要不要也能挂 BSI（倾向先不，留雾）。
- V/X 模式键归属确认：仍 Pico 侧/会话键驱动，BSI 不碰状态机（charting 已定，接线时核对实现即可）。

产出：接线架构决定 + 配置节形状，实现走后续 plan。
