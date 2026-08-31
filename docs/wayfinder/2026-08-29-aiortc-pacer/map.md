---
id: aiortc-pacer-map
title: "aiortc 发送端 pacing：解耦码率与 FPV 延迟"
labels: [wayfinder:map]
status: closed
created: 2026-08-29
---

## Destination

teleimager 的 WebRTC 发送端具备帧内 pacing（把每帧 ~17KB 的 RTP 背靠背突发摊平到帧间隔内匀速发出），消灭「码率↑→到达抖动↑→jitter buffer↑」的耦合。验收双线（时间码照片法 + APK stats）：

- **可用线**：bitrate ≥4M 下 avgJitterBuffer <40ms 且 e2e <100ms
- **良好线**：avgJitterBuffer <30ms 且 e2e <80ms

达标后 4M~8M 画质与延迟不再互为赎金（zed-fpv map 定稿的 2M 只是沿曲线买的延迟）。

## Notes

**领域**：ZED FPV 链路的发送端延迟优化，zed-fpv map（2026-08-29 CLOSED，e2e 120ms@2M）的直接后续。

**背景数据**（zed-fpv ticket 06 实测，剂量效应单调）：

| 码率 | avgJitterBuffer | 端到端 |
|---|---|---|
| 8M | 150-165ms（爬升 + ~1.5% 丢包 NACK 风暴） | ~220ms |
| 4M | 112ms | ~200ms |
| 2M | 78ms | ~120ms |

**组件与位置**：

- `teleimager` — F:\Chufan_Rui\teleop\teleimager（fork 分支 `zed-bridge`）。现已有 `jetson_software_encode_frame` monkey-patch H264Encoder 的先例；pacing 按同一风格内置。
- `aiortc`（目标 patch 面）— 机器人 conda env 内 pip 安装，版本未 pin。发送路径候选挂点（研究 ticket 核实）：`RTCRtpSender` 的 RTP 发送循环 / encoder packet yield 路径 / MediaRelay。
- 接收端不变：pico-bridge APK（`feat/stereo-fpv` `353d70c`，stats 日志 + 时间码照片法已就位）。

**Charting 会话锁定的边界决策**（三票）：

1. 范围 = 只做 pacer；NVENC 硬编 / 60fps 采集 / 专用 AP 各自独立成图，不进本 map。
2. 验收 = 双线制（如上），达标即收图。
3. 实现 = **teleimager 内置 monkey-patch 优先**（部署走已踩熟的 scp 通道，机器人零新增依赖）；fork aiortc 仅当研究证明 patch 不可行时启用（git bundle 走 scp 安装）。

**范围补充**（2026-08-29，经对比研究后用户批准）：+ `tickets/04-remb-bitrate-adaptation-fix`（REMB 码控闭环修复，≈3 行，源自 `research/videoserver-ref-comparison.md` §3.2/§9）。不阻塞 02/03，但须先于 02/03 的复测合入——否则 8M 档下 pacer 与码控的贡献无法分离。

**部署事实**（必读，跨会话记忆 `jetson-teleimager-deploy-topology`）：Jetson 双 checkout 双 env（活体 = `/home/unitree/teleimager` + `teleimager` env），机器人无代理；scp 前先 import 定位活体、改完双推、运行 env 冒烟。

**Tracker 约定**（同 zed-fpv map）：Ticket = `tickets/NN-*.md`（frontmatter labels/status/assignee/blocked-by）；Frontier = open 且依赖全闭且未认领；Resolve = 正文追加 `## Resolution` + status: closed + 本 map Decisions 追加一行；研究产物放 `research/`。

## Decisions so far

