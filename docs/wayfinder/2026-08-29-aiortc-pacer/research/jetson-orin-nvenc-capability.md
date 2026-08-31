# Jetson Orin NX NVENC 硬编能力与 aiortc 集成路径研究

- 地图：`2026-08-29-aiortc-pacer`（研究产物；map 边界决策 1 已把「NVENC 硬编」列为 out of scope、各自独立成图——本文为那张未来图的前期输入）
- 日期：2026-08-29
- 研究问题：流 FPV 视频的远端 Jetson Orin（`unitree@192.168.10.13`）到底有没有 H.264 硬件编码（NVENC），能力几何；若要接进 teleimager 的 aiortc 软件栈，哪条路工作量/风险最小，以及对 REMB 动态码率（ticket 04）与 pacer 延迟目标（buffer<40ms / e2e<100ms @≥4M）意味着什么。
- 方法：一手证据三源——① 实机 SSH 只读探测（BatchMode key 认证，全部命令+输出见 §3，探测时无操作员在线、bridge 未运行，但仍全程只读：无 gst-launch、无试编码、无服务操作）；② NVIDIA 官方文档（模块数据表、L4T 35.3.1 文档、JetPack 归档页）+ aiortc/ffmpeg/PyAV 官方源码仓库；③ 本地 aiortc 1.15.0 源码（与实机 1.14.0 五文件 md5 一致，据 `research/01-send-path.md` §1，file:line 可互引）。标【事实】= 源码/原文/实测直接可见；【推导】= 算术；标【推断】= 分析判断；二手来源（RidgeRun wiki、NVIDIA 论坛员工回复）单独标注。

---

## 0. 六问速答

| # | 问题 | 一句话结论 | 详见 |
|---|---|---|---|
| 1 | 什么模块？有 NVENC 吗？ | **Orin NX 16GB**（`/proc/device-tree/model` = "NVIDIA Orin NX Developer Kit"，15Gi RAM），L4T R35.3.1 = **JetPack 5.1.1**；NVENC **有**（`/dev/nvhost-msenc` 在位，Orin 家族里只有 Orin Nano 没有） | §1 §3 |
| 2 | 硬编规格够 2560x720@30 吗 | **绰绰有余**：官方数据表 H.264 UHP 吞吐 680 MP/s、最高 4K60 单流；本流 55.3 MP/s 只占 **8%**。CBR 是默认模式（`control-rate=1`），固件层支持 CBR+VBR | §2 §3 |
| 3 | ffmpeg/PyAV 能直接用吗 | **不能**：nvmpi/nvv4l2 编码从未进 ffmpeg 主线（源码树 0 匹配 + 2020 邮件列表被拒）；jocover 补丁 2021 年起冻结、只针对 ffmpeg 4.2；PyAV wheel 自带 ffmpeg，必须源码重编 `--no-binary` | §4.2 |
| 4 | aiortc 有官方硬编插件点吗 | **没有**。1.14.0 codec 注册表是模块级 dict + `get_encoder` 硬编码 if/elif，无 `register_codec`；维护者 jlaine 的官方态度就是「monkey-patch `get_encoder`」（issue #116）。teleimager 已有的 `_encode_frame` 替换先例正是他认可的做法 | §4.1 |
| 5 | 推荐集成路径 | **方案 A（推荐）**：系统 python3 + PyGObject 起一个 `appsrc ! nvvidconv ! nvv4l2h264enc ! appsink` 子进程，teleimager 替换 `h264.H264Encoder._encode_frame` 喂帧/收 Annex-B AU（照 `jetson_software_encode_frame` 先例，零新增包、零 aiortc 改动）；方案 B（ffmpeg-nvmpi 重编 PyAV）冻结风险高；方案 C（换媒体栈）过度 | §4.3 |
| 6 | 对 pacer/REMB 的意义 | NVENC **不解决**突发问题（那是 pacer 的活），它砍掉的是编码常数项 + 释放 CPU + 收紧帧尺寸方差；**REMB 动态码率可运行时改**（`bitrate` 属性 PLAYING 态可设，NVIDIA 员工确认，尽管 gst-inspect 标注说不行）→ 硬编路径下 ticket 04 的「漂移重建」可升级为「运行时设值、不重启」 | §4.4 §5 |

---

## 1. 设备识别（模块型号 + JetPack）

| 项 | 值 | 证据 |
|---|---|---|
| 型号串 | `NVIDIA Orin NX Developer Kit` | `cat /proc/device-tree/model`（§3 P1） |
| 内存 | 15 GiB（`MemTotal: 15757796 kB`）→ **Orin NX 16GB** 模块 | `free -h` / `/proc/meminfo`（§3 P1） |
| L4T | **R35.3.1**（REVISION 3.1，BOARD t186ref，2023-03-19） | `cat /etc/nv_tegra_release`（§3 P1） |
| JetPack | **5.1.1** | NVIDIA JetPack 归档页原文「JetPack 5.1.1 … [L4T 35.3.1]」（https://developer.nvidia.com/embedded/jetpack-archive ） |
| `jetson_release` | 未安装（`which jetson_release` 无输出） | §3 P1 |

