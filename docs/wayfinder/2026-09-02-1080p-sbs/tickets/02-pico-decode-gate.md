---
id: 02-pico-decode-gate
title: "解码闸：Pico WebRTC 路径能否收 3840×1080@30 H.264（L5.x）"
labels: [wayfinder:task]
status: open
assignee: "claude-code"
blocked-by: []
---

## Question

**GO/NO-GO 票**。H.264 3840×1080 帧尺寸 16320 宏块 → 编码器必然发 Level 5.x SPS；Pico（XR2）媒体面支持 4K，但 zed-fpv 前科 = 其 WebRTC/解码路径拒过非标准尺寸（1280×480 被拒、2560×720 靠 codec prefs 强制）。闸门问题：**Pico 经现有 APK/WebRTC 链路能否解码渲染 3840×1080 SBS**。

最小代价探法（不需要全链路实装）：PC 侧 aiortc 合成源（synth_zed_source 改 3840×1080，软件编码、fps 可低于 30）起 server → Pico app 连 → 看 `[HttpSignaling] stats` 的 decodeFps/framesDecoded 与目视立体渲染。辅证：logcat 解码器错误行、SPS level 实际值。

- GO → 后续票照走；
- NO-GO → 无 1080 SBS 变体可走（L4.2 上限 8704 MBs 硬顶，改宽度无用），回流 map 重画目的地（双流架构或维持 720p 关图）。

## Resolution

（进行中，第一次尝试记录 2026-09-02 15:31）

**Attempt 1 判定为无效测试（自伤，非 Pico 判决）**：机器人侧合成源（纯随机噪声 3840×1080）+ hard NVENC + APK 实连——用户见**花屏**。机器人日志（`research/server_gate_attempt1.log`）：NVENC 子进程在 1080p 正常拉起零重启；但 **600 帧/48s=12.5fps、每帧 370 包**（720p 基线 ~14 包）——噪声源打 QP 地板（t05 已知源特性在 1080p 复现放大）→ AU ~440KB/帧 ≈ 100Mbps 级，WiFi 扛不住 → 丢包撕裂；且 numpy 每帧 4.1MP 随机数生成拖垮制造者侧帧率。**Pico 侧 logcat 未捕获**（USB 已拔，无 stats 行）。结论：测的是网络上限不是解码接受性。

Attempt 2 备好：`research/synth1080_lowent.py`（预计算静态压缩性场景 + 双眼锁步跳动块，每帧仅 memcpy+patch，PC 冒烟过）——预期落在 CBR 目标档而非 QP 地板。待换电后重跑。

（历史注：attempt 1 服务端启动顺序踩坑——server 有 5s 首帧超时自杀，synth 源必须先起。）
