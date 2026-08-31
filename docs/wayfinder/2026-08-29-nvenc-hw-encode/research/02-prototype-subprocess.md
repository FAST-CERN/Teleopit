# t02 原型：系统 python3 子进程 nvv4l2h264enc + `_encode_frame` 替换闭环

- 地图：`2026-08-29-nvenc-hw-encode`（ticket 02）
- 日期：2026-08-31 19:23–19:36 CST（停机窗口：bridge 无进程、无交互用户、机器人刚上电）
- 设备：`unitree@192.168.10.13`（Orin NX 16GB / JetPack 5.1.1 / L4T R35.3.1）
- 方法：原型代码本地 `research/prototype/`，推至 `/tmp/nvenc_t02/`（不碰 checkout）。子进程 =
  系统 `/usr/bin/python3` + gi（零新增包）；测试 harness = `teleimager` env（av 16.1.0，与活体一致）。
  真实内容 = 单独起 `zed_xr_bridge` C++ 采集进程（teleimager-server 全程停止），测试脚本以
  ZEDBridgeCamera 同款 SUB+CONFLATE 订阅 `ipc:///tmp/zed_xr_head.ipc`。跑完 bridge 停止、IPC 文件
  删除、无残留进程。
- 标注：【事实】= 实测输出；【推导】= 算术；【推断】= 分析判断。

---

## 0. 裁决速答

| # | 问题 | 裁决 |
|---|---|---|
| 1 | 子进程全路径 E（pacer 预算公式的硬编 E 真值） | 带载 p50 **15.2ms**（I420）/ 21.3ms（BGRx）；空载 12.9 / 18.0【事实】 |
| 2 | 解码闭环（fake + 真实内容） | 300/300 + 179/179 帧解码全对账；帧号块 300/300 精确回读；真实内容 PNG 目检 ✓【事实】 |
| 3 | force-IDR（PLI 语义） | **可用**——是 action signal `enc.emit("force-IDR")`，非属性；中流生效（AU 变 [7,8,5]）【事实】 |
| 4 | 降档欠冲真实内容复验 | 无欠冲问题：1s 脱离旧水位，随后按场景熵供水（1.1–1.6M）；满熵 65% 欠冲 = 源特性【事实+推断】 |
| 5 | 崩溃重启语义 | SIGKILL→同帧 AU **268ms**；重启首 AU [SPS,PPS,IDR]；300/300 跨重启解码对账 = 续流成立【事实】 |

---

## 1. 原型结构（research/prototype/）

```
proto_ipc.py        消息帧定：cmd(1)+len(uint32 LE)；父=裸 fd+select，子=buffered file obj
nvenc_child.py      子进程（系统 python3+gi）：appsrc(BGRx|I420) ! nvvidconv ! NVMM NV12
                    ! nvv4l2h264enc(CBR,insert-sps-pps,maxperf) ! appsink；lockstep 一帧一 AU
nvenc_wrapper.py    teleimager 侧 wrapper：BGR→传输格式 cv2 转换、帧发送、AU 接收、
                    force-IDR/码率控制线、崩溃重启+同帧重试；last_encode_s 兼容 pacer 预算
t02_e2e.py          合成源闭环 + E 分解 + 解码对账 + force-IDR 中流验证（--format 可选）
t02_bitrate_real.py 真实内容码率轨迹（1s 窗）+ 带载 E + 存流/解码/PNG
t02_crash.py        SIGKILL 重启行为 + 跨重启解码对账
```

协议：父→子 `C`配置 `F`帧 `B`码率 `I`force-IDR `Q`退出；子→父 `R`就绪 `A`AU `L`日志。

## 2. E 全路径延迟（ticket 核心交付）

【事实】每帧 E = `encode()` 墙钟（cv2 格式转换 + 管道写 + 子进程 VIC/NVENC + AU 读回），首帧单列：

| 场景 | n | p50 | p95 | 分解 p50（conv / write / wait） |
|---|---|---|---|---|
| BGRx 空载 | 299 | 18.00 | 29.96 | 0.60 / 6.26 / 10.65 ms |
| **I420 空载** | 299 | **12.90** | 25.38 | 0.98 / 2.52 / 9.10 ms |
| BGRx 带载¹ | 837 | 21.34 | 28.77 | 0.71 / 9.33 / 10.96 ms |
| **I420 带载¹** | 838 | **15.23** | 21.57 | 1.56 / 3.85 / 9.40 ms |
| （对照）t01 同进程硬编往返 | 59 | 10.72 | 19.02 | 无 IPC |
| （对照）软编产线 E（pacer 口径） | — | ≈26 | — | 现网实测口径 |
| （对照）软编孤立测量（t01） | 300 | 17.7 | 24.6 | 15.6 编码 + 2.1 帧构造 |

¹ 带载 = zed_xr_bridge 采集进程同机运行（真实部署形态）。
首帧 E：BGRx 83.6ms / I420 57.3ms（含 NVMEDIA 会话建立）；子进程 spawn→就绪 152–242ms。

