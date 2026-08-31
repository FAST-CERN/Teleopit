---
id: 03-e2e-dual-line-acceptance
title: "真机 e2e 双线验收与剂量曲线复测"
labels: [wayfinder:acceptance]
status: closed
assignee: ""
blocked-by: [02-teleimager-pacer-impl]
---

## Question

pacer 开启后，头显端真机复测 zed-fpv ticket 06 的剂量曲线并按 map 双线验收：

1. 剂量曲线复测：2M / 4M / 8M 三档下 avgJitterBuffer 与 e2e（时间码照片法 + APK stats 日志），对照无 pacer 基线（150/112/78ms）——**曲线应拉平**（对码率不再敏感）。
2. 双线判定：可用线 ≥4M 下 buffer <40ms 且 e2e <100ms；良好线 buffer <30ms 且 e2e <80ms。
3. 画质回补：4M（或 8M）下主观画质确认（pacer 的意义就是买回画质）。
4. 稳定性：pacer 开启 10 分钟佩戴无断流；断线重连不劣化。
5. 记录最终参数组合（pacer 默认值、bitrate 定稿、aiortc 版本 pin）并宣告 map 终点。

## Resolution

**2026-08-31 真机验收完成，用户裁决收图**（e2e 线全过、buffer 线边缘、残余根因归属编码耗时 → NVENC 图接棒）。

**剂量曲线**（e2e 时间码照片法，用户读数；avgJB=APK stats 累计平均 / inst=Δtarget/Δframes 瞬时斜率）：

| 剂量 | 旧基线 e2e (t06) | off e2e | on e2e | on avgJB（累计） | on inst |
|---|---|---|---|---|---|
| 2M | ~120ms | <100ms | **~80ms** | （logcat 已滚掉） | — |
| 4M | ~200ms | ~120ms | **~80ms** | 57ms（9min 收敛） | 35–48ms |
| 8M | ~220ms | ~130ms | **~80ms** | 61ms | 30–44ms |

**双线判定**：可用线 e2e <100ms ✅（全档 80ms）；可用线 buffer <40ms ⚠️ 边缘（inst 重心 ~42ms @4M、~33ms @8M，多数窗口达标）；良好线 e2e <80ms ⚠️ 压线；良好线 buffer <30ms ❌（仅 8M 运动段瞬时触 29.5）。**e2e 曲线拉平 = map 目标（码率-延迟解耦）在 e2e 轴上达成**；buffer 绝对线未全达。

**残余 buffer 根因定位（服务器遥测）**：真实内容下 avg recv+encode ≈26ms（2560×720 SBS 软编 x264），预算护栏正确把摊平窗口压到 ~4.5ms（fps 30 全程不动 = 设计底线「fps 永不换平滑」守住）。PC A/B 摊平能张开是因 720p 噪声 E≈7ms。**结论：残余下限是编码耗时问题，非 pacer 算法问题** → 已开图的 NVENC 硬编（E 26ms→~5ms，窗口重开 ~25ms）正对口，其 e2e 验收票前置即本票。

**其余票面项**：③画质回补——4M/8M 轮次全程无画质劣化报告，收图决定含对 4M 工作点的接受；④稳定性——18:07:37 起净窗口 ~9.5min 28.1fps、丢包突发（33→112 pkts 三阵）下 buffer 纹丝不动、无断流；重连后收敛同水平（不劣化 ✅）。注：18:03-04 段 PC 大文件下载污染（avgJB 飙 127-167ms）——外部拥塞下旧行为照发，pacer 管不了别人抢带宽，属预期边界。

**REMB/码率（兼清 t04-c）**：8M 档运动期 REMB 同秒重建 6.5→7.2→8→5.655→6.3→7.0M（闭环活着）；packetsLost 合计 16（旧 8M 档 1.5% 风暴 + NACK 消失）；x264 过冲的 outbound 实测未采（NVENC 图复测时补）。

**最终参数组合**：`webrtc.pacer: on`（env `TELEIMAGER_PACER=1`）、k=1.5（默认）、bitrate 工作点 4M（min 2M / default=max 4M）、gop 30、HD720 SBS 2560×720@30 H264、aiortc 1.14.0（锚点断言过）。运行工具：`entry/run_stack.sh <剂量2|4|8> <pacer0|1>`（teleimager 仓库）。