命名注记【事实+推断】：NVIDIA 官网没有名为「Orin NX Developer Kit」的产品——官方说法是 Orin Nano 开发套件的参考载板兼容所有 Orin NX/Nano 模块（https://www.nvidia.com/en-us/autonomous-machines/embedded-systems/jetson-orin/ ）。所以本机大概率是 **Orin NX 16GB 模块插在 Orin Nano 开发套件载板**上；模块级规格不受载板影响，下文按 Orin NX 16GB 数据表论。

**关键分水岭**：如果是 Orin Nano 就可以直接结案——L4T 官方文档原话「**The NVIDIA Jetson Orin Nano does not have the NVENC engine.**」（https://docs.nvidia.com/jetson/archives/r35.3.1/DeveloperGuide/text/SD/Multimedia/SoftwareEncodeInOrinNano.html ），nvidia.com 规格表 Orin Nano 的 Video Encode 格写的是「1080p30 supported by 1-2 CPU cores」（纯 CPU 编码）。本机不是 Nano：`/dev/nvhost-msenc` 在位（§3 P2），且有 15Gi 内存（Nano 顶配 8Gi）。

---

## 2. NVENC 硬件规格（官方表格 + 引用）

来源：**Jetson Orin NX Series Data Sheet**（DS-10712-001 v0.5, 2022-11，https://developer.nvidia.com/downloads/jetson-orin-nx-series-data-sheet ），Table 8「Supported Video Encode Streams」，16GB 与 8GB 同表：

| 编码档 | 分辨率×并发流（括号=最大流数） | 吞吐上限 |
|---|---|---|
| **H.264 UHP** | 4K60 (1) / 4K30 (2) / 1080p60 (5) / 1080p30 (11) | **680 MP/s** |
| H.264 HP | 4K30 (1) / 1080p60 (3) / 1080p30 (7) | 470 MP/s |
| H.264 HQ | 1080p60 (1) / 1080p30 (3) | 220 MP/s |
| H.265 UHP | 4K60 (1) / 4K30 (3) / 1080p60 (6) / 1080p30 (12) | 800 MP/s |
| AV1 UHP/HQ | 4K60 (1) … | 750/380 MP/s |

数据表同时给出编码器特性（原文引用）：「CBR and VBR rate control (**supported in firmware**)；Programmable intra-refresh for error resiliency；Macro-block based and bit based packetization (multiple slice)」。解码侧（Table 7）：H.265 可到 8K30——**8K 编码不存在，4K60 是编码上限**。

家族对照（https://www.nvidia.com/en-us/autonomous-machines/embedded-systems/jetson-orin/ 规格表 + AGX Orin Technical Brief v1.2，https://www.nvidia.com/content/dam/en-zz/Solutions/gtcf21/jetson-orin/nvidia-jetson-agx-orin-technical-brief.pdf ）：

| 模块 | Video Encode | 解读 |
|---|---|---|
| AGX Orin 64GB | 2x 4K60 (H.265)，H.264/AV1 | 双 NVENC 产能 |
| AGX Orin 32GB / **Orin NX 16/8GB** | **1x** 4K60 (H.265)，H.264/AV1 | NX 与 AGX 32GB 同产能 |
| Orin Nano（全系） | 「1080p30 supported by 1-2 CPU cores」 | **无 NVENC**（L4T 文档明示） |

引擎数注记【事实+推断】：NVIDIA 无一手文档逐字写「Orin NX = 1 个 NVENC 引擎」；可确认的是 NX 数据表只描述**一个** Multi-Standard Video Encoder（NVENC）块、产能恰为 AGX 64GB（2 NVENC）的一半。按产能推算即单引擎；该差异对本文结论无影响。

对本流的预算【推导】：2560×720@30 = **55.3 MP/s** = H.264 UHP 680 MP/s 的 **8.1%**（HP 档也只占 11.8%）。单路 FPV 即使以后冲 60fps（110.6 MP/s，16%）也远不触顶；NVENC 不会成为瓶颈。

L4T 35.3.1 软件栈对应关系（https://docs.nvidia.com/jetson/archives/r35.3.1/DeveloperGuide/text/SD/Multimedia/AcceleratedGstreamer.html ）：

- `nvv4l2h264enc` / `nvv4l2h265enc` 在 Orin NX 可用；`nvv4l2av1enc` **仅 AGX Orin**（硬件有 AV1 但本版 L4T 的 GStreamer 元件没放开）——AV1 硬编在本机暂不可用。
- 码控原文：「The supported modes are 0 (variable bit rate, or VBR) and 1 (constant bit rate, **CBR**)」（H.264/H.265 都支持）；另有 `EnableTwopassCBR=1`（须与 control-rate=1 同开；多实例时建议配 `maxperf-enable`）；「Peak bitrate takes effect **only in variable bit rate mode**」。
- 定 QP 模式：`ratecontrol-enable=0 quant-i-frames=.. quant-p-frames=..`（const-QP）。
- `insert-sps-pps` 原文：「a sequence parameter set (SPS) and a picture parameter set (PPS) are inserted **before each IDR frame**」——WebRTC 中途入会/解码恢复所需。
- V4L2 编码设备节点：官方 API 文档原话「The video encoder device node is **"/dev/nvhost-msenc"**」（https://docs.nvidia.com/jetson/archives/r35.3.1/ApiReference/group__V4L2Enc.html ），运行时码率控制 ID 为 `V4L2_CID_MPEG_VIDEO_BITRATE`；同页给出低延迟调优枚举 `V4L2_ENC_TUNING_INFO_LOW_LATENCY / ULTRA_LOW_LATENCY`。
- L4T 甚至有 WebRTC 专页：NVIDIA 自己往开源 WebRTC 框架里集成过硬编 H.264（"NvEncoder"，https://docs.nvidia.com/jetson/archives/r35.3.1/DeveloperGuide/text/SD/HardwareAccelerationInTheWebrtcFramework.html ）——但那需要自建 libwebrtc，对 aiortc 栈无直接用处（见 §4.3 方案 C）。

