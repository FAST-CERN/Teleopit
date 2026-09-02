---
id: 04-pipeline-merge-deploy
title: "合入部署：bridge 尺寸参数 + 配置面 + 双 checkout 冒烟"
labels: [wayfinder:task]
status: open
assignee: ""
blocked-by: [01-zed1080-capture-research, 02-pico-decode-gate, 03-encode-transport-probe]
---

## Question

按 01/02/03 的结论实装合入（TDD 纪律同 NVENC 图 t04）：

1. `zed_xr_bridge` 输出尺寸参数化确认/改动（若 01 发现硬编码假设）；
2. `cam_config_zed.yaml`：`image_shape: [1080, 3840]`、fps、码率档（03 定稿）；
3. aiortc codec prefs / SDP level 面：2560×720 曾需强制——3840×1080 是否同样需要显式 codec prefs（及 Pico 侧 fmtp level 接受性，02 已证）；
4. overlay 时钟字号/位置适配（顺手）；
5. teleimager 侧若有尺寸假设（`_nvenc_child` 配置天然参数化，确认即可）；
6. 双 checkout 部署 + teleimager env 冒烟（同 NVENC t05 流程：import 定位、md5、`TELEIMAGER_ENCODER=hard` + 新分辨率起栈、PC 收流）。

## Resolution
