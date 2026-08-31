# 参考实现 videoserver vs ZED Mini→Pico 图传链路对比研究

- 地图：`2026-08-29-aiortc-pacer`（研究产物，挂靠 ticket 01 的背景面）
- 日期：2026-08-29
- 研究问题：videoserver（`F:\Chufan_Rui\code_dig\video_trans\ref\videoserver`，上游 https://github.com/Linductor-alkaid/videoserver ，本地 git log 到 2025-05-07 `5a50975`，与上游 master 一致）的图传方案，对当前 zedmini↔pico 架构有没有可借鉴的改进点？
- 方法：全部结论以本地源码为准（`file:line` 引用）；aiortc 发送路径以本机 Python314 site-packages 里的 **aiortc 1.15.0** 为准（机器人 env 未 pin 版本，见 §8 源码风险）；网络补充（GitHub README/issue）被网络策略阻断，未采用。标注【推断】的条目是分析而非源码事实。

---

## TL;DR：最值得做的改进（按性价比排序）

1. **修复 monkey-patch 编码器丢掉的动态码率自适应（新增小 ticket 或并入 ticket 02）。**
   teleimager 的 `jetson_software_encode_frame` 整体替换了 `_encode_frame`，只保留「分辨率变化才重建编码器」，把 aiortc 原生「`target_bitrate` 漂移 >10% 即重建 codec」的逻辑丢了（`teleimager/src/teleimager/image_server.py:114-116` vs `aiortc/codecs/h264.py:251-260`）。后果：REMB 下发的目标码率永远进不了正在运行的 libx264，`cam_config_zed.yaml` 里 `min: 2000000  # floor under congestion`（`teleimager/entry/cam_config_zed.yaml:15`）在补丁路径下不生效。这能解释 8M 档「~1.5% 丢包 NACK 风暴」时码率毫不回退、buffer 持续爬升（zed-fpv ticket 06 实测，`docs/wayfinder/2026-08-20-zed-fpv/tickets/06-e2e-stereo-latency.md:38-44`）。修法：在 patch 里补回同样的漂移检查（约 5 行）。**这不是 videoserver 教我们的（它没有真正的码控），而是对比两方案的「降级机制」时暴露的现架构缺口。**
2. **pacer 挂点结论（喂给 ticket 01）：可行挂点在 `RTCRtpSender._run_rtp` 的逐包发送循环，且 NACK 重传确实绕过主循环。**
   aiortc 1.15.0 `_run_rtp` 对一帧的 payloads 是 `for` 循环背靠背 `await self.transport._send_rtp(...)`，中间零间隔（`aiortc/rtcrtpsender.py:377-401`）；NACK 重传走 RTCP 接收路径直接 `_retransmit` → 同一个 transport，不经过主循环（`aiortc/rtcrtpsender.py:274-276, 332-349`）。这正面回答了 map「Not yet specified」第 2 条：**patch 主循环的 pacer 管不住重传**（重传不被拖慢，可能正是期望行为）；patch transport 层则连重传一起 pace。videoserver 在此问题上**没有可抄的代码**——它同样没有 pacer（见 §3.4）。
3. **videoserver 提供的最有价值的参照不是代码，是「固定接收端 jitter 预算」这条替代路线的实证。**
   它用 GStreamer `rtpjitterbuffer latency=100`（`ref/videoserver/client.cpp:182`）把延迟预算钉死在 100ms：码率再高 buffer 也不涨，代价是抖动超预算直接丢帧。这反证了我们的处境：Pico 端 libwebrtc NetEq 是自适应的（码率↑→观察到的抖动↑→buffer↑），而 Unity.WebRTC 3.0.0-pre.7 **不可设** jitter buffer（`pico-bridge/Assets/Scripts/PicoBridge/Camera/WebRtcHttpSignalingClient.cs:397-400` 注释原话"the segment we cannot set in this package version, so we measure it instead"）。接收端不可调 ⇒ **发送端 pacing 是我们唯一杠杆**——这加固了本 map 的立项理由，而不是改变它。
