---
id: 07-pico-bridge-mode-mutex
title: "pico-bridge 模式互斥切换：上半身默认 vs 全身 body tracking，panel 二态 + 远程 set_body"
labels: [wayfinder:prototype]
status: open
assignee: claude
blocked-by: []
---

## Question

t06 主观轮诊断出 body 流「发但空」三因（panel `EnableAutomaticTrackingStreams` 无脑全开流覆盖 scene 默认；手套挡头显相机 → body 数据无效；app 从未调 `StartBodyTracking`）。需要一个**互斥的臂源模式切换**，让操作员在头盔内一键选「上半身 tracker 模式」（默认）或「全身 body 模式」（摘手套+拿手柄时用），替代现在流全开互相干扰的状态。

2026-09-04 21:22 grilling 定案（全部按推荐 settled）：

- **切换形态**：panel 二态按钮（SN 绑定状态一并显示，吸收 t03 panel 欠账）+ 接收端远程 `set_body` 下发——接收端为权威（`arm_source` 三态：`tracker` / `body` / `auto`？定案=三态，默认 tracker）。
- **全身模式开启**：app 调 `StartBodyTracking(BODY_JOINT_SET_BODY_FULL)`；骨长 = 比例表 × `human_height`（`BodyTrackingBoneLength` 为逐段长度结构体，非枚举——已核实）。
- **版本闸**：pc_receiver 0.2.4 + Teleopit 侧 gate 抬到 (0,2,4)。
- **回归**：需重编 APK（Unity 许可周滚签注意 StopDate）+ t03 冒烟（SN 绑定、69Hz、valid 语义）不回退。

验收：panel 切换生效且流互斥；tracker 模式行为与 cb46907 回归后一致；body 模式在摘手套+手柄场景能出有效 body 帧。

## Resolution

（待填）