GStreamer 上游文档缺失注记【事实】：`https://gstreamer.freedesktop.org/documentation/nvv4l2h264enc/nvv4l2h264enc.html` 为 404，gst-plugins-bad 无 `sys/nvv4l2` 目录——该元件是 NVIDIA L4T 专有插件，L4T 文档明言属性详情用 `gst-inspect-1.0` 查询。**即 §3 的实机 gst-inspect 输出就是该元件的一手权威文档。**

---

## 3. 实机探测结果（全部只读；2026-08-29 执行）

探测时设备 uptime 1:08、无 python bridge 在跑（`top` 仅 `videohubd` 25% CPU、整机 ~92% idle）——所以 CPU 数字是空载基线，不代表推流时负载。

### P1 模块与系统

```
$ cat /proc/device-tree/model
NVIDIA Orin NX Developer Kit
$ cat /etc/nv_tegra_release
# R35 (release), REVISION: 3.1, GCID: 32827747, BOARD: t186ref, EABI: aarch64, DATE: Sun Mar 19 15:19:21 UTC 2023
$ grep MemTotal /proc/meminfo
MemTotal:       15757796 kB          # → 16GB 模块
```

### P2 编码器硬件节点

```
$ ls -la /dev/nvhost-msenc* /dev/nvhost-vic* /dev/nvhost-nvdec* /dev/nvhost-gpu
crw-rw---- 1 root video 508, 13 Jun 18  2024 /dev/nvhost-msenc     # ← NVENC 编码引擎（V4L2 设备）
crw-rw---- 1 root video 508, 21 Jun 18  2024 /dev/nvhost-nvdec     # 解码
crw-rw---- 1 root video 508,  1 Jun 18  2024 /dev/nvhost-vic       # VIC（nvvidconv 用的格式转换/缩放引擎）
crw-rw---- 1 root video 504,  1 Aug 29 11:57 /dev/nvhost-gpu
$ v4l2-ctl --list-devices     # 只列出 3 个 RealSense 采集设备 + tegra-camrtc-ca；编码器不是 /dev/video* M2M 节点，而是上面的 /dev/nvhost-msenc（与 §2 V4L2 API 文档一致）
```

### P3 GStreamer + nvv4l2h264enc（关键属性全文摘录，来源即一手文档）

```
$ gst-inspect-1.0 --version
gst-inspect-1.0 version 1.16.3
$ gst-inspect-1.0 nvv4l2h264enc        # 插件 nvvideo4linux2 1.14.0, /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstnvvideo4linux2.so
```

| 属性 | 默认/范围 | 关键信息（原文） |
|---|---|---|
| `device` | `/dev/nvhost-msenc` | 硬件设备位置 |
| sink caps | `video/x-raw(memory:NVMM)` I420/NV12/P010_10LE/Y444/NV24；width/height 1..2^31-1；framerate 0..2^31/1 | **只吃 NVMM 显存**——系统内存帧必须先过 `nvvidconv`（VIC）转 NVMM；2560×720 无压力 |
| src caps | `video/x-h264, stream-format=byte-stream, alignment={au,nal}` | 输出 **Annex-B 字节流**——与 aiortc `_split_bitstream`（h264.py:204-230）期望的输入格式天然一致 |
| `control-rate` | 默认 **1 constant_bitrate**；枚举 {0 variable_bitrate, 1 constant_bitrate} | CBR 是默认，正好是 WebRTC 想要的 |
| `bitrate` | uint32 默认 4000000 | flags「changeable only in NULL or READY state」——**但 NVIDIA 员工确认运行时可改**（§4.4） |
| `peak-bitrate` | 0（=1.2×bitrate） | flags 明示「changeable in NULL, READY, PAUSED or PLAYING」；仅 VBR 生效 |
| `preset-level` | 默认 **1 UltraFastPreset**；0 Disable/2 Fast/3 Medium/4 Slow | 对应数据表 UHP/HP/HQ 产能档 |
| `profile` | 默认 **Baseline**；Main/High/High444 | 与 aiortc SDP 协商的 42e01f（constrained baseline）对齐 |
| `insert-sps-pps` | 默认 **false** | 每个 IDR 前插 SPS/PPS；WebRTC 必开 |
| `iframeinterval` / `idrinterval` | 30 / 256 | I 帧与 IDR 帧间隔是两个旋钮（见 §4.4 GOP 映射） |
| `num-B-Frames` | 默认 **0**（0-2，blurb 自带 "(not recommended)"） | 零 B 帧 = 零重排延迟，WebRTC 语义正确 |
| `maxperf-enable` | 默认 false | 最大性能模式（§5 延迟证据显示它是最大的单项提速旋钮） |
| `vbv-size` | 默认 4000000 bit | 虚拟缓冲；低延迟建议远小于默认（需实测，见 §6） |
| `EnableTwopassCBR` | false | 更紧的 CBR（代价见 L4T 文档） |
| qp 系 | `ratecontrol-enable`(默认 true)、`qp-range`、`quant-i/p/b-frames` | const-QP 模式可用 |
| `SliceIntraRefreshInterval` / `slice-header-spacing` / `bit-packetization` | 0/0/false | 刷新/分包旋钮备选 |
| `MeasureEncoderLatency` | false | **逐帧测编码延迟**的现成开关——§6 实测就用它 |
| Element Actions | **`force-IDR`**（运行时动作信号） | PLI/FIR → 强制关键帧的一手支撑 |

