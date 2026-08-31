# t01 停机窗口实机验证：运行时码率 / 编码延迟 / 管线往返 / NVENC 占用与 SPS

- 地图：`2026-08-29-nvenc-hw-encode`（ticket 01）
- 日期：2026-08-31 14:11–14:25 CST（停机窗口：bridge 无进程、开机 ~10min、load 0.26、无交互用户）
- 设备：`unitree@192.168.10.13`（Orin NX 16GB / JetPack 5.1.1 / L4T R35.3.1，识别依据见前置研究 §1）
- 方法：三个脚本推至 `/tmp/nvenc_t01/`（不碰 checkout），全部 fake/合成源，跑完无残留进程。脚本本地留档 `Teleopit/tmp_nvenc_t01/`。
- 标注：【事实】= 实测输出；【推导】= 算术；【推断】= 分析判断。

---

## 0. 四项裁决速答

| # | 问题 | 裁决 |
|---|---|---|
| 1 | PLAYING 态运行时改 `bitrate` | **可行**【事实】：升档 4M→6M 两秒内干净收敛；降档 4M→2M 欠冲至 ~3.3M（满熵源，见 §1.2 注意项） |
| 2 | 编码延迟 A/B | 硬编管线往返 p50 **10.7ms** / p95 19.1ms（含 BGRx→NVMM VIC 转换）；软编基线 encode-only p50 **15.6ms** / p95 22.5ms（+ 帧构造 2.1ms）【事实】 |
| 3 | appsrc→appsink 全链往返 | 首帧 47.1ms（含 NVMEDIA 会话建立）；稳态见上；**BGR 24 位被 nvvidconv 拒收，集成格式 = BGRx**【事实】 |
| 4 | NVENC 占用 + SPS | `/dev/nvhost-msenc` **零占用**（videohubd 不持编码器）；SPS = **Constrained Baseline（profile_idc 66 + constraint 0x40）/ level 4.0**【事实】 |

---

## 1. item 1：PLAYING 态运行时 `bitrate` 设值（t01_bitrate.py）

管线：`videotestsrc pattern=snow(满熵) ! 2560x720@30 I420 ! nvvidconv ! NVMM NV12 ! nvv4l2h264enc control-rate=1(CBR) bitrate=4M insert-sps-pps=true maxperf-enable=true ! appsink sync=false`。2s 窗口统计 AU 字节；t=8s `set_property("bitrate", 2000000)`，t=16s 设 6M。

【事实】输出（Mbit/s）：

```
[win 1-3]  5.12 / 4.25 / 4.13      (目标 4M,win1 高为 IDR/启动)
EVENT SET->2M @ 8.0s
[win 4-7]  3.98 / 4.23 / 3.32 / 3.34   (过渡后稳定在 ~3.3M,未到 2M)
EVENT SET->6M @ 16.0s
[win 9-11] 7.25 / 5.98 / 6.16      (两秒内收敛 6M ✓)
```

### 1.1 裁决
- **属性在 PLAYING 态可设、输出码率跟随、无状态切换、无报错**——与 NVIDIA 员工论坛结论一致（前置研究 §4.4），gst-inspect 的 "NULL/READY only" 标注确认为误。→ **REMB 映射走实时设值**（03 票的前提成立）。

### 1.2 注意项（→03 票）
- 【推断】**降档欠冲**：满熵 snow 下 2M 目标只收敛到 ~3.3M（约 65%），升档无此问题。归因候选：CBR 降档需逐帧收紧 QP、且每秒 IDR（iframeinterval 默认 30）拖高均值；真实场景（非满熵）行为会不同。**REMB 降档语义需在 02 原型用真实内容复验**；备选缓解：设值后补发 force-IDR。
- 窗口含 IDR 尖峰（insert-sps-pps + 每秒 IDR），2s 窗口均值天然带毛刺。

## 2. item 2：编码延迟 A/B（四线验收第 1 线的两个数据点）

### 2.1 硬编（t01_roundtrip.py，appsrc 驱动单帧同步往返）

管线：`appsrc(BGRx) ! nvvidconv ! NVMM NV12 ! nvv4l2h264enc(同上参数) ! appsink`，满熵双帧交替。

```
first-frame round-trip: 47.1 ms (incl. internal setup)
steady round-trip n=59: min=9.57 p50=10.72 p95=19.02 max=19.08 mean=12.98 ms
```

- 【事实】`MeasureEncoderLatency=True` 属性可设（打印 OK），但 gst 调试日志无对应输出行、未找到 trace 文件落点——该属性在本 L4T 上未产出可读数据，编码段单独延迟未取得；**往返数（含 VIC 转换）即集成关心的工程上界**，已够用。
- 【事实】`H264: Profile = 66, Level = 0`（NVMEDIA 打印）+ SPS 解析（§4）。
- 【事实】NVENC 会话开启正常（`NvMMLiteOpen : Block : BlockType = 4`），伴随 `Need to set EMC bandwidth : 846000`（内存控制器带宽提升，正常行为）。

