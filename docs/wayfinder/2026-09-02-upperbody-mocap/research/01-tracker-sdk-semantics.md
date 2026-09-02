# t01 PICO 体感追踪器 SDK 数据面语义（坐标系/频率/SN 绑定/佩戴/版本）

- 地图：`2026-09-02-upperbody-mocap`（ticket 01，research）
- 日期：2026-09-02（纯源码+文档研究，无实机；实机佐证点已列 §7 移交 03）
- 信源：
  - 本地 SDK 源码 `F:\Chufan_Rui\teleop\pico-bridge\Packages\PICO-Unity-Integration-SDK`（**PICO Integration 3.4.0**，package.json；Unity 2021.3）：
    `Runtime/Scripts/Features/PXR_MotionTracking.cs`、`Runtime/Scripts/Utils/PXR_Type.cs`、`Runtime/Scripts/PXR_Plugin.cs`（native 绑定）
  - 工程现状 `Assets/Scripts/PicoBridge/Tracking/`：`TrackingSignalStatus.cs`、`PicoTrackingCollector.cs`（`ProjectSettings.asset` 无自定义 scriptingDefineSymbols → 原生 PXR 路径生效，非 OpenXR）
  - 接收端现状：`pico_bridge` 包（teleopit env site-packages）`frames.py`；Teleopit `teleopit/inputs/pico4_provider.py`
  - PICO 官方文档「独立追踪」：https://developer.picoxr.com/zh/document/unity/object-tracking/ ；运动追踪示例 PICOMotionTrackerSample
- 标注：【事实】= 源码/文档原文可查；【推导】= 由前者算术/等价变换；【推断】= 分析判断（须实机佐证）。

---

## 0. 六问速答

| # | 问题 | 裁决 |
|---|---|---|
| 1 | 坐标系/单位/四元数 | 位姿在 **HMD 锚定的 local 右手系**；Unity 左手系赋值须转换；位置单位**米**；`Posef` = `Quatf Orientation (x,y,z,w)` + `Vector3f Position`【事实+推断，见 §1】 |
| 2 | 频率/延迟/状态 | 独立追踪模式采样**固定 50Hz**（不随 trackingFps 72Hz）；**无 per-sample 时间戳**；状态=`ref bool isValidPose` 单位有效性位；`tobeContinued` 在 3.4.0 中**不存在**（属旧版文档残留）【事实，见 §2】 |
| 3 | SN↔左右绑定 | 无内置左右标签（角色绑定仅存在于 body tracking 校准：腰+双踝）。活体通道：`MotionTrackerConnectionAction(long id,int state)` 增删 + **`CheckMotionTrackerNumber` 完成回调 `RequestMotionTrackerCompleteEventData{trackerCount, trackerIds[6]}` 作启动枚举**。左右绑定须 app 层自建（推荐单只开机指认法）【事实+推荐，见 §3】 |
| 4 | 与现有坐标约定差异 | tracker `localLocation` 与 body `localPose` 同族（PICO native local，右手系）→ **AppendBody 现有翻转（−Z、−Qz、−Qw）直接复用**；Head/Controller/Hand 是 Unity 系原样直传，勿套翻转。接收端透传 + Teleopit `_INPUT_TO_TELEOPIT_MATRIX` 链路不变【事实+推导，见 §4】 |
| 5 | 佩戴位置约束 | SDK 角色约束只在 body tracking 模式；**独立追踪=通用 6DoF 物件追踪，腕部佩戴无 SDK 限制**。互斥关系：body/object 模式二选一（本图不用 body tracking，无冲突）。约束在光学可见性：须在头显可见范围内，遮挡→6DoF 退化【事实+推断，见 §5】 |
| 6 | SDK 版本 | 工程 in-tree **3.4.0 已含全部活体 API**（本票 §1–§3 所引符号逐一在源码中确认），无需升级；`GetMotionTrackerLocations`（复数+predictTime）已 `[Obsolete(...,true)]` return -1，**禁止使用**【事实】 |

---

## 1. 坐标系、单位、四元数（Q1）

【事实】`PXR_Type.cs:2572-2588` 废弃复数 struct 的注释是唯一的官方框架声明：

- `localLocation`：*"The motion tracker's location in the same reference frame as the HMD."*
- `globalLocation`：*"global system-level reference frame (**not recommended for use**)"*。

【事实】官方文档（独立追踪）：*"Unity 引擎默认使用左手坐标系，而 localLocation 使用右手坐标系。因此，赋值位姿时，需要将右手坐标系转换为左手坐标系"*，示例 `child.localPosition = new Vector3(x, y, -z)`。

