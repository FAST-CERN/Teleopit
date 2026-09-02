---
id: 01-tracker-sdk-semantics
title: "PICO 体感追踪器 SDK 数据面语义（坐标系/四元数/频率/SN 绑定）"
labels: [wayfinder:research]
status: closed
assignee: claude
blocked-by: []
---

## Question

PICO motion tracker 数据面 API 的精确语义收齐（AFK 研究，产物进 `research/`），约束 03（Unity 采集）与 05（Teleopit 合成）：

1. `PXR_MotionTracking.GetMotionTrackerLocations`（单/多 SN 重载）返回的**坐标系**（头显系? 世界/场地系?）、位置单位、四元数分量顺序与手性；
2. 位姿**更新频率**与延迟特性（tracker 固定 50Hz? 随 trackingFps?）；`tobeContinued`/状态枚举的语义（连接/追踪丢失如何区分）；
3. **SN↔左右手绑定**方法：`GetMotionTrackerConnectStateWithSN`、连接回调 `MotionTrackerConnectionAction`、枚举已连 tracker 的 API；有无内置左右标签（如体感追踪器配对时 waist/ankle 角色绑定）可复用；
4. 与 Unity XR / `PXR_Input.GetControllerPredictPosition` 的**坐标约定差异**（现有 body/hand JSON 的 `pico_body_local`/axis-flip 处理是否适用）；
5. 追踪器**佩戴位置约束**：官方支持腰/踝全身方案（3 tracker），腕部佩戴是否有 SDK 层面限制（角色绑定冲突、全身模式互斥）；
6. SDK 版本要求：pico-bridge 工程 `Packages/PICO-Unity-Integration-SDK` 当前版本是否已含上述 API；PICO 官方文档佐证链接。

主要信源：本地 SDK 源码 `F:\Chufan_Rui\teleop\pico-bridge\Packages\.../Runtime/Scripts/Features/PXR_MotionTracking.cs`（~320-566 已确认 API 面）+ PICO 开发者文档（https://developer-cn.pico-interactive.com）。

## Resolution

2026-09-02 闭，产物 `research/01-tracker-sdk-semantics.md`（六问速答+分节+下游快照）。要点：

1. **API 面修正**：复数 `GetMotionTrackerLocations`（predictTime 版）在 3.4.0 已 `[Obsolete(true)]` return -1；活体=单数 `GetMotionTrackerLocation(long, ref MotionTrackerLocation, ref bool isValidPose)`，P/Invoke 直通无坐标转换。`tobeContinued` 不存在于 3.4.0，状态面就是 isValidPose 单位位。SDK 3.4.0 无需升级。
2. **坐标系**：HMD 锚定 local **右手系**（官方文档明示 localLocation 右手、Unity 左手须转换；global 系官方不建议用）→ 与 body `localPose` 同族，**AppendBody 现有翻转（−Z、−Qz、−Qw）直接复用**，标 `pico_tracker_local`；接收端透传 + Teleopit 既有矩阵链零新约定。
3. **频率**：独立追踪固定 **50Hz**（trackingFps 72 只是采集环轮询率）；无 per-sample 时间戳，新鲜度只能用帧级 timeStampNs。
4. **SN 绑定**：无内置左右标签；启动枚举唯一通道 = `CheckMotionTrackerNumber(TWO)` → `RequestMotionTrackerCompleteEventData{trackerCount, trackerIds[6]}`（连接回调只报变化，冷启动空集风险→03 必须走此流程）；推荐单只开机指认法持久化 id。
5. **佩戴**：腕部无 SDK 限制（独立追踪=匿名 6DoF 物件）；真约束是 HMD 光学可见性→06 加手臂位置扫掠、05 加 isValidPose=false 保持策略。
6. 四项实机佐证（坐标系核验/冷启动枚举/单位+遮挡退化/50Hz 实到率）移交 03 冒烟与 05 定参，见 research §7。
