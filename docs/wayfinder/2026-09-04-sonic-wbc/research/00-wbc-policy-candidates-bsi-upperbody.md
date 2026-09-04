# G1 遥操作 WBC 开源策略候选调研（BSI velocity + 上半身动捕契约）

- 日期：2026-09-04（**预研，未绑定 wayfinder 图**）
- 前置研究：`reference/openhomie-integration-feasibility.md`（HOMIE 基线结论：外骨骼座舱输入、LCM、CC BY-NC-SA、仓库停更、腰锁 27-DoF checkpoint——已否决接入主链路，本研究是它的"找替代品"续篇）
- 用户契约（筛选靶）：
  1. 策略输入 ≈ {**速度指令 cmd_vel** + **上半身关节目标**}；关节空间最佳，稀疏 VR 三点位姿（头+双手）或 SMPL 可评估转换成本（本地合成器可产任意一种）；
  2. **公开 G1 29-DoF checkpoint**（23-DoF 或锁腰变体可接受——实机本就锁腰）；
  3. license **非 NC**（MIT/Apache/BSD 优先）；
  4. 训练框架 Isaac Lab / MuJoCo（Isaac Gym Preview 4 已弃用 = 减分）；
  5. 部署 unitree_sdk2 直连或 ONNX 可剥离。
- 本地栈事实（**2026-09-04 更正版**）：Unitree G1 **29-DoF**（`assets/robots/unitree_g1/g1_29dof.xml`；变体 +OpenNeck 2DoF 颈）+ **Inspire RH56E2×2 五指欠驱动手（每手 6 主动 DoF）**，手走独立 Modbus preset-grasp 链（Teleopit→DDS→driver），**不依赖策略的手指输出**。指令面 BSI→DDS 12 点 twist cmd_vel；上半身 Pico tracker×2+头 → 合成上身关节目标（含颈）。部署 Jetson Orin NX / Python 3.10 / DDS。自研 train_mimic（mjlab+rsl_rl，track_g1.onnx）与 velocity_v1（98D obs/29D action，unitree 官方 rl 库血统）。
- 信源（全部一手）：本地浅克隆 `F:\tmp\wbc-{groot,amo,exbody2,hugwbc,hdmi,h2o,television,bfmzero-deploy,ufo,xrtele}`（2026-09-04 克隆）；GitHub REST API（仓库元数据/树，2026-09-04 抓取）；arXiv 摘要页；HF API（hf-mirror）。
- 标注：【事实】= 源码/文档/API 原文可查；【推导】= 算术/等价变换；【推断】= 分析判断。

---

## 0. 六问速答

| # | 问题 | 裁决 |
|---|---|---|
| 1 | Top1 是谁 | **NVIDIA GEAR-SONIC**（`NVlabs/GR00T-WholeBodyControl`）：3 个 G1 checkpoint（含低延迟遥操作版）、teleop 编码模式输入=**未来速度指令 + VR 三点（头+双手）位姿**、代码 Apache-2.0 + 权重 NVIDIA Open Model License（非 NC）、Isaac Lab 2.3.2 训练 + Bones-SEED 288h G1 数据集、**Jetson Orin/JetPack6 官方部署路径**、最后 push 2026-09-03（昨天）【事实，见 §2.1】 |
| 2 | Top2 是谁 | **AMO**（`OpenTeleVision/AMO`，RSS 2025 UCSD）：接口=**vx/vy/yaw + 高度 + 躯干姿态 + 手臂 8 关节目标**（臂直发 PD + 策略据臂姿调平衡）——契约形态与本项目几乎逐字相同；Apache-2.0；jit 权重随仓。短板：23-DoF 变体（无腕）、仅 MuJoCo sim2sim 脚本、无真机部署/训练代码【事实，见 §2.2】 |
| 3 | 契约差距最大项 | 上身输入形式：SONIC teleop 模式收**笛卡尔三点位姿**（我们可从合成关节目标做 FK，或直接透传 Pico 原生头/手位姿——本地已有）；AMO 收**关节目标**但只有 8 臂关节（无腕无颈，腕/颈需像臂一样旁路直发）。两者都**假设腰可动**（SONIC 29-DoF 含腰 3、AMO 输出含腰 3），实机锁腰=分布外但可控（腰部指令钳 0 + 参考中抑制躯干转腰）【事实+推断，见 §2.1/§2.2/§4】 |
| 4 | 手部 | 两候选的策略面都**不含手指**；SONIC deploy 模型用 Unitree 橡胶手 STL（碰撞 geom density=0 视觉件），AMO 同款橡胶手零质量——**换 RH56E2（每手约 0.5kg 级腕端质量）是可仿真的域差项**，无 Dex-3/LEAP 惯量绑定，利好【事实+推断，见 §4.3】 |
| 5 | 用户记忆线索勘误 | **GrASPE 不存在**（GitHub/arXiv 全查无此项目，唯一同名是 2022 导航论文）；**ExBody3 不存在**；"Gese et al. arXiv 2502.18953" 记错——Expressive Whole-Body Control 实为 Cheng et al. arXiv 2402.16796【事实，见 §3】 |
| 6 | 与自研关系 | SONIC = train_mimic 的"工业级同范式"（大库运动跟踪）替代候选 + velocity_v1 的 WBC 位替代候选；AMO = 零训练快速试验线；**unitree_rl_lab**（Apache-2.0、velocity_v1 的娘家）= 若走自训混合契约（cmd_vel+上身目标）策略的最佳基座。三线不互斥【推断，见 §5】 |

