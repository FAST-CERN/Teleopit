---
id: 02-pico-decode-gate
title: "解码闸：Pico WebRTC 路径能否收 3840×1080@30 H.264（L5.x）"
labels: [wayfinder:task]
status: open
assignee: ""
blocked-by: []
---

## Question

**GO/NO-GO 票**。H.264 3840×1080 帧尺寸 16320 宏块 → 编码器必然发 Level 5.x SPS；Pico（XR2）媒体面支持 4K，但 zed-fpv 前科 = 其 WebRTC/解码路径拒过非标准尺寸（1280×480 被拒、2560×720 靠 codec prefs 强制）。闸门问题：**Pico 经现有 APK/WebRTC 链路能否解码渲染 3840×1080 SBS**。

最小代价探法（不需要全链路实装）：PC 侧 aiortc 合成源（synth_zed_source 改 3840×1080，软件编码、fps 可低于 30）起 server → Pico app 连 → 看 `[HttpSignaling] stats` 的 decodeFps/framesDecoded 与目视立体渲染。辅证：logcat 解码器错误行、SPS level 实际值。

- GO → 后续票照走；
- NO-GO → 无 1080 SBS 变体可走（L4.2 上限 8704 MBs 硬顶，改宽度无用），回流 map 重画目的地（双流架构或维持 720p 关图）。

## Resolution
