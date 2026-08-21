---
id: bsi-dds-03
title: "急停设计：键位 + 渐0→STANDING 语义 + keymap 影响"
labels: [wayfinder:grilling]
status: open
assignee: ""
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
