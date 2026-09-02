---
id: 01-zed1080-capture-research
title: "采集面事实：ZED-M HD1080 模式 + zed_xr_bridge 输出尺寸参数"
labels: [wayfinder:research]
status: closed
assignee: ""
blocked-by: []
---

## Question

升级的采集侧事实收齐（AFK 研究，产物进 `research/`）：

1. ZED SDK HD1080 模式约束：分辨率精确值（1920×1080?）、fps 上限（30）、FOV/裁切相对 HD720 的变化（画面内容损失与否）；
2. `zed_xr_bridge`（C++，`eeg_humanoid/teleop/xr_teleoperate/patch/zed_bridge/`）输出尺寸从哪参数化（`--output-height/width`？）、SBS 拼帧逻辑对 3840 宽是否有硬编码假设、发布协议（FrameHeaderV1 的 w/stride 字段）是否天然支持；
3. 采集→发布路径在 1080p 的带宽/拷贝代价（USB3 UVC 1080p30 = ~186MB/s YUV，实测关注点）；
4. cam_config 侧 `image_shape`/`fps` 需动的面。

## Resolution

2026-09-02 研究代理完成，28 项事实全记 `research/01-capture-facts.md`。要点：

1. **fps 三重确认**：HD1080 = 每眼 1920×1080、SBS 3840×1080、**上限 30fps**（SDK 5.0.7 头文件注释 + Stereolabs 文档 + 机器人当日 `ZED_Diagnostic_Results.json` 实机 `HD1080@30 initialization OK`）。map 假设成立。
2. **⚠️ 推翻隐含假设——FOV 收窄**：HD1080 是原生阵列中心裁剪（~71%），HD720 是 2×2 binning；校正 FOV **66°H/40°V vs 720p 的 82°H/52°V（−16°/−12°）**，回报 2.0× 角分辨率。不阻塞验收，但验收线 ③ 画质判定须**declare FOV 损失为已知差异**（已回填票 05）。
3. **bridge 全参数化零硬编码**：`--resolution/--fps/--output-width/--output-height` CLI；SBS 拼帧走 SDK `VIEW::SIDE_BY_SIDE`；机器人源码与本地 `teleop/patch/zed_bridge` md5 一致；帧尺寸无任何 2560/720 假设 → 票 04 大幅减轻（合入面收敛到 launcher 默认值 + yaml）。
4. **协议天然支持**：FrameHeaderV1 全 uint32 可变字段，仅约束宽度为偶；订阅者/NVENC 子进程全自动跟随帧尺寸。代价 = 11.86MiB/帧 ≈ **373MB/s ZMQ IPC**（×2.25）——03 票 E 张力的实测量级。
5. launcher 生产链默认 HD720/2560×720；usage 文本已提前写成 "(default HD1080)/3840/1080"（预存漂移，04 顺手消除）。`/home/unitree/teleimager` checkout 里 launcher 二进制路径坏（非活体路径，注记）。
6. USB3 实为 **~249MB/s**（票面 186 系单目估算）：单流未压缩 SBS UVC，~50% Gen1 链路率，无根本限制；关注与其它 SS 设备共总线的 `grab_errors`（今日 720p 会话 1h 零 send_drop/4 grab_err）。
7. 配置面：`image_shape: [720,2560]→[1080,3840]` + 注释；dose 配置须从 base 重生成（sed 链）不可手改；REMB max 12M 已覆盖计划档。
