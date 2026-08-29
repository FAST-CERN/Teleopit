---
id: aiortc-pacer-map
title: "aiortc 发送端 pacing：解耦码率与 FPV 延迟"
labels: [wayfinder:map]
status: open
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

**部署事实**（必读，跨会话记忆 `jetson-teleimager-deploy-topology`）：Jetson 双 checkout 双 env（活体 = `/home/unitree/teleimager` + `teleimager` env），机器人无代理；scp 前先 import 定位活体、改完双推、运行 env 冒烟。

**Tracker 约定**（同 zed-fpv map）：Ticket = `tickets/NN-*.md`（frontmatter labels/status/assignee/blocked-by）；Frontier = open 且依赖全闭且未认领；Resolve = 正文追加 `## Resolution` + status: closed + 本 map Decisions 追加一行；研究产物放 `research/`。

## Decisions so far

（无——待首张 ticket resolve）

## Not yet specified

- pacing 算法参数：摊平粒度（按包/按字节预算）、帧间隔内分布（均匀/前紧后松）、码率超帧预算时的丢帧策略（与 BGRArrayVideoStreamTrack 队列 maxsize=1 最新帧语义的互动）
- 与重传的互动：NACK/RTX 包是否走同一 pacer、pacer 是否拖慢重传导致丢包恢复变慢（可能抵消部分收益）
- aiortc 版本锁定：patch 依赖内部结构，机器人 env 是否 pin aiortc 版本（防升级碎裂）
- PLI 关键帧请求路径在 pacing 下的时延（入会首帧等待变化）

## Out of scope

- NVENC 硬编、60fps 采集、专用 AP/信道（各自独立成图）
- 接收端（pico-bridge）任何改动
- 向上游 aiortc 回馈 PR（可选后续）
- 分辨率/帧率降档方案