---

## 1. 候选全景与对比矩阵

矩阵按"活到深挖"的候选列出；淘汰名单见 §3。

| 候选 | 输入契约（引代码） | G1 DoF / checkpoint | License（原文可查） | 训练框架 | 最近活跃 | 部署接口 | 手部接口假设 | 与本地契约的 gap |
|---|---|---|---|---|---|---|---|---|
| **GEAR-SONIC**<br>NVlabs/GR00T-WholeBodyControl | teleop 模式：`command_multi_future_lower_body` + `vr_3point_local_target` + `vr_3point_local_orn_target` + `motion_anchor_ori_b`（`gear_sonic_deploy/policy/release/observation_config_sonic_release.yaml:42-50`）；另有 g1 模式=全身 qpos 未来帧流（`docs/.../zmq.md`：支持"SMPL poses **或 G1 whole-body joint positions** from any external source"） | **G1 29-DoF** ×3 checkpoint：default / low_latency（4 帧 80ms lookahead）/ sonic_v1_1（航向归一+腕增强）；encoder+decoder ONNX + PyTorch + 观测 yaml 全放 HF `nvidia/GEAR-SONIC`（HF API 2026-09-04 核实，lastModified 2026-08-26）【事实】 | 代码 **Apache-2.0**，权重 **NVIDIA Open Model License**（`LICENSE` DUAL LICENSE NOTICE 节）【事实】 | Isaac Lab 2.3.2（README badge）；训练代码+finetune 配方开源；Bones-SEED 142k/288h G1 数据（HF bones-studio/seed） | push **2026-09-03**，3516 stars，267+ PR | C++/TensorRT，vendored unitree_sdk2（`gear_sonic_deploy/thirdparty/unitree_sdk2`），**G1 板载 Orin/JetPack6 官方路径**（`docs/.../installation_deploy.md`）；ZMQ 协议可整体绕开其 PICO 栈；ONNX 亦可剥离自建 harness | 策略不含手指；橡胶手 STL；Trigger 抓握走流协议 `left/right_hand_joints` 字段——可弃用，改我们的 Modbus 链 | 上身=笛卡尔三点（需 FK 或透传 Pico 原生头/手）；腰 3-DoF 在策略输出内（实机锁腰=钳 0 域差）；TensorRT 栈偏重，或用 ONNX+onnxruntime 自建 |
| **AMO**<br>OpenTeleVision/AMO | `commands[8]` = [vx, yaw, vy, height_delta, torso_yaw, torso_pitch, torso_roll, arm_toggle]（`play_amo.py:54-101`）；adapter 输入 [height, 躯干三姿态, 臂 qpos×8]→15 维步态风格特征（`play_amo.py:246-257`）；**臂关节直发 PD、策略不控臂但看臂**（`play_amo.py:317-318`） | **G1 23-DoF**（12 腿+3 腰+8 臂，`play_amo.py:124-146`；`g1.xml` 恰 23 joint）；**jit 权重随仓**：`amo_jit.pt`+`adapter_jit.pt`+`adapter_norm_stats.pt`【事实】 | **Apache-2.0**（`LICENSE` © 2025 Li/Cheng/Huang/Wang）【事实】 | 论文 RSS 2025（arXiv 2505.03738）；**仓库无训练代码** | push 2025-11-19，379 stars | `play_amo.py` MuJoCo sim2sim + 键盘交互；无真机代码、无 onnx（torch.jit） | 橡胶手 density=0 零质量（`g1.xml:189-190`）——换 RH56E2 即腕端增重 | 23-DoF 无腕无颈（腕/颈/额外 6 臂自由度需仿其臂处理=旁路直发 PD+可选入 obs？obs 维度固定不可加，只能旁路）；腰在策略输出内（同上钳 0）；yaw 为 heading 目标式非角速度；含步态相位钟（`gait_cycle`，`play_amo.py:200-201`） |
| **unitree_rl_lab**<br>unitreerobotics/unitree_rl_lab | velocity 任务 obs = `base_velocity` 命令 + 关节状态 + last_action（`source/.../locomotion/robots/g1/29dof/velocity_env_cfg.py:199-203`），**无上身指令**，臂靠 `joint_deviation_arms` 奖励拉回默认（:262）；mimic 任务 = BVH 全身参考跟踪 | **G1 29-DoF** 现成 ONNX ×3：`deploy/robots/g1_29dof/config/policy/velocity/v0/exported/policy.onnx` + `mimic/{dance_102,gangnam_style}/exported/policy.onnx`（随仓）【事实】 | **Apache-2.0**（根 `LICENCE`）【事实】 | Isaac Lab（官方继任栈） | push **2026-05-25**，1319 stars | C++ deploy（`deploy/robots/g1_29dof`，State_RLBase/State_Mimic）+ MuJoCo sim2sim；DDS 直连 | 无手（纯本体） | velocity 版不含上身控制（=velocity_v1 现状）；mimic 版是固定曲目全身跟踪。**混合契约（cmd_vel+上身目标）需在此基座上自训** |
| **HugWBC**<br>InternRobotics/HugWBC | commands = [lin_vel_x, lin_vel_y, ang_vel_yaw, …, 高度(±, idx 7)] + 上身干预（`legged_gym/envs/h1/h1.py:615-617, 338`；任务 `h1int`=h1interrupt）——**论文层面契约最像**（速度+上身关节目标+高度，上身干预实验齐） | **H1 专用**（`resources/robots/h1`、`envs/h1`，全仓无 G1 代码）；**无 checkpoint 发布**【事实】 | legged_gym/LICENSE = ETH/NVIDIA BSD-3 系（rsl_rl 谱系） | Isaac Gym Preview 4 + py3.8（README） | push 2025-08-02，166 stars | sim2sim/sim2real 引 unitree_sdk2_python（README） | 无手 | 机器人不对（H1→G1 全套重做）+ 无权重 + IG P4。第三方 G1 移植存在（`Marco-Yang/HugWBC`，0 star 无 license，2026-03）证明可移植但无成品 |
| **ExBody2**<br>edpsw/exbody2 | 部分可观测运动跟踪（论文：稀疏上身信号+扰动训练，arXiv 2412.13196）；仓库只到训练/回放 | **G1 29-DoF** 训练代码；**Release 三项全未勾选**："Release the example policy / complete training pipeline / deployment code"（README §Release）→ **无 checkpoint 无部署**【事实】 | **Apache-2.0**（`LICENSE`） | Isaac Gym Preview 4 + py3.8 | push 2025-06-11，67 stars | 无 | 无手 | 方法论是 ExBody 系核心（众多后续的地基），但开源完成度低；作为配方参考而非即用品 |
| **HOVER**<br>NVlabs/HOVER | 掩码蒸馏多模式（omnih2o 三点 / humanplus / 上身关节+速度模式族，`README.md:195-222` distill_mask_modes） | **H1 专用**（`retarget_h1.sh`、部署 wrapper "currently only supports the Unitree H1"，README:364-376）；README 明言 "**there is no provided teacher policy in the repo**"（:150）【事实】 | **Apache-2.0**（`LICENCE`） | Isaac Lab | push 2025-07-30，756 stars | mujoco/isaac wrapper + H1 hw wrapper | 无手 | 无公开权重 + H1；G1 移植=换资产+重训。作为 SONIC 的"前辈"读其模式设计即可 |
| **UFO / BFM-Zero**<br>Roboparty/UFO · LeCAR-Lab/BFM-Zero | **z 潜变量（行为提示）驱动**：obs=纯本体（ang_vel/gravity/dof_pos/dof_vel/prev_actions，`deploy 分支 rl_policy/observations/bfm_zero.py`）+ 外部算出的 latent z（tracking_inference 从参考运动提取） | **G1 29-DoF**（`config/robot/g1.yaml`、`data/robots/g1/g1_29dof_freebase.xml`）；checkpoint 在 HF `LeCAR-Lab/BFM-Zero`（`download_hf_model.py`）【事实】 | deploy 分支 `LICENSE` = **CC BY-NC 4.0**（UFO 同）——**NC 标红**，与 HOMIE 同病；内部科研或可容忍（须法务/导师确认，标注不确定） | BFM-Zero：Isaac Sim **或 MuJoCo**；**UFO：MJLab**（与本地 train_mimic 同栈！）+ py3.10 | UFO push **2026-09-03**，255 stars；BFM-Zero push 2026-07-15，774 stars | g1_interface（EGalahad/unitree_sdk2 分支）+ CycloneDDS + Jetson py3.10；teleop = PICO/XRobot retarget → 工作站实时编 z → ZMQ 下发（deploy README"teleop sim2real"节）【事实】 | 无手（freebase 模型无手指） | **接口范式不同**：无 cmd_vel、无上身目标通道——意图全编进 z；腰自由（未锁）；且 NC license。作为 **MJLab 训练参照系**价值大于即用价值 |
| **HDMI**<br>LeCAR-Lab/HDMI | 人体视频→全身运动→交互技能跟踪（motion.npz 全身参考，`README.md` Data Preparation 节） | G1 任务（`task=G1/hdmi/move_suitcase`）；无公开 checkpoint（权重走私有 wandb run）【事实】 | **无 LICENSE 文件**（GitHub API license=None）= 默认保留所有权利，**标红** | Isaac Sim 4.5 + Isaac Lab v2.2.0 + py3.10（现代栈） | push 2026-01-17，654 stars | sim2real 另仓 `EGalahad/sim2real` | 无手 | 视频驱动全交互技能，与 cmd_vel 契约不符；作为"Isaac Lab 现代化 train_mimic"参照 |

