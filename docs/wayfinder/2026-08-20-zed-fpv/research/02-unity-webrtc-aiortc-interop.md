# 研究 02：Unity.WebRTC ↔ teleimager (aiortc) HTTP /offer 信令互通性

ticket: `02-unity-webrtc-aiortc-interop` · 日期：2026-08-20 · 所有结论默认「已从本地源码核实」，标注【训练知识】的条目来自模型对 aiortc / Unity.WebRTC / aiohttp / libwebrtc 的既有了解，需在 Jetson/头显上最终验证。

## 结论摘要

1. **可行，且风险偏低**。teleimager 是标准的「浏览器式 /offer 信令 + vanilla ICE（非 trickle）」aiortc 服务器（`image_server.py:410-495`）。Unity 侧只需要：`AddTransceiver(TrackKind.Video)` + `Direction=RecvOnly` → `CreateOffer` → `SetLocalDescription` → **等 ICE 收集完成** → POST `/offer` → `SetRemoteDescription(answer)`，一次 HTTP 往返即可建流。
2. **ice 双方都不 trickle**：客户端必须把候选者嵌进 offer SDP 再 POST；服务器 answer 自带全部 host 候选（aiortc 的 `setLocalDescription` 会先完成收集）。服务器没有任何 `/ice` 或 candidate 端点，POST 第二次会创建全新 PeerConnection（`image_server.py:431-432`）。
3. **编码兼容性已被本工程反向验证**：pico-bridge 现有 PC 推流端 `pc_receiver/webrtc_sender.py` 就是用 aiortc 做 offerer、Unity.WebRTC 3.0.0-pre.7 在 Pico 4 上做 answerer 解码 H.264 成功跑通的（`map.md` line 21）。新链路只是把角色对调（Unity 变 offerer、aiortc 变 answerer），媒体栈配对完全相同，H.264 协商预期成功。
4. **三个真实工程点**（不是协议问题，是实现细节）：HTTPS 自签名证书必须绕过 UnityWebRequest 校验；offer SDP 中候选者嵌入需在 3.0.0-pre.7 上实测 `LocalDescription.sdp` 是否含 `a=candidate`；SBS 大帧（2560x720）超过 aiortc 协商 level 3.1 的 MaxFS，但 Android 硬解按 SPS 配置、按码流解码，实践中可解，留 VP8 回退兜底。
5. 版本确认：**Unity.WebRTC = com.unity.webrtc 3.0.0-pre.7**（manifest + lock 双确认），Unity = **2022.3.62f3**。

## 协议细节（含代码行号引用）

### 1. 请求/响应 JSON schema（`image_server.py:410-495`）

**POST `/offer`**（HTTPS，见下），请求体 JSON：

```json
{
  "sdp": "<offer SDP 全文，含 \\r\\n>",
  "type": "offer",
  "codec": "h264"        // 可选，客户端覆盖服务器配置；null/缺省亦可
}
```

- 必填校验：缺 `sdp` 或 `type` → 400 `{"error": "Missing 'sdp' or 'type'"}`（`image_server.py:418-420`）。
- `codec` 优先级：**客户端 codec > 服务器 `webrtc_codec` 配置 > "h264"**（`image_server.py:441-442`，配置见 `cam_config_server.yaml:30`）。合法值 `h264` / `vp8`，其他值回落 H264（`image_server.py:460-466`）。它通过 `transceiver.setCodecPreferences()` 作用于 answer 端（`image_server.py:444-447`）。
- **必需 header：`Content-Type: application/json`**。服务器用 aiohttp 的 `request.json()`（`image_server.py:412`），该方法在 Content-Type 不是 application/json 时直接抛 TypeError【训练知识：aiohttp `web_request.py` 的 `json()` 默认 `content_type="application/json"` 并校验】，被 except 捕获后返回 400 "Invalid JSON body"。服务器自带 JS 客户端也显式设置了该头（`image_server.py:236`）。
- 协商失败（SDP 坏/编解码不交）→ 400 `{"error": "Negotiation failed: ..."}`（`image_server.py:480-485`）。

