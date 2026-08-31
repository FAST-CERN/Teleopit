---
id: 03-implementation-design
title: "实现设计定案：控制协议 / REMB 映射 / 回退开关 / 崩溃恢复 / 编码参数"
labels: [wayfinder:grilling]
status: closed
assignee: claude
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

## Resolution

**2026-08-31 CLOSED，九项全定**（grilling 一次一问；决策依据 = t01/t02 实测 + aiortc 1.15 源码核查 + 设备 gst-inspect 补证）：

1. **协议形态 = AU 专线管道**：命令留 stdin（C 代码不读 stdin，干净）；AU 回传走 `pass_fds`
   专用管道；子进程 stdout 继承到控制台**专职收噪声**（对任意 C printf 免疫，Q1 回归测试固化）。
   EOF 崩溃语义保留（268ms 恢复依赖它）。ZMQ PAIR 已否：不省时（管道≈unix socket 地板，
   ZMQ 加组帧/拷贝略慢）、系统 python3 无 pyzmq（违零新增包前提）、对端死亡不即通知。
2. **部署落位 = 包内单文件** `src/teleimager/_nvenc_child.py`：自包含（stdlib+gi，帧定内联
   ~40 行），与 image_server.py 同一 scp/md5 部署面，wrapper `__file__` 同目录定位。
   **实现规格：gi 延迟到 `main()` 内 import**，文件顶部只放协议常量+解析函数——PC 测试可直接
   import 测帧定而不触发 gi。
3. **REMB 映射 = 10% 迟滞直传**：wrapper 比较 `target_bitrate` 与上次已发值，>10% 才发 B
   （镜像软编漂移常数；aiortc 侧每 REMB 直设+clamp[2M,12M] 已由 yaml 覆写）。硬编**永不重建**。
   PLI 是唯一 IDR 触发（降档实测无欠冲，不叠加 IDR-on-set；PLI/FIR→`_send_keyframe()`→
   `force_keyframe` 参数→子进程 I 命令，链路天然存在）。
4. **配置开关**：yaml `webrtc.encoder: soft|hard` **默认 soft** + env `TELEIMAGER_ENCODER`
   覆写（pacer 先例，A/B 不改配置）+ 未知值回软编醒目日志；06 关图时同一行翻 hard（默认档
   变更留 git 痕迹）。
5. **崩溃恢复 = 无限重试+退避**：EOF/超时→杀残→重启→同帧重试；连续失败退避 0/250/500ms
   封顶 1s；每次重启一条醒目日志。**无自动软编回退**（验收期硬编故障保持可见，操作员 env
   切换；长期运行若需自动回退另开票）。executor 线程停顿只拖当帧（270ms 卡帧观感）。
6. **编码参数定稿**：profile 不设（enum 默认 Baseline，SPS 已证对齐 42e01f）；control-rate=1
   CBR；insert-sps-pps=true；maxperf-enable=true；preset-level 默认 UltraFast；
   **iframeinterval 显式 = `_GOP_LENGTH`**（防 yaml 改 gop 两边漂移）；idrinterval/num-B-Frames
   默认（256/0；**B=0 是 lockstep 1帧1AU 前提，代码注释固化**）；
   **vbv-size = bitrate/30 随 B 命令运行时设**（默认 4Mb≈1s@4M 太大；该属性 flags 标
   NULL/READY-only 但 t01 已证此类标注不可信——设不动则日志+保持上次值，不重建；
   t04 mock 测协议、t05 冒烟实机裁决可设性）。
7. **pacer 不动**：span=min(window 22.2, budget=33.3−E−3)；硬编 E≈15.2 → budget 15.1ms
   不再被钳且不碰 window 上限（window 成为约束需 E<8.1ms，仅 shm 后可能）——k=1.5/margin 3ms
   原样，wrapper 的 `last_encode_s` 自动进预算公式。**t06 现场核实**：日志输出 span/budget
   证未被钳制（尾部帧 p95≈21.6 → budget 8.7ms，leaky-bucket 自纠，属观测项）。
8. **锚断言 = 双面锚+回退**：①`h264.H264Encoder._encode_frame` 当前实现 ∈ 已知集合
   （aiortc 原版源码特征串 / 本文件 `jetson_software_encode_frame`）；②sender 契约锚
   （`_next_encoded_frame` 的 run_in_executor+`__encoder.encode`、PLI 的 `_send_keyframe`）。
   断言失败 → 醒目错误 + **回软编继续跑**（视频不因加速器假设检查而死，pacer 式 raise 不适用）。
9. **测试 = 三层**：①mock 子进程（纯 stdlib 说同款协议）驱动 wrapper 单测——帧定往返、10%
   迟滞、I 在 F 前、EOF 重启+退避、**stdout 垃圾不破坏协议（Q1 回归）**；②配置/锚断言单测
   （yaml/env/未知值 + 伪造漂移源）；③设备真实 child 冒烟归 05。注意 pacer 图教训：asyncio
   用例本地 pytest 可能挂起，协议单测全部走子进程/mocking 不碰 asyncio。
