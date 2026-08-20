---
id: 06-e2e-stereo-latency
title: "端到端立体链路打通与延迟调优"
labels: [wayfinder:prototype]
status: open
assignee: ""
blocked-by: [02-unity-webrtc-aiortc-interop, 04-jetson-baseline, 05-unity-stereo-immersive-design]
---

## Question

全链路（ZED Mini → zed_xr_bridge → teleimager → HTTP 信令 WebRTC 单跳 → Pico 4 pico-bridge APK 沉浸模式双目渲染）能否打通，运动到成像延迟能否首次 <250ms、调优后 <150ms？

子步骤：

1. 在 ticket 05 原型上接入真实流：Unity HTTP 信令客户端连 teleimager `/offer`，沉浸模式显示 ZED SBS 实时画面。
2. 延迟测量：同 ticket 04 方法（遮挡/闪光 + 双机对拍逐帧），对照基线算 Unity 链路增量。
3. 若超标，按序调优：teleimager bitrate/GOP（cam_config 的 webrtc 段）、分辨率降档（HD720→VGA）、帧率、Unity 侧纹理路径。
4. 稳定性：连续佩戴 10 分钟无断流、无追踪通道干扰；WebRTC 断线后重连可用。
5. 主观验收：深度感真实（近处物体伸手可判断距离）、无不可忍受晕动。

Resolution 时记录：各阶段延迟数字、最终参数组合、遗留问题。达标即宣告 map 终点达成。