**响应 200**（`image_server.py:487-495`）：

```json
{"sdp": "<answer SDP，含服务器全部候选>", "type": "answer"}
```

带 CORS 头（`Access-Control-Allow-Origin: *` 等，Unity 原生客户端不涉及 CORS，仅浏览器需要；OPTIONS 预检路由在 `image_server.py:378-380, 388-396`）。

### 2. 传输层：HTTPS + 自签名证书（`image_server.py:519-521`）

信令站点强制 `ssl_context`（`cert.pem`/`key.pem`，路径逻辑 `image_server.py:62-73`，可用 `XR_TELEOP_CERT`/`XR_TELEOP_KEY` 环境变量覆盖，或 `~/.config/xr_teleoperate/cert.pem`）。即 URL 是 `https://<jetson-ip>:<webrtc_port>/offer`（默认端口 60001，`cam_config_server.yaml:28`）。**UnityWebRequest 默认会拒绝自签名证书，必须挂自定义 `CertificateHandler`（ValidateCertificate 返回 true）**。媒体面（ICE/DTLS/SRTP）走独立 UDP，不受此证书影响。

### 3. ICE：vanilla（非 trickle），双向内嵌候选

- **客户端行为（Unity 必须复刻）**，来自内嵌 JS 客户端 `negotiate()`（`image_server.py:209-247`）：
  1. `pc.addTransceiver('video', {direction:'recvonly'})`（line 210）；
  2. `createOffer()` → `setLocalDescription(offer)`；
  3. **等 `iceGatheringState === 'complete'`**（lines 214-226，无超时）；
  4. 取 `pc.localDescription`（此时浏览器已把候选合入 SDP）POST 出去；
  5. 收 answer 后 `setRemoteDescription(answer)`（lines 242-243）。
- **服务器侧 answer 自带候选**：`_offer` 的流程是 `setRemoteDescription(offer) → createAnswer() → setLocalDescription(answer)` 后**直接**返回 `pc.localDescription.sdp`（`image_server.py:476-489`）。aiortc 的 `setLocalDescription` 内部会 await ICE 收集完成，`localDescription` 因此含全部候选【训练知识：aiortc `RTCPeerConnection` 实现，其官方 webcam 示例同样直接 POST localDescription——teleimager 的 JS 就是照抄该示例】。服务器 `RTCPeerConnection()` 无任何 ICE server 配置（`image_server.py:431`），所以 answer 里只有 host 候选（Jetson 全部网口），无 srflx/relay —— 局域网单跳正合适。
- **Firefox mDNS 兼容分支**（`image_server.py:422-428`）：aioice 解析不了 `.local` mDNS 候选时删掉 `a=end-of-candidates` 保持 ICE 敞开。Unity.WebRTC 是原生 libwebrtc，默认不做 mDNS 混淆【训练知识】，offer 会带明文 host IP，不触发该分支。
- **服务器没有 trickle 端点**：若 Unity 的 offer 里没有候选（比如没等收集完就 POST，且 libwebrtc 的 `LocalDescription` 不含候选），ICE 将无从连线且无第二次补发机会——重发 POST 会新建一个 PeerConnection。这是本链路最关键的实现正确性点。

### 4. 轨道方向与媒体流（`image_server.py:434-439`）

服务器对每个会话 `relay.subscribe(track)` 后 `pc.addTransceiver(relayed_track, direction="sendonly")`——**只加一路 sendonly video，无 audio**。客户端 offer 带 `a=recvonly` 的 m=video，answer 即 sendonly。Unity 侧 offer **只放一个 video recvonly transceiver，不要加 audio**（多余 m 线在 answer 里会被置 inactive）。视频源是 BGR 帧 → `av.VideoFrame`（90kHz PTS，`image_server.py:311-349`），队列 maxsize=1、新帧覆盖旧帧（最新帧语义，lines 301, 340-349），MediaRelay 保证全局只编码一次（lines 434-436）。

