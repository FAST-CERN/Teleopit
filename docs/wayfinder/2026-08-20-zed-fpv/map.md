---
id: zed-fpv-map
title: "ZED Mini 立体 FPV：G1 → Pico 4 pico-bridge APK"
labels: [wayfinder:map]
status: closed
created: 2026-08-20
---

## Destination

真实硬件端到端立体 FPV 演示：ZED Mini 装在宇树 G1 头部，Jetson 上 g1_zed_bridge（ZMQ IPC）→ teleimager（aiortc H.264 WebRTC 单跳）直连 Pico 4 上 fork 的 pico-bridge APK；佩戴者进入沉浸 FPV 模式，左右眼分别看到 ZED 校正图像、具有真实深度感。运动到成像延迟 <250ms 为可用线，<150ms 为调优目标。

## Notes

**领域**：Unitree G1 遥操作第一人称双目视觉（纯视觉 FPV，不含控制回路）。

**组件与位置**（charting 时已查实）：

- `g1_zed_bridge` — F:\Chufan_Rui\teleop\g1_zed_bridge（FAST-CERN fork）。C++ 进程 `zed_xr_bridge`，ZED SDK 采集校正 SBS 立体帧（左眼在左），BGR8，ZMQ PUB `ipc:///tmp/zed_xr_head.ipc`。已在 Jetson (aarch64, ZED SDK 5.0.7) 验证。
- `teleimager` — F:\Chufan_Rui\teleop\teleimager（FAST-CERN fork）。`type: zed_bridge` 相机已实现（commit `7e739bb`），`binocular: true` 走 SBS 拼帧。WebRTC 栈为 aiortc，信令为 HTTP POST `/offer`（浏览器式）。配置参考 `cam_config_server.yaml` 内注释块。
- `pico-bridge` — F:\Chufan_Rui\teleop\pico-bridge（上游 BotRunner64，**待 fork 到 FAST-CERN**，分支 `feat/stereo-fpv`）。Unity 2022.3.62f3。现状：视频回传走 PC push → WebRTC → 头显 mono `RawImage` 面板（`WebRtcCameraReceiver.cs` + `PicoBridgePanelView.cs`）；信令走 TCP（PC 发 offer，APK 应答）。**缺口：无立体渲染、无 HTTP 信令客户端。**
- `televuer` — github.com/unitreerobotics/televuer。**仅参考实现**，不进链路：vuer 封装的浏览器 WebXR 路径，immersive/ego 模式，V4.0 有 image plane 高度调优经验可抄。

**Charting 会话锁定的边界决策**（详情见各 ticket）：

- 传输：直连单跳（Unity 新增 HTTP 信令客户端，直连 teleimager `/offer`；一次编码一次解码）。
- 头动行为：沉浸画面为**头锁定 image plane 被动渲染**；头动→G1 头部的映射与控制已有实现，不在本 map。
- 延迟验收：运动到成像法（摄像头前拍手/闪 LED + 头显对拍），<250ms 首次达标，<150ms 调优目标。
- 构建闭环在本 Windows 机（Unity 2022.3.62f3 + Android Build Support，当前**未安装**）。

**Skills**：grilling/prototype 类 ticket 先 `/grilling` + `/domain-modeling`，需要实物反应时 `/prototype`；research 类由 `/research` 子代理解决。

**Tracker 约定**（本地 markdown fallback）：

- Ticket = `tickets/NN-*.md`，frontmatter：`labels`（含 `wayfinder:<type>`）、`status: open|closed`、`assignee`（空为未认领）、`blocked-by`（ticket id 列表）。
- Frontier = status:open 且 blocked-by 全部 closed 且 assignee 为空的 ticket。
- Claim = 在 frontmatter `assignee` 填入驱动者标识。
- Resolve = 正文追加 `## Resolution` 章节、`status: closed`、并在本 map 的 Decisions so far 追加一行。
- 研究产物放 `research/` 目录，ticket 内链接指向。

## Decisions so far

