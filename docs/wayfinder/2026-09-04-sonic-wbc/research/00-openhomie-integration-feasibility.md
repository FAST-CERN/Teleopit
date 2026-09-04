# OpenHomie 接入 Teleopit 可行性研究

- 日期：2026-09-04（**研究性质：预研，未绑定 wayfinder 图**）
- 对象：https://github.com/InternRobotics/OpenHomie （commit `cefcd85`，2025-09-01）
- 信源（全部一手）：
  - 本地浅克隆 `F:\tmp\openhomie-study`（`git clone --depth 1`，仓库外临时目录，研究后保留）：README ×4、`HomieDeploy/`（C++ + Python 源码、LCM 消息定义、`deploy.onnx` 1.8MB）、`HomieRL/`、`MujocoDeploy/`
  - GitHub REST API：仓库元数据 / commits / issues（含作者回复）/ org 信息（2026-09-04 抓取）
  - arXiv:2502.13013 v2（2025-04-28）摘要页 + HTML 全文（附表数据）
- 标注：【事实】= 源码/文档/API 原文可查；【推导】= 由前者算术/等价变换；【推断】= 分析判断。
- 本地侧锚点：`docs/knowledge/architecture.md`、`docs/knowledge/repo-guide.md`（只读引用）。

---

## 0. 五问速答

| # | 问题 | 裁决 |
|---|---|---|
| 1 | 是什么 | 上海 AI Lab（InternRobotics，前身 OpenRobotLab）+ CUHK 的 **HOMIE** 论文官方实现（arXiv:2502.13013）。**操作员输入是"同构外骨骼臂 + 传感手套 + 踏板"的座舱，不是 VR**；机器人侧 = Unitree G1 + Dex-3 灵巧手的 RL 全身策略部署。License **CC BY-NC-SA 4.0**（代码），非商业。**仓库 12 个月未更新（最后 push 2025-09-01），0 release，近期 issue 无人回复**【事实，见 §1】 |
| 2 | 架构分层 | 操作员设备=外骨骼（$430, 0.26kHz）+手套（$30/对, 0.3kHz, 15+ DoF Hall）+踏板（$20, 0.5kHz），**无任何 VR/Pico/Quest/VRAN 成分**；上位机栈=Python+C++，**中间件是 LCM（非 ROS）**；重定向=**无 IK，关节空间直读直发**（同构设计的核心卖点）；下行=unitree_sdk2 的 DDS `rt/lowcmd`（29 电机低位位置 PD）+ `rt/dex3/*/cmd`（手）；FPV=**D455 640×480@30 JPEG over 裸 TCP**（另两台 D435 装在小臂）【事实，见 §2】 |
| 3 | 接入面 | A 整体替换操作员侧=**不可行也无价值**（要自建外骨骼硬件、公开仓还缺座舱侧代码）；B 保留 pico-bridge 采机器人侧栈=技术上自洽但**控制面与 BSI velocity 模式互斥**、deploy.onnx 只支持腰锁 27-DoF G1、等于换掉自研策略，中→大；C 摘组件=**推荐**（低位控制参考 + 训练配方思想 + MuJoCo 沙盒），小【事实+推断，见 §3】 |
| 4 | 风险 | license 三重问题（NC 商业禁用 / SA 传染 / CC 授权代码本身法律上有模糊性）；维护停滞（org 活着但项目弃更，作者明示先升级设备再说）；Isaac Gym Preview 4 已弃用 → **重训门槛高**；与 DDS 架构的冲突不在中间件层（LCM 多播可与 DDS 共存）而在**控制权层**（低位 rt/lowcmd vs 高位 cmd_vel 二选一）【事实+推断，见 §4】 |
| 5 | 结论 | **不接入主链路**。推荐路径 C：把 `g1_control.cpp` 作 G1 低位控制的参考实现、把"上身姿态课程 + 高度跟踪奖励"思想喂给 train_mimic（若 squat/高度控制成为目标）、可选 MujocoDeploy 做零硬件风险的政策沙盒。工作量分级：C=小，B=中~大，A=大【推断，见 §5】 |

---

## 1. OpenHomie 是什么

