---
id: 04-pipeline-merge-deploy
title: "720/1080 切换接口 + bridge↔server 帧头协商（重画后收束版）"
labels: [wayfinder:task]
status: closed
assignee: "claude-code"
blocked-by: []
---

## Question

**（2026-09-02 用户重画：跳过正式部署与四线验收，本票收束为两件）**

1. **切换接口**：`run_stack.sh` 加分辨率档参数（720|1080），透传 launcher 的 `ZED_RESOLUTION/ZED_OUT_WIDTH/ZED_OUT_HEIGHT` env 覆写 + 按档生成对应 cam_config（image_shape [720,2560]/[1080,3840]、码率 4M/8M）——消除 usage 文本与实产默认的预存漂移；
2. **程序间协商**：server 侧不再依赖 yaml `image_shape` 硬对齐 bridge 输出——订阅后从 FrameHeaderV1 的 w/h **自适应**尺寸编码链（yaml 仅作期望值/校验告警），杜绝「换档忘改配置」的静默错配。

验收：同机切 720↔1080 两档各起一次栈，零配置手改、出流正常。

背景（原票事实仍有效）：bridge 全参数化零硬编码（01）；`_nvenc_child` 配置天然跟随帧尺寸；codec prefs/SDP level 面经 02/03 实证无需额外强制（L5.0 直接过）。

## Resolution

2026-09-02 用户实机验收**成功**（720↔1080 现场切换，FOV 82°↔66° 肉眼可辨）。

**实现 = offer 驱动的 managed bridge**（teleimager `118555f`，zed-bridge 已推）：`TELEIMAGER_MANAGE_BRIDGE=1` 时 server 接管 zed_xr_bridge 生命周期——offer body 带 `"resolution": "720p"|"1080p"`（pico-bridge APK 发出）→ 不同档则重启 bridge 于新尺寸（同 IPC endpoint，~2-3s，HMD 转圈盖住间隙）；SDP 应答从不等帧；编码器按首帧自适应尺寸（帧头驱动，帧中不变档——切换只在 新连接 生效，单客户端语义下即"每次 Connect 生效"）。默认关 = 既有部署（launch_zed_bridge.sh / run_stack.sh）零影响。4 单测（spec 映射/非法值忽略/同档不重启/换档 terminate+重启）+ 全套 49 passed。双 checkout 已推（md5 `e7d0fee3`）。

**原票面第 1 项（run_stack 分辨率档参数）被更好的形态取代**：切换接口落在 app 内 Resolution 药丸 + managed server，不再需要命令行换档；launcher usage 文本漂移降为 cosmetic 残留。码率随分辨率分档（720→4M / 1080→8M）未做——REMB 兜底，需要时一行补。