### 5. H.264 编码与码控（`image_server.py:83-141` + `cam_config_server.yaml:6-11`）

- **aiortc H264 answer 固定参数【训练知识】**：`profile-level-id=42001f`（Baseline, level 3.1）、`packetization-mode=1`、`level-asymmetry-allowed=1`，这是 `aiortc/codecs/h264.py` 模块常量，aiortc 1.x 各版本长期如此。可用 `python -c "from aiortc import RTCRtpSender; print(RTCRtpSender.getCapabilities('video'))"` 在 Jetson 上核实。
- **实际码流参数**（比 SDP 更重要，硬解按 SPS 配置）：teleimager 把 `H264Encoder._encode_frame` 整个替换为 libx264 软编（`image_server.py:101-141`）：`preset=ultrafast`（无 CABAC、无 8x8dct → SPS profile 为 Baseline/Constrained Baseline，全设备可解【训练知识：x264 preset 推导】）、`tune=zerolatency`（无 B 帧、无 lookahead）、`threads=1`、`g=GOP`、`yuv420p`、码率=aiortc target_bitrate。
- **码率与 GOP 全局配置**（`_apply_webrtc_config`，`image_server.py:85-96`）：直接 setattr 到 aiortc 模块常量 `MIN/DEFAULT/MAX_BITRATE`（h264 与 vpx 同时设）。当前仓库配置：min 2M / default 5M / max 12M，`gop_length: 60`（`cam_config_server.yaml:7-11`）。分辨率变更时重建编码器并强制 I 帧（lines 102-103, 122）；每 GOP 手动补 I 帧（lines 127-131）。

## Unity 侧改造面

现状（answerer，`Assets/Scripts/PicoBridge/Camera/WebRtcCameraReceiver.cs`）：TCP 收 `WebRtcOffer`/`WebRtcIceCandidate` 函数帧 → SetRemoteDescription → CreateAnswer → TCP 回 `WebRtcAnswer`，候选经 TCP 双向 trickle（`WebRtcCameraReceiver.cs:113-168, 181-191, 244-258`；PC 侧对应 `pc_receiver/src/pico_bridge/webrtc_sender.py:163-211, 235-244`）。

改为 offerer 的新流程（新增一个 HTTP 信令客户端类，如 `WebRtcHttpSignalingClient`，复用 `WebRtcCameraReceiver` 的渲染/看门狗部分）：

1. `CreatePeer()` 大体可复用（`WebRtcCameraReceiver.cs:170-242`）：`RTCConfiguration` 空 iceServers（lines 175-178，局域网正确）、`OnConnectionStateChange`（lines 193-216）、`OnTrack` + `OnVideoReceived`（lines 218-241）、`WebRTC.Update()` 协程（lines 276-280）全部照旧。
2. 新增握手序列（协程）：
   - `var tr = _peer.AddTransceiver(TrackKind.Video); tr.Direction = RTCRtpTransceiverDirection.RecvOnly;`【训练知识：com.unity.webrtc 3.x 的 recv-only 官方姿势，包内 VideoReceive 样例即此写法】；
   - `CreateOffer()` → `SetLocalDescription`；
   - 等 `IceGatheringState == Complete`（或 OnIceCandidate 收尾）；
   - **确认 `LocalDescription.sdp` 含 `a=candidate:` 行**；若不含，把 OnIceCandidate 收集到的候选按 `a=candidate:...` + `a=end-of-candidates` 手工追加进 offer SDP 的 m=video 段再 POST【此点在 3.0.0-pre.7 需实测，见风险 2】；
   - `UnityWebRequest.Post` 到 `https://<jetson>:60001/offer`，`SetRequestHeader("Content-Type","application/json")`，body `{"sdp":...,"type":"offer","codec":"h264"}`，挂跳过校验的 `CertificateHandler`；
   - 解析 `{"sdp","type"}` → `SetRemoteDescription`。响应即含服务器候选，**无需再 AddIceCandidate**。