【事实】仓库自述为论文 *"HOMIE: Humanoid Loco-Manipulation with Isomorphic Exoskeleton Cockpit"* 的官方实现（`OpenHomie/README.md`）。论文：**arXiv:2502.13013**（v1 2025-02-18，v2 2025-04-28），作者 Qingwei Ben*、Feiyu Jia*、Jia Zeng、Junting Dong、Dahua Lin、Jiangmiao Pang，单位 **Shanghai AI Laboratory & CUHK**（README 作者栏；arXiv 摘要页）。

【事实】归属机构：GitHub org **InternRobotics**，自述 *"Building inclusive infrastructure for Embodied AI, from Shanghai AI Lab"*（API `users/InternRobotics`），即上海 AI Lab 具身智能中心（庞江淼团队）的组织更名。证据链：仓内 merge commit 引用旧地址 `github.com:OpenRobotLab/OpenHomie`（`git log`），README 安装指令仍写 `git clone https://github.com/OpenRobotLab/Homie.git`（`OpenHomie/README.md:81`）；org 内还并存同内容旧仓 `InternRobotics/Homie`（49 stars，最后 push 2025-03-21，API 搜索）。

【事实】活跃度（GitHub API，2026-09-04 抓取）：

| 指标 | 值 |
|---|---|
| 创建 / 最后 push | 2025-02-19 / **2025-09-01**（距今 12 个月） |
| stars / forks | 609 / 50 |
| releases | **0** |
| issues | 共 22；2026 年两个求助/求图纸 issue（#22 2026-08-26、#20 2026-01-29）**0 回复** |

org 本身活跃（88 仓，2026-09 仍有 push），但 OpenHomie 项目线已停更；作者在 issue #9（2025-02，HF 求 数据集）回复"应先升级设备和控制器"，即团队资源已转向后续工作。README TODO 的"more robots / more terrains"未兑现【事实】。

【事实】License：四个 README 均声明 **CC BY-NC-SA 4.0** 并明示 *"it is strictly forbidden to use it for commercial purposes before asking our team"*；根 `LICENSE` 文件的文本是 **CC BY-NC 4.0**（无 SA 条款）——两处不一致，按更严者（BY-NC-SA）对待。论文 PDF 同为 CC BY-NC-SA 4.0（arXiv license 标注）。仓内 vendored 的 `HomieDeploy/unitree_sdk2` 是 Unitree 官方 SDK，其自带 license 为 **BSD-3-Clause**（`HomieDeploy/unitree_sdk2/LICENSE`），与 HOMIE 自有代码的 CC 条款互相独立。

【事实】支持的机器人：**Unitree G1（29 电机布局：12 腿 + 3 腰 + 14 臂）+ Dex-3 灵巧手** 是唯一有完整部署代码的组合（`HomieDeploy/README.md` 前置条件；`HomieDeploy/unitree_sdk2/g1_control.cpp:38` `G1_NUM_MOTOR=29 // not included 7*2 of two hands`；`hand_control.cpp:38-47` DDS topic `rt/dex3/left|right`）。HomieRL 声称改配置可训其他机器人（README 举 Fourier GR-1 例子）；issue #4 中第三方在 H1-2 上训练成功（作者提供了 H1-2 config）。**关键限制：随仓发布的唯一 checkpoint `deploy.onnx` 只适配腰锁 27-DoF 版 G1**——作者在 issue #18 回复 *"this open-source version was only for 27dof version, and if you unlock the waist, it can't be used directly"*。

【事实】硬件成本（论文表）：外骨骼 $430、手套 $30/对、踏板 $20，合计约 **$500**（摘要称 just $500）。

---

## 2. 架构分层（与 Teleopit 逐层对照）

### 2.1 操作员输入设备

【事实】座舱三件套（论文 §Hardware + README）：

- **同构外骨骼臂** ×2：与 G1 机械同构，关节角直读（0.26kHz，12-bit），$430；
- **传感手套** ×2：Hall 传感器而非舵机，每只 15+ DoF（原理参考 HomunCulus 项目，README 致谢节），0.3kHz，$30/对；
- **踏板**：行走指令源（0.5kHz，270°），解放操作员上身，$20。

**没有 VR 头盔、没有头部跟踪、没有 Pico/Quest/VRAN/streaming SDK 任何成分**。操作员坐在座舱里看屏幕。论文 Table IV：臂指令输出 **263Hz**、手 **293Hz**，座舱 PC 无需 GPU；座舱→机器人每包仅 **128 字节（32 个 float32）**，实测通信延迟约 **16ms**（论文 §C-A）。