`nvv4l2h265enc` 同族在位（profile 默认 Main，`num-B-Frames` blurb 标注 "Supported only on Xavier"）；`nvv4l2decoder` 在位（rank primary+11）。**但 H.265 对本链路暂不可用**：aiortc 1.14/1.15 只内置 VP8+H264 两个视频 codec（`codecs/__init__.py:95-104`），加 HEVC 要自写整个 codec 类+fmtp+打包，且 Pico 端 libwebrtc HEVC 支持未知——不在本图范围。

### P4 ffmpeg

```
$ command -v ffmpeg || echo "ffmpeg NOT on PATH"
ffmpeg NOT on PATH        # /usr/bin/ffmpeg、/usr/local/bin/ffmpeg 均不存在
```

即：设备上**根本没有独立 ffmpeg**；PyAV（aiortc 依赖）用的是 wheel 自带的那份（§4.2 引 PyAV README）。这与「ffmpeg 无 Jetson 硬编」共同构成方案 B 的两重障碍。

### P5 CPU（软编 vs 硬编背景）

```
$ nproc
8
$ top -bn1 | head -5      # 空载基线（bridge 未运行）
%Cpu(s):  1.5 us,  3.8 sy, 92.5 id
  2515 root  25.0  videohu+   # videohubd
```

### P6 teleimager 环境

```
$ /home/unitree/miniconda3/envs/teleimager/bin/python -c "import av, aiortc; print(av.__version__, aiortc.__version__)"
av 16.1.0
aiortc 1.14.0
$ /home/unitree/miniconda3/envs/xr_tele/bin/python -c "..."     # 第二 checkout 的 env（对照）
av 17.1.0 / aiortc 1.15.0
```

与 `research/01-send-path.md` §1 一致：**活体 FPV 链路 = `teleimager` env，aiortc 1.14.0**（该文已做五文件 md5 比对：1.14.0 与本机 1.15.0 的 `h264.py`/`rtcrtpsender.py` 字节一致——本文引用的 aiortc 行号两版通用）。注意 `/home/unitree/teleimager/entry/launch_zed_bridge.sh` 里 `PYTHON_DEFAULT` 指向 xr_tele env 且按 `../../..` 推 REPO_ROOT——该脚本是 repo 风格副本，实际部署拓扑以跨会话记忆 `jetson-teleimager-deploy-topology`（活体 = `/home/unitree/teleimager` + `teleimager` env）为准；动手前照例先 import 定位。

**方案 A 的地基探测**：系统 python3 的 PyGObject 可用（无需装任何包）：

```
$ /usr/bin/python3 -c "import gi; gi.require_version('Gst','1.0'); from gi.repository import Gst; Gst.init(None); print('OK', Gst.version_string())"
OK GStreamer 1.16.3
$ gst-inspect-1.0 nvvidconv    # 在位（VIC 转换器，系统内存↔NVMM 桥）
```

---

## 4. aiortc 集成路径

### 4.1 aiortc 侧接口（一手源码，1.14.0/1.15.0 逐行同）

【事实】编码器工厂与注册表（`aiortc/codecs/__init__.py`）：

- `CODECS: dict[str, list[RTCRtpCodecParameters]]`（:31）模块级 dict，`init_codecs()` 在 import 时填入 VP8 + 两个 H264 fmtp（`42001f`/`42e01f`，packetization-mode=1，:95-104）；**没有 `register_codec` 之类的公开插件点**。
- `get_encoder()`（:167-183）是硬编码 if/elif：`video/h264 → H264Encoder()`。
- 调用点：`rtcrtpsender.py:14` 以 `from .codecs import get_encoder` 导入；`_next_encoded_frame` 内 `if self.__encoder is None: self.__encoder = get_encoder(codec)`（:308-309）——即使想换工厂函数，patch 处应是 `aiortc.rtcrtpsender.get_encoder`（模块命名空间），而非 `aiortc.codecs.get_encoder`。

【事实】H264Encoder 必须满足的接口（`aiortc/codecs/h264.py`，与实机 1.14.0 md5 一致）：