4. **连接建立延迟是现架构明显差于 videoserver 的一段，值得单开研究（非本 map 范围）。**
   videoserver：UDP 广播发现（3s 周期）+ TCP 握手 + 立即出流，亚秒级（`ref/videoserver/server.cpp:125-136, 482-526`）。我们：HTTPS POST /offer + vanilla ICE，实测 POST 一趟 5.3s、首帧 6-10s（zed-fpv ticket 06，`tickets/06-e2e-stereo-latency.md:34`，根因是服务端 aiortc 跨 4 网口收集 ICE 慢）。FPV 中途断线重连 = 重付这笔 6-10s，比 videoserver 的 3×2s 重试（`ref/videoserver/client.cpp:292-318`）重得多。
5. **低价值/不借鉴**：videoserver 的分辨率降级阶梯（720p→360p→180p，`server.cpp:35`）对立体 FPV 不可接受（320x180 SBS 毁掉深度感，且 map 已把「分辨率/帧率降档」列为 out of scope）；它的裸 RTP 无加密、无 RTCP、无重传，全面劣于 WebRTC 栈，只换不借。

---

## 0. 两方案概览（源码级事实）

**videoserver（参考实现）**：OpenCV V4L2 采集 → `appsrc` 喂 GStreamer C 管道 → `x264enc tune=zerolatency speed-preset=ultrafast`（软编）→ `rtph264pay config-interval=1` → `udpsink`（**裸 UDP/RTP，无 SRTP、无 RTCP 会话**，端口 5000）→ 客户端 `udpsrc ! rtpjitterbuffer latency=100 ! rtph264depay ! avdec_h264`（软解）→ 640x360 窗口显示。服务发现 UDP 广播 37020，心跳兼拥塞反馈走 TCP 5001（500ms 周期，客户端回 200=正常/300=拥塞，服务端据此升降分辨率）。单客户端会话。

**当前架构**：ZED Mini → **g1_zed_bridge**（C++ `zed_xr_bridge`：ZED SDK 采集校正 SBS → BGR → resize 2560x720 → ZMQ PUB IPC，CONFLATE=1）→ **teleimager**（Python：`ZEDBridgeCamera` SUB → TripleRingBuffer → `_webrtc_pub` 30fps 节拍 → 线程队列 maxsize=1 → `BGRArrayVideoStreamTrack` maxsize=1 → MediaRelay → aiortc：libx264 ultrafast/zerolatency/threads=1/g=30 软编，PACKET_MAX=1300 → **背靠背逐包 await 发送**，SRTP/DTLS）→ WiFi → **Pico 4 pico-bridge**（Unity.WebRTC 3.0.0-pre.7 / libwebrtc：自适应 jitter buffer → MediaCodec 硬解【训练知识，见 zed-fpv research/02:123】→ `OnVideoReceived` 纹理 → 双源择优 → `StereoSbsQuad` shader 按眼半幅采样 → 锁头 quad）。

一句话：**videoserver 是「无加密、无重传、无 pacer、接收缓冲钉死」的最小 RTP 系统；现架构是「全功能 WebRTC 栈 + 全链路最新帧语义、但发送端无 pacer 且码率自适应被补丁意外禁用」。**

---

## 1. 采集段

### videoserver（`ref/videoserver/server.cpp`）
- `cv::VideoCapture`（V4L2 后端，`server.cpp:220`），普通单目摄像头，fps 取 `CAP_PROP_FPS`、非法则 30（`server.cpp:287-288`）。
- 采集节拍：每帧推送后按 `1000/fps - elapsed` 精确补眠（`server.cpp:419-425`）——采集级 pacing，与网络无关。
- 摄像头读取失败自动重开（`server.cpp:365-377`）；分辨率切换直接对运行中的 `VideoCapture` 做 `cap.set(FRAME_WIDTH/HEIGHT)`（`server.cpp:336-337`）。
- `appsrc block=TRUE`（`server.cpp:316`）：编码器跟不上时 `push-buffer` 阻塞、采集被反压——**用延迟换不丢帧**。

### 现架构
- 采集独立成 C++ 进程：ZED SDK `grab()` 按 30fps 硬件节拍，`retrieveImage(SIDE_BY_SIDE)` BGRA → `cvtColor` → `resize` 到 2560x720（`g1_zed_bridge/src/zed_xr_bridge.cpp:220-250`；默认输出尺寸由 `teleimager/entry/launch_zed_bridge.sh:33-34` 传 2560x720）。
- 帧头 44B `FrameHeaderV1` 带 `sequence`/`timestamp_ns`（`g1_zed_bridge/include/zed_frame_protocol.hpp:24-39`）——为丢帧统计预留（videoserver 无对应物）。
- 连续 grab 失败 60 次（约 2s）退出非零交给监督进程（`zed_xr_bridge.cpp:225-230`）；`launch_zed_bridge.sh:201-206` 有双向存活监督。

