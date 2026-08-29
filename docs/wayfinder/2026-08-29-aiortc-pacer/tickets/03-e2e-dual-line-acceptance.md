---
id: 03-e2e-dual-line-acceptance
title: "真机 e2e 双线验收与剂量曲线复测"
labels: [wayfinder:acceptance]
status: open
assignee: ""
blocked-by: [02-teleimager-pacer-impl]
---

## Question

pacer 开启后，头显端真机复测 zed-fpv ticket 06 的剂量曲线并按 map 双线验收：

1. 剂量曲线复测：2M / 4M / 8M 三档下 avgJitterBuffer 与 e2e（时间码照片法 + APK stats 日志），对照无 pacer 基线（150/112/78ms）——**曲线应拉平**（对码率不再敏感）。
2. 双线判定：可用线 ≥4M 下 buffer <40ms 且 e2e <100ms；良好线 buffer <30ms 且 e2e <80ms。
3. 画质回补：4M（或 8M）下主观画质确认（pacer 的意义就是买回画质）。
4. 稳定性：pacer 开启 10 分钟佩戴无断流；断线重连不劣化。
5. 记录最终参数组合（pacer 默认值、bitrate 定稿、aiortc 版本 pin）并宣告 map 终点。

## Resolution

（待填）