【事实】活体单数 API `GetMotionTrackerLocation(long trackerid, ref MotionTrackerLocation location, ref bool isValidPose)`（`PXR_MotionTracking.cs:551`）经 `PXR_Plugin.cs:5098` P/Invoke 直通 `Pxr_GetLocateMotionTracker`，**C# 层零坐标转换**。`MotionTrackerLocation`（`PXR_Type.cs:2544`）= `Posef pose`（`Quatf Orientation` x/y/z/w + `Vector3f Position`）+ 角/线速度加速度各 [3]。

【推断】单数 API 文档页（object-tracking）即描述 localLocation 语义，归 **HMD local 系（右手）**；与复数 struct 的 localLocation 同族。此点 + 位置单位米（文档示例为米量级；struct 注释里速度单位 meter/millimeter 自相矛盾，属 SDK 文档 bug）→ 列 §7 实机佐证第一项。

【推导】四元数分量顺序 = Posef 字段序 x,y,z,w（工程 `AppendPose` 对 Head/Body 均按此序列化，接收端 `_parse_pose_array` 同序）；z 镜像下 `(qx,qy,−qz,−qw)` 与 `(−qx,−qy,qz,qw)` 等价（整体差 −1），故与 AppendBody 翻转形式一致即可。

## 2. 频率、延迟、状态语义（Q2)

【事实】官方文档：独立追踪模式**采样频率 50Hz**。工程采集环 trackingFps 默认 72Hz → 每 tracker 约 22Hz 重复帧，接收端/合成端按帧到时戳（app `timeStampNs`）处理新鲜度即可；`MotionTrackerLocation` **无 BodyTrackingRoleData.localPose.TimeStamp 那样的 per-sample 时间戳**——新鲜度只能用帧级时间。

【事实】状态面：活体仅 `ref bool isValidPose`（TrackingSignalStatus.cs:126 已按 `==0 && isValidPose` 消费）；废弃路径的 `MotionTrackerConfidence` 四档（STATIC/6DOF_ACCURATE/3DOF_NOT_ACCURATE/6DOF_NOT_ACCURATE）与 `tobeContinued` 均不在 3.4.0 活体面（全 Packages grep 零匹配）。连接/断开事件：`MotionTrackerConnectionAction(long, int)`（0=断、1=连，id=数字 SN）；电源键事件 `MotionTrackerPowerKeyAction`；电量 `GetMotionTrackerBattery(long, ref float[0,1], ref XrBatteryChargingState)`。

【推断】连接断开≠追踪丢失：断连走 ConnectionAction，追踪丢失（遮挡/出视野）走 isValidPose=false——04 的 Motion 解析与 06 断连安全线须分别覆盖两个维度。延迟特性官方未载 → 06 验收实测（e2e 链路已含）。

## 3. SN↔左右手绑定（Q3)

【事实】活体通道三件套：

1. 增量：`MotionTrackerConnectionAction(long trackerId, int state)`（TrackingSignalStatus.cs:139 已订，HashSet 维护）；
2. **启动枚举**：`CheckMotionTrackerNumber(MotionTrackerNum number)`（[0,3]，不匹配弹系统面板引导用户切模式/校准）→ 完成回调 `RequestMotionTrackerCompleteAction(RequestMotionTrackerCompleteEventData{UInt32 trackerCount; long[6] trackerIds; PxrResult result})`（`PXR_Type.cs:2743`）；
3. 单查：`GetMotionTrackerBattery` / `GetMotionTrackerLocation(id, …)` 按 id 逐只。

【事实】旧枚举 API `GetMotionTrackerConnectStateWithSN`（返回 string SN 数组）已 `[Obsolete(true)]` return -1——**启动时"id 列表从哪来"的答案只有通道 2**，且连接回调只报变化：app 启动前已连好的 tracker 不保证补发事件（TrackingSignalStatus 现实现依赖回调播种，冷启动可能空集——03 须补 CheckMotionTrackerNumber 流程）。

【推断】无内置左右标签：tracker 无屏幕、SN 为长数字；PICO 的 waist/ankle 角色绑定只发生在 body tracking 校准流程，独立追踪模式 tracker 是匿名 6DoF 物件。**推荐 03 采单只开机指认法**：UI 引导先开左→回调 id 落 left 槽、再开右→落 right 槽，持久化到 app 配置；重连时按持久化 id 复位姿，不重指认。备选：手套本体贴 SN 标签手工配。

## 4. 与现有坐标约定比对（Q4）

【事实】工程内三档约定并存（`PicoTrackingCollector.cs`）：