【推导】**摊平窗口重算（本图核心论点，03 票输入）**：W = 33.3 − E − margin。软编 E≈26 →
W≈4.5ms（挤死，pacer 图结论）；**I420 硬编带载 E≈15.2 → W≈17ms**——预算重开成立。
【推断】BGRx 传输 7.37MB/帧是瓶颈（write 6.3→9.3ms 且挤占内存带宽）；I420 2.76MB（−62%）
同时让 VIC 转换更便宜（wait 10.7→9.1ms）。**I420 = 03 集成推荐格式**。p95 尾部（21–30ms）
来自 NVENC 会话内抖动，margin 按 p95 计。

## 3. force-IDR 裁决（PLI 语义）

【事实】gst-inspect 尾行 `"force-IDR" : void user_function(GstElement*)`——**action signal，
不是属性**（set_property 三种拼写全拒）。正确用法 `enc.emit("force-IDR")`；PLAYING 态中流
emit 后下一 AU = [7,8,5]（SPS+PPS+IDR，insert-sps-pps 生效）。

【事实】⚠️ 坑：NULL 态 emit 触发 NVIDIA C 层 printf **直接写 fd 1**（`device is not open\n
Error while signalling force IDR`），裸字节污染 stdout 协议流（首跑 10s 超时假象即此）。
探测必须用 `GObject.signal_lookup`（无副作用）；运行态 emit 未观察到打印，但见 §6-3。

## 4. 码率真实内容复验（t01 §1.2 遗留）

【事实】真实场景（静止实验室，ZED-M HD720@30 SBS）1s 窗口轨迹：

- 4M 段：3.8–4.0M（低熵场景略欠供水，正常）
- **SET→2M**：下一窗 2.5→0.7–1.7M，10s 内稳定在场景熵水位（~1.1–1.6M）
- **SET→6M**：**1s 收敛**（设值窗 1.6→6.25/6.08/6.29…）
- `--force-idr-on-set` 变体：行为同型，降档后水位略低（1.06–1.17M），无副作用
- gaps=0（ZMQ CONFLATE 下零丢帧），restarts=0

【推断】t01 满熵 snow 的「降档只收敛到 ~65%」是**满熵源特性**（CBR 无内容腾挪空间），
真实内容无此问题。REMB 映射：实时设值即可；force-IDR-on-set 为可选增强（语义已验证），
03 定夺。

## 5. 崩溃重启（重启→IDR→续流雏形）

【事实】frame 120 处 SIGKILL 子进程：父侧 BrokenPipeError 感知 → 硬杀重启 → **kill 后
268ms 同帧 AU 返回**（其中重启→AU 232ms ≈ spawn 152 + NVMEDIA 首帧 ~80）。重启后首 AU
[7,8,5]；**全流 300/300 解码、300/300 帧号块精确回读，跨重启点不重置解码器**——续流语义
成立，上层零丢帧（同帧重试覆盖）。

## 6. 问题清单（→ 03 设计票）

1. **传输格式定 I420**（本图数据直接支持）：BGRx 带载 21.3ms 不敌软编孤立值 17.7，I420
   15.2ms 全面占优。注意 cv2 `BGR2YUV_I420` 的色彩矩阵（BT.601 vs ZED 输出约定）在 06 四线
   第 4 线主观画质验收时核对。
2. **p95 计预算**：硬编 p95 21–30ms，尾部长于软编孤立 p95（24.6）不显著占优；pacer margin
   与 W 用 p95 口径重算（03）。
3. **协议噪声隔离**：C 层 printf 可直写子进程 stdout（本次 NULL 态 force-IDR 实证）。t04
   合入前协议必须免疫：side-pipe fd 专走协议（stdio 留给 C 打印）或 magic-byte 重同步。
4. **lockstep 假设**：一帧进恰一 AU（零延迟无 B 帧，多轮 300 帧实证）。引入 B 帧/lookahead
   需改 AU 关联协议。
5. **带载敏感性**：同机采集进程使 E +3ms（内存带宽竞争）；03 预算取带载数值，t06 在完整
   stack 下复测。
6. **重启常数**：崩溃恢复 ~270ms 量级（spawn+会话建立）；期间该帧阻塞（同帧重试），
   aiortc 层表现为单帧延迟尖峰——可接受，不需要预启动备用会话（03 复核此结论）。

## 7. 环境事件注记

- 开机后 ZED-M 又只在 USB2 口枚举（仅 HID f681，无 UVC f682）——同 t01 症状复发；重插
  USB3 后 f682@5000M 恢复、采集 30fps 零 gap。**该物理口接触/选口问题已两次挡路**，建议
  固定 USB3 口并做标记。
- pkill -f 自匹配坑：清理命令行里含目标串会杀死自身 ssh shell（拼接字符串避开）。

## 8. 产物位置

- 代码：`research/prototype/`（6 文件 + diag_child.py 诊断工具）
- 证据：`research/prototype/artifacts/`（真实内容解码 PNG + I420 合成源 PNG）
- 设备侧：`/tmp/nvenc_t02/`（含 .h264 流，重启即失，不复盘）
