---
id: 05-unity-stereo-immersive-design
title: "Unity 沉浸立体渲染设计与原型"
labels: [wayfinder:prototype]
status: closed
assignee: "claude-main"
blocked-by: [01-build-environment, 03-televuer-immersive-rendering]
---

## Question

pico-bridge APK 的沉浸 FPV 模式如何设计：SBS 帧拆分到左右眼的渲染方案、image plane 摆位、模式进出交互、与现有面板/追踪功能的共存结构？

先用 `/grilling` + `/domain-modeling` 定方案，再用 `/prototype` 在 fork 的 `feat/stereo-fpv` 分支上做可戴上的场景桩（可先用 PC 本地推 SBS 测试帧，不必等真实流）。

需决策的点：

1. SBS 拆分层：material UV offset（两 quad 共享一纹理）vs 双相机 vs shader 重映射 — 权衡清晰度、改动面、与 WebRtcCameraReceiver 纹理输出的耦合。
2. 沉浸模式载体：独立 Scene vs 在主场景加状态切换；进入/退出手势或面板按钮。
3. Plane 摆位初值（吃 ticket 03 的研究结论）：头锁定（本 map 既定），距离/尺寸/垂直偏移。
4. 与 mono 预览面板的关系：沉浸模式下隐藏面板还是保留切换。
5. HTTP 信令客户端（吃 ticket 02 结论）在本 ticket 的落点：先做渲染、信令留桩，还是一并实现。

产出：设计决策记录 + fork 分支上的可运行原型（Pico 上能进入沉浸模式看到本地测试立体帧）。

## Resolution

**2026-08-22 完成，Pico 4 真机验证通过**（立体深度感 + per-eye 采样正确 + 方向正确）。提交：fork `feat/stereo-fpv` `324ba50`。

**设计决策**（全部按 grilling 共识落地）：

1. SBS 拆分 = 单纹理 + `StereoSbsQuad` shader（Resources/，`unity_StereoEyeIndex` UV 半幅偏移；Multi Pass 与 Single Pass Instanced 均兼容）
2. 模式载体 = 同场景 `StereoImmersiveRig`（Bootstrap 运行时自组装，工程惯例），面板绿色「沉浸 FPV」按钮进入、右手柄 grip 退出
3. Plane = 锁头公告板，距离 2m、高 1.66m（~45° 垂直张角）、per-eye 16:9、无垂直偏移、unlit、黑面罩
4. 视频源 = PC receiver 新增 `sbs-test-pattern`（左右半幅带 视差白柱 + L/R 角标），真实流接口 `SetVideoTexture(Texture)` 就绪

**调试过程中修掉的四个真机 bug**（对 ticket 06 有复用价值）：

- shader 被打包剥离 → 移入 `Resources/`（`Shader.Find` 失败时 `Resources.Load` 兜底；失败必须 `Destroy(gameObject)` 否则残留白 quad）
- **Pico H.264 硬解拒绝非标 1280x480** → 请求改 2560x720 SBS（与 teleimager 基线一致）
- **`pc.addTrack()` 让头显 answer 选 VP8，aiortc 的 VP8 编码器对 SBS 宽度零输出且无报错** → 改 `addTransceiver + setCodecPreferences(H264)`（teleimager 同款修法）
- **进入沉浸模式 = 隐藏面板 = `PanelController.OnDisable → StopPreview()` 杀掉视频流**（头显 2.5s 断 TCP）→ 沉浸活跃时跳过 StopPreview
- WebRTC 接收纹理是 top-down，shader `_FLIP_Y` 默认必须为 0（开启则上下颠倒）