3. TCP 侧 `StartReceivePcCamera`/`WebRtcOffer`/`WebRtcIceCandidate` 通道保留不动（手部追踪仍走 TCP），视频信令完全独立，互不阻塞——这回答了 map.md 的共存问题：两通道无共享状态。
4. 重连：服务器每个 POST 新建 pc、failed/closed 时自我清理（`image_server.py:471-474, 497-501`），客户端重连=重新走一遍握手。现有 `ShouldRetry` 看门狗（`WebRtcCameraReceiver.cs:31-44`，10s 首帧超时/12s 断线重试）可直接复用。

## 兼容性风险清单

按严重度排序：

1. **HTTPS 自签名证书（高，必现）**：不做 CertificateHandler 绕过，POST 直接失败。Android 上还需确认不命中 cleartext 限制（本例是 https，无此问题）。
2. **offer SDP 候选嵌入（高，正确性）**：服务器无 trickle 端点，offer 无候选=必挂。Unity.WebRTC 3.0.0-pre.7 的 `LocalDescription.sdp` 在收集完成后是否已含候选【训练知识未定，libwebrtc 原生行为与浏览器有差异】——首日联调先用日志打印 SDP 确认，缺则手工拼接 OnIceCandidate 的候选。
3. **H264 SDP 协商参数错位（中低，理论性）**：aiortc answer 固定 `42001f`（level 3.1，MaxFS=3600 MB）；SBS 2560x720=7200 MB 超出 level 3.1 声明。但 (a) 本工程现有链路（aiortc offer 42001f → Unity 解码）已验证可跑；(b) Android MediaCodec 按 SPS/码流配置解码，不看 SDP level【训练知识】；(c) libwebrtc 对 `level-asymmetry-allowed=1` 的 answer 接受度与浏览器一致。若个别固件拒解，回退 VP8（服务器支持，`image_server.py:452-458`；其 JS 客户端同样内置 5s 无帧→VP8 重连兜底，`image_server.py:260-269, 277`，Unity 建议照抄该策略）。
4. **多网口候选与端口（中，部署性）**：answer 会带 Jetson 全部网口 host 候选【训练知识：aioice/ifaddr 枚举】，libwebrtc 会逐对尝试，选通的即可；但媒体 UDP 走 aioice 临时端口，Jetson 防火墙需放行入站 UDP（ticket 06 部署清单项）。
5. **入会关键帧等待（低，体验）**：GOP=60 @30fps，中途入会最长等 ~2s 才有 I 帧（`image_server.py:127-131` 的补 I 帧逻辑）；aiortc 对 PLI 的响应【训练知识：aiortc 发送端处理 PLI/FIR 请求强制关键帧】可缩短，但首帧延迟按 2s 估。若要更低，把 `gop_length` 调小（如 30）——代价是码率上升。
6. **aiortc 版本差异（低）**：`42001f` 固定值与 `setLocalDescription` 先收集的行为基于 aiortc 1.x 主线【训练知识】；teleimager 的 `pyproject.toml` 未 pin 版本（`aiortc` 裸依赖，line 22），Jetson 上以实机 `getCapabilities` 输出为准。

## 对 ticket 05、06 的实现要点

