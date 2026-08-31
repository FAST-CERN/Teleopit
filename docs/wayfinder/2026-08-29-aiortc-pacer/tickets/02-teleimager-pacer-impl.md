---
id: 02-teleimager-pacer-impl
title: "teleimager 内置 pacer 实现与 PC 端单机验证"
labels: [wayfinder:prototype]
status: open
assignee: claude
blocked-by: [01-aiortc-send-path-research]
---

## Question

按研究 ticket 选定的挂点，在 teleimager `image_server.py` 内实现 pacing（与现有 H264Encoder monkey-patch 同风格），并在**不戴头显**的前提下先于真机验收完成单机验证：

1. pacing 参数选型（摊平粒度/分布策略/超预算丢帧策略——吃研究结论 + map Not yet specified 的三个开放点在此升格）。
2. 配置开关：`webrtc.pacer: on|off`（yaml），默认先 off 保底，验收过后再定默认值。
3. 单机验证法：PC 浏览器（或 python aiortc 接收脚本）连 `/offer`，用 `getStats` 读接收端 jitterBufferDelay 对比 on/off——不依赖头显即可证伪/证实 pacing 效果。
4. 回归：NACK 丢包恢复延迟、PLI 关键帧时延在 pacing 下不劣化。
5. 部署：双 checkout 推送 + 运行 env import 冒烟（按 deploy-topology 记忆的流程）。

产出：patch 实现 + on/off 对照数据（研究/验证记录进本 ticket Resolution）。

## Progress（2026-08-31）

实现 + PC 单机验证完成（teleimager `zed-bridge` `441a998`）；部署与真机对照待硬件会话（与 t05 部署同批）。

**参数定案**（map Not-yet-specified 三点在此升格）：

1. 摊平粒度 = **逐包**，包距 = span/(N−1)，首包立即、尾包后不留 sleep；span = min(k 窗口, 本帧预算)。
2. 帧内分布 = **均匀 + 绝对时间表**（anchor + i·gap；睡过头被吸收不累积；deadline 一到即冲掉剩余间隔）。
3. 超预算策略 = **不丢帧**。每帧预算 `budget = 帧间隔 − 实测编码耗时 − 3ms`（编码耗时由 h264 patch 在 `codec.encode` 外圈计时、`encoder.last_encode_s` 上报）；预算不足缩窗、预算 ≤0 退化不 pace——**fps 永远优先于平滑**；连续零等待帧按 0.5ⁿ 衰减预算（粗定时器/落后态防螺旋）。帧堆积仍由 t05 有界队列兜底，分工不变。
4. 配置：`webrtc.pacer`（默认 off）+ `TELEIMAGER_PACER` env 覆盖（免改 yaml 做 A/B）+ `webrtc.pacer_k`（默认 1.5，clamp 1.0–3.0）。版本护栏 = 启动锚点断言（`_run_rtp`×3 / `_retransmit` / `stop`），断言破 → 拒绝安装 patch（fail-fast）。

**PC 单机 on/off 对照**（loopback；合成噪声源走 zed ZMQ 协议 → 真 ImageServer → aiortc 接收端 + `_handle_rtp_packet` 到达时间 tap；harness 已提交 tests/）：

| 臂 | 源 | fps | goodput | 帧到达跨度 median/p95/max (ms) | 1ms 窗最大包 |
|---|---|---|---|---|---|
| off | 2560×720 噪声 | 29.8 | 4.0M | 1 / 25 / 485 | 86 |
| on 无护栏（已废弃） | 同上 | **10.4** | 4.7M | 23 / 146 / 6083 | 81 |
| on 护栏 v1（保守式） | 同上 | 29.7 | 4.0M | 3 / 40 / 229 | 84 |
| off-720 | 1280×720 噪声 | 29.9 | 11.5M | 2 / 7 / 226 | 76 |
| **on-720（E 锚定护栏）** | 同上 | **29.9** | **12.2M** | **11 / 29 / 58** | 77 |

- **护栏必要性被反证**：无护栏版在编码饱和（E≈33ms，2560 噪声）下，Windows 15.6ms 定时器量子把 22ms 窗口撑成 ~31ms → E+W > 33.3ms → sender 慢性落后 → t05 队列丢帧（10.4fps、56KB 大帧）→ REMB 锯齿钉死 2–2.8M。护栏版同条件恢复 29.7fps。
- **E 锚定的作用**：保守式（连等帧时间一起扣）在编码有富余时给不出预算；E 锚定版在 720p（E≈7ms、等帧≈15ms）给出满预算 23ms → 摊平真正张开（median 2→11ms、max 226→58ms），fps/goodput 持平。server 遥测：`avg recv+encode 22.1ms, avg pace budget 23.0ms`。
- **Windows 残余**（非缺陷，平台属性）：1ms 窗 77 包、RFC3550 jitter 升高 = 15.6ms 量子印记（0.57ms 的 sleep 实际睡 ~15.6ms）。Linux/Jetson ~1ms 量子下预期消失——t03 实机验证项。
- **REMB 观察**：2560 噪声下两臂都有 ~1 次/s 重建锯齿（off 锯 2–12M；无护栏 on 钉 2–2.8M）；720p 仅 6 次/40s。噪声+无 VBV 过冲是极端组合；真实内容动力学不同（t04-b 真机 2M 档 REMB 自然爬 10M）。t03 记录即可，不在本票修。

**NACK/PLI 回归（票面第 4 条）**：结构性不回归——重传在 DTLS 泵任务直达 transport（research §3），patch 只换 `_run_rtp`；锚点断言显式校验 `_retransmit` 旁路仍在。pacer 的 sleep 窗口即重传调度窗口（零额外延迟）。PLI 仅置 `force_keyframe`（rtcrtpsender.py:351-355），关键帧时延最多加一个摊平 span（≤22ms 上界，t03 实测）。A/B 全程 NACK 活动（丢包 0.01–0.07%）无风暴迹象。

**测试**：`tests/test_pacer_impl.py` 22 例（pacer 数学 9 / 预算守卫 4 / 配置门控 6 / 锚点断言 3）+ REMB 回归 4 例全绿；`tests/standalone_pacer_check.py` 驱动真 `RTCRtpSender` 实例跑 patched 协程（每 payload 恰一次上线、帧跨度≈窗口、MediaStreamError 清理路径完整、`__rtp_exited` 置位）。本机 pytest asyncio 挂死债不变（t05），协程行为以 standalone 见证。

**待办（硬件会话）**：①双推 + 冒烟（deploy-topology 流程，与 t05 部署同批）；②t03 剂量曲线复测（pacer on/off × 2M/4M/8M：Linux 定时器下的真实平滑度 + avgJitterBuffer 双线判定 + 实际 outbound 码率）。

## Resolution

（待填）
