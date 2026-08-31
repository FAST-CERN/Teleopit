---
id: nvenc-hw-encode-map
title: "NVENC 硬编替换软编：FPV 编码段换引擎并四线验收"
labels: [wayfinder:map]
status: open
created: 2026-08-29
---

## Destination

Jetson Orin NX 的 NVENC 硬编（GStreamer `nvv4l2h264enc` 子进程，方案 A）替换 teleimager 现行 libx264 软编：合入 `zed-bridge` 分支、双 checkout 部署、Pico 实机**四线验收**全过：

1. **编码段 A/B**：硬编延迟（同法实测）≤ 软编基线（量级预期 ~8ms vs 10-25ms 级）
2. **CPU**：编码占用下降可观测（先量软编基线）
3. **e2e 不劣化**：≤ **85ms**（pacer-t03 基线 80ms + 5ms 容差）
4. **主观画质不降**：Pico 同码率对比；同步记实际 outbound 码率对照（x264 无 VBV 过冲 vs NVENC CBR 收敛）

达标即收图；e2e 改善与 buffer 下探（预算重开论点）均记红利、不设线（2026-08-31 决策）。

## Notes

**领域**：ZED FPV 链路发送端编码段换引擎。aiortc-pacer 图（**2026-08-31 CLOSED**，5/5 票）边界决策 1 已将 NVENC 列为独立成图——本图即那张图。

**前置研究**（本图的直接输入，开图前已完成）：`docs/wayfinder/2026-08-29-aiortc-pacer/research/jetson-orin-nvenc-capability.md`。要点：设备 = Orin NX 16GB / JetPack 5.1.1，NVENC 在位，2560×720@30 仅占 680 MP/s 吞吐的 8%；推荐路径 = 系统 python3 + PyGObject 子进程跑 `appsrc ! nvvidconv ! nvv4l2h264enc ! appsink`，teleimager 照 `jetson_software_encode_frame` 先例替换 `h264.H264Encoder._encode_frame`（~150-250 行，零新增包、零 aiortc 改动）；ffmpeg-nvmpi/PyAV 重编路线已被证据否决。

**Charting 会话锁定的边界决策**（2026-08-29，四项）：

1. 终点 = **实装上线**（合入 + 部署 + Pico 验收 + A/B 对照；先例 zed-fpv / bsi-real-hw 图）。本图携带执行，非纯规划图。
2. 排序 = **现在开图、验收挂闸**：前期票（01/02/03/04/05）与 pacer 图并行推进互不阻塞；仅 06 验收等 pacer 图 ticket 03（e2e 双线验收）关闭后执行——两图归因都干净。
3. 验收 = **四线制**（见 Destination）。
4. 范围 = 只换编码器；H.265（需给 aiortc 写整套新 codec 类、Pico 侧不确定）与 60fps（动 ZED 采集面与 Pico 解码面）双双出图，将来各自独立成图。

**背景数据**（pacer 图 CLOSED 2026-08-31 后的现状）：

- **e2e 全档拉平：2M/4M/8M 均 ~80ms**（pacer 前软编：120/200/220ms）。工作参数基线：pacer on / k=1.5 / 4M / gop30 / HD720 SBS。
- **残余 jitter-buffer 下限 ~30-48ms 归因软编 E≈26ms**：摊平窗口 W = 33.3ms − E − margin 被挤到 ~4.5ms。硬编后 E → ~11-13ms（t01 同进程往返 10.7ms + IPC），W 重开至 ~17-20ms → **buffer 下探 = 本图核心论点**（红利观测不设线）。
- **x264 ABR 无 VBV，8M 目标实测 15-28Mbps 过冲（3-4×）**（pacer t04 发现）——NVENC 的 CBR + `vbv-size` 是对症药；outbound 实测量化欠账归本图 06 第 4 线复测。
- NVENC `bitrate` PLAYING 态可运行时设——t01 已实机裁决可行（升档 2s 收敛；满熵降档欠冲 ~65% 待 02 真实内容复验 + force-IDR 备选）。

**组件与位置**：

- `teleimager` — F:\Chufan_Rui\teleop\teleimager（fork 分支 `zed-bridge`）。挂点：`h264.H264Encoder._encode_frame` 替换（`jetson_software_encode_frame` 先例，`src/teleimager/image_server.py:114-166`）；RTP 打包/`_split_bitstream`/FU-A 路径不动。
- 子进程编码器 — 系统 `/usr/bin/python3` + PyGObject（gi + Gst 1.16.3 实机已验证可用），不进 conda env、零新增包。
- aiortc — 实机 `teleimager` env 1.14.0（av 16.1.0），与本机 1.15.0 发送路径五文件 md5 一致（`01-send-path.md` §1）；无插件 API，monkey-patch 是维护者认可做法（issue #116）。
- 接收端不变：pico-bridge APK（`feat/stereo-fpv`）。SDP fmtp 42e01f（constrained baseline level 3.1）现状下 2560×720 已被 Pico 正常解码（zed-fpv t06 实证）。

**部署事实**（必读，跨会话记忆 `jetson-teleimager-deploy-topology`）：Jetson 双 checkout 双 env（活体 = `/home/unitree/teleimager` + `teleimager` env）；机器人无代理；scp 前先 import 定位活体、改完双推、运行 env 冒烟、md5 核对。

**停机窗口纪律**：01/02 涉及实机操作，只在 bridge 停止、无操作员的窗口执行；全程禁止在直播时试编码。

