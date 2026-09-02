# 01 采集面事实：ZED-M HD1080 模式 + zed_xr_bridge 输出尺寸参数（ticket 01）

- 地图：`2026-09-02-1080p-sbs`（ticket `01-zed1080-capture-research`）
- 日期：2026-09-02 CST
- 方法：① 官方文档 web 检索（Stereolabs docs/support/datasheet + NVIDIA Jetson 设计指南）；② 机器人侧只读取证（ssh `unitree@192.168.5.5`，md5/stat/cat/ps，零写入）；③ 本机源码镜像比对（`F:\Chufan_Rui\teleop\patch\zed_bridge\`）；④ 机器人上现成的 `ZED_Diagnostic_Results.json`（2026-09-02 14:26 本机诊断输出）。
- 标注：【事实】= 文档/源码/实测原文；【推导】= 算术；【推断】= 分析判断。

---

## 0. 四项裁决速答

| # | 问题 | 裁决 |
|---|---|---|
| 1 | HD1080 分辨率/fps | 每眼 **1920×1080**（SBS 3840×1080），**fps 上限 30**（15/30 两档）——SDK 头文件 + 官方文档 + 本机诊断三方一致【事实】 |
| 2 | FOV/裁切 | **1080 不是「同 FOV 更多像素」，是更窄的中心裁切**：rectified H-FOV **66°（1080）vs 82°（720）**，垂直 40° vs 52°；720 是 2×2 binning 的宽模式【事实+推断】 |
| 3 | bridge 尺寸参数化 | **全参数化，零硬编码**：`--resolution/--fps/--output-width/--output-height`；FrameHeaderV1 全部 uint32 字段，3840×1080 天然支持【事实】 |
| 4 | USB3 带宽 | 1080p30 未压缩 YUV422 SBS ≈ **248.8 MB/s ≈ 2.0 Gbps**（Gen1 5Gbps 的 ~50%）；本机诊断 HD1080@30 init OK，无根本性约束，关注 hub 共享【事实+推导】 |

---

## 1. ZED-M HD1080 模式约束

1. 【事实】机器人所装 ZED SDK 5.0.7 头文件 `/usr/local/zed/include/sl/Camera.hpp`（L9026-9036）`enum class RESOLUTION` 原文：`HD1080, /**< 1920*1080 (x2) \n Available FPS: 15, 30*/`；`HD720, /**< 1280*720 (x2) … 15, 30, 60*/`；`HD2K, /**< 2208*1242 (x2) … 15*/`。→ 每眼 1920×1080、fps 上限 30，**以实际部署的 SDK 版本为准的直接证据**。
2. 【事实】官方文档 [camera-controls](https://www.stereolabs.com/docs/video/camera-controls)「Selecting a Resolution」表（ZED 2/2i/Mini 页签）：HD1080 → SBS **3840×1080**，fps 30/15，FOV 标注 "Wide"；HD720 → 2560×720，fps 60/30/15，"Extra Wide"；HD2K → 4416×1242@15；VGA → 1344×376@100。且原文 "The left and right video frames are synchronized and streamed as a single uncompressed video frame in a side-by-side format"——**UVC 线上原始帧本身就是 SBS 单流**（HD1080 时线帧即 3840×1080）。
3. 【事实】**本机诊断**（`/home/unitree/eeg_humanoid/teleop/xr_teleoperate/ZED_Diagnostic_Results.json`，2026-09-02 14:26 跑在目标机上）：设备 Model=ZED Mini，Serial 13732359，Firmware 1523；resolutions 列表实测 `HD1080@30: 1920x1080 input/output, fps 30/30, initialization OK, status True`；`HD1080@15` 同样 OK；**列表中不存在 HD1080@60**（HD720@60 存在且 True，VGA@100 True，HD2K@15=2208×1242 True）。→ fps≤30 在本台相机 + 本 Orin NX + 本 USB 口上实证。
4. 【事实】rectified 每-mode FOV 表（[support 360007395634](https://support.stereolabs.com/hc/en-us/articles/360007395634)，USB 立体相机 ZED Mini 列）：**HD1080 = 66°H / 40°V；HD720 = 82°H / 52°V**；HD2K = 73°/46°；WVGA = 85°/54°。同表焦距（px）：HD1080 1478，HD720 736；像元尺寸：HD1080 0.002mm，HD720 0.004mm，WVGA 0.008mm。文章注明数值为 nominal、依出厂标定浮动。
5. 【事实】硬件光学（datasheet Rev1.2 + [商店页](https://www.stereolabs.com/store/products/zed-mini)）：1/3" 4MP CMOS，有效阵列 **2688×1520/眼**，6 片全玻璃固定镜头 3.06mm f/2.0；当前官标最大 FOV 102°(H)×57°(V)×118°(D)（旧版标 90°H，见 zed-sdk issue #198）。
6. 【推断】**裁切机理**：HD1080 用原生 2µm 像元只读 1920×1080 区域（约占阵列宽 71%）→ 中心裁切、FOV 收窄到 66°H；HD720 是 2×2 binning（像元等效 0.004mm）覆盖约 95% 阵列宽 → 82°H 宽模式。依据是第 4/5 条像元尺寸与阵列尺寸的算术关系，官方未明文写"crop"一词，但 docs 的 Wide/Extra Wide 标注与此一致。
7. 【推导】**角分辨率收益**：1478/736 ≈ **2.0× px/°**（中心约 25.8 vs 12.8 px/°），代价 **−16°H / −12°V**。对本图的意义：验收线③「画质提升可辨」应成立（同物距细节密度翻倍），但**操作员周边视野收窄约两成**——这是地图 Notes 未列出的新权衡，四线验收主观判定时应知悉（若需要，A/B 时把 FOV 差异作为已知项告知判定人）。
8. 【事实】SDK 侧无其它隐藏档位：SDK 头文件同处还有 HD4K/QHDPLUS/HD1536/HD1200/SVGA 等枚举，均为其它机型（ZED X 系/imx678）模式，ZED-M 诊断实测不出现。

## 2. zed_xr_bridge 源码事实（C++ 采集桥）

9. 【事实】**机器人源码与本机镜像逐字节一致**：机器人 `/home/unitree/eeg_humanoid/teleop/xr_teleoperate/patch/zed_bridge/src/zed_xr_bridge.cpp` md5 `e286b589239d6f36049dfc298c87f89c` = 本机 `F:\Chufan_Rui\teleop\patch\zed_bridge\src\zed_xr_bridge.cpp`；协议头 `include/zed_frame_protocol.hpp` md5 `07a3ab5e6a74c639c25ee829d4145f8d` 亦一致。本机另有旧副本 `F:\Chufan_Rui\teleop\g1_zed_bridge\`（全文件差异，8-15 旧版）——**以 `patch\zed_bridge\` 为准**。
10. 【事实】**已部署二进制比源码新**：机器人 `patch/zed_bridge/build/zed_xr_bridge`（48008 B）mtime 2026-07-27 11:24 > 源码 11:17 → 现役二进制含当前源码，无"改了没编"的坑。
11. 【事实】**输出尺寸全参数化**（`zed_xr_bridge.cpp` Args/parse_args，L54-105）：`--resolution HD2K|HD1080|HD720|VGA|AUTO`、`--fps`、`--output-width`、`--output-height`、`--serial`、`--endpoint`、`--open-retries`、`--grab-fail-threshold`。采集与输出的唯一耦合是 `cv::resize(bgr, out, cv::Size(out_w, out_h))`（L250）——**任意宽高都走同一条 resize 路径**。二进制裸跑内部默认 1280×480/HD720（L59-60），生产从不裸跑（launcher 显式传参）。
12. 【事实】**SBS 拼帧由 SDK 完成，不在 bridge**：`zed.retrieveImage(sbs, sl::VIEW::SIDE_BY_SIDE, MEM::CPU)`（L237）返回"宽度翻倍"的拼帧（注释 L236）；HD1080 时即 3840×1080 BGRA。bridge 只做 BGRA→BGR（L249）+ resize（L250）。**全文件 grep 无 2560/720/3840/1080 任何硬编码**，缓冲全部 OpenCV Mat 按需分配后复用（L214-215 注释）。
13. 【事实】**发布协议对 3840×1080 天然支持**（`zed_frame_protocol.hpp`）：FrameHeaderV1 44 字节 packed，`width/height/stride/payload_size` 全为 uint32；填充处 `h.stride = h.width*3; h.payload_size = h.stride*h.height`（cpp L267-270）。校验不变量（C++ `is_valid_header` L46-57 与 Python 侧 `_validate_header`，`image_server.py` L1982-1987 镜像）只有：magic/version/header_size/channels=3/pf=1、`stride==w*3`、`payload==stride*h`、**`w % 2 == 0`（双眼均分）**、`msg_len==44+payload`。3840 为偶数 ✓，全部字段 uint32 无上限问题。
14. 【推导】**每帧消息体积**：3840×1080×3 = **12,441,600 B ≈ 11.86 MiB/帧**（+44 B 头），30fps 下 ZMQ IPC 流量 ≈ **373 MB/s**（现 720p 为 5.53 MB/帧、166 MB/s，×2.25 与像素比一致）。ZMQ 侧 `SNDHWM=1 + CONFLATE=1`（cpp L198-201）单消息模式对大帧无碍（MAXMSGSIZE 默认不限）。这正是地图已列的「conv+pipe write ×2.25、E 20.2ms → +5-8ms」张力的具体数值面。
15. 【事实】**Python 订阅侧同样零硬编码、完全跟随帧头**：`ZEDBridgeCamera._update_frame`（`F:\Chufan_Rui\teleop\teleimager\src\teleimager\image_server.py` L1989-2013）`np.frombuffer(msg, count=hh*w*3, offset=44)` → `reshape(hh,w,3)`；WebRTC 编码器 codec 宽高跟帧走（L158-171 `self.codec.width = frame.width`）；NVENC 子进程 `matches(width,height)` 不匹配即按帧尺寸重启（L284-285、L462-466）。**配置里的 `image_shape` 对 zed_bridge 相机只用于日志/启动一致性，不做帧校验**——但按注释约定仍应与 `--output-width/height` 保持一致。
16. 【事实】**现役启动链与默认值**：生产入口 `run_stack.sh` → `./launch_zed_bridge.sh --config cam_config_zed_<DOSE>000000.yaml`（不传分辨率/尺寸参数 → 吃默认）。活体 launcher 在 `<xr_teleoperate>/teleop/teleimager/entry/`，其 `REPO_ROOT/teleop/zed_bridge` 经符号链接 `<xr_teleoperate>/teleop/zed_bridge → ../patch/zed_bridge` 解析到已部署二进制。**operative 默认 = HD720 / 30 / 2560×720**（launcher L31-34）。另一个 checkout `/home/unitree/teleimager/entry/` 的 launcher 默认二进制路径 `/home/unitree/teleop/zed_bridge` **不存在**（该副本非现役，除非 env 覆盖）。
17. 【事实】**launcher usage 文本已经"预告"了 1080**：两份机器人副本与本机副本的 usage（L53-56）都印着 `--resolution … (default HD1080)`、`--output-width … (default 3840)`、`--output-height … (default 1080)`，而 operative 默认仍是 HD720/2560/720——**help 文本与实际默认不一致的既有漂移**（本图合入时顺手把默认值改成与 usage 一致即可消除）。
18. 【推断】**一个可选微优化**：HD1080 下 SDK 给的 SBS 已是 3840×1080，与输出同尺寸，`cv::resize` 无同尺寸短路、仍跑一遍 INTER_LINEAR 全图插值（BGRA→BGR 也是 16.6MB 读）。合入票可在 `in_w==out_w && in_h==out_h` 时跳过 resize（省一段纯拷贝开销），非必须。
19. 【事实】当前生产实况（取证时 bridge 正在跑）：`/tmp/zed_xr_bridge.log` 最新行 `cap_fps=29.999 pub_fps=29.999 grab_errors=4 send_drops=0`，seq≈37248——720p30 稳态零丢帧，为 A/B 基线提供了健康起点。

## 3. USB3 / UVC 带宽

20. 【事实】官方口径：ZED-M 接口 "USB 3.0 Type-C"，输出格式 **YUV 4:2:2 未压缩**、左右同步单条 SBS UVC 流（datasheet Rev1.2 + camera-controls docs）；"The ZED Mini is not backwards compatible with USB 2.0"（[support 206918309](https://support.stereolabs.com/hc/en-us/articles/206918309)）。
21. 【推导】**带宽算术**（YUV422=2 B/px，SBS 单流）：HD1080@30 = 3840×1080×2×30 = **248,832,000 B/s ≈ 248.8 MB/s ≈ 1.99 Gbps**（含 8b/10b 线上 ~2.49 Gbps ≈ Gen1 5Gbps 的 50%）。参照系：HD720@60 ≈ 221 MB/s（**比 1080p30 还高**）、现役 HD720@30 ≈ 110.6 MB/s（升级即 ×2.25）、HD2K@15 ≈ 165 MB/s。票面 "~186MB/s" 系单目 RGB24 口径；立体 YUV422 实为 249 MB/s。
22. 【事实】**本机链路实证**：诊断 USBList 显示 ZED mini 视频接口 `USBMode 3, bcdUSB 3.0`，挂 **bus 2 根集线器 /3 口**（不经过下挂 hub；同 bus 另有 Realtek/Genesys hub 与若干设备在 /2/* 下），IMU 走独立 USB2 HID 接口（bus 1）；HD1080@15/30 init OK status True（第 3 条）。→ 2.0 Gbps 在本口本机上被 SDK 实测接受。
23. 【事实】Orin NX 侧（[Jetson 设计指南 r36.4](https://docs.nvidia.com/jetson/archives/r36.4/DeveloperGuide/HR/JetsonModuleAdaptationAndBringUp/JetsonOrinNxNanoSeries.html)）：3 个 SuperSpeed 口（UPHY0 lane0-2，与 PCIe/DP 共享 lane），**单一 xHCI 控制器**服务三口；官方未公布控制器聚合带宽数；参考底板 Type-A 口堆经板载 hub 下挂。平台：Orin NX DevKit 16GB / L4T 35.3.1 / 8 核 / CUDA 11.4（诊断 Processor+SDK 节）。
24. 【推断】**结论：无根本性带宽约束，留两个观察点**。① ZED 已在根口独占 Gen1（50% 线速），但与 bus 2 其它设备共享控制器——若日后同 bus 挂上腕部相机等 SS 设备，先看 `grab_errors` 抬升（Stereolabs 官方排障指引也是"直插、去 hub、隔离它设备"）；② 诊断的 status True 只证明 init+短测，**30 分钟量级长跑的 grab_errors 曲线**留给本图 03 实测票顺带看一眼即可（现役 720p 约 1h 仅 4 次 grab_error，健康）。

## 4. 配置面（本机，琐碎）

25. 【事实】`F:\Chufan_Rui\teleop\teleimager\entry\cam_config_zed.yaml`：`image_shape: [720, 2560]` → 需改 **`[1080, 3840]`**（注释 "left 1280 + right 1280" 同步改 1920）；`fps: 30` **不动**；`webrtc.bitrate min/default/max = 2M/2M/12M`（12M 上限即地图 REMB 天花板，本图 03 若选 8-12M 档无需动 max）；`gop_length: 30` 不动。机器人侧同名文件内容一致（已 cat 比对）。
26. 【事实】**剂量配置是派生物**：`run_stack.sh` 用 sed 从 `cam_config_zed.yaml` 现生成 `cam_config_zed_<DOSE>000000.yaml`（机器人 entry 目录现存 `cam_config_zed_4000000.yaml` 烤着 `[720,2560]`、还有 `cam_config_zed.yaml.bak-t04`）——改完 base 后按流程重新生成即可，不要手改派生文件。
27. 【事实】启动面改动二选一：显式传参 `--resolution HD1080 --output-width 3840 --output-height 1080`，或把 launcher L31-34 默认改为 HD1080/3840/1080（顺带消除第 17 条 usage 漂移，推荐后者，run_stack 无需动）。
28. 【事实】overlay 时钟（地图"小事顺手带"项）：`overlay_clock.py` 是 Jetson 屏上 tkinter 全屏钟（字号固定 110pt，与分辨率无关）；帧内烙印在 `image_server.py` L966-971 按 `shape[0]>=90` 与 `shape[1]//2` 自适应——**无 2560/720 硬编码**，新分辨率下大概率直接工作，仅烙印字号视觉复核一下。