【事实】**座舱侧（读外骨骼/手套/踏板并发出指令）的完整代码不在公开仓里**：`HomieDeploy/README.md` NOTE 节写明 *"we only include the g1 policy deployment code of HOMIE. If you want to have access to the full code, please enter the form"*（Google 表单，需真实姓名+机构）；`HomieHardware/README.md` 的结构件/PCB/Keil 工程同样只给表单不给文件。公开的 `g1_gym_deploy/envs/lcm_agent.py` 中外骨骼通路全部被注释（`get_arm_action()`、`arm_action` publish，行 87-88/101-103），佐证公开版是阉割版。

### 2.2 上位机软件栈

【事实】无 ROS。机器人侧中间件是 **LCM**（UDP 多播 `udpm://239.255.76.67:7667?ttl=255`，`g1_gym_deploy/scripts/deploy_policy.py:17`）；对外网络是裸 TCP（论文 §C-A；`d455.py` 为 TCP 客户端）。语言：部署侧 Python（`requirements.txt`: pyrealsense2、numpy、opencv-python、**lcm**、onnxruntime，跑在 G1 板载 Jetson Orin 275 TOPS 上，论文 §C-A）+ C++（unitree_sdk2，CMake 构建 `g1_control` / `hand_control` 两个二进制）。训练侧 HomieRL = **Isaac Gym Preview 4 + Python 3.8 conda**，HIMLoco 代码库（rsl_rl 变体 + `him_ppo.py` 含 `flip_g1_actor_obs` 对称数据增强）。

【事实】Teleopit 对照：Python 3.10（teleopit conda env）、自研 Protocol 管线 + InProcessBus、DDS（BSI bridge）到驱动、train_mimic（rsl-rl + **mjlab**，非 Isaac Gym）。**Python 3.8 vs 3.10、Isaac Gym vs mjlab、LCM vs DDS 三处栈不重叠**（`docs/knowledge/architecture.md` §2/§5）。

### 2.3 身体重定向 / IK

【事实】**HOMIE 没有重定向层**——这正是其设计核心：外骨骼与 G1 同构 → 臂关节角 1:1 直发（README：*"directly set upper-body joint positions from the exoskeleton readings, dispensing with IK"*；论文：*"The exoskeleton, by eliminating the reliance on inverse dynamics, delivers faster and more precise arm control"*）。手指：手套 15 DoF → Dex-3 7 关节，靠每手的关节限位表映射（`hand_control.cpp:18-21` min/maxTorqueLimits 数组）。下肢无重定向：行走由 RL 策略按踏板速度/高度指令生成。

【事实】Teleopit 对照：GMR（自包含 IK）把 Pico/BVH 人形帧重定向为 G1 参考轨迹，TemporalCNN 策略全身跟踪（167D 观测 / 29 关节动作，`docs/knowledge/architecture.md` §1/§3.1）。**两者是同一问题的两个极端：HOMIE 用专用硬件消灭 IK，Teleopit 用通用 VR + IK 消灭专用硬件。**

### 2.4 下行控制接口（逐 topic，源码级）

【事实】G1 机器人侧三个进程（`HomieDeploy/README.md` 步骤 A-D + 源码）：

```
外骨骼/手套/踏板(座舱PC, 代码不公开)
   │ TCP WiFi, 128B/包, ~16ms          (论文 §C-A)
   ▼
[LCM 多播域] ── arm_action(14 double) ──────────► g1_control (C++)
   pd_plustau_targets(29+29 double+int64) ◄──── deploy_policy.py (ONNX 50Hz)
   pedal_command(4 double: vx,vy,yaw,height) ──► (cheetah_state_estimator.py:82,94)
   hand_action(14 double) ─────────────────────► hand_control (C++)
   ▼ DDS (unitree_sdk2 / CycloneDDS)
   rt/lowcmd / rt/lowstate   (unitree_hg LowCmd_/LowState_, 29 电机, CRC32 校验)
   rt/dex3/{left,right}/cmd + /state
   rt/wirelesscontroller     (Unitree 遥控器, 启停用)
```