- 2026-08-31 **t03 真机验收 + map CLOSED（用户裁决）**：e2e 剂量曲线拉平 120/200/220 → **80/80/80ms**（2/4/8M × pacer-on，照片法）；可用线 e2e <100ms ✅、buffer inst ~30-48ms 边缘（累计 57-61）；良好线未全达。t05 运动恢复 ✅（零 overflow、秒级追回免重连）、9.5min 稳定 ✅、重连不劣化 ✅、8M NACK 风暴消失。**残余 buffer 下限归因 = 软编 E≈26ms 挤压摊平窗口至 ~4.5ms**（fps 底线守住）→ 结构性解法=NVENC 硬编（已开图，验收票前置 t03 就此解除）。最终参数：pacer on / k=1.5 / 工作点 4M / gop 30 / HD720 SBS。t02/t04/t05 同日闭票（01 前期已闭）——**全图 5/5 票闭，map 终点以「e2e 轴达成 + buffer 轴移交 NVENC」结算**。换轮工具 `entry/run_stack.sh` 入 teleimager 仓库。
- 2026-08-29 t01 CLOSED：pacer 挂点定为**替换 `_run_rtp` 主循环**（~90-110 行，teleimager 内置 monkey-patch，照 `_encode_frame` patch 先例）；encoder 层不可行、transport 层否决（会连 NACK/RTCP 一起 pace）；NACK 重传天然旁路、不受影响；`relay.subscribe(buffered=True)` 无界队列是 pacer 的新增堆积风险 → 须绝对时间表 + 落后追赶；实机 aiortc 1.14.0（pin 精确版本 + 启动锚点断言）；fork 不触发。产出 `research/01-send-path.md`。
- 2026-08-29 t04 验收 a PASS（teleimager `6e738ac`+`e1a0e56` 已双推）：REMB→target_bitrate→codec 闭环双向打通——接收端钉 REMB=3M 后服务端**同秒**重建 7.758M→3M、46s 稳持零丢包、恢复 8s 爬回 ~12M；重建审计行常驻 image_server 日志。新发现：x264 ABR 无 VBV，8M 目标实测 15-28Mbps 过冲（3-4×）——t03 复测须记实际 outbound 码率。b/c 待 Pico 会话。
- 2026-08-29 **新缺陷实锤（阻塞 t04-c，真机两轮复现+干预验证）**：运动后延迟 ~5s 钉死，仅重连可清。根因 = `relay.subscribe(buffered=True)` **无界订阅队列常驻化**（t01 §4 风险兑现）：运动瞬态灌入 ~150 帧后输入=输出=30fps、永不排空；接收端 buffer 仅 93ms 无辜；REMB 对内部排队无感。修复方向 = 订阅队列丢旧保新（有界），与 pacer 正交且**独立成 ticket**；「丢帧策略」从 Not-yet-specified 升格为硬需求。证据在 t04 Progress。
- 2026-08-31 t02 实现 + PC 单机验证完成（teleimager `441a998`，部署待硬件会话与 t05 同批）：pacer = 逐包均匀摊平 + **每帧预算护栏** `budget = 帧间隔 − 实测编码耗时(h264 patch 上报) − 3ms`，预算不足缩窗、为零退化不 pace——**fps 永不换平滑**；k 默认 1.5、`webrtc.pacer` 默认 off + `TELEIMAGER_PACER` env 覆盖；启动锚点断言 fail-fast。PC A/B 反证了护栏必要性（编码饱和下无护栏 10.4fps → 护栏 29.9fps），E 锚定护栏在 720p 下摊平真正张开（帧到达跨度 median 2→11ms、max 226→58ms）且 fps/goodput 持平；Windows 15.6ms 定时器量化是 PC 残余突发根因，Linux 平滑度待 t03 实机判定。

## Not yet specified

- pacing 算法参数：（t02 已答，2026-08-31——逐包均匀摊平 + 每帧预算护栏 `budget=帧间隔−实测编码−3ms`，缩窗/为零退化不 pace，不丢帧；k 默认 1.5；详见 t02 Progress）
- 与重传的互动：（t01 已答，`research/01-send-path.md` §3——重传在 DTLS 泵任务上直达 transport、绕过主循环，pacer 管不住也不该管；pacer 的 sleep 窗口即重传调度窗口，零额外延迟）
- aiortc 版本锁定：（t01 已答 §8——实机 1.14.0 与本机 1.15.0 发送路径五文件 md5 一致；pin 精确版本 + patch 启动时锚点断言 fail-fast；t02 已实现锚点断言并接入配置门控）
- PLI 关键帧请求路径在 pacing 下的时延（入会首帧等待变化；t02 已给上界 ≤ 一个摊平 span ≈22ms，实测归 t03）

## Out of scope

- NVENC 硬编、60fps 采集、专用 AP/信道（各自独立成图）
- 接收端（pico-bridge）任何改动
- 向上游 aiortc 回馈 PR（可选后续）
- 分辨率/帧率降档方案