**判断**：现架构采集段**不弱于**参考实现，且 ZMQ IPC CONFLATE=1 + SNDHWM=1 + `dontwait` 丢帧（`zed_xr_bridge.cpp:196-207, 281-284`）明确选择了「丢帧不排队」，对 FPV 延迟语义正确；videoserver 的 `block=TRUE` 反压策略在过载时积累延迟，反而不可取。此段无借鉴需求。

---

## 2. 机内传递（videoserver 无此段）

ZMQ PUB `ipc:///tmp/zed_xr_head.ipc`，单消息=一帧（协议设计原则见 `g1_zed_bridge/docs/plan/01-frame-protocol.md:5-9`：「最新帧优先，不追求每帧必达」）。订阅端 `ZEDBridgeCamera` 同样 CONFLATE=1/RCVHWM=1/RCVTIMEO=1000（`teleimager/src/teleimager/image_server.py:1332-1337`）。

对 pacing/延迟的影响：**这一环不构成延迟源**——两级 conflate 保证任何上游停顿最多让订阅端丢旧帧，不会积压（协议冒烟测试专门验证了「暂停 5 秒不积压」，`g1_zed_bridge/docs/plan/01-frame-protocol.md:121`）。但注意进入 asyncio 世界前的最后两级是 `TripleRingBuffer`（`image_client.py:71-92`，读永远取最新）→ `_webrtc_pub` 30fps 节拍循环（`image_server.py:1589-1612`）→ 线程 `queue.Queue(maxsize=1)` 丢旧（`image_server.py:570-579`）→ publisher 线程每 5ms 轮询搬运（`image_server.py:550-561`）→ `asyncio.Queue(maxsize=1)` 丢旧（`image_server.py:314, 364-373`）。**四段全部最新帧语义，丢帧点充分，编码器永远不会看到旧帧**——这是 pacer 实施时「超预算丢帧策略」的既有地基（map「Not yet specified」第 1 条的丢帧语义已有答案：上游全线就是丢旧保新，pacer 若需要丢帧应沿用同一语义）。
【推断】多级 30fps 节拍循环互相不同相 + 5ms 轮询，贡献量级为毫秒级的确定性抖动，相对 78-150ms 的 jitter buffer 分量可忽略，但 ticket 03 复测时可从 stats 的 `jitter` 字段验证。

---

## 3. 编码段

### 3.1 编码器参数：两方案几乎相同（事实）

| 参数 | videoserver | teleimager patch |
|---|---|---|
| 编码器 | `x264enc`（GStreamer，软编） | `libx264`（PyAV，软编） |
| preset/tune | `speed-preset=ultrafast tune=zerolatency`（`server.cpp:294`） | `preset=ultrafast tune=zerolatency`（`image_server.py:128-131`） |
| 线程 | 未设（GStreamer 默认） | `threads=1`（`image_server.py:131`） |
| GOP | **未设**（x264enc 默认，代码不可见） | `g=30`，YAML 可调（`image_server.py:132`；`cam_config_zed.yaml:18`） |
| 码率 | **未设**（管道字符串无任何 bitrate/量化参数，`server.cpp:290-296`） | `bit_rate = target_bitrate`（仅建 codec 时一次性，`image_server.py:123`） |
| profile/level | 未设 | 未设（依赖 ultrafast 落在 Baseline，zed-fpv research/02:63 分析） |

README 与代码不符之一：README 称「H.264**硬编码**」（`ref/videoserver/README.md:23`），代码是 `x264enc` 软编——**该参考实现并没有硬编经验可抄**（我们也无需它：NVENC 已单独立图）。

### 3.2 码率控制与降级：videoserver 有「粗但闭环」的降级，我们的闭环被补丁断开（事实 + 新发现）

