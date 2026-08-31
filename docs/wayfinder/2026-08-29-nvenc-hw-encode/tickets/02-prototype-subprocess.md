---
id: 02-prototype-subprocess
title: "原型：系统 python3 子进程跑通 nvv4l2h264enc + _encode_frame 替换闭环"
labels: [wayfinder:prototype]
status: open
assignee: ""
blocked-by: [01-offline-verification]
---

## Question

方案 A 骨架的最小可用原型（一次性代码允许糙，目标是暴露真问题而非合入质量）：

- 系统 `/usr/bin/python3`（gi + Gst 1.16.3，实机已验证）起 `appsrc ! nvvidconv ! nvv4l2h264enc ! appsink` 子进程；
- teleimager 侧写 `_encode_frame` 替换 wrapper（照 `jetson_software_encode_frame` 先例）：喂帧 / 收 Annex-B AU / 控制行；
- fake source 2560×720@30 连续编码，本机端（aiortc 本地回环或 OpenCV 解码）解出可看画面闭环；
- 控制行验证：改码率（若 01 裁决可行）、force-IDR（PLI 语义）生效；
- 记录：单帧往返延迟、子进程崩溃后重启的实际行为（重启→IDR→续流的语义雏形）。

原型代码挂 `research/prototype/`；暴露的问题清单（缓冲堆积、格式转换代价、控制时序）回流 03 设计票。