- 控制分配：策略输出只管 **腿+腰**（`pd_plustau_targets.q_des[0:15]`），**双臂 14 关节由 `arm_action` 旁路直发**（`g1_control.cpp` `Control()`，行 401-413，固定 Kp/Kd 表行 85-100）【事实】。
- 控制线程 `CreateRecurrentThreadEx(..., 5000, ...)` = 5ms → **200Hz**（源码注释写 "[2ms] thus 500hz" 与实际参数不符，注释过期）【事实+推导】。
- 策略 ONNX 50Hz 板载推理，观测 76×6=456D（commands[4]×scale + 角速度 + 重力向量 + 全身关节状态 + 上身动作回显），命令缩放 `[2.0, 2.0, 0.25, 1.0]`（`lcm_agent.py:71`；`MujocoDeploy/g1.yaml`）【事实】。
- 启动流程要求先用遥控器组合键 **L2+A / L2+R2 / L2+A / L2+B 关闭 G1 原生控制进程**（`HomieDeploy/README.md` 部署节），即 HOMIE 完全接管低位、放弃 Unitree 自带行走【事实】。

【事实】Teleopit 对照：现真机走 **DDS 高位 cmd_vel velocity 模式**（BSI bridge → 驱动 → unitree sdk，12 点 twist 共识、双控制器），另有 train_mimic 策略经 unitree SDK 的直接通路（`docs/knowledge/repo-guide.md` `sim2real/unitree_g1.py`）。**HOMIE 的 rt/lowcmd 低位接管与我们的 velocity 高位模式是同一台机器上互斥的控制面**。

### 2.5 FPV 视频方案

【事实】HOMIE：G1 头部 D455 彩色流 **640×480@30fps，OpenCV JPEG（质量 90）打包长度前缀后走裸 TCP** 发到座舱 PC（`HomieDeploy/d455.py`，IP:port 硬编码）；另有 2× D435 装在**小臂**上（论文 §C-A，用于操作/IL 采集，非头显）。论文自述受 TCP 与板载算力限制。操作员在 PC 屏幕上看画面（无立体声、无 HMD）。

【事实】Teleopit 对照：ZED 双目 **SBS 1080p** → Jetson Orin NX **NVENC 硬编** → **aiortc WebRTC**（自研 pacer）→ Pico 4 HMD 沉浸显示，e2e 延迟 ~80-120ms（已收官的 zed-fpv/nvenc/pacer/sbs 系列图）。**HOMIE 视频栈整体落后我们一到两个世代**，无任何可反向吸收的东西。

---

## 3. 接入面分析

### 路径 A：整体采用 OpenHomie 替换操作员侧

- 需要做：填表申请（真实姓名+机构）拿 HomieHardware 结构件/PCB/Keil + 完整座舱代码；自制/采购外骨骼、手套、踏板（~$500 BOM + 装配调试）；为 Pico 操作员换座舱工作流【事实（流程）+推断（工作量）】。
- 丢失：Pico VR 沉浸式 FPV（换成 640×480 屏幕画面）、刚落地的 2×Pico motion tracker 上半身动捕链、WebRTC/NVENC 全部投资、头/手 6DoF 自然交互【推断】。
- 硬件前提：**手指价值要求 Dex-3 手**——我们是 Inspire（Modbus preset grasp），手套 15 DoF 无处可去；HOMIE 的 `hand_control` 是 Dex-3 专用 DDS topic，对 Inspire 无用【事实（topic）+推断（结论）】。
- 依赖冲突：无软件层冲突（整套自带），但等于放弃 Teleopit 全部差异化资产。
- **裁决：不可行也无价值。工作量：大（且被表单门槛卡脖子）。**

### 路径 B：保留 pico-bridge/视频栈，采用其机器人侧重定向/控制栈

- 需要写的适配层（设想图）：`Teleopit 合成端（GMR 输出 q[29]）→ 新增 LCM publisher`：
  - `arm_action` ← `q[15:29]`（14 关节角，GMR 已有此输出，映射是一行切片）；
  - `pedal_command` ← 现有 VELOCITY 模式 cmd (vx, vy, yaw) + 新增高度指令（HOMIE 给我们的新能力：**蹲起/变高度**，cmd[3] 默认 0.74m）；
  - 机器人侧跑 `g1_control` + `deploy_policy.py`（onnxruntime+lcm，板载或同网段 Jetson 均可——LCM 是多播，不挑主机）。
  输入格式转换量本身**小**（一个薄 publisher，~百行级）【事实（接口）+推断（工作量）】。