- videoserver：客户端把 GStreamer QoS 消息（帧迟到 >20ms，`client.cpp:196-208`）折算成 200/300，随 TCP 心跳每 500ms 上报（`client.cpp:101-107`；`server.cpp:201`）；服务端 `handle_status` 据此在 {{1280,720},{640,360},{320,180}} 阶梯上升/降一级（`server.cpp:35, 47-57`）。**没有码率控制，只有分辨率控制**；README 所称「基于 RTT 的 QoS 算法」（`README.md:24`）在代码中不存在 RTT 测量——不符之二。
- 现架构：WebRTC 全套反馈（REMB/TCC→`target_bitrate`、NACK、PLI/FIR）都在（`aiortc/rtcrtpsender.py:274-290`），**但** teleimager patch 的重建条件只有宽高变化（`image_server.py:115-116`），没有 stock 的 `abs(self.target_bitrate - self.codec.bit_rate)/bit_rate > 0.1 → 重建`（`aiortc 1.15.0 codecs/h264.py:251-260`；stock 重建时把新 `target_bitrate` 写进 codec，`h264.py:269-273`）。⇒ REMB 对运行中编码器无效，实际码率 = 建流时刻的 `DEFAULT_BITRATE`（2M）。【此结论基于本地 aiortc 1.15.0；机器人 env 版本未 pin（`teleimager/pyproject.toml` 裸依赖，见 zed-fpv research/02:92），但任何版本的漂移重建逻辑都位于被替换的 `_encode_frame` 内，结论应版本无关——ticket 01 第 6 项核实版本时顺带确认。】

**借鉴判断**：不是照抄 videoserver 的分辨率阶梯（对 SBS 立体不可用），而是**把断开的码控闭环接回来**（TL;DR 第 1 条）。接回后 8M 档拥塞时 REMB 会把码率压向 min floor，NACK 风暴应自行缓解——与 pacer 正交互补（pacer 管「怎么发」，码控管「发多少」）。

### 3.3 编码执行位置

videoserver：编码在 GStreamer C 线程池。现架构：`await loop.run_in_executor(None, encoder.encode, ...)`（`aiortc/rtcrtpsender.py:318-320`）——已出事件循环，`threads=1` 时单帧 2560x720 ultrafast 编码耗时毫秒级，Jetson 软编 66% CPU、decodeFps 恒 30，非瓶颈（zed-fpv ticket 06，`tickets/06:44`）。此段无需动作。

### 3.4 打包与 pacing：两方案都没有 pacer——这是最重要的对比结论（事实）

- videoserver 发送路径：`rtph264pay`（未显式设 mtu；GStreamer 默认 1400B【训练知识】）+ `config-interval=1`（`server.cpp:295`，每秒重发 SPS/PPS）→ `udpsink`（除 host/port 未设任何属性，`server.cpp:296`）。**GStreamer 发送管线里没有 pacer 元素**，一帧的 RTP 包同样背靠背迸发。
- 现架构发送路径：编码产出 payloads 列表（FU-A/STAP-A，`PACKET_MAX=1300`，`aiortc/codecs/h264.py:24`），`_run_rtp` 内层 `for i, payload in enumerate(enc_frame.payloads)` 逐包 `await self.transport._send_rtp(packet_bytes)`，**包间零 sleep**（`aiortc/rtcrtpsender.py:377-401`）。
- 突发体量（算术，非实测）：帧字节 ≈ bitrate/30fps。2M→~8.3KB/帧→~7 包；4M→~17KB→~13 包（map.md 所引「每帧 ~17KB」与 4M 档吻合，`map.md:11`）；8M→~33KB→~26 包。帧间隔 33.3ms；若摊平，4M 档包间距 ~2.6ms。
- 【推断】两者虽然都无 pacer，突发「时长」可能不同：videoserver 的发送在 C 里同步 `sendmsg` 逐包完成；aiortc 每包一次 Python `await`（含 SRTP 加密、序列化），突发在时间上被 Python 事件循环拉得更长、也更受同循环其它任务（信令、心跳、frame 搬运）干扰——这可能与「到达抖动」的程度相关，但未实测，不作为论断。

**结论**：videoserver **不能给 ticket 02 提供 pacer 参考代码**；它的延迟稳定性来自接收端固定缓冲（§5）和低码率（未控、默认量化下 720p 单目码率不高）。对我们唯一可迁移的思路是「接收端预算固定」——但 Pico 端不可设（§5），故维持发送端 pacer 路线不变。pacer 若做，`_run_rtp` 内层循环是最小 patch 面（包数已知、帧预算 = payloads 总长/帧间隔，摊平 = 每包 `await asyncio.sleep(间隔)` 或按字节预算补发）；ticket 01 应正式评估它与「给 `_next_encoded_frame` 包异步节流」（不可行：`encode()` 在 executor 里同步返回列表，`image_server.py` 的 patch 同理）以及「transport 层」（会连 NACK 重传一起 pace，见 TL;DR 第 2 条）三个挂点。