---

## 2. 深挖：Top 候选的证据链

### 2.1 GEAR-SONIC（推荐 Top1）

**是什么**【事实】：NVIDIA GEAR 组（Zhengyi Luo 等，PHC/ASE/BeyondMimic 谱系）的行为基础模型线，论文 *"SONIC: Supersizing Motion Tracking for Natural Humanoid Whole-Body Control"*（arXiv 2511.07820）。仓 `NVlabs/GR00T-WholeBodyControl`（创建 2025-11-05，push 2026-09-03，3516 stars）三合一：**GEAR-SONIC**（本节）、**Decoupled WBC**（GR00T N1.5/1.6 用的 RL 下半身 + IK 上半身，`decoupled_wbc/`，其 G1 资产表甚至列有 `g1_29dof_lock_waist` 变体——`decoupled_wbc/sim2mujoco/resources/robots/g1/README.md:14`）、**MotionBricks**（生成式动作预览）。

**输入张量**（teleop 编码模式，`gear_sonic_deploy/policy/release/observation_config_sonic_release.yaml`）【事实】：
- tokenizer obs（历史窗口）：`his_base_angular_velocity/body_joint_positions/body_joint_velocities/last_actions/gravity_dir` 各 `10frame_step1`；
- encoder 输入 **1751 维**（1 encoder_index + 1750），64 维 latent token，控制器 50Hz（yaml 头注 + README Model Card："produce 64-dimensional latent motion tokens, run the controller at 50 Hz"）；
- 三编码模式：`g1`（全身关节未来帧）/ `teleop`（**下半身未来速度指令 + VR 三点位姿**）/ `smpl`（SMPL 关节未来帧+腕）。
- **对外接口是 ZMQ**：`--input-type zmq` 支持"SMPL poses 或 **G1 全身关节位置 qpos** from any external source"，且明示 *"You can write your own motion capture retargeting pipeline… No PICO hardware is needed"*（`docs/source/tutorials/zmq.md` Tip 节）——**这就是 Teleopit 的接入缝**：我们不用它的 PICO 栈，自写 ZMQ publisher 喂 {速度指令/三点位姿 或 合成 qpos}，策略输出经其 C++ DDS（vendored unitree_sdk2）下发。

