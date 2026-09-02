---
id: 04-pipeline-merge-deploy
title: "720/1080 切换接口 + bridge↔server 帧头协商（重画后收束版）"
labels: [wayfinder:task]
status: open
assignee: ""
blocked-by: []
---

## Question

**（2026-09-02 用户重画：跳过正式部署与四线验收，本票收束为两件）**

1. **切换接口**：`run_stack.sh` 加分辨率档参数（720|1080），透传 launcher 的 `ZED_RESOLUTION/ZED_OUT_WIDTH/ZED_OUT_HEIGHT` env 覆写 + 按档生成对应 cam_config（image_shape [720,2560]/[1080,3840]、码率 4M/8M）——消除 usage 文本与实产默认的预存漂移；
2. **程序间协商**：server 侧不再依赖 yaml `image_shape` 硬对齐 bridge 输出——订阅后从 FrameHeaderV1 的 w/h **自适应**尺寸编码链（yaml 仅作期望值/校验告警），杜绝「换档忘改配置」的静默错配。

验收：同机切 720↔1080 两档各起一次栈，零配置手改、出流正常。

背景（原票事实仍有效）：bridge 全参数化零硬编码（01）；`_nvenc_child` 配置天然跟随帧尺寸；codec prefs/SDP level 面经 02/03 实证无需额外强制（L5.0 直接过）。

## Resolution