| 数据源 | API | 序列化处理 | wire 标注 |
|---|---|---|---|
| Head | `PXR_System.GetPredictedMainSensorStateNew` | 原样（Unity 系） | 无 |
| Controller | `PXR_Input.GetControllerPredictPosition/Rotation` | 原样（Unity 系） | 无 |
| Hand | `PXR_HandTracking.GetJointLocations` | 原样（Unity 系） | 无 |
| Body | `PXR_MotionTracking.GetBodyTrackingData` | **翻转**：PosZ→−Z、RotQz→−Qz、RotQw→−Qw | `poseSpace:"pico_body_local"` |

【事实】接收端 `pico_bridge/frames.py` `_parse_body` 透传无变换（`coordinate_space="pico_native"`）；Teleopit `pico4_provider._coordinate_transform_input` 统一套 `_INPUT_TO_TELEOPIT_MATRIX = [[1,0,0],[0,0,-1],[0,1,0]]`（x→x, y→z, z→−y）+ 同旋转四元数左乘。

【推导】tracker localLocation 与 body localPose 同为 PICO native local 右手系 → **03 的 `AppendMotion` 直接套 AppendBody 同款翻转**、标 `poseSpace:"pico_tracker_local"`；04 透传、05/Teleopit 沿用既有矩阵——三段链零新约定。与 `GetControllerPredictPosition` 的差异即"Unity 系 vs PICO native local 系"两族，勿混。

## 5. 佩戴位置与模式约束（Q5)

【事实】`MotionTrackerMode` 二值（BodyTracking / MotionTracking）；`CheckMotionTrackerNumber` 面板负责引导用户切换模式+校准——模式互斥由系统层保证。官方全身方案 = 腰+双踝 3 tracker（角色经 PICO Motion Tracker app 校准绑定）；官方文档定位独立追踪为"体感追踪器绑定于**物体**上进行位置追踪"。

【推断】腕部（手套手背）佩戴在 SDK 层面**无任何限制**（独立追踪不关心贴在哪）；本图 app 的 `BodyTrackingEnabled=false` 默认关，与 tracker 并行无冲突。真正的约束是**光学可见性**：文档"在一体机可见范围内可实时追踪"——手放身侧/背后/超出 HMD FOV 时 6DoF 退化甚至 isValidPose=false（官方 tracker=光学+IMU 融合，遮挡时退化行为未载）→ 06 采集质量线须含**手臂位置扫掠**（前伸/侧平/下垂/交叉/背后），05 合成须有 isValidPose=false 时的保持/衰减策略。

## 6. SDK 版本（Q6）

【事实】in-tree 3.4.0 逐符号确认：`GetMotionTrackerLocation`（活体）、`MotionTrackerConnectionAction`、`RequestMotionTrackerCompleteAction`、`CheckMotionTrackerNumber`、`GetMotionTrackerBattery`、`MotionTrackerLocation`/`Posef`/`RequestMotionTrackerCompleteEventData` 全部在。**无需升级 SDK**；升级反而要重验（3.4.0 的废弃面说明 PICO 正在收缩该 API 族）。文档佐证：https://developer.picoxr.com/zh/document/unity/object-tracking/ （SDK 3.x 世代）。

## 7. 移交 03/05 的实机佐证点（本票无实机）

1. **单数 API 坐标系核验**（03 冒烟首项）：tracker 平移/抬举方向 vs JSON 分量方向，确认 HMD local 系 + 翻转正确；
2. **冷启动枚举**：tracker 先连后开 app，验证 `CheckMotionTrackerNumber(TWO)` 回调是否携带已连 id（§3 通道 2）；
3. 位置单位米（量级核对）；遮挡退化行为（isValidPose 翻转时延）→ 喂 05 的保持策略参数；
4. 50Hz 实到率（连续 N 帧 per-tracker 位姿差分统计重复率）。

## 8. 对下游票的输入快照

- **03（Unity 采集）**：AppendMotion 结构 = Body 同款（`"Motion":{"poseSpace":"pico_tracker_local","trackers":[{"sn":<long>,"p":"x,y,z,qx,qy,qz,qw","valid":<0|1>},…],"len":N}`）+ 启动 CheckMotionTrackerNumber(TWO) + 单只开机指认绑定 UI + MotionTrackerEnabled 门控已有。
- **04（接收解析）**：`_parse_motion` 仿 `_parse_body` 透传；active 判定 = len>0 且至少一只 valid；帧级 timeStampNs 为唯一新鲜度源。
- **05（合成设计）**：输入=2×tracker 位姿（HMD local，已翻转到 Unity 系）+ HMD 位姿；输出=现有 HumanFrame 臂段（换源复用 GMR/mink 链）；isValidPose=false 策略与肘部退化路线（map "Not yet specified" §1）按本票 §5 风险定参。
