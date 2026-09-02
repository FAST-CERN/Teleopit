---
id: 03-unity-motion-collection
title: "Unity 采集实装：Motion 数据面上行（2 tracker + SN 绑定 + panel 开关）"
labels: [wayfinder:prototype]
status: open
assignee: ""
blocked-by: ["01-tracker-sdk-semantics", "02-unity-build-env"]
---

## Question

`PicoTrackingCollector.AppendMotion()` 从占位变实装（原型票，做出可装的 APK 供人上手）：

1. 采集循环：按 01 的语义读 2 个 tracker 位姿（SN 绑定左右手），入 `Motion` JSON 字段——结构定稿（与占位 `{"joints":[],"len":0}` 兼容升级，含 per-tracker SN/状态/位姿），坐标约定对齐现有 body/hand 处理；
2. SN 绑定 UX：panel 加绑定/显示（或配置文件固定 SN），连接丢失的降级（字段置空 vs 发占位）；
3. `PicoBridgeManager` 加 `sendMotion` 开关（默认值讨论：默认关，与 sendBody 同风格?）；
4. 出包装机（HITL：Pico 侧 APK 安装、tracker 与手套固定）；
5. 顺手项（开票后定）：硬编码 `/offer` URL 改可配置——若做，清 1080p 图同款欠账。

验收：真机 TCP 流里 `Motion` 字段带 2 tracker 位姿、72Hz 帧率不塌、与 Head/Controller 同帧串流。

**欠账带入**（04 已闭挂此）：装机后真机 Motion 流录一段 JSONL → `from_tracking_payload` 回放，确认 `trackers` 解析通过（04 Resolution §6）。
