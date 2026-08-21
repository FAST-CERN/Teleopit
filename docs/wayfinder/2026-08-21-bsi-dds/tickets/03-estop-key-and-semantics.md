---
id: bsi-dds-03
title: "急停设计：键位 + 渐0→STANDING 语义 + keymap 影响"
labels: [wayfinder:grilling]
status: closed
assignee: "claude/main"
blocked-by: []
created: 2026-08-21
---

## Question

BSI 模式下的操作者急停怎么做？已定语义骨架：**cmd_vel 渐 0 → 切 STANDING**（非 damping）；joint-vel 超限/过速→damping 维持原行为（velocity_session 既有安全层不动）。待定：

- **键位**：Pico 手柄侧（摇杆按键 R/L 按下？ grip？）+ 键盘侧（哪个键不与现有 W/S/J/L/N/M/K 及会话键 h q y v x a b r space p 冲突）。急停是否同时也作为普通 VELOCITY（纯摇杆）模式的急停——即它是**会话级**新增而非 BSI 专属？
- **渐 0 时长**：多长的 ramp（与 X 退出 VELOCITY 的 pose-B 缓动怎么配合——先 vel 渐 0 再走 X 的切换流程，还是一步合并）？
- **优先级**：急停按下期间 BSI/摇杆指令是否被抑制（防松开急停后残余 twist 立即恢复行走）？需要「重新使能」动作吗？
- **UI/日志反馈**：HMD 侧/控制台怎么显示急停状态？

产出：急停行为规格（键位表更新 + 状态机交互图），实现走后续 plan。

## Resolution

**2026-08-21 grilling 锁定**：

1. **作用域**：会话级新增——任何 VELOCITY 会话可用（含纯摇杆），非 BSI 专属。安全键不区分指令源。
2. **语义链路**：触发 → 目标 twist **0.3s 渐 0**（指数收敛加速）→ 既有 `exit_velocity_to_standing` 缓动（pose-B yaw 对齐）→ STANDING。完整停步 <1.5s，非 damping。joint-vel 超限/过速 → damping（velocity_session 既有安全层）不动，与急停并存。
3. **键位（双端对称 toggle）**：
   - Pico 手柄：**右手 menuButton**（deliberate 按压不误触；A/B 已占暂停/arms，摇杆占平移/转向，grip/trigger 为模拟量不做阈值键）。
   - 键盘：**E**（emergency，闲字母 c d e f g i o u z 中最佳 mnemonic，与现有全部键位零冲突——含 T 扰动调试键）。
   - Esc→STOP（damping）语义保留不变，velocity_session 双入口不动。
4. **抑制与恢复**：急停**锁存**——触发后抑制所有指令源（BSI+摇杆+键盘），防脑控持续 FORWARD 绕过急停；解锁 = **同键再按**（toggle，与 A 键暂停模式一致）；回到 STANDING 后锁自动清除（状态机重建复位）。
5. **反馈**：控制台 key_feedback（触发/解锁各一条）+ 日志 WARNING；HMD 不加叠层（视频通道只传画面，超出本图）。

**对 keymap ticket（05）的输出**：E + menuButton 进键位表；toggle 模式进 H 帮助文本；BSI 哑音键是否需要留给 05。

**环境事实依据**（查证于本仓）：pico_bridge frames 每侧手柄暴露 primaryButton/secondaryButton/axisClick/menuButton + grip/trigger 模拟量；A=`("right","primaryButton")` 已占暂停、B=`("right","secondaryButton")` 已占 arms（`_poll_button_control_event` 上升沿+防抖模式可复用）；键盘 T 已被占用为扰动调试键（`velocity_session._handle_keyboard`）；X 退出路径 = `session.exit_velocity_to_standing()`（目标归 0 与 pose-B 缓动一步走）。