- `encode(frame, force_keyframe=False) -> tuple[list[bytes], int]`（:290-296）——**同步函数**，返回「RTP 化后的 payload 列表（FU-A/STAP-A，`PACKET_MAX=1300`，:25）+ 90kHz 时间戳」；在 `run_in_executor(None, encoder.encode, ...)` 里执行（rtcrtpsender.py:318-320，executor 线程，**阻塞式 IPC 在这里不卡事件循环**）。
- 可替换的核心是生成器 `_encode_frame(frame, force_keyframe) -> Iterator[bytes]`（:248-288）：**yield 的是 Annex-B NAL 单元**，由 `encode()` 里的 `_packetize`（:232-246）切包。teleimager 的 `jetson_software_encode_frame`（image_server.py:114-166）替换的正是它——**NVENC 只需替换同一个函数，RTP 打包路径零改动**。
- `target_bitrate` property（:304-314）：REMB 回包 → `rtcrtpsender.py:282-292` 检查 `hasattr(encoder, "target_bitrate")` 后直接赋值（clamp 到模块级 MIN/MAX_BITRATE，teleimager 已用 yaml setattr 覆盖，image_server.py:98-109）。沿用 H264Encoder 类则此路径自动保留。
- PLI/FIR → `_send_keyframe()` 只置 `__force_keyframe` 标志（:277-281），下一帧作为 `force_keyframe=True` 传入 `encode`——映射到 GStreamer 的 `force-IDR` 动作信号即可（§3 P3）。
- 上游先例：aiortc 曾内置树莓派硬编 `h264_omx`（PR #488，2021 由维护者本人合入 `_encode_frame` 层的 try/except 回退写法；2025 PR #1252 移除）；打开中的 nvenc PR #1199 同样动 `_encode_frame`。**「在 `_encode_frame` 层做硬编」是上游验证过的形状。**

【事实】维护者立场（aiortc/aiortc，注意仓库在 `aiortc/` org 下）：

- issue #116（2018，codec 插件机制请求，jlaine 原话）："A generic mechanism for registering encoders / decoders unfortunately sounds like a long shot… I'm not too confident writing a public API for all this." 以及 "This is Python, and not compiled code, so you can **monkey-patch `get_decoder`** without needing to actually change `aiortc`"（https://github.com/aiortc/aiortc/issues/116 ）
- issue #390（2020）：「aiortc relies on PyAV for its FFmpeg bindings, and its readme states hardware acceleration is out of scope」（https://github.com/aiortc/aiortc/issues/390 ）
- issue #588（2021，用户接 h264_nvenc 出现抖动）——jlaine 无 CUDA 环境无从排查（https://github.com/aiortc/aiortc/issues/588 ）
- PR #1199（2024-12 至今 open，"changes requested"）：给 `_encode_frame` 加 `h264_nvenc`（**dGPU 的 nvenc，非 Jetson nvmpi**），前提是 PyAV 自编接系统 ffmpeg（https://github.com/aiortc/aiortc/pull/1199 ）
- issue 搜索：`nvv4l2` **0 条**；`jetson` 命中的全是装依赖问题（#126/#395）。没有现成轮子，也没有人反对 monkey-patch。
- 另有已合并的 #559（track 直接产 `av.Packet` 走 `encoder.pack()` 免转码路径）——见 4.3 变体。

### 4.2 为什么 PyAV/ffmpeg 直连不可行（方案 B 的证据）

【事实】三重确认 nvmpi/nvv4l2 编码不在 ffmpeg 主线：

1. FFmpeg master `libavcodec/allcodecs.c` 对 `nvmpi|nvv4l2` 零匹配（同文件里 dGPU 的 `ff_h264_nvenc_encoder` 等在册；https://raw.githubusercontent.com/FFmpeg/FFmpeg/master/libavcodec/allcodecs.c ），`configure` 无对应开关；官方文档 https://ffmpeg.org/ffmpeg-codecs.html 亦零匹配。
2. 2020-06 NVIDIA 员工的 nvv4l2 **解码**补丁在邮件列表被维护者挡下、无下文：Anton Khirnov 原话 "we already have two NVidia hardware decoding APIs. Why is there a need for a third one?"（https://ffmpeg.org/pipermail/ffmpeg-devel/2020-June/263746.html 及回复 263762）。
3. 民间实现是 **`jocover/jetson-ffmpeg`**（不是 "ffmpeg-nvmpi"，该名仓库不存在）：README 给 `h264_nvmpi`/`hevc_nvmpi` 编码用法，但 `ffmpeg_nvmpi.patch` 最后修改 **2021-04-30**、目标分支 **ffmpeg release/4.2**，此后未再 rebase（https://github.com/jocover/jetson-ffmpeg ）；社区续命 fork `LinusCDE/mad-jetson-ffmpeg` 最后推送 2023-04。

【事实】PyAV wheel 自带 ffmpeg："Binary wheels are provided on PyPI … with **FFmpeg bundled**"；要接系统/自编 ffmpeg 必须 `pip install av --no-binary av` 源码构建（PyAV README，https://raw.githubusercontent.com/PyAV-Org/PyAV/main/README.md ）。实机 teleimager env 是 av **16.1.0**（wheel，对应 ffmpeg 7.x），把 2021 年的 4.2 时代 nvmpi 补丁 rebase 上去再在 aarch64 上自编 PyAV——工作量与长期维护成本远超收益。

### 4.3 方案排序（工作量 / 风险 / 部署）