**checkpoint 现状**【事实】：HF `nvidia/GEAR-SONIC`（license: other=NVIDIA Open Model License）三变体：default（10 帧 200ms lookahead）、`low_latency/`（4 帧 80ms，专为遥操作响应）、`sonic_v1_1/`（机器人航向归一 + 腕位姿增强，配 `--motor-kp-scale 4,10=1.5` 踝增益调参，README News 2026-08-31）。编码器/解码器 ONNX + PyTorch `last.pt` + 观测 yaml 齐备（HF API 文件列表核实）。

**部署面**【事实】：`docs/source/getting_started/installation_deploy.md`："Jetson / G1 onboard Orin — 10.7 (required; requires JetPack 6)"，附 Orin NX 刷机指南（`docs/source/references/jetpack6.md` — "flash the Orin NX on the Unitree G1"），Docker ROS2 Humble aarch64。遥操作文档（`docs/source/tutorials/vr_wholebody_teleop.md`）为 **PICO 头显+手柄+脚追** 的全身遥操作，含急停键约定（`O`/`A+B+X+Y`）。

**风险/gap**【推断】：
1. 上身契约形式=稀疏三点笛卡尔。两条转换路径：(a) 合成器输出关节目标 → G1 模型 FK 得头/手位姿（精确、复用现有合成）；(b) 直接透传 Pico 原生头/手位姿（更快，但绕开我们的关节空间合成与颈）。倾向 (a)，FK 是薄层。
2. 29-DoF 含腰：参考动作中的躯干转腰在锁腰实机上不可实现——retarget 时抑制腰 yaw（合成器已有关节空间控制权）或接受跟踪误差。SONIC 以鲁棒性为卖点（O.O.D. 姿态恢复），锁腰属温和域差，但**必须 sim2sim 先验证**（其 `g1_29dof_lock_waist.xml` 场景资产在 decoupled_wbc 里就有，可拼装仿真）。
3. TensorRT C++ 栈与本地 Python/DDS 现有 harness 不同——但 ZMQ 输入 + ONNX 可剥离给了"Python 自建 harness"退路；50Hz 小模型在 Orin NX 上无算力压力。
4. NVIDIA Open Model License：允许商用但要求 attribution + 遵守 Trustworthy AI 条款（`LICENSE` Part 2）——比 CC BY-NC 干净得多，产品化路径无 NC 污染，但法务过目一次。

