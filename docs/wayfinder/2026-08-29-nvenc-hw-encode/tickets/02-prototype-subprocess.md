---
id: 02-prototype-subprocess
title: "原型：系统 python3 子进程跑通 nvv4l2h264enc + _encode_frame 替换闭环"
labels: [wayfinder:prototype]
status: closed
assignee: claude
blocked-by: [01-offline-verification]
---

## Question

方案 A 骨架的最小可用原型（一次性代码允许糙，目标是暴露真问题而非合入质量）：

- 系统 `/usr/bin/python3`（gi + Gst 1.16.3，实机已验证）起 `appsrc ! nvvidconv ! nvv4l2h264enc ! appsink` 子进程；
- teleimager 侧写 `_encode_frame` 替换 wrapper（照 `jetson_software_encode_frame` 先例）：喂帧 / 收 Annex-B AU / 控制行；
- fake source 2560×720@30 连续编码，本机端（aiortc 本地回环或 OpenCV 解码）解出可看画面闭环；
- 控制行验证：改码率运行时设值（01 已裁决可行；**用真实内容复验降档欠冲**——满熵下 4M→2M 只收敛到 ~65%，备选 = 设值后补 force-IDR）、force-IDR（PLI 语义）生效；
- 记录：**子进程全路径单帧往返延迟 = pacer 预算公式的硬编 E**（budget = 33.3ms − E − margin；t01 量的是同进程 10.7ms，此处补 IPC 后真值，03 用它重算 W）、子进程崩溃后重启的实际行为（重启→IDR→续流的语义雏形）。

原型代码挂 `research/prototype/`；暴露的问题清单（缓冲堆积、格式转换代价、控制时序）回流 03 设计票。

## Resolution

**2026-08-31 CLOSED，五项全裁决**（停机窗口实测，详见 `research/02-prototype-subprocess.md`）：

1. **E 真值（pacer 预算公式硬编 E）**：带载 p50 **15.2ms（I420）** / 21.3ms（BGRx），空载 12.9/18.0；
   首帧 57–84ms、spawn→就绪 ~150ms。摊平窗口 W：软编 ~4.5ms → **I420 硬编 ~17ms**——预算重开论点成立（03 输入）。
2. **解码闭环**：合成源 300/300 帧号块精确回读；真实内容（ZED 经 zed_xr_bridge）179/179 解码 + PNG 目检 ✓。
3. **force-IDR 可用**：是 **action signal**（`enc.emit("force-IDR")`）非属性；中流生效（AU→[SPS,PPS,IDR]）。
   ⚠️ NULL 态 emit 触发 C printf 直写 stdout 污染协议流——探测用 signal_lookup；t04 前协议需噪声隔离（side-pipe）。
4. **降档欠冲复验**：真实内容无欠冲（1s 脱离旧水位后按场景熵供水 1.1–1.6M）；升档 1s 收敛；
   满熵 65% 欠冲 = 源特性。REMB 走实时设值，force-IDR-on-set 为可选增强。
5. **崩溃重启**：SIGKILL→同帧 AU 268ms；重启首 AU [SPS,PPS,IDR]；跨重启 300/300 解码对账——续流语义成立、上层零丢帧。

问题清单六条回流 03（传输格式定 I420、p95 计预算、协议噪声隔离、lockstep 假设、带载敏感性、重启常数）。
环境注记：ZED USB2 口枚举问题**复发**（重插 USB3 修复）——建议固定选口。
