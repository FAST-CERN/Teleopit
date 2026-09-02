---
id: sbs-1080p-map
title: "每眼 1080p SBS：FPV 链路采集→解码全分辨率升级并四线验收"
labels: [wayfinder:map]
status: open
created: 2026-09-02
---

## Destination

ZED-M 采集面提到 **HD1080 模式（每眼 1920×1080，SBS 3840×1080 @30fps）**，全链路（bridge 采集 → NVENC 硬编 → pacer/WebRTC → Pico 解码立体渲染）实装上线并**四线验收**：① e2e 同日 A/B 不劣化（vs 720p 同日基线 +5ms 容差）② 30fps 不掉 ③ 画质主观提升可辨（正向判定，本次升级的意义）④ 码率按选定档 CBR 窄带收敛。

## Notes

**领域**：NVENC 硬编图（2026-09-02 CLOSED）「分辨率变更出图」欠账的本图。工作参数起点继承：pacer on/k=1.5/4M/gop30（码率档待 03 实测定，8M 起测 12M 备选）。

**本图携带执行**（同 zed-fpv/nvenc 图惯例，覆盖 wayfinder 默认纯规划）：终点=实装上线，票链含合入部署与真机验收。

**术语**：「1080p」= **每眼 1920×1080 的 SBS 拼帧 3840×1080**（非整帧 1920×1080 单目）；「解码闸」= Pico WebRTC 路径对 3840×1080 H.264（L5.x）的接受性。

**硬事实（开图即知，约束全部票面）**：
- H.264 帧尺寸（宏块数）：3840×1080 ≈ 240×68 = **16320 MBs > L4.2 上限 8704 → 必然 Level 5.x**；任何 1080 高度 SBS 变体都绕不开（无「中间档降到 L4.x」的退路）。
- ZED-M HD1080 模式 **fps 上限即 30**——60fps 在此分辨率物理不可达（60fps 欠账仍指向 720p，保持独立出图）。
- 像素量 ×2.25 的三个张力：E（conv+pipe write 段约 ×2.25，现 E 20.2ms → 预计 +5-8ms，pacer budget 12.0ms 可能再缩）；码率（同画质需 ~8-12M vs REMB 上限 12M vs 今日 WiFi RTT 19ms 带宽未知）；RTP 每帧包数 ×2.25（pacer 窗口内摊平压力）。
- 前科：zed-fpv 图 Pico H.264 解码器曾拒 1280×480（靠 aiortc codec prefs 强制 2560×720 才过）——解码闸是真风险，故为最早期票。

**部署事实**（跨会话记忆 `jetson-teleimager-deploy-topology`）：双 checkout 双推、run_stack.sh 换轮、APK 硬编码 URL/别名坑、/tmp 重启清空。**停机窗口纪律**同前图。

**Tracker 约定**（同前图）：Ticket = `tickets/NN-*.md`（frontmatter labels/status/assignee/blocked-by）；Frontier = open 且依赖全闭且未认领；Resolve = 正文追加 `## Resolution` + status: closed + 本 map Decisions 追加一行；研究产物放 `research/`。

## Decisions so far

- [采集面事实：ZED-M HD1080 + bridge 参数](tickets/01-zed1080-capture-research.md)：fps 上限 30 三重确认（含实机诊断 OK）；**FOV 收窄 82°→66°H（中心裁剪非同 FOV 加像素）**，验收线③须 declare；bridge 全参数化零硬编码（04 收窄到 launcher 默认值+yaml）；协议天然支持 3840 宽，代价 373MB/s IPC；USB3 ~249MB/s 无根本限制。
- 2026-09-02 用户 scoping：NVENC 图留账「pico-bridge URL 可配置化重构建」移入本图（多场真机会话持续踩别名摩擦）→ [pico-bridge URL 可配置化重构建](tickets/06-url-configurable-rebuild.md)；解码闸 attempt 1 花屏定性为噪声测试源自伤（AU ~440KB QP 地板压垮 WiFi + numpy 拖帧），闸门未裁决，attempt 2 低熵源备好。
## Not yet specified

- E/预算张力若挤爆（budget < ~6ms 且 JB 回吐）：shm 环形缓冲优化（t02 原型估 −3.5~4ms）是否进本图作为补票——看 03 实测再定
- 解码闸若 NO-GO：无 1080 SBS 变体可走（L4.2 上限硬顶），需改双流架构或维持 720p 关图——届时重画目的地
- overlay 时钟在新分辨率的字号/位置适配（小事，合入票顺手带）
- e2e 绝对值欠账（回有线复测）与 NVENC 图共用一笔，本图 A/B 线不依赖它

## Out of scope

- 60fps（ZED-M HD1080 物理上限 30fps；60fps 欠账仍属 720p 独立图）
- H.265/AV1（NVENC 图已出图，不变）
- 接收端 pico-bridge 渲染逻辑改动（中点拆分对 3840 宽天然成立；仅解码接受性问题属本图）
- 腕部相机等第二路流（不变）
