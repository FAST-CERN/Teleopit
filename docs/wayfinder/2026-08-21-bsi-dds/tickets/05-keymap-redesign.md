---
id: bsi-dds-05
title: "BSI 模式 keymap 重排：Pico 摇杆/键盘键位分配与冲突排查"
labels: [wayfinder:grilling]
status: open
assignee: ""
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