### 2.2 AMO（推荐 Top2）

**是什么**【事实】：`OpenTeleVision/AMO`（RSS 2025，arXiv 2505.03738，UCSD Xiaolong Wang 组——TeleVision/HOMIE 作者群的姊妹作）。仓库极简：`play_amo.py` + `amo_jit.pt`/`adapter_jit.pt`/`adapter_norm_stats.pt` + `g1.xml`，即装即玩 MuJoCo。

**输入契约**（`play_amo.py` 源码级）【事实】：
- `commands[8]`：`[0]`=Vx、`[1]`=yaw（**heading 目标**，代码算 dyaw 进 obs，`play_amo.py:235-239`）、`[2]`=Vy、`[3]`=高度偏移（0.75 基准）、`[4..6]`=躯干 yaw/pitch/roll、`[7]`=臂控制开关；
- **臂 = 关节空间目标直发 PD**（`pd_target[15:] = arm_action` 带斜坡混合，`play_amo.py:317-319`），策略不输出臂动作但 obs 里看臂关节角（`dof_pos[15:]` 入 obs_prop/obs_demo）——**"策略管平衡、臂姿进观测"正是本项目想要的控制分配**；
- adapter：[高度, 躯干姿态×3, 臂 qpos×8] → 15 维"步态风格"特征（从动作库学得，让步态风格与臂姿相容）；
- obs 总量：obs_prop 93D + obs_demo 17D + obs_priv 3D + 历史 93×10=930D，另传 extra_hist 93×25=2325D 作第二输入（`play_amo.py:180-208, 287, 300`）。

**短板**【事实+推断】：23-DoF 变体（`g1.xml` 恰 23 joint；臂每侧 4 关节，无腕）；腰 3-DoF 在策略 15 维输出里（锁腰机=钳 0 域差，且其躯干 yaw 指令路径将失效——需钉 0）；无真机部署代码（sim2sim 脚本可参考其 PD 增益/力矩限幅表 `play_amo.py:110-139`）；无训练代码；最后 push 2025-11-19。**定位：一周内可跑通 sim2sim 的零训练 PoC + 控制分配范式样板**。README 自带警告勿轻易上真机（Alert & Disclaimer 节）。

### 2.3 unitree_rl_lab（基座事实，非新候选）