- 依赖冲突：LCM 多播组与我们的 DDS 互不干扰，可同机共存；**真正的冲突是控制权**——HOMIE 要 rt/lowcmd 低位接管并杀掉 G1 原生控制（= 杀掉我们 velocity 模式的宿主），BSI DDS 桥在该会话必须整体让位；两套系统只能分时切换，不能并存【事实（机制）+推断（结论）】。
- 硬件前提：**本机 G1 必须是腰锁 27-DoF 版**才能直接用 `deploy.onnx`；若腰 3-DoF 解锁则 checkpoint 不可直接用（issue #18 作者原话），重训需 Isaac Gym Preview 4 + py3.8（**Isaac Gym 已被 NVIDIA 标记 Deprecated，官方继任 Isaac Lab 且无同构迁移**，重训门槛实质上升）【事实】。另需核实本机 G1 板载算力（HOMIE 用 275 TOPS Orin 跑 50Hz ONNX；1.8MB 模型本身很轻）【推断】。
- 隐性代价：**等于把我们的 TemporalCNN 全身跟踪策略换成 HOMIE 的腿腰策略**（臂直发）。我们的策略跟踪全身参考；HOMIE 策略只承诺"任意上身姿态下走得稳、蹲得到高度"。换栈后上身精度取决于 GMR 直发的 PD 跟踪（无策略整定），与现行为的差异未知【推断】。
- **裁决：技术自洽的实验路线，但不是工程主线。工作量：中（27-DoF 直配）/ 大（需重训）。**

### 路径 C：只摘个别组件（推荐）

- **C1 低层控制参考**（小）：`g1_control.cpp` 是一份可运行的 G1 29 电机 rt/lowcmd 参考实现——关节索引 enum（含 23/29-DoF 差异注释）、全身 Kp/Kd 表、CRC32 填充、无线遥控接管、急停（rpy>1.6 rad 回标定）。若 Teleopit 未来要低位直控（train_mimic 策略上真机的近路），这份代码 + 我们仓里已有的 `unitree_sdk2_python` submodule 互补。**读它无 license 负担（unitree_sdk2 本体 BSD-3），抄它才有**【事实】。
- **C2 训练配方思想**（中）：上身姿态课程（upper-body pose curriculum）、高度跟踪奖励 r_height/r_knee、对称数据增强 L_sym——三者公式在论文 §Method 与附录，可移植进 train_mimic（rsl-rl + mjlab）。代码栈不同（HIMLoco/Isaac Gym vs mjlab），**移植的是思想不是代码**；若"squat/变高度作业"成为需求，这是现成的方法论【事实+推断】。
- **C3 MuJoCo 沙盒**（小~中）：`MujocoDeploy/mujoco_deploy_g1.py`（mujoco==3.2.3，纯 Python，含 `g1.yaml` 配置）可在零硬件风险下跑 `deploy.onnx` sim2sim。若想验证"我们的 GMR 输出喂 HOMIE 策略"是否成立，这是 B 路径的前置实验台，且完全避开 license 争议之外的硬件风险【事实+推断】。

---

## 4. 风险

1. **License（最大风险，三重）**：
   - **NC**：禁止商业用途（README 明示 forbidden before asking our team）。Teleopit 现为内部科研仓，属 NonCommercial 范畴；但任何未来商业化/产品化路径都会被污染——**引用其代码的文件会永久携带该约束**【事实+推断，商业化判定需导师/法务确认，标注不确定】；
   - **SA**：衍生作品须同 license 分享。把其代码拷进 Teleopit 并在组织内/对外分发衍生版时触发传染【事实（条款）+推断（适用性）】；
   - **CC 授权代码本身**：Creative Commons 官方长期不建议用 CC 协议授权软件（缺少专利/源码特定条款），法律边界有模糊性；且仓内 LICENSE（BY-NC）与 README（BY-NC-SA）自相矛盾，采用前无法确定适用哪个版本【事实+推断】。
   - 结论口径：**参考阅读安全；逐字拷贝代码须先走法务确认 + 保留 attribution**。
