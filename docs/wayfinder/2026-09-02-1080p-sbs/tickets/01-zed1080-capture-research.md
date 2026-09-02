---
id: 01-zed1080-capture-research
title: "采集面事实：ZED-M HD1080 模式 + zed_xr_bridge 输出尺寸参数"
labels: [wayfinder:research]
status: open
assignee: ""
blocked-by: []
---

## Question

升级的采集侧事实收齐（AFK 研究，产物进 `research/`）：

1. ZED SDK HD1080 模式约束：分辨率精确值（1920×1080?）、fps 上限（30）、FOV/裁切相对 HD720 的变化（画面内容损失与否）；
2. `zed_xr_bridge`（C++，`eeg_humanoid/teleop/xr_teleoperate/patch/zed_bridge/`）输出尺寸从哪参数化（`--output-height/width`？）、SBS 拼帧逻辑对 3840 宽是否有硬编码假设、发布协议（FrameHeaderV1 的 w/stride 字段）是否天然支持；
3. 采集→发布路径在 1080p 的带宽/拷贝代价（USB3 UVC 1080p30 = ~186MB/s YUV，实测关注点）；
4. cam_config 侧 `image_shape`/`fps` 需动的面。

## Resolution
