---
id: 01-offline-verification
title: "停机窗口实机验证：运行时码率 / 编码延迟 / 管线往返 / NVENC 占用与 SPS"
labels: [wayfinder:task]
status: closed
assignee: claude
blocked-by: []
---

## Question

前置研究（`aiortc-pacer/research/jetson-orin-nvenc-capability.md` §6）列出的未验证项，在停机窗口（bridge 停止、无操作员）用 fake source 逐项裁决，并补齐软编基线：

1. **PLAYING 态运行时 `bitrate` 设值**：`g_object_set` 在本机 L4T R35.3.1 实测——gst-inspect 标注 "changeable only in NULL or READY" 与 NVIDIA 员工 "can be changed in runtime"（论坛 t/255386）矛盾，实机裁决。成 → REMB 映射走实时设值（03 票）；败 → 回退语义进 03 票。
2. **编码延迟**：`nvv4l2h264enc` 开 `MeasureEncoderLatency=true` 量 2560×720@30 H.264 CBR，记均值/峰值；**同窗口同口径量软编基线**（libx264 ultrafast/threads=1 单帧耗时，对应 `image_server.py` 现配置）——四线验收第 1 线的两个数据点。
3. **appsrc→nvvidconv→appsink 全链往返**：喂单帧到收 Annex-B AU 的往返延迟 + 首帧建立时间；顺带确认 BGR→NVMM(NV12) 转换路径可用及代价。
4. **NVENC 会话占用与 SPS**：`videohubd`（探测时 25% CPU）是否持 `/dev/nvhost-msenc` 句柄；摘录输出流 SPS 的 profile/level_idc（对照 SDP 42e01f；参照事实：现网 2560×720 level 超标已被 Pico 正常解码）。

产出：`research/01-offline-verification.md`（命令 + 输出 + 四项裁决），Resolution 记结论要点。

## Resolution

**2026-08-31 CLOSED，四项全裁决**（停机窗口实测，详见 `research/01-offline-verification.md`）：

1. **运行时改码率：可行**——PLAYING 态 `set_property("bitrate", …)` 生效，升档 4M→6M 两秒内收敛；注意项：满熵源下降档 4M→2M 欠冲至 ~3.3M，REMB 降档语义在 02 原型用真实内容复验，备选缓解 = 设值后 force-IDR。
2. **编码延迟 A/B（四线验收第 1 线数据点）**：硬编管线往返 p50 10.7ms / p95 19.1ms（含 BGRx→NVMM 转换，同进程——IPC 未计入，02 补）；软编基线 encode-only p50 15.6ms / p95 22.5ms（+ 帧构造 2.1ms，镜像部署配置 grep 核对过）。
3. **格式路径：BGR 24 位被 nvvidconv 拒 → 集成格式 BGRx**（numpy 补 alpha）；首帧 47.1ms 含 NVMEDIA 会话建立（崩溃恢复常数，03 计入）。
4. **NVENC 零占用**（videohubd 不持 msenc）；SPS = Constrained Baseline / level 4.0，profile 族与 SDP 42e01f 对齐（level 落差同现网软编，Pico 已实证容忍）。

附：gst 1.16 gi 绑定两个 API 坑（`pull-sample`/`push-buffer` 须走 emit signal）已记录在 research §5，02 直接复用。

⚠️ 环境事件：窗口内一次外部 bridge 启动尝试失败——**ZED 相机当前打不开**（CAMERA STREAM FAILED TO START ×5）。02 若用真源、pacer 图 t03/t05 硬件会话都被此挡；排期前先重插/查 USB。
  - ✅ 2026-08-31 已解决：ZED-M 曾插在 USB2 口（仅 HID 枚举）；重插 USB3 后 2b03:f682 UVC @5000M 稳定、cap_fps=30.0 零错。注意首插曾「识别→3.4fps→掉线」一次，接触不良症状，换口后未复现。