2. **维护活跃度**：12 个月零更新、0 release、2026 年 issue 零回复、作者明示优先升级设备（即换代 HomieBot 类后续，未在本 org 落地新仓）。接入即"接盘"，bug 只能自己修（issue 区已有多例真机部署问题未解）【事实】。
3. **与 DDS 架构的冲突**：中间件层无冲突（LCM udpm 与 DDS 可共存同网）；冲突在控制面（低位 rt/lowcmd 接管 vs BSI 高位 velocity，互斥分时）；以及版本耦合——vendored unitree_sdk2 是 2023 年代 API，与我们 submodule 的 `unitree_sdk2_python` 无版本对齐义务但需各自验证【事实+推断】。
4. **checkpoint 适配面窄**：唯一发布物 deploy.onnx 绑死腰锁 27-DoF G1 + 作者自述"policy seems not stable enough on 29dof"（issue #18 第三方复现）；换手机器人要整套重训，而训练基建（Isaac Gym Preview 4）已被 NVIDIA 弃用【事实】。
5. **安全面**：HOMIE 部署流程要求组合键杀 G1 原生控制后手工接管，急停仅 rpy 阈值 + 遥控器；对比我们 BSI 已有的 L1/L2 分级急停共识，安全面是裸的，真机实验须叠我们的安全层【事实+推断】。

---

## 5. 结论与建议

**推荐：不接入主链路（否掉 A 与 B 作为工程路线），执行路径 C 的选择性吸收。**

理由归一：OpenHomie 与 Teleopit 在**操作员范式（专用外骨骼 vs 通用 VR+IK）、视频栈（JPEG/TCP vs WebRTC/NVENC）、机器人侧策略（自带腿腰 RL vs 自研全身跟踪）**三层全部错位；它能给我们的增量只有三样——低位控制参考代码、RL 训练配方思想、以及"变高度作业"这一个能力方向——而这三样都不需要接入它的主链路就能拿到。

| 路径 | 工作量 | 前置条件 | 建议 |
|---|---|---|---|
| A 整体替换操作员侧 | **大** | 表单申请+硬件自制+Dex-3 | 否决 |
| B 采机器人侧栈 | **中~大** | 27-DoF 腰锁 G1（否则重训）；BSI 让位 | 仅作实验，非主线 |
| **C 摘组件** | **小（C1/C3）~中（C2）** | 无 | **推荐** |

建议落地顺序（若采纳）：先 C1（把 `g1_control.cpp` 读进低位控制知识，服务 train_mimic 真机线）；若"蹲起/变高度"进入需求池，再做 C2（curriculum/height-reward 思想进 train_mimic 训练任务）；C3 仅在考虑 B 实验时作为零风险前置。

---

## 附：本研究引用一览

- 本地克隆（保留）：`F:\tmp\openhomie-study`（depth-1，commit `cefcd85` 2025-09-01）；论文 HTML 快照 `F:\tmp\openhomie-study-paper.html`
- 仓库文件：`OpenHomie/README.md`、`HomieDeploy/README.md`、`HomieRL/README.md`、`HomieHardware/README.md`、`MujocoDeploy/README.md`、`HomieDeploy/d455.py`、`HomieDeploy/g1_gym_deploy/scripts/deploy_policy.py`、`.../envs/lcm_agent.py`、`.../utils/cheetah_state_estimator.py`、`.../lcm_types/{command,pd_tau_targets,arm_action}_lcmt*`、`HomieDeploy/unitree_sdk2/{g1_control,hand_control}.cpp`、`HomieDeploy/unitree_sdk2/LICENSE`、`HomieRL/legged_gym/legged_gym/envs/g1/g1_29dof_config.py`、`HomieRL/rsl_rl/rsl_rl/algorithms/him_ppo.py`、`MujocoDeploy/{mujoco_deploy_g1.py,g1.yaml}`
- GitHub API（2026-09-04）：`repos/InternRobotics/OpenHomie`（元数据/commits）、`issues` #4 #9 #18 #20 #22 及评论、`users/InternRobotics`、org 仓搜索
- arXiv:2502.13013（v2, 2025-04-28）摘要页 + HTML 全文（硬件频率/成本表、Table IV、§C-A 部署细节）
- Isaac Gym 弃用：NVIDIA 开发者页标注 "Now Deprecated"（developer.nvidia.com/isaac-gym）+ Isaac Lab 官方迁移指南（isaac-sim.github.io/IsaacLab，"From IsaacGymEnvs" 章）
- 本地：`docs/knowledge/architecture.md`、`docs/knowledge/repo-guide.md`