| | **A.（推荐）GStreamer 子进程 + 替换 `_encode_frame`** | B. ffmpeg-nvmpi + 自编 PyAV | C. 换掉 aiortc 媒体面 |
|---|---|---|---|
| 做法 | 系统 python3 起子进程跑 `appsrc ! nvvidconv ! nvv4l2h264enc ! appsink`；teleimager 换 `_encode_frame`：帧数据写管道 → 读回 AU → `yield from self._split_bitstream(au)` | 重编 ffmpeg(nvmpi)+PyAV 源码装，`av.CodecContext.create("h264_nvmpi","w")` 替 libx264 | webrtcbin / NVIDIA WebRTC NvEncoder / 自建 RTP——整体替换 |
| aiortc 改动 | **零**（沿用 image_server.py:114-166 的 patch 点，只换函数体） | 零（同上） | 推倒重来 |
| 新增依赖 | **零**（python3-gi 实测在位、nvv4l2h264enc/nvvidconv 实测在位；map 边界决策 3「机器人零新增依赖」满足） | 设备上引入编译链 + 私有 ffmpeg/PyAV 构建 | 全新栈 |
| 工作量【推断】 | **~150-250 行**（子进程脚本 ~100：管道 + 帧协议 + 控制协议；`_encode_frame` 替换 ~60；崩溃兜底 ~30） | ffmpeg rebase + 交叉编译 + PyAV 源码装 + 部署固化，1-2 天起且每次升级重付 | 周-月级 |
| 风险 | 管道缓冲调参（appsink `sync=false max-buffers=1 drop=true` 必设，否则引入排队帧）；子进程崩溃需检测+重启（重启后 IDR 恢复，insert-sps-pps 兜底）；BGR→NV12 走 VIC 的格式核对 | nvmpi 包装层选项覆盖不全（IDR 间隔/SPS-PPS 插入等映射未知）；av 16.1.0 ↔ ffmpeg 4.2 补丁的 API 断层；wheel 可复现性丧失 | 丢 SRTP/RTCP/REMB/NACK 与 pico-bridge 兼容；map 已有边界决策否决 |
| Pico 兼容 | profile=Baseline + CBR + 无 B 帧 + insert-sps-pps=true——全部与现产线一致（见下） | 同左（若 nvmpi 暴露这些旋钮） | 未知 |
| 结论 | **做** | 否 | 否（过度） |

**Pico 兼容性事实核对**【事实+推导】：aiortc SDP 只 offer `42001f`/`42e01f`（constrained baseline, level 3.1, packetization-mode 1；codecs/__init__.py:96-104）。2560×720=7200 宏块/帧 ×30 = 216000 MB/s，按 H.264 Annex A 已超 level 3.1 上限（3600 MB/帧、108000 MB/s）、需 level 4.0——**但今天 2M 档软编流就在这个"名不副实"的 SDP 下被 Pico 正常硬解**（zed-fpv map e2e 120ms 验收在案），nvv4l2h264enc 出的 SPS level_idc 同样自动按分辨率抬升，风险等级不变【推断：接收端不强制 level 校验，有现网实证】。保持 profile=Baseline（默认）即可，不必动 disable-cabac。

**方案 A 变体**（记录备选）：aiortc #559 的免转码通道——让自定义 track 直接产 `av.Packet`，sender 走 `encoder.pack()`（rtcrtpsender.py:321-323，`_split_bitstream`+`_packetize` 复用）。编码线程从 executor 挪到自家子进程读线程。改动面更大（track 类+线程模型），收益与 A 相同，**不建议首选**。

### 4.4 对 REMB 动态码率的影响（与 ticket 04 的关系）

【事实】运行时改码率可行，但证据有一处矛盾需要实测关闭：

- `gst-inspect` 说 `bitrate`「changeable only in NULL or READY state」（§3 P3）；
- NVIDIA 员工 DaneLLL 2023-06-05 论坛原话："**Bitrate can be changed in runtime.** We will check this and fix the description."（起因是 RidgeRun 工程师用 GstD 在 PLAYING 态改 `bitrate` 成功；https://forums.developer.nvidia.com/t/missing-bitrate-documentation-for-nvv4l2h264enc/255386 ）——即属性 flag 标注是错的/没人修；
- V4L2 层对应 `V4L2_CID_MPEG_VIDEO_BITRATE`（L4T API 文档在册）。

【推断→设计】硬编路径下 REMB 闭环比软编更顺：

```
现状（ticket 04 修法）：REMB → target_bitrate → 漂移>10% → 整个 libx264 codec 重建（出 IDR）
硬编方案：REMB → target_bitrate → 漂移>10%（同一迟滞）→ 控制行 "BITRATE <v>" 写子进程
         → g_object_set(enc, "bitrate", v)（PLAYING 态，NVIDIA 员工确认）
         → 不重启、不强制 IDR；骤降时可选 force-IDR 一次保画质
```

即 ticket 04 的「漂移重建」语义在硬编版升级为「运行时设值」——重建路径（管道重启 ~几十 ms + 黑帧）留作兜底。PLI 路径同理：`force_keyframe=True` → 控制行 → `enc.emit("force-IDR")`。

GOP 映射【事实+需实测】：nvv4l2h264enc 有两个独立旋钮：`idrinterval`（IDR 间隔，默认 256）与 `iframeinterval`（I 帧间隔，默认 30）。对 WebRTC 应设 `idrinterval = <GOP>`（对齐 teleimager `_GOP_LENGTH`/yaml）+ `insert-sps-pps=true`；`iframeinterval` 语义（非 IDR 的 I 帧节拍）建议置 0 以免产生无 SPS/PPS 的裸 I 帧——两个参数的交互在实机 A/B 复核（§6）。

---

## 5. 对 pacer / 延迟目标的影响（buffer<40ms / e2e<100ms @≥4M）