---

## 5. 与地图假设的对照（供 tracker 决策）

- ✅ **fps 上限 30**：地图硬事实成立（SDK 头/文档/本机诊断三方）。
- ⚠️ **新事实：FOV 收窄**。地图未提及 1080 的 FOV 代价：rectified 66°H/40°V vs 现役 82°H/52°V（−16°/−12°），换来 2.0× 角分辨率。不阻塞四线验收，但验收线③主观判定与操作员体验评估时应作为已知差异声明。
- ✅ **bridge 无硬编码**：`--output-*` 全参数化、协议 44B 头 uint32 全字段、Python 侧跟随帧头——采集侧改动收敛为「launcher 默认值 + cam_config image_shape」两处配置。
- ⚠️ **usage 文本漂移**（第 17 条）与**派生剂量配置**（第 26 条）是合入票要顺手的两个坑。
- ℹ️ 票面 "~186MB/s" 应修正为 **~249 MB/s（立体 YUV422）**；量级结论不变（Gen1 的 ~50%）。

## 证据来源索引

- SDK：`/usr/local/zed/include/sl/Camera.hpp` L9026-9036（机器人，ZED SDK 5.0.7）
- 实机诊断：`/home/unitree/eeg_humanoid/teleop/xr_teleoperate/ZED_Diagnostic_Results.json`（2026-09-02 14:26，Model/Firmware/resolutions/USBList/Processor）
- 源码：`F:\Chufan_Rui\teleop\patch\zed_bridge\src\zed_xr_bridge.cpp`（=机器人 md5 `e286b589…`）、`include\zed_frame_protocol.hpp`（=`07a3ab5e…`）、`build` mtime 2026-07-27 11:24
- Python：`F:\Chufan_Rui\teleop\teleimager\src\teleimager\image_server.py` L158-171/1982-2013/268-285/462-466；`entry\launch_zed_bridge.sh` L31-34/L53-56；`entry\cam_config_zed.yaml`；`entry\overlay_clock.py`
- 机器人启动链：`<xr_teleoperate>/teleop/teleimager/entry/{run_stack.sh,launch_zed_bridge.sh,cam_config_zed*.yaml}`、`teleop/zed_bridge -> ../patch/zed_bridge` 符号链接、`/tmp/zed_xr_bridge.log`
- 官方文档：[camera-controls](https://www.stereolabs.com/docs/video/camera-controls)、[support 360007395634 FOV/焦距表](https://support.stereolabs.com/hc/en-us/articles/360007395634)、[ZED-M 商店页](https://www.stereolabs.com/store/products/zed-mini)、[Datasheet Rev1.2](https://www.mouser.com/pdfDocs/ZED_Mini_Datasheet_Rev1.2.pdf)、[support 206918309 USB2 不兼容](https://support.stereolabs.com/hc/en-us/articles/206918309)、[support 207635225 USB3 排障](https://support.stereolabs.com/hc/en-us/articles/207635225)、[NVIDIA Jetson Orin NX 设计指南 r36.4](https://docs.nvidia.com/jetson/archives/r36.4/DeveloperGuide/HR/JetsonModuleAdaptationAndBringUp/JetsonOrinNxNanoSeries.html)
