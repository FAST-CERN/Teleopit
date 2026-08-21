---
id: bsi-dds-05
title: "BSI 模式 keymap 重排：Pico 摇杆/键盘键位分配与冲突排查"
labels: [wayfinder:grilling]
status: closed
assignee: "claude/main"
blocked-by: [bsi-dds-03]
created: 2026-08-21
---

## Question

急停键引入 + BSI 使能切换（如果有）后，完整键位表重排：

- **键盘侧**：现有 W/S/J/L/N/M/K（twist）+ 会话键 h q y v x a b r space p 全占。急停键选哪个（候选：`t` terminate/stop？`0`？）；BSI 使能/禁用切换键要不要（BSI 不碰状态机，但操作者要不要能一键哑掉脑控源）？
- **Pico 手柄侧**：摇杆 L/R 已占平移/转向；按键面（A/B/X/Y、grip、trigger、menu）分配急停 + BSI 哑音；注意 pico-bridge 现有按键映射到 Teleopit 的通道里还剩哪些可用（需查证 controller state 的按键位掩码）。
- **冲突排查**：新键不得与 tee 双消费者路径再撞车（task #6 的 q/a/x 三连撞教训）；键盘 fallback 与 run_velocity_sim.py 双入口的键位一致性。
- 输出更新到 H 键帮助文本的键位表。

产出：双端键位分配表（键盘 + 手柄）+ 与急停 ticket 的联动确认。

## Resolution

**2026-08-21 grilling 锁定**：

**键盘键位表**（双入口 `session.py` / `run_velocity_sim.py` 一致）：

| 键 | 功能 | 状态 |
|---|---|---|
| W/S, J/L, N/M | 前后/平移/转向 | 不变 |
| K | 急零 twist | 不变 |
| **E** | **急停 toggle（锁存→STANDING）** | 新增（T3） |
| **C** | **BSI 哑音 toggle（cut 脑控源）** | 新增（本 ticket） |
| h q y v x a b r space p t Esc | 会话键 | 不变 |

E/C 均在左手区（W/S 手位上方），应急动线集中；与 tee 双消费者路径零冲突（不在 `_KEY_MAP` 也不在会话键表）；闲字母余量 `d f g i o u z`。

**Pico 手柄键位表**：

| 输入 | 功能 | 状态 |
|---|---|---|
| L 摇杆 / R 摇杆 | 平移 / 转向 | 不变 |
| 右手 A / B | 暂停 / arms | 不变 |
| **右手 menuButton** | **急停 toggle** | 新增（T3） |
| **左手 Y**（left secondaryButton） | **BSI 哑音 toggle** | 新增（本 ticket） |
| 左手 X、左手 menuButton、axisClick | 保留未来 | 未分配 |

左右手对称分工：右手管安全（急停），左手管源控制（哑音）；左手 X 刻意不占（与键盘 `x` 退 VELOCITY 重名，避免双端认知混淆）。

**哑音语义**（本 ticket 新锁）：provider 层 toggle——BSI 输出强制 idle（平滑归 0），DDS 订阅不断（解除即恢复，无重连延迟）；不影响摇杆、不碰模式状态机。分层：急停=全部源+切 STANDING（会话层），哑音=只关 BSI、模式不变（provider 层）——与 T4「融合在 provider、安全在会话」一致。

**反馈**：key_feedback（mute/unmute 各一条，result 字段标 live/muted）+ WARNING 日志；H 帮助文本加急停/哑音两行；HMD 不加叠层（与 T3 一致）。

**冲突排查结论**：E/C 与现有全部键位（含 T 扰动键）、手柄按键面（A/B/menuButton/Y）零冲突；`_poll_button_control_event` 上升沿+防抖模式可直接复用于两个新按钮路径（急停走 ControlEvent 新类型，哑音同构）。

**联动确认**：T3 键位（E + 右 menuButton）原样进本表；T4 `merged_bsi` 配置下哑音键仅对 BSI provider 生效（纯摇杆模式下按 C 反馈 ignored）。
