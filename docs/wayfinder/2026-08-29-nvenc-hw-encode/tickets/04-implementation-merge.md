---
id: 04-implementation-merge
title: "teleimager 实现硬编路径并合入 zed-bridge 分支（TDD）"
labels: [wayfinder:task]
status: closed
assignee: claude
blocked-by: [03-implementation-design]
---

## Question

按 03 定案实现（TDD，RED→GREEN，沿用 t04 先例的 conftest 测试基建）：

- 子进程编码器脚本（系统 python3 + gi）；
- `_encode_frame` 硬编 wrapper + 配置开关 `encoder: soft|hard`（默认 soft，软编路径行为零变化）；
- REMB 映射 / PLI→force-IDR / 崩溃恢复按 03 定案；
- 启动锚断言（aiortc 版本 + 挂点存在性）；
- 本地（Windows 侧无 NVENC）测试全绿 + 可行的部分实机测试；
- 合入 teleimager `zed-bridge` 分支。

## Resolution

**2026-08-31 CLOSED**（commit `9c0014a`，teleimager `zed-bridge`，已推 origin）。t03 九项全落实：

- **`src/teleimager/_nvenc_child.py`**：自包含单文件（stdlib+gi），gi 延迟到 `main()` 内，协议层（帧定/管道 fd 解析/build_pipeline）在文件顶部——PC 可无 gi import。POSIX 子进程收 fd 号（pass_fds）；Windows 开发路径收 handle 值（`msvcrt.open_osfhandle`，因 Windows 无 pass_fds）。编码参数按 03 #6：control-rate=1 CBR、insert-sps-pps、maxperf-enable、iframeinterval 显式来自 C 配置、num-B-Frames=0 注释固化 lockstep 前提、vbv-size=bitrate/30 初始+B 命令双处 best-effort 设（失败仅 stdout 日志，不重建）。
- **`image_server.py`**：`_NvencSubprocessEncoder`（BGR→I420 复用缓冲、10% 迟滞 update_bitrate 永不重建、I 在 F 前、EOF/超时/协议错→杀残→退避 0/250/500 封顶 1s→重启→同帧重试，无限重试默认、`_NVENC_MAX_RETRIES` 供测试注入上限）+ `nvenc_encode_frame` 生成器（lazy 建 child、几何变更重起、`last_encode_s` 供 pacer、异常兜底丢帧不杀 RTP 环）+ `_assert_encoder_anchors` 双面锚（当前 `_encode_frame` ∈ {jetson patch, aiortc 原版特征串 `data_to_send`/`self.buffer_data`}；sender 契约 `_next_encoded_frame` 的 run_in_executor+`__encoder.encode`、`_send_keyframe` 的 `__force_keyframe = True`、`_handle_rtcp_packet` 调 `_send_keyframe`）失败→醒目错误+回软编（非 pacer 式 raise）+ `_apply_webrtc_config` 接 `webrtc.encoder: soft|hard` 默认 soft + `TELEIMAGER_ENCODER` env 覆写 + 未知值回软编醒目日志。子进程解释器 = `TELEIMAGER_NVENC_PYTHON` 覆写，默认非 nt 下 `/usr/bin/python3`。
- **测试三层之一二落地（19 个，`tests/test_nvenc_impl.py` + `tests/mock_nvenc_child.py`）**：mock 子进程 = 独立实现的 stdlib 协议对端（故障注入 garbage/die/stall-once/badmsg + C 严格校验 + AU 回报 frame_idx/bitrate/frame_len/IDR 位）——真实子进程驱动 wrapper：往返、I-before-F（以 mock 效果断言次序）、迟滞、EOF/超时重启同帧重试、stdout 噪声免疫（Q1 回归）、协议错、重试上限；生成器端到端过真 aiortc `H264Encoder`（C 内容含 iframeinterval、REMB 流转、PLI→IDR、几何变更重起、异常吞帧）；配置/锚断言单测。第三层实机冒烟归 05。全部同步、不碰 asyncio。
- **TDD 过程修出两个真 bug**：① `_send_cmd` 用 `len(payload)` 对 2-D I420 数组取到行数 72 而非 4608 字节 → 头/实体不符 → 流错位（第二帧起 AU 超时）——改 `memoryview.nbytes`，生成器测试的 frame_len 断言即为此设计；② `_kill_child` 不置 `proc=None` → 重试循环永远"child exited before encode"死循环无法复活。两 bug 均有测试覆盖。
- **PC 环境事实**：Windows 无 `Popen(pass_fds)`（assert 拒绝）→ handle 继承分支；teleimager pytest 唯一可用解释器 = conda `teleopit` env（3.10.20 + pytest 9.1.1 + aiortc 1.15 + cv2 + av）。验证：nvenc 19 + pacer 21 = **41 passed**；`test_relay_bounded_queue` 的 asyncio 用例本机间歇挂死为 pacer 图已知债，与本票无关。
- 软编路径零变化（默认 soft 下仅多两行日志）；机器人部署（双 checkout scp + import 定位 + 冒烟）整体归 05。