【事实】官方 Isaac Lab RL 库（Apache-2.0，push 2026-05-25）。`deploy/robots/g1_29dof/` 内有现成 velocity v0 ONNX 与 mimic 舞蹈 ONNX、C++ State_RLBase/State_Mimic、MuJoCo sim2sim。G1 29dof velocity 任务观测无上身指令、臂被 `joint_deviation_arms` 奖励拉回默认（`velocity_env_cfg.py:262`）——即 **velocity_v1 只解决 locomotion**。mimic 任务 = BVH 全身跟踪（与 train_mimic 同范式）。
【推断】若结论是"自训混合契约策略"，此处是 license/框架/部署三优的基座：把上身目标加入 obs（照 HugWBC h1int / AMO 配方）+ 保留 velocity 命令头，即得本项目契约的原生策略；deploy harness 直接复用。

### 2.4 UFO/BFM-Zero（同栈参照系）

【事实】LeCAR BFM-Zero（arXiv 2511.04131）：G1 29-DoF z 潜变量策略，HF 有 checkpoint，Isaac Sim/MuJoCo 双仿真；Roboparty UFO（2026-07 新仓，push 2026-09-03）是其 **MJLab** 重写 + "robot-aware motion import + real-world teleoperation"，deploy 分支为 G1 真机/PICO 遥操作运行时（CycloneDDS、Jetson py3.10、ZMQ、XRoboToolkit retarget）。**License 均 CC BY-NC 4.0**（两仓 deploy LICENSE 原文）。
【推断】接口是"全身 retarget→实时编 z"，无 cmd_vel/上身目标通道——契约不匹配；但 MJLab 训练栈与 train_mimic 同款，其分布式训练与真机部署工程可作为 train_mimic 走向真机的**参照实现**（读代码不受 NC 约束，抄代码才有——同 openhomie 报告 §4.1 口径）。

---

## 3. 淘汰名单（一行理由）

| 候选 | 淘汰理由（一手来源） |
|---|---|
| **GrASPE**（用户线索） | **查无此项目**：GitHub 全域搜索零命中（GuoPingPan 名下 72 仓无此名），arXiv 唯一 GrASPE=2022 UMD 导航论文（arXiv 2209.05722）——记忆线索失效【事实】 |
| **ExBody3**（用户线索） | **不存在**：arXiv/GitHub/project page 全查无（2026-09-04）；ExBody 系到 ExBody2（arXiv 2412.13196）为止【事实】 |
| **"Gese et al. 2502.18953"**（用户线索） | **编号记错**：2502.18953 是 RISC-V SoC 硬件论文；Expressive Whole-Body Control 实为 **Cheng et al., arXiv 2402.16796**（仓 `chengxuxin/expressive-humanoid`，Apache-2.0，G1，IG P4，无 checkpoint，push 2025-03-30）——本身也因"无权重+IG P4"出局【事实】 |
| **HumanPlus**（MarkFzp/humanplus） | **无 LICENSE 文件**（API license=None=保留所有权利）+ H1 机器人 + 死仓（push 2024-07-01）【事实】 |
| **OmniH2O / OmniH2O-2** | OmniH2O：**CC BY-NC 4.0** + Isaac Gym P4 + H1 + push 2025-02-21（`LeCAR-Lab/human2humanoid` LICENSE-CC-BY-NC-4.0.md + README）；OmniH2O-2：**无公开仓**（GitHub 搜索零命中）【事实】 |
| **OpenWBC**（jiachengliu3/OpenWBC） | 是 **AVP+OpenHomie 组合 harness**（README："using …avp_teleoperate to control upper body and the **OpenHomie** algorithm to control lower body"），顶层无 LICENSE、内嵌 OpenHomie（NC）——策略核心仍是 HOMIE，承其 license 与腰锁 27-DoF 全部旧账【事实】 |
| **Television**（OpenTeleVision/TeleVision） | Apache-2.0 但定位=手部/视觉遥操作 harness（Isaac Gym 手部 sim），G1 全身策略不在仓内；push 2024-09-27【事实】 |
| **xr_teleoperate**（unitreerobotics 官方） | Apache-2.0、支持 AVP/Quest/PICO + Inspire 手（DFX_inspire_service），但**是输入侧 harness**：行走走 G1 原生、臂走 IK——无 WBC 策略可摘（README）；作为"官方 cmd_vel+IK"路线的参照保留【事实】 |
| **HDMI**（LeCAR-Lab/HDMI） | **无 LICENSE 文件** + 视频驱动全交互跟踪范式（无 cmd_vel 面）+ 无公开 checkpoint——仅作 Isaac Lab 现代训练栈参照【事实】 |
| **FAST**（arXiv 2602.11929，北大） | 论文在（2026-02，预训练+残差快适配），**无代码/权重放出**（arXiv 页 Links to Code 空）【事实】 |
| **AnyBody**（arXiv 2606.29209，Notre Dame/HKU） | 任意关键点子集驱动——概念上与契约相容（2026-06），**无代码放出**；跟踪其开源动态【事实】 |
| **JAEGER**（arXiv 2505.06584） | GitHub 无官方仓（搜索零命中）【事实】 |
| **HugWBC G1 民间移植**（Marco-Yang/HugWBC） | 0 star、无 license、个人实验性质，不作为 checkpoint 来源【事实】 |