1. **NVENC 不治病灶**【事实链】：jitter buffer 膨胀的主因是**发送端帧内背靠背突发**（01-send-path.md §2.3：8M 档 26 包/帧零间隔连发）+ REMB 码控断开（ticket 04）。这两项由 pacer（tickets 02/03）与 04 修复；NVENC 一个包都不会替你匀着发。**先 02/03/04、后 NVENC** 的顺序不变。
2. **NVENC 砍的是常数项与方差**：
   - 编码时延：硬编同族元件量级参考（**二手证据**，RidgeRun wiki，TX2+JetPack 4.5，非 Orin）：`nvv4l2h264enc maxperf-enable=true` 下 1080p50 **均值 ~8ms**/峰值 ~12ms，720p50 **均值 ~5ms**/峰值 ~10ms；码率与码控模式不影响处理时间，High profile 显著抬高峰值（https://developer.ridgerun.com/wiki/index.php/GStreamer_Encoding_Latency_in_NVIDIA_Jetson_Platforms ）。Orin NX 世代更新，2560×720（1.84MP，介于 720p/1080p 之间）@30 预期落在个位数 ms【推断，需用元件自带 `MeasureEncoderLatency` 实测】。
   - 对照软编：现产线 libx264 **threads=1** ultrafast（image_server.py:139）跑 2.6MP——单核 A78AE 上单帧编码时间从未实测，量级怀疑 10-25ms+ 且随画面复杂度波动【推断；探测时 bridge 未运行，无 CPU 基线】。NVENC 把这项变成近似常数并释放约一个核给 asyncio/DTLS/信令。
   - 帧尺寸方差：HW CBR（可选 EnableTwopassCBR）+ 小 `vbv-size` 让每帧字节数更贴预算 → pacer 的 leaky-bucket 更好摊、REMB/到达时间估计更少被大 IDR 帧扰动【推断】。
3. **对验收线的净效应**【推断】：4M 档 e2e <100ms 的预算里，编码段若从 ~15ms±波动 降到 ~5ms 近似常数，直接给网络+pacer 段腾出 10ms 余量；`vbv-size` 默认 4M bit（≈1 秒@4M）必须调小（帧预算的 1-2 倍量级），否则 CBR 收敛慢反而制造帧间尺寸波动——列为上机第一调参项。
4. **8M 档与 60fps 展望**【推导】：55→111 MP/s 仍只占 NVENC 产能 8→16%；软件栈瓶颈届时转移到 ZMQ/转换/打包侧，编码器不再是指名对象——这正是把它独立成图的立项理由。

---

## 6. 未验证项 / 下一步（全部要求非操作员时段或停机窗口；本次全程只读未做）

| # | 未验证项 | 验证方法（占位） | 风险 |
|---|---|---|---|
| 1 | `bitrate` PLAYING 态运行时改在 **本机 L4T 35.3.1** 是否成立（NVIDIA 员工说行、属性 flag 说不行） | 空闲窗口起子进程管道 + `g_object_set` 改值 + 观测输出码率 | 低；失败则退回「管道重启式码控」（4.4 兜底） |
| 2 | 2560×720@30 实测编码延迟与 `maxperf-enable`/`preset-level`/`vbv-size` 剂量 | 元件 `MeasureEncoderLatency=true` + appsink 时戳 | 低 |
| 3 | `appsrc→nvvidconv→appsink` 全链往返延迟与丢帧语义（含 BGR 直喂 vs I420 预转换的选择；nvvidconv 系统内存输入支持哪些格式未逐条核对） | 空闲窗口管道化测试（非推流时段） | 中（方案 A 的核心调参面） |
| 4 | `iframeinterval=0 + idrinterval=<GOP>` 组合的实际 IDR/SPS-PPS 节奏；nvenc 自动 level_idc 与 SDP 42e01f 并存下 Pico 解码（现网 2M 已实证类似局面，但硬编 SPS 细节不同） | PC 浏览器/python 接收脚本先验，再上 Pico | 低-中 |
| 5 | 软编基线编码耗时（libx264 threads=1@2560×720）——A/B 对照的诚实前提 | bridge 运行时段 `py-spy`/日志打点（不动 aiortc，只观测） | 低 |
| 6 | 子进程崩溃检测/重启语义、NVENC 会话独占性（`videohubd` 是否长期占用 msenc 未查） | 读 `/dev/nvhost-msenc` 打开者（fuser/lsof，只读）后再定 | 低 |
| 7 | aiortc 升级耦合：方案 A patch 面全在 teleimager（`_encode_frame` 替换），沿用 t01 的「启动锚点断言 + 版本 pin」护栏即可 | 照 01-send-path.md §8.2 套用 | 低 |

**下一步排序建议**：本图（aiortc-pacer）按既定顺序收 02/03/04；NVENC 立图时以本文 §4.3 方案 A 为蓝本、§6 的 1-3 为首批 spike（半天量级、不碰产线），验收复用双线制（时间码照片法 + APK stats）。

---

## 来源清单

实机（`unitree@192.168.10.13`，SSH BatchMode 只读，2026-08-29）：
- P1-P6 全部命令见 §3 原文（`cat /proc/device-tree/model`、`/etc/nv_tegra_release`、`ls /dev/nvhost-*`、`v4l2-ctl --list-devices`、`gst-inspect-1.0 {nvv4l2h264enc,nvv4l2h265enc,nvv4l2decoder,nvvidconv,--version}`、`command -v ffmpeg`、`nproc`、`top -bn1`、两个 conda env 的 `import av, aiortc`、`/usr/bin/python3` import gi）