### 2.2 软编基线（t01_soft_baseline.py，teleimager env：av 16.1.0）

镜像部署配置（先 grep `/home/unitree/teleimager/src/teleimager/image_server.py:158-161` 核对：`preset=ultrafast, tune=zerolatency, threads=1, g=60(_GOP_LENGTH), bit_rate=target_bitrate`），同分辨率满熵 300 帧：

```
libx264 encode-only  n=300: min=12.67 p50=15.59 p95=22.51 max=23.24 mean=16.93 ms
from_ndarray(BGR)    n=300: p50=2.10 ms  (真实路径另有此项)
```

### 2.3 对照【推导】

| 量 | 软编（现网） | 硬编（管线往返，含转换） |
|---|---|---|
| p50 | 15.6 + 2.1 ≈ **17.7ms** | **10.7ms** |
| p95 | 22.5ms | 19.1ms |
| 首帧 | （x264 首编未单列，含在 n 中） | 47.1ms |

【推断】**IPC 未计入**：本测为同进程往返；02 票的子进程方案每帧要过一次管道（BGRx 7.37MB/帧 @30fps ≈ 221MB/s，本机管道吞吐 GB/s 级，预计 +2~5ms）——02 原型实测后才是最终 A/B 数。即便加 IPC，p50 余量 ~5ms 足够。

## 3. item 3：appsrc→appsink 往返 + 格式路径

- 【事实】`format=BGR`（24 位）协商失败：nvvidconv 系统 内存 caps 白名单 = `{I420, UYVY, YUY2, YVYU, NV12, NV16, NV24, P010_10LE, GRAY8, BGRx, RGBA, Y42B}`——**无 24 位 BGR**。改 `BGRx` 后通过。
- 【推导】teleimager 的 ZMQ 帧是 BGR8 → 集成时 numpy 侧补 alpha（`np.dstack([bgr, alpha255])` 或 cvtColor BGR2BGRA），SIMD 级成本（02 票实测，预计 <1ms @720p SBS…为 2560×720 时同量级）。
- 【事实】首帧 47.1ms 含内部建立（NVMEDIA 会话、EMC 升频）；崩溃重启场景（03 票）要计入这个恢复常数。

## 4. item 4：NVENC 占用 + SPS

- 【事实】`fuser -v /dev/nvhost-msenc` 无持有者；`/proc/*/fd` 扫描 0 命中——**编码器完全空闲**（videohubd 25% CPU 与 NVENC 无关）。
- 【事实】SPS（首个 AU 内，起始码后 8 字节 `67 42 40 28 96 54 01 40`）：
  - NAL hdr `0x67`（SPS）
  - `profile_idc = 0x42 = 66`（Baseline）
  - `constraints = 0x40`（constraint_set1=1 → **Constrained Baseline**）
  - `level_idc = 0x28 = 40`（**Level 4.0**）
- 【推导】profile 族与协商 SDP `42e01f`（Constrained Baseline L3.1）的 **profile 完全对齐**；level 4.0 vs 3.1 的落差是 2560×720@30 的宏块算术必然（160×45=7200 MB/帧 ×30 = 216k MB/s > L3.1 的 108k），**现网软编流同样超 L3.1 且 Pico 已实证正常解码**（zed-fpv t06，e2e 120ms 验收过）→ 兼容性风险判定：低。

## 5. 踩坑记录（02 原型直接复用）

1. **gst 1.16 的 gi 绑定**无 `appsink.try_pull_sample`、无 `appsrc.push_buffer` 方法——用 `sink.emit("pull-sample")` / `src.emit("push-buffer", buf)`（signal 形式），配 `signal.alarm` 看门狗。
2. **BGR→BGRx** 见 §3。
3. 满熵源（snow）让 CBR 行为真实；静止图会导致码率欠射、测不出码控。

## 6. 环境事件（非本票操作）

【事实】14:16（本窗口内）有一次外部 `launch_zed_bridge.sh` 启动尝试：ZED 相机 `CAMERA STREAM FAILED TO START` ×5 后放弃退出，无残留进程。**ZED 相机当前打不开**（疑似 USB 未插好）——影响后续需真源的票（02 若用真源、pacer 图硬件会话 t03/t05 验收），先重插/查 USB 再排期。

## 来源清单

- 命令与输出：本文各节内嵌（脚本留档 `Teleopit/tmp_nvenc_t01/`，设备侧 `/tmp/nvenc_t01/`）
- 前置研究：`aiortc-pacer/research/jetson-orin-nvenc-capability.md`（§2 官方规格、§4.4 运行时码率的 NVIDIA 论坛证据）
- 软编配置核对：`/home/unitree/teleimager/src/teleimager/image_server.py:142-167`（REMB 漂移重建 + options 字典）