---

## 4. 横向风险与适配层清单（Top1/Top2 通用）

1. **锁腰域差**（两候选都假设腰可动）【事实+推断】：SONIC 29-DoF 与 AMO 23-DoF 的策略输出都含腰 3 关节。实机 mode≈6 锁腰时：腰部电机指令无效、obs 中腰读数恒为默认值——训练分布里"腰保持默认"是常见子集（站立/行走时腰摆动小），属温和域差；适配动作 = 参考合成时钳腰目标为 0 + sim2sim 用 weld 腰模型验证。注意 AMO 的躯干 yaw 指令（commands[4]）物理上由腰实现，锁腰机必须钉 0。
2. **上身通道形态**【推断】：SONIC 需头+双手**笛卡尔**位姿 → 适配层 = 合成关节目标上的 FK（G1 URDF/XML 上 30 行级）；AMO 直收 8 臂关节角（切片即可）。腕（6）+颈（2）两候选都不管 → 与 AMO 的臂同法：旁路直发 PD（可复用 openhomie 报告 §2.4 记录的 Kp/Kd 表思路，但代码自写）。
3. **手部质量/惯量失配**【事实+推断】：SONIC deploy 模型 = Unitree 橡胶手 STL（SONIC xml 中碰撞件 density=0 视觉件 + 一处默认密度物理 geom；AMO 全零质量）；无 Dex-3/LEAP 质量绑定。换 RH56E2（含支架每手约 0.4–0.7kg 腕端集中质量）→ 域差中等、方向保守（加重末端略降稳定裕度）：**先在 MuJoCo 中给腕端加等效质量块做 sim2sim 对比**再上真机；必要时用其 finetune 配方微调（SONIC 支持 checkpoint finetune）。
4. **指令语义**【事实】：BSI 12 点 twist → SONIC 的 `command_multi_future_lower_body`（未来帧缓冲，低延迟版 4 帧 80ms）或 AMO 的 heading 式 yaw；两处都需小转换层，无本质障碍。急停：SONIC 栈有键盘/PICO 急停约定，我们的 BSI L1/L2 分层急停需在外层持有 DDS 通道优先权【推断】。
5. **部署算力/中间件**【事实+推断】：SONIC 官方路径=C++/TensorRT+JetPack6（**本地 Orin NX 若仍是 JetPack 5 需刷机**——项内风险单列）；退路 = ONNX + onnxruntime 自建 Python harness 接现有 DDS 桥（encoder+decoder 均有 ONNX）。AMO = torch.jit，Python 直跑即可。

---

## 5. 排名、推荐与自研关系

### 排名

| 名次 | 候选 | 一句话 |
|---|---|---|
| **1** | **GEAR-SONIC**（GR00T-WholeBodyControl） | 契约覆盖（teleop=速度+三点；zmq=关节流）、3 个 G1 checkpoint、非 NC 双 license、Isaac Lab+288h 数据+finetune、Orin 官方部署路径、昨日还在更新——**唯一"三五年内不会弃更"级别的选项** |
| **2** | **AMO** | 接口形态与本项目契约逐字吻合（速度+躯干+臂关节直发+策略看臂姿）、Apache-2.0、权重随仓——**零训练 PoC 与控制分配样板**；受限于 23-DoF/无腕/无部署代码 |
| **3** | **unitree_rl_lab（自训路线）** | velocity_v1 娘家，Apache-2.0 + Isaac Lab + C++ deploy 齐备——若决定自训混合契约策略，这是最短路径基座 |
| 4 | UFO/BFM-Zero | G1 权重+MJLab 同栈+PICO 遥操作，但 z 接口不符 + CC BY-NC——参照系 |
| 5 | HugWBC / ExBody2 / HOVER | 论文契约相关但 H1/无权重/IG P4，读配方不取代码 |