NVIDIA 官方：
- Jetson Orin NX Series Data Sheet（DS-10712-001 v0.5）：https://developer.nvidia.com/downloads/jetson-orin-nx-series-data-sheet （Table 7/8、NVENC 特性、功耗档）
- Orin 家族规格表：https://www.nvidia.com/en-us/autonomous-machines/embedded-systems/jetson-orin/
- AGX Orin Technical Brief v1.2：https://www.nvidia.com/content/dam/en-zz/Solutions/gtcf21/jetson-orin/nvidia-jetson-agx-orin-technical-brief.pdf
- Orin Nano 无 NVENC：https://docs.nvidia.com/jetson/archives/r35.3.1/DeveloperGuide/text/SD/Multimedia/SoftwareEncodeInOrinNano.html
- L4T 35.3.1 Accelerated GStreamer（元件清单/码控/Two-pass/SPS-PPS）：https://docs.nvidia.com/jetson/archives/r35.3.1/DeveloperGuide/text/SD/Multimedia/AcceleratedGstreamer.html
- L4T 35.3.1 V4L2 Encoder API（/dev/nvhost-msenc、BITRATE control ID、LOW_LATENCY 调优枚举）：https://docs.nvidia.com/jetson/archives/r35.3.1/ApiReference/group__V4L2Enc.html
- L4T 35.3.1 WebRTC 硬编集成页（NvEncoder）：https://docs.nvidia.com/jetson/archives/r35.3.1/DeveloperGuide/text/SD/HardwareAccelerationInTheWebrtcFramework.html
- JetPack↔L4T 对应：https://developer.nvidia.com/embedded/jetpack-archive （「JetPack 5.1.1 … [L4T 35.3.1]」）
- NVIDIA 论坛（员工确认运行时改码率，**官方员工回复，非正式文档**）：https://forums.developer.nvidia.com/t/missing-bitrate-documentation-for-nvv4l2h264enc/255386

ffmpeg / PyAV / GStreamer：
- ffmpeg master `allcodecs.c`（nvmpi 零匹配）：https://raw.githubusercontent.com/FFmpeg/FFmpeg/master/libavcodec/allcodecs.c
- ffmpeg 官方 codec 文档（nvmpi 零匹配）：https://ffmpeg.org/ffmpeg-codecs.html
- ffmpeg-devel 2020-06 nvv4l2 补丁线程：https://ffmpeg.org/pipermail/ffmpeg-devel/2020-June/263746.html （及 Khirnov 回复 …263762.html）
- jocover/jetson-ffmpeg（nvmpi 实体仓库，2021 冻结、目标 ffmpeg 4.2）：https://github.com/jocover/jetson-ffmpeg
- 社区续命 fork：https://github.com/LinusCDE/mad-jetson-ffmpeg
- PyAV README（wheel 自带 ffmpeg / `--no-binary`）：https://raw.githubusercontent.com/PyAV-Org/PyAV/main/README.md
- GStreamer 上游无此元件：https://gstreamer.freedesktop.org/documentation/nvv4l2h264enc/nvv4l2h264enc.html （404）

aiortc（repo = `aiortc/aiortc`）：
- 1.14.0 `codecs/__init__.py`：https://raw.githubusercontent.com/aiortc/aiortc/1.14.0/src/aiortc/codecs/__init__.py （本机 1.15.0 同构，md5 依据 01-send-path.md §1）
- issue #116（jlaine：无插件 API、建议 monkey-patch）：https://github.com/aiortc/aiortc/issues/116
- issue #390 / #588（PyAV 依赖、nvenc 排查）：https://github.com/aiortc/aiortc/issues/390 、https://github.com/aiortc/aiortc/issues/588
- PR #488（h264_omx 硬编先例，已合后移除 #1252）：https://github.com/aiortc/aiortc/pull/488 、https://github.com/aiortc/aiortc/pull/1252
- PR #1199（open 的 nvenc PR）：https://github.com/aiortc/aiortc/pull/1199
- PR #559（免转码 pack() 路径）：https://github.com/aiortc/aiortc/pull/559

二手（已在正文标注）：
- RidgeRun 编码延迟 wiki（TX2/JP4.5 实测表）：https://developer.ridgerun.com/wiki/index.php/GStreamer_Encoding_Latency_in_NVIDIA_Jetson_Platforms

本地源码与仓库文档：
- 本机 aiortc 1.15.0（conda `teleopit` env）：`codecs/__init__.py:31,95-104,167-183,190`、`codecs/h264.py:20-25,204-246,248-296,298-302,304-314`、`rtcrtpsender.py:14,277-292,308-309,318-320`（1.14.0 实机 md5 一致）
- teleimager（`F:\Chufan_Rui\teleop\teleimager`，zed-bridge 分支）：`src/teleimager/image_server.py:48,87-109,114-166,477-503`
- 仓库文档：`docs/wayfinder/2026-08-29-aiortc-pacer/map.md`（边界决策 1/3、验收双线）、`tickets/04-remb-bitrate-adaptation-fix.md`、`research/01-send-path.md`（§1 md5、§2.3 突发体量、§8 pin 建议）、`research/videoserver-ref-comparison.md`（现链路软编参数、Pico 端 Unity.WebRTC 3.0.0-pre.7 不可设 jitter buffer）