---

## 4. 传输层（协议/加密/拥塞控制/丢包恢复）

| 维度 | videoserver | 现架构 |
|---|---|---|
| 协议 | 裸 RTP over UDP（`server.cpp:296`），无 rtpbin/RTCP 会话 | SRTP over DTLS（aiortc 栈），RTCP SR 周期 0.5-1.5s（`aiortc/rtcrtpsender.py:434`） |
| 加密 | **无**（明文，可被嗅探/注入） | DTLS-SRTP 全加密 |
| 丢包恢复 | **无** NACK/FEC：丢包=花屏直到下个 IDR；`config-interval=1` 每秒重发 SPS/PPS（`server.cpp:295`）缓解参数集丢失 | NACK 重传（`rtcrtpsender.py:274-276`）+ PLI/FIR 强制关键帧（`rtcrtpsender.py:277-282`）+ GOP 30（每秒 IDR） |
| 拥塞控制 | 无网络层拥塞控制；「降级」走 §3.2 的自定义 TCP 反馈 | REME/TCC 反馈通道在（`rtcrtpsender.py:283-290`），但见 §3.2 补丁断链 |
| 多客户端 | 单会话（accept 循环串行，`server.cpp:482-526`） | 每个 POST /offer 一个 PeerConnection，MediaRelay 单次编码多订阅（`image_server.py:458-463`） |
| socket 选项 | 仅 SO_REUSEADDR/SO_BROADCAST/SO_RCVTIMEO（`server.cpp:105, 165, 458`）；**无 TCP_NODELAY、无收发缓冲区调优**（主动核实过，没有就是没有） | 不适用（传输由 aiortc/aioice 管理，UDP 无 Nagle 问题） |

**判断**：现架构传输层全面占优。videoserver 在此段没有可借鉴项；它的 `config-interval=1`（周期性重发 SPS/PPS，利于中途入会）在我们这由 g=30 的每秒 IDR + PLI 路径等效覆盖，无需动作。

---

## 5. 接收端：固定 jitter 预算 vs 自适应 jitter buffer（本对比的核心洞察）

- videoserver：`rtpjitterbuffer latency=100`（`client.cpp:182`）——**固定 100ms**，与码率无关。超预算的迟到包按丢失处理，buffer 永不增长 ⇒ 延迟上界确定。解码 `avdec_h264` 软解（`client.cpp:183`；README 称「硬件加速流水线」不符之三），显示前统一缩到 640x360（`client.cpp:184`）。
- 现架构：libwebrtc NetEq 自适应。实测码率-延迟剂量关系（zed-fpv ticket 06，`tickets/06:38-44`）：

| 码率 | avgJitterBuffer | 丢包 | e2e |
|---|---|---|---|
| 8M | 150-165ms 爬升 | ~1.5% NACK 风暴 | ~220ms |
| 4M | 112ms 稳定 | ≈0 | ~200ms |
| 2M（定稿） | 78ms | 0 | ~120ms |

  且该 buffer 在 Unity.WebRTC 3.0.0-pre.7 **不可配置**，只能测量（`WebRtcHttpSignalingClient.cs:397-400`；stats 每 5s 打 `avgJitterBuffer`，`WebRtcHttpSignalingClient.cs:402-441`）。

**判断**：videoserver 用「钉死接收预算」斩断了码率-延迟耦合，我们没法在 Pico 上复制这一手（不可设）；但这个对照把问题定性得很清楚——**我们链路里唯一的「延迟放大器」是自适应 buffer 对发送突动的响应，而能在发送侧消灭突动的只有 pacer**。另外它给 ticket 02 的「单机验证」提了个醒：GStreamer `rtpjitterbuffer latency=<x>` 恰好是可控对照组——若 ticket 02 需要一个「固定预算接收端」来分离「到达抖动」与「buffer 策略」两类因素，PC 上用 GStreamer 收流（`udpsrc ! rtpjitterbuffer latency=40 ! ...`）是现成的实验骨架，比浏览器 getStats 更可控【推断：作为测量工具建议，未验证与 aiortc 的 SRTP 互通——裸 rtpjitterbuffer 不解 SRTP，需 gst-webrtcbin 或关加密的测试拓扑，ticket 02 实施时评估】。

