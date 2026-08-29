---
id: 02-teleimager-pacer-impl
title: "teleimager 内置 pacer 实现与 PC 端单机验证"
labels: [wayfinder:prototype]
status: open
assignee: ""
blocked-by: [01-aiortc-send-path-research]
---

## Question

按研究 ticket 选定的挂点，在 teleimager `image_server.py` 内实现 pacing（与现有 H264Encoder monkey-patch 同风格），并在**不戴头显**的前提下先于真机验收完成单机验证：

1. pacing 参数选型（摊平粒度/分布策略/超预算丢帧策略——吃研究结论 + map Not yet specified 的三个开放点在此升格）。
2. 配置开关：`webrtc.pacer: on|off`（yaml），默认先 off 保底，验收过后再定默认值。
3. 单机验证法：PC 浏览器（或 python aiortc 接收脚本）连 `/offer`，用 `getStats` 读接收端 jitterBufferDelay 对比 on/off——不依赖头显即可证伪/证实 pacing 效果。
4. 回归：NACK 丢包恢复延迟、PLI 关键帧时延在 pacing 下不劣化。
5. 部署：双 checkout 推送 + 运行 env import 冒烟（按 deploy-topology 记忆的流程）。

产出：patch 实现 + on/off 对照数据（研究/验证记录进本 ticket Resolution）。

## Resolution

（待填）
