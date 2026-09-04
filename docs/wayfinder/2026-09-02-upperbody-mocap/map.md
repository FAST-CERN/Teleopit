---
id: upperbody-mocap-map
title: "Pico bridge 上半身动捕：体感追踪器×2 采集链实装 + sim ARMS 输入验证"
labels: [wayfinder:map]
status: open
created: 2026-09-02
---

## Destination

上半身动捕**采集链**实装并**仿真验证**过线：pico-bridge app 读取 2 个 Pico 体感追踪器（固定于 MANUS 动捕手套手背）+ HMD 位姿，经现有 TCP 追踪协议（cmd 0x6D 的 `Motion` 字段）上行 → pico_bridge Python 接收端解析暴露 → Teleopit 合成上半身参考喂现有重定向 → **sim 中以现有 ARMS 模式（单一 mocap arms，不动模式机）验证双臂跟随**。验收四线（采集质量 / 跟随稳定 / 断连安全 / 主观）过线即达。

统一 policy（obs 吃 velocity+上半身动捕）与真机线**另开新图**。

## Notes

**领域**：上下半身解耦策略的第一段（采集 + 输入验证）。下半身（velocity/走路）本图不动；手指链路 manus_server（`F:\teleop\manus_server`）独占，本图零手指工作。

**本图携带执行**（同 zed-fpv/nvenc/1080p 图惯例，覆盖 wayfinder 默认纯规划）：终点=采集链合入 + sim 验证过线。

**开图定案**（2026-09-02 会话与用户对齐）：

1. 硬件：**Pico 体感追踪器 ×2**（SN 绑定左右手），固定于 MANUS 动捕手套手背；手指数据走 manus_server 既有 DexPilot→DDS→Orin 链（已整链验证）。
2. 手指仲裁：**manus_server 独占手指**，Teleopit 侧手输出静音——本图无手指面，真机图再处理 Teleopit 手 worker 配置。
3. 覆盖范围：**仅双臂**（颈已有 HMD 主动跟随；腰 3DOF 不动）。
4. 模式形态：**不动模式机**——sim 验证用现有 ARMS 模式（MOCAP 内 B 键切换）单独测；VELOCITY 臂开关 / 新 RobotMode / 颈白名单扩 velocity 全部留给统一 policy 图。
5. 验收风格：四线（采集质量、跟随稳定、断连安全、主观），数值线在验收票内定稿。

**术语**：「体感追踪器」= PICO 官方 motion tracker 配件（SDK `PXR_MotionTracking` 的 MotionTracker 系列 API）；「腕目标」= tracker 位姿经安装偏移折算的腕部位姿；「合成帧」= HMD+2 tracker 合成的上半身 HumanFrame（对照：现状全身 HumanFrame 来自 PICO body tracking 24 角色骨架）。

**硬事实（开图侦察定案，约束全部票面）**：

- Unity app 是**纯追踪串流桥**（无模式机；TCP 63901，`PackageHandle` 帧，JSON 信封 `{"functionName":"Tracking",...}`，trackingFps 默认 72Hz）。`PicoTrackingCollector.AppendMotion()` 是占位符（`"Motion":{"joints":[],"len":0}`），但 SDK 数据面 API 齐备（`GetMotionTrackerLocation(s)`/电池/SN 连接回调，`Packages/.../Runtime/Scripts/Features/PXR_MotionTracking.cs` ~320-566），信号门控 `TrackingSignalStatus.cs` 已在调连接状态——缺的只是数据采集。
- Teleopit 侧 ARMS 模式已存在且整链验证过：`pico4_provider` 全身 HumanFrame → GMR/mink+daqp 重定向（`ik_configs/pico_bridge_to_g1.json`：`wrist_yaw_link↔Wrist` 姿态任务权重 10、臂 human scale 0.8）→ `arm_mocap.compose_arm_reference` 拼接 14 臂关节（idx 15–28）进站立位。**输入换源即可复用**。
- PICO body tracking（`sendBody`，默认关）的臂估计依赖头显+手柄/相机手部追踪——**戴 MANUS 手套时两者皆不可用**，这正是腕部改用独立 tracker 的动因；本图臂源=tracker，不用 body tracking 臂。
- sim 侧现状保持：`TOGGLE_ARMS` 在 VELOCITY 被忽略、`VALID_NECK_ACTIVE_MODES` 不含 velocity、MOCAP 入场需 10 帧连续有效 + 参考龄 ≤0.25s（`mocap_switch`）——合成帧须满足这些既有闸门。
- Unity **Personal 许可 term 已于 2026-08-31 到期**（`C:\ProgramData\Unity\Unity_lic.ulf` StopDate，AlwaysOnline=false）→ 重编 APK 前须 Unity Hub 重新登录签发（票 02）。
- 上次 APK 改 URL 走的等长二进制改写**加不了新代码**——本图必须从源重编。

**部署/环境**：本机 teleopit conda env（3.10 全家桶）跑接收端测试与 sim；APK 装机 HITL。**停机窗口纪律**同前图（真机面本图无）。

