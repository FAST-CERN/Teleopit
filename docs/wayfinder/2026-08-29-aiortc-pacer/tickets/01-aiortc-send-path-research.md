---
id: 01-aiortc-send-path-research
title: "aiortc 发送路径与 pacing 挂点研究"
labels: [wayfinder:research]
status: closed
assignee: claude
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

**CLOSED 2026-08-29** — 产出：`research/01-send-path.md`（288 行；本机 1.15.0 + Jetson 实机 1.14.0 双源核实，发送路径五文件 md5 字节级一致，行号两版通用）。

六点结论：

1. **发送循环**：`_run_rtp` 单一长活协程——每帧 `recv()` + executor 编码（唯一真实挂起点），随后 `for payload` 逐包 `serialize → SRTP protect → sendto`（rtcrtpsender.py:377-401）；帧内 await 全不真实挂起，**突发对事件循环原子**；逐包 sleep 插 :401 前可行且改善循环响应性。
2. **主线无 pacer**：CHANGELOG 全历史无条目；discussion #965 官方原话「does not implement a leaky-bucket pacer or anything like that」；无 related PR。
3. **NACK 重传旁路**：在 DTLS 泵任务 `__run` 上经 `_handle_rtcp_packet → _retransmit` 直达 transport（:274-276, :332-349），完全绕过主循环——pacer 管不住也**不该管**（pacer 的 sleep 窗口恰是重传的调度窗口，零额外延迟）。
4. **队列语义（新发现）**：上游三级丢旧保新（maxsize=1），但 `relay.subscribe` 默认 `buffered=True` → 订阅者队列**无界**（contrib/media.py:537/628）——发送持续慢于 30fps 时无界堆积（≈5.3MB/帧）；pacer 必须绝对时间表 + 落后追赶（k≈1.2-1.5），可选 `buffered=False`。
5. **挂点判定**：A. 替换 `_run_rtp`（**推荐**，~90-110 行，照 `_encode_frame` patch 风格；坑：`__` 名字改写、`__rtp_exited` 兜底）；B. encoder 层不可行（executor 内同步返回整帧列表）；C. transport 层否决（~30-50 行但会把 NACK 重传和 RTCP SR 一起 pace）。
6. **版本**：实机 1.14.0 / 本机 1.15.0；建议 pin 精确版本 + patch 启动时源码锚点断言 fail-fast。

**fork-aiortc 判定：不触发**（monkey-patch 可行，有同风格先例 + 版本一致护栏）；中止条款移交 ticket 02（≥3 处耦合改动 / 锚点连续破 / 决定上游提 PR）。
