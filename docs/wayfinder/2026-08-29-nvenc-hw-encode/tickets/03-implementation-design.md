---
id: 03-implementation-design
title: "实现设计定案：控制协议 / REMB 映射 / 回退开关 / 崩溃恢复 / 编码参数"
labels: [wayfinder:grilling]
status: open
assignee: ""
blocked-by: [02-prototype-subprocess]
---

## Question

原型 + 01 数据在手，grilling（一次一问）把实现设计问定：

- **控制协议**：长度前缀帧流 + 控制行的最终形态（对照原型实际体验）。
- **REMB→硬编映射**：实时设 `bitrate`（01 若裁决可行）的迟滞/幅度语义；不可行时的回退——重启管线 vs 漂移重建（对照 pacer 图 t04 语义，注意 aiortc `target_bitrate` clamp [500k,3M] 与 yaml 覆写）。
- **配置开关**：`cam_config_zed.yaml` 增 `encoder: soft|hard`；默认值与切换纪律（验收前默认 soft？）。
- **崩溃恢复**：子进程挂掉 → 重启 → 强制 IDR → 队列排空的语义；aiortc executor 线程的阻塞面（`_encode_frame` 在 executor 跑，`rtcrtpsender.py:316-320`）。
- **编码参数定稿**：profile=Baseline（对齐 SDP 42e01f）；`idrinterval`/`iframeinterval` 与现 GOP 语义映射；`insert-sps-pps=true`；`vbv-size` 低延迟取值（默认 4Mb ≈ 1s@4M 太大）；`maxperf-enable=true`；`preset-level`；CBR。
- **pacer 参数重调（本图落地）**：E 换硬编值（02 实测）后 W = 33.3ms − E − margin 重算、`pacer_k`/margin 复核——pacer 图已 CLOSED，重调在本图内做，不回改彼图。
- **挂点锚断言**：照 pacer 图 t01 先例——启动时断言实机 aiortc/`_encode_frame` 挂点版本，fail-fast。
- **测试计划**：teleimager 测试基建（t04 先例 `conftest.py`）怎么覆盖子进程边界（mock IPC、控制行单测）。
- **部署落位**：子进程脚本进包内还是 `entry/`（影响双 checkout scp 面）。

产出：定案清单进 Resolution，作为 04 的实现规格。
