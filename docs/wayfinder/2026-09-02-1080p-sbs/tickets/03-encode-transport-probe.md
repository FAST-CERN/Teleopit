---
id: 03-encode-transport-probe
title: "编码传输实测：1080p E 分段 / 码率档 / pacer 预算 / WiFi 容量"
labels: [wayfinder:prototype]
status: open
assignee: ""
blocked-by: []
---

## Question

像素 ×2.25 的三个张力在 Jetson 上量化（NVENC 子进程直驱 + 若 01 已闭可接真源），定 04 合入的工作参数：

1. **E 分段**：3840×1080 I420 的 conv / pipe write / enc 三段各多少（现 720p 带载 E 15.2ms、栈内 recv+enc 20.2ms）→ pacer budget 会缩到多少（现 12.0ms）；若 budget < ~6ms 且 JB 回吐，shm 环形缓冲（估 −3.5~4ms）升级为正式票；
2. **码率档**：8M 起 / 12M 备选的 AU 尺寸、CBR 收敛窄带度、vbv-size=bitrate/30 跟随；
3. **包数与摊平**：每帧 RTP 包数（现 ~14 → 预计 ~32）在 22.2ms 窗口内的实际摊平形态；
4. **WiFi 容量**：今日接入（RTT 19ms）在 8M+ 出流下的丢包/REMB 行为——决定码率档与「回有线」优先级。

产出：`research/03-*.md` 工作参数建议（码率档定稿、预算判定、是否激活 shm 票）。

## Resolution
