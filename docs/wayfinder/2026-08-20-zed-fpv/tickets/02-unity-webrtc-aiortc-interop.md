---
id: 02-unity-webrtc-aiortc-interop
title: "Unity.WebRTC ↔ teleimager (aiortc) HTTP /offer 信令互通性"
labels: [wayfinder:research]
status: closed
assignee: "research-subagent-02"
blocked-by: []
---

## Question

Unity.WebRTC（pico-bridge 工程所用版本）作为**纯接收端**，能否通过 HTTP POST `/offer` 信令与 teleimager 的 aiortc WebRTC 栈建立视频会话并解码 H.264 SBS 流？

需要回答的子问题：

1. teleimager `/offer` 的精确协议：请求体字段（sdp/type）、响应格式、ICE 处理（aiortc 是否 trickle、candidate 怎么走）、必需 headers（CORS/Content-Type）。源头：本地 F:\Chufan_Rui\teleop\teleimager\src\teleimager\image_server.py 的 `WebRTC_PublisherThread`、`_offer`、内嵌 HTML/JS 客户端（约 150–240 行）。
2. 信令方向：teleimager 是浏览器式（客户端 CreateOffer → POST → 服务器 answer）。Unity 侧需实现"CreateOffer → POST /offer → SetRemoteDescription(answer)"。现有 `WebRtcCameraReceiver.cs` 是 answerer（TCP 收 offer），确认改造为 offerer 的工作面。
3. 编码兼容：aiortc 的 H.264 编码参数（profile、packetization-mode、level）与 Unity.WebRTC 解码能力在 Android aarch64 上是否匹配；Unity.WebRTC 接收轨道输出纹理的路径（`VideoStreamTrack.OnVideoReceived`）对分辨率/像素格式有无约束。
4. pico-bridge 工程实际用的 Unity.WebRTC 版本（查 Packages/manifest.json），该版本在 Android 的接收端支持与已知 issue。

产出：`research/02-unity-webrtc-aiortc-interop.md`，含结论、风险清单、给 ticket 05/06 的实现要点、来源链接。

## Resolution

结论：**互通可行，风险偏低**。详见 `../research/02-unity-webrtc-aiortc-interop.md`。

- 协议（已从 `image_server.py:410-495` 核实）：POST `https://<jetson>:60001/offer`，body `{"sdp","type":"offer","codec"?}`，必需 `Content-Type: application/json`；响应 `{"sdp","type":"answer"}`。HTTPS 强制自签名证书——UnityWebRequest 必须挂 CertificateHandler 绕过。
- ICE 为 vanilla 非 trickle：客户端须等 `IceGatheringState==Complete` 把候选嵌进 offer 再 POST；answer 自带服务器全部 host 候选，客户端 SetRemoteDescription 即通，无需 AddIceCandidate。服务器无 candidate 端点，重复 POST 会新建 pc。
- 编码：aiortc answer H264 `42001f/packetization-mode=1`（训练知识），实际码流是 libx264 ultrafast+zerolatency（Baseline、无 B 帧），按 SPS 硬解，Android MediaCodec 兼容；本工程 aiortc→Unity.WebRTC 反向配对（`pc_receiver/webrtc_sender.py`）已在 Pico 4 验证。VP8 回退兜底建议移植 JS 的 5s 无帧重连策略。
- 版本：com.unity.webrtc **3.0.0-pre.7**（manifest+lock 双确认），Unity 2022.3.62f3。
- Top 风险：① 自签名证书必现拒绝；② 3.0.0-pre.7 的 `LocalDescription.sdp` 是否含 `a=candidate` 待实测（缺则手工追加）；③ SBS 2560x720 超 level 3.1 MaxFS（理论性，留 VP8 兜底）。
- Unity 改造面：新增 HTTP 信令客户端（AddTransceiver RecvOnly → CreateOffer → 等 ICE → POST → SetRemoteDescription），复用现有 peer 搭建/OnVideoReceived/看门狗；与 TCP 追踪通道解耦。