### 推荐

- **Top1 = GEAR-SONIC**：以 `zmq_manager`/`zmq` 输入面为接入缝——自写 ZMQ publisher 把 BSI cmd_vel（转未来指令缓冲）+ 合成上身目标的 FK 三点位姿（或合成 qpos 全身流）喂给现成 C++ 部署栈；或剥 ONNX 进自建 harness。先 sim2sim（含锁腰模型 + RH56E2 等效质量）再上真机；真机会话与 BSI 急停的通道优先权需按 openhomie 报告 §2.4 的"控制面互斥"教训设计。
- **Top2 = AMO**：一周级 sim2sim 即可验证"臂直发+策略平衡"在本项目参考轨迹下是否成立，为 SONIC/自训线提供对照与下限；23-DoF 差异使其更可能止步于实验线。
- **并行保留自训线**（train_mimic/velocity_v1 的延长线）：velocity_v1 = SONIC/AMO 要替换的对象；train_mimic（mjlab 全身跟踪）与 SONIC 的 G1 模式是同范式——SONIC 相当于"288h 数据+基础模型化+部署齐装"的 train_mimic 工业版，二者关系是**替代（部署）+ 基线（训练评估）**；若 OpenNeck/O6/RH56E2 特化需求变强（候选都不认识我们的颈与手），回到 unitree_rl_lab 基座自训混合契约策略，SONIC 配方（Bones-SEED + finetune）与 AMO 分配范式直接反哺。

---

## 附：本研究引用一览

- 本地克隆（`F:\tmp\`，depth-1，2026-09-04）：`wbc-groot`（GR00T-WholeBodyControl）、`wbc-amo`、`wbc-exbody2`（edpsw/exbody2）、`wbc-hugwbc`、`wbc-hdmi`、`wbc-h2o`（LeCAR human2humanoid）、`wbc-television`、`wbc-bfmzero-deploy`（BFM-Zero deploy 分支）、`wbc-ufo`、`wbc-xrtele`
- 关键文件：`wbc-groot/gear_sonic_deploy/policy/release/observation_config_sonic_release.yaml`、`wbc-groot/docs/source/tutorials/{zmq.md,vr_wholebody_teleop.md,keyboard.md}`、`wbc-groot/docs/source/getting_started/installation_deploy.md`、`wbc-groot/LICENSE`、`wbc-groot/decoupled_wbc/sim2mujoco/resources/robots/g1/README.md`；`wbc-amo/play_amo.py`、`wbc-amo/LICENSE`、`wbc-amo/g1.xml`；unitree_rl_lab 远程树（`deploy/robots/g1_29dof/…policy.onnx`、`source/.../g1/29dof/velocity_env_cfg.py`、根 `LICENCE`）；`wbc-hugwbc/legged_gym/envs/h1/h1.py`；`wbc-h2o/LICENSE-CC-BY-NC-4.0.md`；`wbc-bfmzero-deploy/rl_policy/observations/bfm_zero.py`、`wbc-bfmzero-deploy/config/policy/motivo_newG1.yaml`、`wbc-bfmzero-deploy/LICENSE`；`wbc-ufo/LICENSE`、UFO deploy README；`wbc-xrtele/LICENSE`
- GitHub API（2026-09-04）：上述各仓库元数据（created/pushed/stars/license）+ 搜索（GrASPE/omnih2o2/exbody/television/hugwbc/jaeger/anybody 零命中记录）
- arXiv：2511.07820（SONIC）、2505.03738（AMO）、2412.13196（ExBody2）、2502.03206（HugWBC）、2402.16796（Expressive WBC）、2410.21229（HOVER）、2511.04131（BFM-Zero）、2509.16757（HDMI）、2602.11929（FAST）、2606.29209（AnyBody）、2505.06584（JAEGER）、2209.05722（同名导航 GrASPE）
- HF API（hf-mirror，2026-09-04）：`nvidia/GEAR-SONIC`（文件表+lastModified 2026-08-26）、`LeCAR-Lab/BFM-Zero`
- 本地锚点：`reference/openhomie-integration-feasibility.md`（HOMIE 基线与控制面互斥教训）
