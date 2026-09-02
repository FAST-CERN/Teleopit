---
id: 05-e2e-acceptance
title: "Pico 实机四线验收：A/B 不劣化 + 30fps + 画质提升 + 码率收敛"
labels: [wayfinder:task]
status: open
assignee: ""
blocked-by: [04-pipeline-merge-deploy]
---

## Question

同日同法 A/B（map Destination 四线，工具链沿用 NVENC t06：照片法/`[Pacer]` 遥测/APK stats/采样器）：

1. **e2e 同日 A/B 不劣化**：720p 基线轮 vs 1080p 轮（+5ms 容差）；绝对值欠账与 NVENC 图共用「回有线复测」笔，不设绝对线；
2. **30fps 不掉**：decodeFps / Pacer 帧计数全程 30（注意 ZED-M HD1080 上限即 30，无余量）；
3. **画质主观提升可辨**：用户正向判定（升级图的意义所在；对照 720p 同码率与选定档）；**declare 已知差异：1080p 为中心裁剪、FOV 66°H vs 720p 82°H（−16°），判定口径 = 清晰度/角分辨率增益，FOV 损失另行记录不算画质劣化**（01 票事实）；
4. **码率档 CBR 收敛**：outbound 窄带（对齐 03 定稿档），对照 720p/4M 基线；
5. 红利观测（不设线）：JB 对照、每帧包数摊平形态。

四线全过 → 收图；画质不可辨 → 回流码率档（03）；fps 掉 → 回流采集/编码（01/03）；e2e 劣化超容差 → 回流预算（03/shm 票）。

## Resolution
