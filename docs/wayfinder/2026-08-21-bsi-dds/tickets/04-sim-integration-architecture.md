---
id: bsi-dds-04
title: "pico4 仿真接线架构：BSI 与摇杆并联的融合层选择"
labels: [wayfinder:grilling]
status: closed
assignee: "claude/main"
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

## Resolution

**2026-08-21 grilling 锁定（7 项）**：

1. **融合层 = 方案 A（provider 层组合）**：新建 `MergedTwistProvider(joystick, bsi)`，对 session 仍是单个 `CommandProvider`；核心循环（`loop.attach_velocity_stack`、`VelocitySimSession` 步进路径）零改动，BSI 接入是纯增量。
2. **优先级裁决 = 整包互斥**：摇杆 `get_cmd` 非零向量 → 取摇杆整包；否则取 BSI 整包。任意时刻只有一个源生效，不逐轴叠加（避免脑控前进+手控转向的复合意图，行为空间可枚举）。
3. **切换平滑**：不加额外 ramp——BSI 内部 alpha 0.3 + 摇杆天然连续，幅值域相近（摇杆满推 1.0 vs BSI 0.6），直接切换跳变与键盘既有跳变同量级，既有平滑链路承接。
4. **配置节形状**：`command.provider: merged_bsi` 新枚举值（`pico_joystick`/`keyboard` 不动）；`command.bsi.*` 子节传静默阈值/防抖参数/映射幅值，`command.joystick.*` 照旧。默认行为零变化：不配 `merged_bsi` 就不建 BSI provider、不引 DDS import（submodule 缺席时现有测试不红）。
5. **DDS 生命周期**：`BsiTwistProvider` 内部自持订阅线程（reader callback → 最新意图缓存 → `get_cmd` 读缓存，`close()` 停线程），同 `PicoJoystickProvider` 快照缓存模式；单测注入假 reader。
6. **急停耦合**：锁存抑制在**会话层**（get_cmd 结果覆盖为零），`MergedTwistProvider` 不感知急停——安全层在会话、融合层在 provider，与 T3「会话级急停」分层一致。
7. **bvh/udp 通路**：先不接；`MergedTwistProvider` 构造签名接任意两个 `CommandProvider`（不绑 Pico input_provider），未来接入只需工厂分支加一段。
8. **V/X 归属核对**（查证 `session.py:399/406`）：V/X 仍由 session 键驱动，BSI 不碰状态机——与 charting 决策一致，无需改动。

**环境事实依据**：`pipeline.py::_attach_velocity_stack` 按 `command.provider` 构建单个 cmd_provider（pico_joystick/keyboard 二选一）传入 `attach_velocity_stack`；`VelocitySimSession.__init__` 只收一个 `command_provider`——方案 A 与现有接线点吻合。