---

## 6. 渲染/显示

- videoserver：桌面窗口 `autovideosink`，单目，640x360。
- 现架构：`OnVideoReceived` 纹理（`WebRtcHttpSignalingClient.cs:305-319`）→ 双源择优（直连真流优先，PC-push 兜底，`StereoImmersiveController.cs:81-88`）→ `StereoSbsQuad` shader 按 `unity_StereoEyeIndex` 半幅采样、锁头 quad 2m 距离（commit `324ba50`，`pico-bridge` feat/stereo-fpv）。VR 双目立体渲染为 videoserver 所无，无需对比。

---

## 7. 连接建立、发现、断线重连

| 维度 | videoserver | 现架构 |
|---|---|---|
| 发现 | UDP 37020 广播 JSON，3s 周期，多网卡（`server.cpp:60-141`） | 无发现（IP 写死进 `WebRtcHttpSignalingClient.cs:45` 默认 URL） |
| 建连 | TCP 5001 connect → 摄像头列表/选择（JSON over 同一 socket，`server.cpp:504-522`）→ 立即出流；亚秒级【推断：无 ICE/DTLS，TCP 握手即用】 | HTTPS POST /offer（自签证书需 `AcceptAnyCertificate`，`WebRtcHttpSignalingClient.cs:443-447`）+ vanilla ICE 双向内嵌候选；实测 POST 5.3s、首帧 6-10s（`tickets/06:34`，服务端跨 4 网口收 ICE 慢） |
| 断线检测 | 心跳 500ms，2s 超时判死（`server.cpp:196-201`） | libwebrtc `ConnectionState` + 首帧 10s 超时/断线 12s 重试/POST 失败 2s 退避（`WebRtcHttpSignalingClient.cs:66-69, 55-64, 118-127`） |
| 重连 | 3 次 × 2s，记住上次摄像头（`client.cpp:292-318`） | 每次重连 = 全新握手（重付 6-10s 首帧代价） |
| 服务端鲁棒性 | v1.0.2 专修断连崩溃（git log `3cbf1b7`）；`heartbeat_listener` 仍有重复 `recv` 疑似残留 bug（`server.cpp:168-193` 每轮收两次） | 每次 POST 新建 pc、failed/closed 自清理（`image_server.py:495-498, 521-525`）；10 分钟佩戴 + watchdog 重连已验收（`tickets/06:50`） |

**判断**：稳态鲁棒性我们不差；**建连/重连的首帧时延是明确差距**（TL;DR 第 4 条）。改善方向【推断，需研究】：限制 aiortc answer 端 ICE 收集范围（如绑定单一网口/子网，避免 4 网口全枚举）可能把 5.3s 压到亚秒——涉及 aioice 内部，宜单开研究 ticket，不进本 map（本 map 范围已锁定「只做 pacer」，`map.md:38`）。

---

## 8. 源码风险与诚实声明

- aiortc 结论取自本机 1.15.0（`C:\Users\user\AppData\Roaming\Python\Python314\site-packages\aiortc`）；机器人 env 未 pin（zed-fpv research/02:92）。§3.2/§3.4 的结构性结论（漂移逻辑在 `_encode_frame` 内、逐包 await、NACK 旁路）不依赖具体小版本，但 ticket 01 第 6 项仍应以机器人实机源码复核为准。
- videoserver README 与代码三处不符：硬编（实为 x264enc 软编，`README.md:23`）、RTT-based QoS（实为帧迟到启发式，`README.md:24`）、硬件加速解码/延迟<200ms（实为 avdec_h264 软解 + 固定 100ms buffer，`README.md:31`）。对比一律以代码为准。
- GitHub 上游补充（commit 历史/issue）因网络策略未能获取；本地 git log（8 commits，2025-05-03→05-07）与上游 master 一致，故本地即上游快照，影响很小。
- 次要发现（顺带）：`teleimager/entry/launch_zed_bridge.sh` 的 usage 文本写着默认 HD1080/3840x1080（`launch_zed_bridge.sh:53-56`），实际默认 HD720/2560x720（`launch_zed_bridge.sh:31-34`）——陈旧帮助文本，不影响运行。
- videoserver 明确**没有**的东西（找过、确认没有）：网络层 pacer、码率控制、TCP_NODELAY/缓冲区调优、RTCP、加密、FEC、重传、多客户端。

