---
id: 04-jetson-baseline
title: "Jetson 侧基线验证：zed_bridge → teleimager WebRTC → Pico 浏览器"
labels: [wayfinder:task]
status: closed
assignee: "user+claude-main"
blocked-by: []
---

## Question

不依赖任何 Unity 改动，Jetson→WiFi→Pico 这半条链路能否跑通并测出基线延迟？即：zed_xr_bridge 启动 → teleimager 以 `type: zed_bridge, binocular: true` 相机发布 WebRTC → Pico 4 浏览器打开流页面看到 SBS 立体画面。

子步骤（需真机 Jetson + ZED + Pico，人执行为主）：

1. Jetson 上启动 `zed_xr_bridge --resolution HD720 --fps 30 --output-width 1280 --output-height 480`。
2. teleimager 的 cam_config_server.yaml 启用 zed_bridge 相机（参考文件内注释块：endpoint、image_shape [480,1280]、binocular: true），启动 image server 开 WebRTC。
3. Pico 4 浏览器访问 WebRTC 流页，确认 30fps 左右、左右半幅内容有视差（可拍远近两个物体对比）。
4. 测运动到成像基线延迟：ZED 前快速遮挡/闪手机灯，另一手机同时拍 ZED 画面与头显画面，逐帧数差；记录 3 次取中位。
5. 记录 Jetson 编码负载（tegrastats：CPU/GPU/编码器占用）与 WiFi 信号环境。

Resolution 时记录：基线延迟 ms、帧率、卡顿情况、tegrastats 摘要、失败项（若有）。这是 ticket 06 调优的对照基线：Unity 链路的延迟增量 = 端到端 − 本基线。

## Resolution

**2026-08-20 用户在真机验证通过**：zed_xr_bridge → teleimager WebRTC → Pico 浏览器，**720P @ 30fps 正常，主观"无延迟感"**（未做逐帧对拍的精确 motion-to-photon 测量，主观验收通过）。

结论：Jetson→WiFi→Pico 半条链路就绪，H.264 SBS (packed 1280x480) 单跳在当前 WiFi 环境下带宽/延迟余量充足。ticket 06 的延迟调优若逐帧测量超标，瓶颈大概率在 Unity 侧（纹理路径/解码），而非网络与编码段。
