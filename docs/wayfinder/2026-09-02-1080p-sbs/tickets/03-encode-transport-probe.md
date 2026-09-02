---
id: 03-encode-transport-probe
title: "编码传输实测：1080p E 分段 / 码率档 / pacer 预算 / WiFi 容量"
labels: [wayfinder:prototype]
status: closed
assignee: "claude-code"
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

2026-09-02 四项全落定（探针 `research/t03_probe.py` 真源 3840×1080 直驱子进程 + 真源 8M 佩戴轮；工件 stats_03_wear.txt / server3 摘录）：

**① E 分段（真源，conv/write/enc 三段 p50）**：conv **1.7-2.1ms**（NEON 优化，720p 持平，非瓶颈）/ pipe write 6.2MB **4.7-5.3ms** / **enc 等待 17.8-18.7ms（占 E ~70%，唯一大头；720p ~9.4 翻倍）**；E 合计 p50 24.9-26.6ms，enc p95 27.5ms。栈内 `avg recv+encode 31.1ms`、**pace budget 0.8ms**。**SPS level_idc=50（L5.0）实锤**——解码闸即在 L5.0 下通过。

**② 码率档**：静景三档全部内容受限（4M/8M/12M 的 AU mean 15.0/14.2/13.1 KiB，p90 ~18.7 持平，远低于 CBR 标称；无 filler 填充）——**档位对静态无感，运动场景才是考场**（归 05 观测）。vbv 跟随无失败打印（R 握手 vbv_set=true + B 切档零报错）。

**③ 包数摊平**：8M 真源 **20 包/帧**（720p ~14）；29.4fps 满速（产 29.2）；budget 0.8ms 下摊平事实上关闭，但 **JB 未回归**（见④）。

**④ WiFi 容量（8M 真源佩戴 3.5min）**：出流 ~5.2Mbps（内容受限）、**packetsLost=0 全程**、decodeFps 29.4-30.0、**avgJB cum ~15.0ms 稳定 / inst ~12.5ms**（对照 720p NVENC t06：cum 22.9-38 / inst 11.8——不劣反平）。

**裁定**：
- **04 工作参数定稿**：8M default / max 12M / gop30 / pacer on（budget ~1ms 事实无害）/ hard / `image_shape [1080,3840]` / bridge `--resolution HD1080 --output-width 3840 --output-height 1080`（真源 29.2fps 上限即产即消）。
- **shm 环形缓冲不转正**：只省 write ~5ms（budget 0.8→~6ms），治不了 enc 等待 18ms 大头；且 budget 0.8 下 JB 无回归 → 无强制力。留雾区为「E 优化包」的一部分（enc 等待拆解 = appsrc→nvvidconv→enc→appsink 全链时延，含 VIC I420→NV12——若 05 的 e2e A/B 线失败再启）。
- 风险注记：enc p95 27.5ms 逼近帧间隔，运动场景 AU 增大时 E 尾部可能触顶掉帧——05 监测 decodeFps 谷值。
