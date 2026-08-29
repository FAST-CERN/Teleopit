---
id: 01-aiortc-send-path-research
title: "aiortc 发送路径与 pacing 挂点研究"
labels: [wayfinder:research]
status: open
assignee: ""
blocked-by: []
---

## Question

aiortc 的 RTP 发送路径里，从 encoder 产出 packet 到 socket send 的完整调用链是什么？哪个点可以插入 pacing（把每帧的背靠背突发摊平到帧间隔内）而 (a) 不破坏 NACK/RTX 重传路径，(b) 不引入 asyncio 任务阻塞，(c) patch 面最小（teleimager 内 monkey-patch 可行性）？

需核实（读机器人 env 内实际安装的 aiortc 源码，版本以实机为准）：

1. `RTCRtpSender` 的发送循环：encoder generator yield packet → 打包 RTP → `loop.create_datagram_endpoint` send 的具体协程结构；await 点在哪、能否逐包 sleep。
2. 是否已有任何 pacing/速率控制（aiortc 主线历史上有无 related PR）。
3. NACK 响应重传（`RTX` / send stream）与主发送流的并发关系——重传是否绕过主循环（pacer 是否管得住它）。
4. `MediaRelay` 与 `BGRArrayVideoStreamTrack` 队列语义在发送变慢时的行为（会不会反压丢帧，还是队列堆积）。
5. 备选挂点对比：patch `RTCRtpSender` 内部 vs 给 encoder yield 路径包一层异步节流 vs datagram transport 层。
6. 机器人 env 的 aiortc 具体版本号 + pin 建议。

产出：`research/01-send-path.md`（调用链图 + 挂点对比表 + patch 面积估计 + fork-aiortc 触发判定）。研究类，可用 `/research` 子代理 + 本地/机器人源码核实。

## Resolution

（待填）