**ticket 05（Unity 立体沉浸设计）**：
- 新建 `WebRtcHttpSignalingClient`（offerer）：`AddTransceiver(TrackKind.Video)+RecvOnly → CreateOffer → SetLocalDescription → 等 IceGatheringComplete → POST /offer（https+自签绕过+Content-Type: application/json+可选 "codec":"h264"）→ SetRemoteDescription(answer)`。offer 中只放一个 recvonly video m 线。
- 候选嵌入策略做成可切换（`LocalDescription.sdp` 直用 vs OnVideoReceived 前手工追加候选），首版日志打印 SDP。
- `OnVideoReceived` 的 `Texture` 直接进 SBS 拆分渲染（项目已验证该事件在 Pico 4 Android 上出帧——现有 mono 预览即此路径，`WebRtcCameraReceiver.cs:223-237`）。
- 复用 `ShouldRetry` 看门狗 + 移植 JS 的「5s 无帧→VP8 重连」兜底；重连=重新 POST。
- 与 TCP 追踪通道完全解耦，不需要改 `PicoTcpClient`。

**ticket 06（e2e 延迟）**：
- 码率：`cam_config_server.yaml` 全局 `webrtc.bitrate`（当前 2M/5M/12M）是唯一码控入口；SBS 2560x720@30 建议 default 8M 起（ultrafast+x264 CRF 无，纯 CBR-ish bit_rate）。
- GOP：60（2s I 帧间隔）影响入会首帧与丢包恢复；追求低入会延迟可降到 30，注意码率余量。
- 编码已是 zerolatency/threads=1/最新帧覆盖（队列 maxsize=1），链路延迟主要剩：采集→ZMQ→编码（Jetson）+ 网络 + Unity 解码渲染。测延迟时以 `OnVideoReceived` 时间戳为锚。
- 部署清单：Jetson 放行信令 TCP 60001（TLS）+ aioice UDP 临时端口；头显与 Jetson 同网段（无 STUN/TURN）。

## 来源

本地源码（已核实）：
- `F:\Chufan_Rui\teleop\teleimager\src\teleimager\image_server.py` — `_apply_webrtc_config` L85-96；libx264 patch L101-141；CLIENT_JS L205-290（negotiate L209-247、VP8 兜底 L260-269/277）；路由与 CORS L374-396；`_offer` L410-495；TLS L519-521；`BGRArrayVideoStreamTrack` L295-349。
- `F:\Chufan_Rui\teleop\teleimager\cam_config_server.yaml` — 码率/GOP L6-11；端口/codec L26-30。
- `F:\Chufan_Rui\teleop\teleimager\pyproject.toml` — aiortc 裸依赖 L22。
- `F:\Chufan_Rui\teleop\pico-bridge\Packages\manifest.json` L41（com.unity.webrtc 3.0.0-pre.7）；`Packages\packages-lock.json` L180-190（registry 解析确认）。
- `F:\Chufan_Rui\teleop\pico-bridge\ProjectSettings\ProjectVersion.txt` L1（2022.3.62f3）。
- `F:\Chufan_Rui\teleop\pico-bridge\Assets\Scripts\PicoBridge\Camera\WebRtcCameraReceiver.cs` — answerer 流程 L113-168、peer 搭建 L170-242、看门狗 L31-44、Update 循环 L276-280。
- `F:\Chufan_Rui\teleop\pico-bridge\pc_receiver\src\pico_bridge\webrtc_sender.py` — PC 侧 aiortc offerer + TCP trickle L163-211, 235-244（反向角色已验证的证据）。

外部知识（训练知识，建议实测核对）：
- aiortc：`setLocalDescription` 先完成 ICE 收集、answer 含候选；H264 answer 固定 `profile-level-id=42001f; packetization-mode=1; level-asymmetry-allowed=1`（`aiortc/codecs/h264.py`）；PLI 强制关键帧。
- aiohttp：`request.json()` 强校验 Content-Type。
- Unity.WebRTC 3.0.0-pre.7：`AddTransceiver(TrackKind.Video)` + `Direction=RecvOnly` 为官方接收端姿势（包内 VideoReceive 样例）；`LocalDescription.sdp` 收集完成后是否含候选行不确定；libwebrtc 原生默认不用 mDNS；Android 走 MediaCodec 硬解、按 SPS 配置。
- x264：`ultrafast` → Baseline/Constrained Baseline SPS。