**Tracker 约定**（同前图）：Ticket = `tickets/NN-*.md`（frontmatter labels/status/assignee/blocked-by）；Frontier = open 且依赖全闭且未认领；Resolve = 正文追加 `## Resolution` + status: closed + 本 map Decisions 追加一行；研究产物放 `research/`。

## Decisions so far

- 2026-09-02 t01 闭（research/01）：活体 API=单数 `GetMotionTrackerLocation`（复数+`tobeContinued` 已废弃/不存在，SDK 3.4.0 无需升级）；位姿=HMD local 右手系→复用 AppendBody 翻转（−Z/−Qz/−Qw）标 `pico_tracker_local`，接收端+Teleopit 链零新约定；采样固定 50Hz、无 per-sample 时戳；左右绑定=app 层单只开机指认持久化（启动枚举走 `CheckMotionTrackerNumber` 完成回调）；腕部无 SDK 限制、真约束=HMD 光学可见性（06 加手臂扫掠、05 加 valid=false 策略）。
- 2026-09-02 t05 闭（grilling 六问，research/05）：合成形态=**完整合成 body 等价帧**（方案 A，ik 表零改动）住 **provider 层**（`tracker_arm_synth.py`；03 哑传感器、04 只透传）；肩锚=HMD 刚体常数、肘=中点+外偏（k=0.05 配置，swivel 留 06 对局）；安装偏移=静态测量 YAML（tracker 系，`p_腕=p_tracker−R·offset`，06 ±2cm 灵敏度）；坐标全链复用零新变换；失效=hold 0.3s→整帧 invalid→现有闸门链（新语义=0）；时间=03 同帧结构保证、有效 50Hz。06 实装清单+接口签名在 research/05 §1–2。
- 2026-09-02 t04 闭（TDD；pico-bridge `7e83469` 0.2.2 + Teleopit `71e3588`）：wire 契约 side-first（`Motion.left/right{sn,p,valid}`）；`PicoFrame.trackers` 容错解析（无 Motion/占位=inactive）；recording 零改动透写往返锁契约；provider `get_tracker_snapshot()` pico_native xyzw 原样透传（body 拒帧时照常捕获）；版本闸抬 (0,2,2)（gate 测试原传 bridge_cls 绕闸缺陷一并修）。真机回放补验欠账回写 03 票面。pc_receiver 108 过、Teleopit 589 过（4 失败+11 收集错均为预置欠账）。
- 2026-09-03 t02 闭（research/02-build-env）：许可已重签（UnityPersonal，StopDate 2026-09-07，Hub 周滚签）；干净树 `7e83469` 批处理 Validate 全绿 + IL2CPP 出包 Success（59.2 MiB，热缓存 41s）；**坑=批处理成功后 Unity.exe 挂死须 taskkill+删锁**；出包命令在 notes §3，t03 增量包直接复用。sbs-1080p spinner WIP 已 stash 隔离，归该图处置。
- 2026-09-03 t03 代码面落地（pico-bridge `fdefb58` 0.2.3，装机验收待 HITL）：用户定序「先 t03 核心避开 panel」——SN 绑定走 MotionTrackerBinding 自动指认（先左后右+JSON 持久化），panel 面推迟；sendMotion 真机开启走 BridgeControl tracking/set_motion（接收端 `--motion-trackers`）；wire 契约以 t04 side-first 为准（t01 数组形 sketch 作废）；mock+dump 端到端验证过，109 测试（1 预置 aiortc 败）。APK 已出待装机（票内 runbook）。
- 2026-09-04 t03 闭（HITL 真机四项全过；APK 链 `fdefb58`→`ec5c73d`(UI)→`cb46907`(fix)）：中位 69.4Hz 零间隙、坐标冒烟三轴符号全对（y+2.02/x−0.98/z+0.38）、valid 遮挡语义活、27451 帧全量回放零错误（**04 §6 欠账清**）。**SN 实测=trackerid 1/2**。HITL 暴露启动竞态（预连接 tracker 惰性订阅漏绑→power-cycle 才绑）已修（早订阅）并装机回归通过。录制数据留 pc_receiver（坐标冒烟段可作 05/06 输入）。frontier→t06。

## Not yet specified

- ~~APK 重编时是否顺手把硬编码 `/offer` URL 改可配置~~——已被 pico-bridge `af50f5f`（1080p 图 t06）清掉，03 无剩余顺手项
- receiver 追踪录制（recording）扩展 `Motion` 字段作为 06 验收的可重复输入工具——recording 零改动透写已天然覆盖（t04 已锁往返），06 直接用
- t03 panel 面（SN 绑定显示 + sendMotion 面板开关）——推迟到 sbs-1080p UI WIP（pico-bridge stash）合流后的小票；当前用 BridgeControl tracking/set_motion 远程开关

## Out of scope

- 真机上半身动捕（真机验收、estop/关节限位真机化、Teleopit 手 worker 静音配置落地）
- 统一 policy 训练/接入（velocity+臂 obs 融合、模式机改动、VELOCITY 臂覆盖层）
- 手指链路改动（manus_server 侧任何工作、haptics、手指-腕时间同步）
- FPV 视频链路、腰/颈增强、60fps（各属既有出图）