- [Unity.WebRTC ↔ teleimager /offer 信令互通性](tickets/02-unity-webrtc-aiortc-interop.md) — **互通可行、风险偏低**：POST `/offer`（HTTPS 自签名证书需 Unity 侧 CertificateHandler 绕过）、ICE 为 vanilla 非 trickle（候选须嵌进 offer SDP 再 POST）、aiortc H264 baseline 按 SPS 硬解兼容 Pico 4；Unity.WebRTC 3.0.0-pre.7，改造面 = 新增 HTTP 信令客户端（RecvOnly → CreateOffer → 等 ICE → POST → SetRemoteDescription），复用现有 peer/纹理/看门狗。详见 [research/02](research/02-unity-webrtc-aiortc-interop.md)。
- [televuer immersive 渲染机制研究](tickets/03-televuer-immersive-rendering.md) — 机制已拆解：SBS 分发首选**单纹理 + Single Pass Instanced shader 按 `unity_StereoEyeIndex` 做 UV 半幅偏移**（同构 vuer VideoMaterial，零拷贝）；plane 为**锁头公告板**，immersive 初值 height=1m @ 距离 1m（zmq 实测值），无垂直偏移、unlit、bilinear；抗晕动三件套 = 面罩暗角（plane 张角 < 头显 FOV）+ ego 小窗降级模式 + 接受 30fps（延迟优先于帧率）。详见 [research/03](research/03-televuer-immersive-rendering.md)。
- [Jetson 侧基线验证](tickets/04-jetson-baseline.md) — **真机验证通过**：zed_bridge → teleimager WebRTC → Pico 浏览器，720P@30fps 正常，主观无延迟感（未做逐帧精确测量）。结论：网络+编码段余量充足，端到端若超标瓶颈在 Unity 侧。
- [Unity 沉浸立体渲染设计与原型](tickets/05-unity-stereo-immersive-design.md) — **Pico 4 真机验证通过**（立体深度 + per-eye 正确）。方案：单纹理 StereoSbsQuad shader（unity_StereoEyeIndex 半幅采样）+ 锁头 quad（2m/1.66m/16:9）+ 同场景状态切换 + sbs-test-pattern 视差测试源。四个真机坑已修：shader 剥离→Resources/、Pico 拒 1280x480→2560x720、addTrack 被 answer VP8 零输出→setCodecPreferences(H264)、进沉浸隐藏面板触发 StopPreview 杀流→跳过。提交 324ba50。
- [构建环境就绪](tickets/01-build-environment.md) — **已完成并全链验证**（fork = FAST-CERN/pico-bridge `feat/stereo-fpv`；Unity 2022.3.62f3 + Android 模块装 F 盘；CLI 构建入口一次通过；APK 已装 Pico 4，连接 + 彩条 + 追踪验证 OK）。关键坑：头显 USB 须选"传输文件"模式才枚举 ADB；wheel 0.2.1 的 PicoBridge() 必须显式 .start() 否则静默无监听；Unity Personal license 8/31 到期需续。

- [端到端立体链路打通与延迟调优](tickets/06-e2e-stereo-latency.md) — **2026-08-29 全链真机验收通过，map 终点达成**：首次 220ms < 250ms 可用线，调优后 **~120ms < 150ms 目标线**。新增 `WebRtcHttpSignalingClient`（HTTP POST /offer offerer，候选实测自动内嵌）+ 双源沉浸控制器（pico-bridge `353d70c`）。根因：aiortc 无 pacer 的帧突发 → 到达抖动 → jitter buffer 抬升（8M/4M/2M 剂量效应 150/112/78ms）；定稿 bitrate 2M + GOP 30。修 2 个握手期 NRE。稳定性/重连/主观深度全过。后续候选：发送端 pacer、NVENC 硬编、60fps、专用 AP。

## Not yet specified

- Image plane 几何标定：距离、尺寸、FOV 的实测微调区间（初值已有：height=1m @ 1m，来自 ticket 03），以及 ZED 基线 (~63mm) 与佩戴者 IPD 差异的补偿策略 — 待 ticket 05 原型戴上后升格。
- 码率/分辨率/帧率权衡：HD720@30 SBS（packed 1280x480）在 WiFi 单跳下的 H.264 档位；teleimager 的 bitrate/GOP 配置调整（当前 2M/5M/12M + GOP 60）— 待 ticket 04 基线数据后升格。
- 与既有手部追踪会话的共存：沉浸模式与追踪通道并行时的稳定性（追踪数据仍走 TCP，视觉走 HTTP+WebRTC，互不阻塞？）— 待 ticket 05/06 集成时升格。
- 沉浸模式下 WebRTC 断线重连的状态机与 UI 行为（research/02 建议移植 JS 客户端的 5s 无帧重连策略）— 待 ticket 06 稳定性阶段升格。
- ZED Mini 在 G1 头部的物理安装与线缆约束（若尚未装好）。

## Out of scope

- 头动→G1 头部控制映射（已存在于其他链路，本 map 只做头锁定被动渲染）。
- 手部追踪→G1 控制回路集成（pico-bridge 追踪数据流已验证，拼装属下一张 map）。
- televuer 浏览器链路的维护或增强（只读其源码作参考）。
- 向上游 BotRunner64/pico-bridge 回馈 PR（fork 内开发即可，回馈是可选后续）。
