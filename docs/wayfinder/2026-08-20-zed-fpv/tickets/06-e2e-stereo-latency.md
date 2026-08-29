---
id: 06-e2e-stereo-latency
title: "端到端立体链路打通与延迟调优"
labels: [wayfinder:prototype]
status: closed
assignee: "claude-main"
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

## Resolution

**2026-08-29 完成，全链真机验收通过。首次 220ms < 250ms 可用线；调优后 ~120ms（峰值）< 150ms 目标线。**

**新增代码**（pico-bridge `feat/stereo-fpv` `353d70c`）：

- `WebRtcHttpSignalingClient` — offerer：`AddTransceiver(TrackKind.Video)+RecvOnly → CreateOffer → SetLocalDescription → 等 GatheringState.Complete → POST /offer（CertificateHandler 绕自签 + Content-Type: application/json + codec 字段）→ SetRemoteDescription`。实测 **libwebrtc 的 LocalDescription.sdp 自动内嵌候选**（embedded=True，研究02 风险2 解除），候选手工修补函数留作保险。自监督重试（Update 轮询 ShouldRetry 重新 POST——沉浸期面板隐藏、无人驱动重试，故必须自治）。每 5s 打 inbound-rtp stats（decodeFps/avgJitterBuffer/packetsLost）。
- `WebRtcSignalingProtocol` — 纯 SDP/JSON 逻辑独立成类（无 Unity 依赖），`tools/SignalingProtocolTests` dotnet 测试壳 19 断言全绿。
- `StereoImmersiveController` 双源择优：直连真流有帧优先，PC-push（sbs-test-pattern）兜底；进沉浸自动握手、grip 退出即停。

**调试修掉的真机 bug**：① 握手 5s+ 期间（服务端 aiortc 跨 4 网口收 ICE 慢）退出沉浸 → StopStream 不停握手协程 → NRE（修：StopStream 停 `_connectCoroutine` + 协程每个 yield 后 `_peer == null` 守卫）；② 首帧前黑屏期 ~6-10s 属正常（POST 5.3s + I 帧 + 解码启动），需等 15s 再判。

**延迟根因与剂量效应**（GetStats 归因 + 时间码照片法）：

| 码率 | avgJitterBuffer | 丢包 | 端到端 |
|---|---|---|---|
| 8M | 150-165ms 持续爬升 | ~1.5%/s 级 NACK 风暴 | ~220ms |
| 4M | 112ms 稳定 | ≈0 | ~200ms |
| **2M（定稿）** | **78ms** | **0** | **~120ms** |

链路：**aiortc 发送端无 pacer → 每帧 ~17kB 背靠背突发 → WiFi 排队抖动 → libwebrtc 抬 jitter buffer**。码率＝突发大小，剂量效应单调。Jetson 软编 66% CPU 非瓶颈（decodeFps 恒 30）。`jitterBufferTargetDelay` stat 疯涨至数百秒为 libwebrtc 报数口径异常，实测 avg 才是真值。

**测量基建**（teleimager `zed-bridge` `6f2c365` 等）：帧内双半幅毫秒墙钟叠印（`TELEIMAGER_OVERLAY_CLOCK=0` 关）+ `entry/overlay_clock.py` 全屏同源钟——单张照片读延迟；APK stats 日志归因。

**最终参数**：`webrtc: bitrate default 2M / gop 30`，HD720 SBS 2560x720@30 H264（`cam_config_zed.yaml`）。

**验收**：10 分钟连续佩戴无断流 ✅；watchdog 断线重连 ✅；主观深度感（近距离伸手判距）✅。

**遗留（后续 map 候选）**：aiortc 发送端 pacer（再砍 ~50ms 上限，真正解耦码率与延迟）；Jetson NVENC 硬编（省 ~15ms + CPU）；60fps 采集（需硬编先行）；专用 5GHz AP；Pico 拒非标分辨率的降档方案；双 env 双 checkout logging_mp 拓扑债（见跨会话记忆 jetson-teleimager-deploy-topology）。