**Tracker 约定**（同 aiortc-pacer map）：Ticket = `tickets/NN-*.md`（frontmatter labels/status/assignee/blocked-by）；Frontier = open 且依赖全闭且未认领；Resolve = 正文追加 `## Resolution` + status: closed + 本 map Decisions 追加一行；研究产物放 `research/`。跨图依赖写法：`aiortc-pacer-map/t03`（人工核对其 map 的 Decisions 确认已 CLOSED）。

## Decisions so far

- 2026-08-31 t04 CLOSED（TDD 合入，teleimager `zed-bridge` `9c0014a` 已推 origin）：`_nvenc_child.py`（gi 延迟 import；POSIX pass_fds / Windows handle 继承双分支）+ `image_server.py` wrapper/开关/双面锚全按 t03 九项落实；19 测试三层之一二（mock 子进程真实驱动 + 生成器端到端过真 aiortc 编码器 + 配置锚单测），41 passed。TDD 修出两真 bug：2-D I420 数组 `len()`=行数 → 头实体不符流错位（改 nbytes）；`_kill_child` 不置 None → 重试死循环。Windows 无 pass_fds、pytest 唯一 env = conda teleopit 环境事实入档。实机部署冒烟归 05。
- 2026-08-31 t03 CLOSED（设计 grilling 九项全定，实现规格见票 Resolution）：**协议 = AU 专线管道**（stdin 命令 + pass_fds 专线回 AU + stdout 专职收 C 噪声；ZMQ PAIR 否决——不省时/无 pyzmq/EOF 语义差）；**落位 = 包内自包含单文件** `_nvenc_child.py`（gi 延迟 import 供 PC 测试）；**REMB = 10% 迟滞直传**（永不重建，PLI 唯一 IDR 触发）；**开关 = yaml encoder:soft|hard 默认 soft + TELEIMAGER_ENCODER env 覆写**；**崩溃 = 无限重试+退避封顶 1s**（无自动回退，故障可见）；**参数定稿**（iframeinterval=_GOP_LENGTH 显式、vbv-size=bitrate/30 随码率运行时设、B=0 固化 lockstep）；**pacer 不动**（budget 15.1ms 不再被钳，t06 核实）；**锚断言双面+回退软编**；**测试三层**（mock 子进程/配置锚单测/05 冒烟）。
- 2026-08-31 t02 CLOSED：原型五项全裁决——**E 真值 = 带载 p50 15.2ms（I420 传输）/ 21.3ms（BGRx）**（摊平窗口 ~4.5→~17ms，预算重开论点量化成立）；解码闭环合成 300/300 + 真实内容 179/179 + PNG 目检；**force-IDR = action signal**（`enc.emit`，非属性；NULL 态 emit 的 C printf 污染 stdout 是坑，协议须噪声隔离）；真实内容降档无欠冲（满熵 65% 为源特性）、升档 1s 收敛；崩溃重启 268ms 恢复 + SPS/PPS/IDR 续流对账成立。**03 关键输入：传输格式定 I420**（BGRx 不敌软编孤立值）、p95 计预算、协议噪声隔离、lockstep 一帧一 AU 实证。ZED USB2 口问题复发一次（重插修复）。详见 `research/02-prototype-subprocess.md`。
- 2026-08-31 **前置闸门解除（跨图依赖 `aiortc-pacer-map/t03` 已 CLOSED）**：pacer 图真机验收 e2e 拉平 120/200/220→80/80/80ms（2/4/8M），t06 的 e2e 基线 = 80ms +5ms 容差。**移交三件套**：①残余 buffer 下限归因软编 E≈26ms（摊平窗口被挤到 ~4.5ms）→ 硬编后预算重开是本图核心论点，02/03 设计按此展开；②x264 ABR 无 VBV 过冲（8M 目标 3-4×）的 outbound 实测量化欠账归本图复测；③ZED USB2 口故障已修（重插 USB3 后 30fps 稳），t01 环境事件注记已更新。工作参数基线：pacer on/k=1.5/4M/gop30/HD720 SBS。
- 2026-08-31 t01 CLOSED：停机窗口四项全裁决——①PLAYING 态运行时改 `bitrate` **可行**（升档 2s 收敛；满熵下降档欠冲 ~65%，02 用真实内容复验 + force-IDR 备选）→ REMB 映射走实时设值；②编码 A/B：硬编往返 p50 **10.7ms**（含 VIC 转换，IPC 未计）vs 软编 p50 **15.6+2.1ms**——第 1 验收线数据点已齐；③**BGR 24 位被 nvvidconv 拒，集成格式 = BGRx**；首帧 47ms（会话建立，崩溃恢复常数）；④NVENC 零占用，SPS = Constrained Baseline/L4.0 与 SDP 42e01f profile 族对齐。产出 `research/01-offline-verification.md`。⚠️ ZED 相机当前打不开（外部启动尝试失败 ×5）——真源票与 pacer 图硬件会话前排期先修。

## Not yet specified

- 验收通过后 `encoder: hard` 是否转为默认档、切换纪律怎么定（收图前一行定案即可）
- 硬编路径下 PLI→force-IDR 的入会首帧时延变化（06 观测项，仅异常时展开成票）

## Out of scope

- H.265 / AV1 编码（aiortc 无 codec 类，Pico 侧不确定；将来独立成图）
- 60fps、分辨率变更（动 ZED 采集面与 Pico 解码面；将来独立成图）
- ffmpeg-nvmpi / PyAV 源码重编路线（方案 B，前置研究已否决：nvmpi 未进主线、补丁冻结 2021）
- 接收端（pico-bridge）任何改动
- 多视频流共用 NVENC 的会话/吞吐预算分配（腕部相机等将来接入时另图）
- 向 aiortc 上游回馈硬编 PR（可选后续）