---

## 9. 对活跃地图 3 张 ticket 的影响

- **ticket 01（aiortc 发送路径研究）**：研究问题**不变**，但本文预答了两点，可缩短其核实路径——(a) 1.15.0 的发送循环为 `_run_rtp` 内层逐包 await、零间隔（`aiortc/rtcrtpsender.py:377-401`），挂点候选成立；(b) NACK 重传经 `_handle_rtcp_packet → _retransmit` 直达 transport，**绕过主循环**（`rtcrtpsender.py:274-276, 332-349`）——map「Not yet specified」第 2 条（重传是否走同一 pacer）的答案倾向「主循环 pacer 天然不管重传」，这大概率是期望行为（重传要快）。01 的剩余工作：机器人实机版本核实、MediaRelay 队列语义确认（map 问题 4）、挂点对比定稿。
- **ticket 02（pacer 实现）**：实现思路不变；新增输入——(a) 摊平参数可从算术出发：包数 = ceil(帧字节/1300)，帧预算 = 1/fps，均匀分布即可（videoserver 无参考代码，GStreamer 侧亦无）；(b) 超预算丢帧应沿用全线已有的「丢旧保新」语义（§2）；(c) 建议把 §3.2 的「REME 码控修复」作为可选项并入本 ticket 或并行小改动（patch 同文件同风格，约 5 行，恢复 stock `h264.py:251-260` 的漂移重建）——先修码控再开 pacer 还能让 8M 档复测更干净（否则 8M 下 NACK 重传流量与 pace 后的原始流量混在一起，ticket 03 归因会脏）【推断：顺序建议，非硬依赖】。
- **ticket 03（双线验收）**：验收口径不变；建议复测时同步记录 `packetsLost`/NACK 次数（stats 已有，`WebRtcHttpSignalingClient.cs:435-437`），以便区分「pacer 消抖」与「码控回退」各自的贡献。
- **是否新增 ticket**：建议两张（均不阻塞本 map）——
  1. `REME 码率自适应修复`（小，见上）；
  2. `ICE 收集范围与首帧时延`（研究类：限制 aiortc/aioice 候选枚举，目标把重连首帧 6-10s 压向 2s 内）——来自 §7 与 videoserver 建连路径的对照。
  此外不建议为 videoserver 的分辨率降级/UDP 广播发现/心跳机制立 ticket（对立体 FPV 无增益或已有等价物）。

## 来源清单

本地代码（相对各仓库根）：
- `ref/videoserver/{README.md, server.cpp, client.cpp, CMakeLists.txt}`（`F:\Chufan_Rui\code_dig\video_trans\ref\videoserver`；git log 8 commits 至 2025-05-07）
- `teleimager/src/teleimager/image_server.py`、`teleimager/src/teleimager/image_client.py`、`teleimager/cam_config_server.yaml`、`teleimager/entry/{cam_config_zed.yaml, launch_zed_bridge.sh, overlay_clock.py}`（`F:\Chufan_Rui\teleop\teleimager`，分支 zed-bridge）
- `g1_zed_bridge/{README.md, include/zed_frame_protocol.hpp, src/zed_xr_bridge.cpp, docs/plan/01-frame-protocol.md}`（`F:\Chufan_Rui\teleop\g1_zed_bridge`）
- `pico-bridge/Assets/Scripts/PicoBridge/Camera/WebRtcHttpSignalingClient.cs`、`pico-bridge/Assets/Scripts/PicoBridge/Immersive/StereoImmersiveController.cs`（`F:\Chufan_Rui\teleop\pico-bridge`，feat/stereo-fpv `353d70c`）
- aiortc 1.15.0：`C:\Users\user\AppData\Roaming\Python\Python314\site-packages\aiortc\{rtcrtpsender.py, codecs/h264.py}`

仓库文档：
- `docs/wayfinder/2026-08-29-aiortc-pacer/map.md` 及 `tickets/01…02…03…md`
- `docs/wayfinder/2026-08-20-zed-fpv/map.md`、`tickets/06-e2e-stereo-latency.md`、`research/02-unity-webrtc-aiortc-interop.md`

网络来源：https://github.com/Linductor-alkaid/videoserver （仅作出处标注；内容获取被阻断，全部以本地快照为准）
