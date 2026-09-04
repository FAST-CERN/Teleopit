# t01 SONIC 接口面语义（ZMQ 契约 / checkpoint 三选一 / 锁腰腕颈 / 配重仿真 / sim2sim 路径）

- 地图：`2026-09-04-sonic-wbc`（ticket 01，research）
- 日期：2026-09-04（纯代码+文档研究，无实机、无模型试跑；harness 佐证点列 §9 移交 02）
- 信源：
  - 本地克隆 `F:\tmp\wbc-groot`（NVlabs/GR00T-WholeBodyControl，depth-1，HEAD `087f9ac` 2026-09-03 = 最新 push）——**一切接口结论以下列文件为准逐条核实**：
    - ZMQ 线格式：`gear_sonic_deploy/src/g1/g1_deploy_onnx_ref/include/input_interface/zmq_packed_message_subscriber.hpp`
    - ZMQ 协议/流式语义：`.../include/input_interface/zmq_endpoint_interface.hpp`、`.../include/input_interface/streamed_motion_merger.hpp`、`docs/source/tutorials/zmq.md`
    - 关节序/增益/action_scale/default：`.../include/policy_parameters.hpp`
    - obs 注册表与 gatherer：`.../src/g1/g1_deploy_onnx_ref.cpp`
    - planner 契约：`docs/source/references/planner_onnx.md`、`.../include/input_interface/zmq_manager.hpp`
    - checkpoint：`docs/source/model_card.md`、`gear_sonic_deploy/policy/release/observation_config{,_low_latency,_sonic_release}.yaml`、`policy/sonic_v1_1/observation_config.yaml`、`download_from_hf.py`、`gear_sonic/pyproject.toml`
    - sim2sim：`gear_sonic/scripts/run_sim_loop.py`、`gear_sonic/utils/mujoco_sim/{base_sim.py,unitree_sdk2py_bridge.py,wbc_configs/g1_29dof_sonic_model12.yaml}`、`install_scripts/install_mujoco_sim.sh`
    - 模型 XML：`gear_sonic_deploy/g1/g1_29dof.xml`、`gear_sonic_deploy/g1/g1_29dof_with_hand.xml`、`gear_sonic/data/robot_model/model_data/g1/g1_29dof_with_hand.urdf`
  - HF `nvidia/GEAR-SONIC` 文件表（hf-mirror API，2026-09-04，含 blob 大小；lastModified 2026-08-26）
  - 本地 Teleopit（只读）：`teleopit/robots/mujoco_robot.py`、`teleopit/sim/{velocity_session.py,runtime_components.py}`、`teleopit/inputs/tracker_arm_synth.py`、`assets/robots/unitree_g1/g1_29dof.xml`
  - 预研 `research/00-wbc-policy-candidates-bsi-upperbody.md`（线索定位用；其 §4 gap 本票逐条重验）
- 标注：【事实】= 源码/文档原文可查（含行号）；【推导】= 算术/等价变换；【推断】= 分析判断（须 02 试验台佐证）。

---

## 0. 六问速答

| # | 问题 | 裁决 |
|---|---|---|
| 1 | 输入通道 | **直灌可行且免 FK**：`pose` topic **协议 v1**（joint_pos[N,29]+joint_vel[N,29]+body_quat[N,4](wxyz)+frame_index[N]，单条 ZMQ 消息=topic前缀+1280B JSON 头+二进制拼接，端口 5556/topic "pose"）。**但 v1 无速度槽位**——decoder obs 只有 token+历史（994D），cmd_vel 只能活在参考运动或 planner：官方速度面 = **planner 模式**（`planner` topic：mode/movement[3]/facing[3]/speed/height + **upper_body_position[17] 关节直灌上身**）。→ 建议：上身跟随线走 v1 直灌，指令跟踪线走 planner 模式（或 harness 内自产步态参考）【事实+推导，§1/§3】 |
| 2 | checkpoint 三选一 | 三变体 ONNX 全在 HF：default（enc 50.1MB/dec 40.9MB）、**low_latency**（45.9/149.8MB，4帧80ms lookahead+step1）、**sonic_v1_1**（50.1/149.8MB，航向归一+腕增强，实机配 kp-scale 4,10=1.5）。decoder 输入 994D（64 token+10×93 历史）、输出 29D action；encoder 输入 low_latency 1247D / default 1762D，输出 64D token。**inference 不需要 Isaac Lab**（三重证据：官方部署=C++/TensorRT+ONNX；sim2sim venv=`gear_sonic[sim]` 无 torch 无 isaaclab；PyTorch last.pt 才是 Isaac Lab 评估/续训用）【事实，§4】 |
| 3 | 锁腰 | 腰在 obs（历史 29D 含腰，**偏差坐标 q−default**）与 action（29D 含腰）都在；但腰 default=0 → 锁腰时 obs/action 腰分量恒 0 = 干净的常值输入。v1 直灌时参考腰直接置 0 即可；sim2sim 建议腰 weld/钳 0 双保险。训练分布中站立/行走腰摆小（Bones-SEED G1 retarget），恒 0 属温和域差【事实+推断，§5】 |
| 4 | 腕/颈 | 腕 = IsaacLab 交错序 {23..28}（L_roll,R_roll,L_pitch,R_pitch,L_yaw,R_yaw）/ 本地 XML 序 {19,20,21,26,27,28}。v1 直灌下**无冲突**：策略跟踪我们参考里的腕（重定向腕目标直接写进 joint_pos[23..28]）；可选项 = 输出侧 q_target 腕覆盖直发 PD（腕 pitch/yaw 限 ±5Nm、roll ±25Nm，弱执行器须注意）。**颈完全旁路确认**：G1 29 序里无颈，obs/action 定长 29 无槽位【事实，§6】 |
| 5 | RH56E2 配重 | SONIC 橡胶手 = wrist_yaw_link 上 pos (0.0415,0.003,0) 双 geom（视觉 density=0 + 碰撞默认密度）。实验：本地 `g1_29dof.xml` 腕 yaw link 加显式 mass geom，对照组 0/0.25/0.5kg 点质量/0.5kg 分布质量四档，指标=上身 RMSE+力矩饱和率+失效安全【事实+设计，§7】 |
| 6 | sim2sim 最短路径 | 仓内官方 sim2sim = `run_sim_loop.py`（MuJoCo 200Hz 物理+显式扭矩 PD）+ **C++ deploy 二进制**（TensorRT+CUDA 硬依赖，经 DDS rt/lowcmd\|lowstate 与 sim 互通，sim 冒充真机）→ Windows 本机不可行。最短路径 = **Python harness**：onnxruntime enc/dec + 本地 `MuJoCoRobot`（builtin PD、ctrl=q_des、50Hz 策略+200Hz 物理，pd_hz 200 不变量与官方 sim 同构）+ obs 装配照抄 C++ registry【事实，§8】 |

---

## 1. ZMQ qpos 流精确契约（Q1 前半）

### 1.1 线格式与连接拓扑【事实】

- 我们是 **PUB 端**（"publisher"），官方 C++ 是 SUB 端：`deploy.sh --input-type zmq --zmq-host <our-ip> --zmq-port 5556 --zmq-topic pose`（zmq.md:25-30）。
- 每条消息为**单分片**：`[topic 前缀（"pose"）][1280 字节 null 填充 JSON 头][各字段二进制按头内顺序拼接]`（zmq_packed_message_subscriber.hpp:5-27, HEADER_SIZE=1280:99）。
- JSON 头示例（订阅端原文）：`{"v":1,"endian":"le","count":100,"fields":[{"name":"joint_pos","dtype":"f32","shape":[100,29]},{"name":"body_quat","dtype":"f64","shape":[100,1,4]}]}`（zmq_packed_message_subscriber.hpp:16-20）。dtype 支持 f32/f64/i32/i64/u8/bool；小端默认。
- 可开 `--zmq-conflate` 丢旧帧保最新（单分片设计使 conflate 安全，zmq_packed_message_subscriber.hpp:26-27）。
- 会话内协议版本不可切换，切了强制退出流模式回参考动作（安全机制，zmq.md:221-225）。

### 1.2 协议 v1（我们直灌所用）字段表【事实，zmq.md:227-244 + zmq_endpoint_interface.hpp:872-917】

| 字段 | 形状 | dtype | 语义 |
|---|---|---|---|
| `joint_pos` | `[N,29]` | f32/f64 | **IsaacLab 交错序**（§2），**绝对关节角**（rad） |
| `joint_vel` | `[N,29]` | f32/f64 | 同序，rad/s，帧数必须与 joint_pos 一致 |
| `body_quat` | `[N,4]` 或 `[N,B,4]` | f32/f64 | 每帧参考根（pelvis）四元数 **wxyz**（首元素=1 的默认值证实 w 在前，zmq_endpoint_interface.hpp:1077） |
| `frame_index` | `[N]` | i32/i64 | 全局时间线单调递增帧号（对齐用，别名 `last_smpl_global_frames` 也被接受:662） |

可选项（所有协议通用，zmq.md:330-341）：`left/right_hand_joints[7]`（Dex3 手，我们弃用——手走 RH56E2 Modbus 链）、`vr_position[9]`+`vr_orientation[12]`（**注意：出现即触发 teleop 编码模式**，§3.3）、`catch_up`（默认 true）、`heading_increment`（标量，逐消息 yaw 增量，zmq_endpoint_interface.hpp:1483-1513）。

### 1.3 消费语义（发布器要满足什么）【事实+推导】

- 解码后进 `StreamedMotionMerger` 滑窗：frame_index 步距自动检测（如发 50Hz 收 50Hz → step1），重采样到控制率 50Hz；保留播放点后 5 帧历史（HISTORY_FRAMES=5），**播放点与流前沿间距 >200 帧（4s）触发 catch-up 重置**（MAX_GAP_FRAMES=200，streamed_motion_merger.hpp:63-69）。
- obs 前瞻：encoder 读 `current_frame + k×step` 帧（默认 checkpoint g1 模式 10 帧 step5 = 需要 0.9s 前瞻；low_latency step1 = 200ms）。**帧供应不足时钳位保持最后帧**（g1_deploy_onnx_ref.cpp:655-659 注释 "clamp to last frame"）——实时流天然前沿受限，前瞻段的"持尾"是结构性现象，低延迟版受影响最小【推导】。发布器建议 ≥50Hz 供帧、frame_index 严格递增；是否在发布端做恒速外推（把前沿前方补外推帧）留给 02 试验【待验】。
- `body_quat` 只以**相对量**进 obs：`motion_anchor_ori_b` = 6D 旋转( inv(robot_base_quat) · (apply_delta_heading · ref_root_quat) )，其中 apply_delta_heading 把参考航向重基到机器人初始航向（g1_deploy_onnx_ref.cpp:584-626, 667-697）。**结论：合成帧发 identity 四元数即可**（或仅 yaw），绝对航向语义被重基覆盖【推导】。
- **v1 无根位置通道**：obs 的 `motion_root_z_position` 读 `BodyPositions(frame)[0][2]`（g1_deploy_onnx_ref.cpp:449），而流式合并器只接 joint/vel/quat/smpl，**body positions 零初始化**（ReserveCapacity(15000,29,1,1,0,0)，zmq_endpoint_interface.hpp:594；merger IncomingData 无 body positions，:1681-1694）→ 走官方 C++ 栈时 v1 流的 root_z 恒 0（encoder 见到"根在地面上"的参考）——潜在 OOD。自建 harness 我们可控 obs，可填站立高度常数【事实+风险标注】。
- **坐标系语义（对齐我们的合成器）**：joint_pos 绝对角 vs 机器人历史 obs 偏差角（q−default，g1_deploy_onnx_ref.cpp:2846-2847 与训练侧 observations.py:1876 `joint_pos - default_joint_pos` 两侧一致）；参考侧绝对性由训练命令的误差度量证实（commands.py:2455 直接 |motion_q − robot_q|）【事实】。

### 1.4 与 teleop 编码模式的对照（VR 三点）

teleop 编码（encode_mode 1）不是独立协议，而是 **obs 通道切换**：encoder 改吃 `motion_joint_positions_lowerbody_10frame`（参考仍来自流/planner 的下半身）+ `vr_3point_local_target[9]`（左腕/右腕/头位置）+ `vr_3point_local_orn_target[12]`（wxyz×3）+ `motion_anchor_orientation`（g1_deploy_onnx_ref.cpp 观测注册表 1775-1778；config policy/release/observation_config.yaml:65-73）。VR 三点默认值（站姿腕/头位姿）见 zmq_endpoint_interface.hpp:1332-1341。用 v1 流时**只要不发 `vr_position` 字段就停留在 encode 0**，不会误入 teleop 模式（zmq_manager.hpp:655-662 仅在 vr 控制标志翻转时切 mode 1）。

---

## 2. 关节序映射表（直灌路径核心，Q1 关键交付）

**两套序并存**（policy_parameters.hpp:6-15 自述"Two ordering conventions coexist"）：

- **MuJoCo/URDF 序（= 本地 `assets/robots/unitree_g1/g1_29dof.xml` 关节序，已逐一比对相同）**：blocked——L 腿 0-5、R 腿 6-11、腰 12-14、L 臂 15-21、R 臂 22-28。
- **IsaacLab 序（= 策略 obs/action/ZMQ joint_pos/upper_body_position 所用）**：**交错**——由 depth 分组交错左右。

映射数组原文（policy_parameters.hpp:100-104；行 99/102 注释自证方向："mujoco order in isaaclab index" / "isaaclab order in mujoco index"）：

```python
# isaaclab_to_mujoco[mj] = il（MuJoCo 关节 mj 的 IsaacLab 下标）
ISAACLAB_TO_MUJOCO = [0,3,6,9,13,17,1,4,7,10,14,18,2,5,8,11,15,19,21,23,25,27,12,16,20,22,24,26,28]
# mujoco_to_isaaclab[il] = mj（IsaacLab 关节 il 的 MuJoCo 下标）——互逆
MUJOCO_TO_ISAACLAB = [0,6,12,1,7,13,2,8,14,3,9,15,22,4,10,16,23,5,11,17,24,18,25,19,26,20,27,21,28]
```

**SONIC qpos 关节序（IsaacLab）↔ 本地 g1_29dof.xml 关节序（MuJoCo）完整对照表**【事实，交叉验证自 policy_parameters.hpp:76-97 三组索引集（upper17/lower12/wrist6）+ zmq.md:276 腕索引 + pico_manager_thread_server.py:1428-1435 腕写入下标】：

| SONIC(IsaacLab) idx | 关节 | 本地 XML(MuJoCo) idx |
|---|---|---|
| 0 | left_hip_pitch | 0 |
| 1 | right_hip_pitch | 6 |
| 2 | **waist_yaw** | 12 |
| 3 | left_hip_roll | 1 |
| 4 | right_hip_roll | 7 |
| 5 | **waist_roll** | 13 |
| 6 | left_hip_yaw | 2 |
| 7 | right_hip_yaw | 8 |
| 8 | **waist_pitch** | 14 |
| 9 | left_knee | 3 |
| 10 | right_knee | 9 |
| 11 | left_shoulder_pitch | 15 |
| 12 | right_shoulder_pitch | 22 |
| 13 | left_ankle_pitch | 4 |
| 14 | right_ankle_pitch | 10 |
| 15 | left_shoulder_roll | 16 |
| 16 | right_shoulder_roll | 23 |
| 17 | left_ankle_roll | 5 |
| 18 | right_ankle_roll | 11 |
| 19 | left_shoulder_yaw | 17 |
| 20 | right_shoulder_yaw | 24 |
| 21 | left_elbow | 18 |
| 22 | right_elbow | 25 |
| 23 | left_wrist_roll | 19 |
| 24 | right_wrist_roll | 26 |
| 25 | left_wrist_pitch | 20 |
| 26 | right_wrist_pitch | 27 |
| 27 | left_wrist_yaw | 21 |
| 28 | right_wrist_yaw | 28 |

- 直灌填充公式：`sonic_q[il] = local_qpos[MUJOCO_TO_ISAACLAB[il]]`（sonic_q = ZMQ joint_pos 行）。
- **上身 17 维（planner topic `upper_body_position` 的序）** = IsaacLab 上身按 IsaacLab 序 = {2,5,8,11,12,15,16,19,20,21,22,23,24,25,26,27,28} = [waist_yaw, waist_roll, waist_pitch, L_sh_pitch, R_sh_pitch, L_sh_roll, R_sh_roll, L_sh_yaw, R_sh_yaw, L_elbow, R_elbow, L_w_roll, R_w_roll, L_w_pitch, R_w_pitch, L_w_yaw, R_w_yaw]（policy_parameters.hpp:80；17 维也含腰，zmq_manager.hpp:889-916）。
- 我们的重定向产物 = G1 臂 14 关节（本地序 idx 15-28，tracker_arm_synth.py:13 注释 "the retarget takes arm idx 15-28"）→ 直灌时填 sonic 11,12,15,16,19,20,21,22,23-28，腰三位置 0，腿部用站立模板。
- **陷阱记录**：SONIC 仓内 `g1_29dof_sonic_model12.yaml` 的 `WeakMotorJointIndex` 块标了 hip_yaw=0/hip_roll=1/hip_pitch=2（与 URDF 矛盾），是旧 sim-loop 残留；权威序以 URDF（`gear_sonic/data/robot_model/model_data/g1/g1_29dof_with_hand.urdf` 关节声明序=blocked）+ policy_parameters.hpp 映射数组为准【事实】。

---

## 3. 三条上身/速度注入通道对比与 cmd_vel 注入点（Q1 后半）

### 3.1 通道 A：`pose` topic 协议 v1（qpos 直灌，encode 0）

- 语义 = 参考运动跟踪：策略输出跟踪我们流的全身参考。上身 = 我们的 14 臂关节直接进参考（**无 FK、无冲突**）。
- **速度无槽位**：decoder（策略）obs = `token_state(64) + his_base_ang_vel(30) + his_joint_pos(290) + his_joint_vel(290) + his_last_action(290) + his_gravity(30)` = 994D，无任何速度指令项（observation_config.yaml:5-23）；v1 可选字段里也只有 `heading_increment`（yaw 微调）。机器人要走，参考就得走。
- 适用：上身跟随线（原地操作、慢速挪步）；指令跟踪线需另配步态参考源。

### 3.2 通道 B：planner 模式（`--input-type zmq_manager`，cmd_vel 的官方家）

`ZMQManager` 同端口订三 topic（zmq_manager.hpp:5-24）：

| topic | 内容 |
|---|---|
| `command` | `{start:bool, stop:bool, planner:bool, delta_heading?}` —— planner=true 进 PLANNER 模式 |
| `planner` | **速度指令面**：`mode`(i64，0=idle/1=slowWalk/2=walk/3=run/…27 种)、`movement[3]`f32（世界 Z-up 移动方向，内归一）、`facing[3]`f32（世界朝向，atan2(y,x) 得 heading）、`speed`f32（m/s，<=0 用模式默认）、`height`f32（<0 禁用）；**可选 `upper_body_position[17]`+`upper_body_velocity[17]`（上身关节直灌！）**、hand joints、vr fields（zmq_manager.hpp:774-1000 逐字段解码；planner_onnx.md:20-27 输入张量） |
| `pose` | 流式参考（=通道 A，PLANNER 模式下不用） |

- planner ONNX（HF `planner_sonic.onnx` **773.95MB**，opset17）从高层指令生成未来全身 qpos（30Hz→50Hz 重采样、8 帧 blend、10Hz replan，planner_onnx.md:334-411）；**teleop/上身注入不必须 planner 的 vr 字段**——不发 vr_position 时 encode 保持 0（g1 编码器），`upper_body_position[17]` 在 obs gather 时覆盖 planner 参考的上身 17 关节（g1_deploy_onnx_ref.cpp:784-795，`has_upper_body_data_` 路径）→ **速度走 planner 步态 + 上身走我们的关节目标，正是本项目契约**。
- **BSI cmd_vel 映射【推导】**：cmd (vx,vy,ω) → `movement=(vx,vy,0)`（方向内归一）、`speed=√(vx²+vy²)`、`facing=(cosθ,sinθ,0)` 其中 θ 每拍积分 ω（SONIC 是 heading 目标式非角速度式，与 AMO 的 yaw 语义同类）。1s 无 planner 消息自动回 IDLE（超时保护，zmq_manager.hpp:581-646）。
- 代价：planner 模型 774MB + 其上下文构造/blend 逻辑目前只在 C++/TensorRT 栈（localmotion_kplanner*.hpp）；Python harness 复刻 = 重活（planner_onnx.md "Deployment Integration" 节给了完整算法描述，可照抄）。

### 3.3 通道 C：teleop 编码（vr_position 三点）

v1/v3 消息带 `vr_position[9]`(+`vr_orientation[12]`) 即切 encode 1（zmq_manager.hpp:655-662；zmq_endpoint_interface.hpp:1751-1756）——头/双腕笛卡尔三点。**不作主链**：三点绕过我们的关节空间合成（颈/腕语义丢失），且下半身参考仍需来源。留作对照/后备。

### 3.4 与我们首选链路的对表

- 合成帧→现有 GMR/mink 重定向→上身 qpos 直灌：**通道 A/B 都吃这套产物**（A=拼全身参考流，B=upper_body_position[17]），免 FK 成立（通道 C 才需要 FK 产三点位姿）。
- 现有资产直接可复用：`TrackerArmSynthesizer` 合成 24 关节 body 帧（tracker_arm_synth.py:1-16）→ provider 现有 body 路径（dedup→坐标变换→地面校直→GMR/mink 重定向）→ 臂 14 关节；或直接回放 `pico_bridge_recordings/tracking_20260904_104418.jsonl`。

---

## 4. checkpoint 三选一（Q2）

### 4.1 HF 文件与大小【事实，hf-mirror API 2026-09-04】

| 变体 | 部署文件（大小） | 训练文件 | lookahead | g1/teleop 前瞻步距 |
|---|---|---|---|---|
| **default**（根目录） | model_encoder.onnx 50.10MB / model_decoder.onnx 40.90MB / observation_config.yaml | sonic_release/last.pt 469.42MB + config.yaml | 10 帧@20ms ≈ 200ms（SMPL 面） | **step5**（10×5 帧 @50Hz = 0.9s 窗） |
| **low_latency** | enc 45.93MB / dec 149.76MB / observation_config.yaml + config.yaml + model_config.yaml | last.pt 1125.41MB | **4 帧 ≈ 80ms** | **step1**（10×1 = 200ms 窗） |
| **sonic_v1_1** | enc 50.12MB / dec 149.78MB / 同上 | last.pt（列表未单列，随目录） | 10 帧 ≈ 200ms | step5 |
| planner | planner_sonic.onnx **773.95MB** | — | 24-64 帧（token×4） | — |

（model_card.md:7-13 变体说明；observation_config_low_latency.yaml 头注 "Encoder 1247 / Decoder 994"；sonic_release 训练变体 1751D 是 nonflat tokenizer 导出，**不是部署入口**。）

### 4.2 张量形状【事实，observation_config.yaml 系 + g1_deploy_onnx_ref.cpp 注册表】

- **decoder（控制器，50Hz）**：输入 994D = token_state 64 + his_base_ang_vel 30 + his_joint_pos 290 + his_joint_vel 290 + his_last_action 290 + his_gravity 30（observation_config.yaml:5-23）；输出 action **[1,29] IsaacLab 序**（g1_deploy_onnx_ref.cpp:3121-3145 注释 "maps the action output (IsaacLab order) to a MotorCommand (hardware order)"）。
- **encoder**：输入 = obs 列表拼接（low_latency 1247D：encoder_mode_4 4 + joints 290×2 + anchor 60+6 + lowerbody 120×2 + vr 9+12 + smpl 288+24 + wrists 24；default 为 step5/10frame 变体 1762D）；输出 token **[1,64]**（encoder.hpp:114-121 输出名 `encoded_tokens`，输入名 `obs_dict`）。
- **动作语义**：`q_target[mj] = default_angles[mj] + action[il] × g1_action_scale[mj]`（g1_deploy_onnx_ref.cpp:3140-3142；公式 policy_parameters.hpp:29）。default_angles = 站姿（hip_pitch −0.312 / knee 0.669 / ankle_pitch −0.363 / elbow 0.6 / sh_pitch 0.2 / L sh_roll 0.2 / R −0.2，与训练 init_state 一致，g1.py:224-233）。
- **每个 ONNX 必须配它自己的 observation_config.yaml**（model_card.md:151-152 明确警告）。

### 4.3 推理依赖：不需要 Isaac Lab（三重证据）【事实】

1. 官方部署路径 = C++/TensorRT 吃 ONNX："Deployment uses C++ and TensorRT; the PyTorch checkpoints support Isaac Lab evaluation and continued training"（model_card.md:24-27）。
2. 官方 sim2sim 的 MuJoCo 侧环境 = `pip install -e "gear_sonic[sim]"` → mujoco/tyro/pin/pyyaml/pyzmq/msgpack/msgpack-numpy/opencv（pyproject.toml:44-53）——**无 torch、无 isaaclab**（推理在 C++ 侧）。
3. Isaac Lab 仅出现在：quickstart 的 last.pt 评估（quickstart.md:16-38）、训练/finetune 文档、安装文档训练节。
4. 自建 Python harness 需要的只是 **onnxruntime + numpy**（teleopit conda env 已有 numpy；onnxruntime 需确认版本——[待验] pip 装即可）+ 模型 ~100-200MB 下载（HF_ENDPOINT=hf-mirror 可达，本研究已用镜像 API 验证）。
5. torch 版本问题只在碰 last.pt（1125MB/469MB）时存在——sim2sim 线**不碰**。

### 4.4 选择建议（决议草案详见 §9）

- **主线 low_latency**：4 帧 80ms 前瞻对流式直灌最友好（§1.3 持尾失真最小）、teleop 响应定位、step1 观测窗 200ms。风险：其 PyTorch 训练 checkpoint 最大（1125MB），复训最贵；dec 149.76MB。
- **对照 sonic_v1_1**：腕位姿增强训练（wrist-pose augmentation）直接对症 RH56E2 腕端增重的鲁棒性问题；机器人航向归一（obs 用 `motion_anchor_orientation_heading*` 变体，sonic_v1_1/observation_config.yaml:16-17）对我们 heading 多变的遥操利好；`--motor-kp-scale 4,10=1.5` 是**实机踝**调参，sim2sim 不需要（除非对照增益敏感性）。
- default：兼容基线，仅作回退。

---

## 5. 锁腰面（Q3）

- **腰的角色**【事实】：waist_yaw/roll/pitch = IsaacLab {2,5,8} / 本地 XML {12,13,14}；同时出现在 (a) 参考通道（v1 joint_pos 或 planner 参考或 upper_body_position 前 3 维）；(b) 机器人 obs（his_body_joint_positions 290D 含腰，**偏差坐标**）；(c) decoder action 29D（含腰，action_scale 依电机型号）。default 腰角 = 0（policy_parameters.hpp:223-225）。
- **qpos 输入腰恒 0 是否被接受**：参考侧恒 0 = 腰在偏差坐标 obs 里恒 0（因 default=0）——训练分布中站立/常规行走腰摆动小（Bones-SEED G1 retarget 数据，288h；AMO 侧同结论见 research/00 §4.1），恒 0 属常见子集，是**温和域差**而非结构外【推断——02 sim2sim 定量验证】。合成器侧我们完全可控腰三维度（重定向只产臂 14，腰天然置 0）。
- **输出腰参考需否再钳**：sim2sim 里 decoder 输出腰 action → q_target；若用锁腰仿真模型（腰 weld 或 range=0），指令无效果、obs 腰读数恒 0——与训练分布的自洽性反而更好（机器人本体状态恒 default）。**不需要额外钳输出**；真机 mode≈6（unitree_rl_lab issue #6/#114 经验值 29dof 锁腰 mode）下电机层自动忽略腰指令，obs 同样恒 0【事实+推导】。
- 仓内可借资产：decoupled_wbc 线有 `g1_29dof_lock_waist` 场景变体（decoupled_wbc/sim2mujoco/resources/robots/g1/README.md:14）——**属于 Decoupled WBC 不是 SONIC**，仅作锁腰 XML 写法参考（equality weld 或零行程 joint）【事实】。

---

## 6. 腕/颈面（Q4）

- **腕 6 DoF**【事实】：SONIC(IsaacLab) 交错 {23=L_roll, 24=R_roll, 25=L_pitch, 26=R_pitch, 27=L_yaw, 28=R_yaw}（zmq.md:276 + pico_manager_thread_server.py:1428-1435 官方发布器实证）↔ 本地 XML blocked {19,20,21=L, 26,27,28=R}。
- **冲突分析**：v1 直灌下**不存在策略腕输出 vs 我们腕目标的双头控制**——策略是跟踪器，腕参考 = 我们流里的 joint_pos[23..28]（重定向腕目标直接写入）。我们的 GMR/mink 重定向现产 14 臂关节含腕 3+3（tracker_arm_synth 链），即腕目标已在手。
- **旁路 PD/直发选项**（若 02 发现策略腕跟踪差）：harness 输出侧把 q_target 腕位替换为参考腕值直发（等价 AMO 臂处理范式）。**约束**：腕 roll 电机 5020（Kp=STIFFNESS_5020≈14.25，±25Nm，action_scale≈0.44 rad）、腕 pitch/yaw 电机 4010（Kp≈16.78，**±5Nm**，scale≈0.074 rad，policy_parameters.hpp:62-65,109-138 与 g1_29dof.xml `actuatorfrcrange`）——直发时 0.5kg RH56E2 在 ~8-10cm 力臂的重力矩 ~0.4-0.5Nm 已占 pitch/yau 限幅 ~10%，动态摆臂更甚（联动 §7）。
- **颈**【事实】：G1 29 关节序（两种序都）无任何颈关节；SONIC obs/action 定长 29、planner qpos 36 维定长——**OpenNeck 2dof 完全旁路**，与 RH56E2 手同层处理（颈目标走既有直发 PD 链，不进策略面）。teleop 三点模式的"head"点是参考帧锚（用于上身编码），不是颈控制。

---

## 7. RH56E2 配重仿真法（Q5）

**SONIC 侧腕端现状**【事实，gear_sonic_deploy/g1/g1_29dof.xml:168-186】：腕链 roll(0.085kg)→pitch(0.484kg)→yaw(**0.2546kg**，末端 link)；橡胶手 = wrist_yaw_link 上 pos `(0.0415, 0.003, 0)` 处**两个 geom**：视觉件 `density="0"` + 碰撞件默认密度（质量由 STL 体积×1000 决定，量级[待验]——加载后 `model.body('left_wrist_yaw_link').mass` 可读）。Dex3 变体（g1_29dof_with_hand.xml:300-313）同安装点 palm，wrist_yaw inertial 增至 0.4574kg。

**实验设计（在本地 `assets/robots/unitree_g1/g1_29dof.xml` 上做，不动 SONIC 仓）**：

1. **加在哪**：`left/right_wrist_yaw_link` 内、手安装偏移 `(0.0415, 0.003, 0)` 处（与 SONIC 手几何同位，质心尽量贴真 RH56E2+支架——装机后实测[待验]）。
2. **怎么给质量**：加一个显式 `mass` 属性的 box geom（MuJoCo geom `mass` 直接指定，惯性由形状推导；`contype=0 conaffinity=0` 关碰撞，只做惯量载体）——两档给法分离"质量 vs 惯量"效应：
   - 点质量档：小 sphere、mass=0.5（惯量≈0）；
   - 分布档：box ~0.09×0.07×0.045 m、mass=0.5（近似真手包络）。
3. **对照组（四档）**：① 基线 0g（纯腕）② +0.25kg 点 ③ +0.5kg 点 ④ +0.5kg box；（可选 ⑤ 复刻 SONIC 橡胶手碰撞 geom 作"官方质量"锚点）。
4. **指标**（喂 03 票数值线）：上身参考跟随 RMSE（臂+腕分列）、腕关节力矩饱和率（pitch/yaw ±5Nm、roll ±25Nm 限幅占用）、全身稳定裕度（根高/倾角/接触力）、推扰恢复（复用 velocity_session 的 T 键 220N pelvis 冲击，velocity_session.py:86-89）、失效安全（estop 后跌倒判定）。
5. **注意**：策略不感知质量变化（obs 无质量项）——这正是要测的 sim 域差鲁棒性；若不过线再评估 finetune（model_card 说明支持 continued training，但那要 Isaac Lab 复训线，Out of scope）。

---

## 8. sim2sim 最短路径（Q6）

### 8.1 SONIC 仓内盘点【事实】

- **官方 sim2sim = 双进程**：`gear_sonic/scripts/run_sim_loop.py`（MuJoCo 场景 `gear_sonic/data/robot_model/model_data/g1/scene_43dof.xml`，SIMULATE_DT=0.005 即 200Hz 物理，wbc_configs/g1_29dof_sonic_model12.yaml:24）+ C++ `deploy.sh sim`。**没有纯 Python 的策略推理 sim2sim 脚本**（scripts/ 里无 play_*.py 类物——与 AMO 相反）。
- 两进程经 **DDS `rt/lowcmd`/`rt/lowstate`**（unitree_sdk2py_bridge.py:89-90）互通——sim 冒充真机：C++ 收 LowState、发 MotorCommand{q_target, dq_target, kp, kd, tau_ff}（500Hz 命令写线程，g1_deploy_onnx_ref.cpp:19-21）；sim 显式扭矩 PD `tau = tau_ff + kp(q_des−q) + kd(dq_des−dq)`（base_sim.py:259-282）→ mj ctrl。
- **C++ 栈硬依赖 CUDA/TensorRT**（encoder.hpp:13/TRTInference；planner 同）→ 本机 Windows 不可行；Linux+GPU 可行但与地图"teleopit conda env 本机 sim2sim"路线不合。vendored unitree_sdk2 + DDS 使其真机路径完整（Out of scope，真机另议时这是官方 onboard 路径）。

### 8.2 与本地 MuJoCoRobot 的对接面（Python harness 清单）

| 对接面 | SONIC 侧语义 | 本地落点 |
|---|---|---|
| 物理/PD | 200Hz 物理 + 50Hz 控制 + 显式扭矩 PD（kp/kd 随命令下发） | `MuJoCoRobot` builtin PD（affine bias，ctrl=q_des，mujoco_robot.py:115-133）数学等价；**sim_dt 0.005 + policy 50Hz = pd_hz 200 不变量保持**（与 SONIC 官方 sim 同构）【事实】 |
| 策略输入 | obs 994D：token 64 + 10 帧历史（偏差坐标 q−default、dq 原值、last_action 原值、ang_vel、gravity） | 新建 SONIC obs builder（照抄 g1_deploy_onnx_ref.cpp gatherers：历史环形缓冲 10×93） |
| 参考输入 | v1 流/planner 参考上身 17 覆盖（§3） | 合成帧→重定向→§2 映射→直灌 |
| 关节序 | IsaacLab 交错（§2 表） | 本地 XML blocked；映射数组进 harness 常量 |
| 动作输出 | `q_target = default + action×scale`（IsaacLab→motor 映射后） | `set_position_target`（注意 MuJoCoRobot 直接吃 blocked 序，先映射） |
| heading | apply_delta_heading 重基（进入流时重初始化，`I` 键语义） | harness 复刻（合成参考发 identity quat 即可弱化此面，§1.3） |
| root_z | 官方流式路径恒 0（§1.3 风险） | harness 自填站立高度常数【待验敏感性】 |
| 模式机 | `]` 起控 / ENTER 切流 / O 急停 / ramp 到 default（g1_deploy_onnx_ref.cpp:2742-2766） | 复用 VelocitySimSession 模式机（STANDING/VELOCITY/STOP + EstopController），BSI L1/L2 急停在外层持有通道优先权 |
| 增益 | kps/kds 按电机型号（policy_parameters.hpp:143-207） | 本地 XML actuator + MuJoCoRobot cfg 对表（v1_1 的 4,10=1.5 是实机踝项，sim 不用） |

---

## 9. 决议草案（供 02 试验台票开稿）

1. **通道选择**：
   - 上身跟随线 = **`pose` 协议 v1 直灌**（合成帧→GMR/mink 重定向→臂 14 关节+腰 0+站立腿→§2 映射→ZMQ/或 harness 内直供 obs）。免 FK、零新变换、官方明示支持外源 qpos（zmq.md tip 节）。
   - 指令跟踪线（四线之一）= **planner 模式语义**（movement/facing/speed 高层指令 + `upper_body_position[17]` 上身直灌）——SONIC 生态里唯一原生 cmd_vel 面。两条实现路径由 02 定：**(a)** harness 内用 onnxruntime 跑 planner_sonic.onnx（774MB，planner_onnx.md 算法文档齐全）；**(b)** 先用通道 A + Bones-SEED 样例步态片段（HF sample_data walk_forward pkl 0.35MB）作速度线占位，planner 后补。BSI 映射：vx,vy→movement 方向、|v|→speed、ω→积分 heading→facing【推导】。
   - teleop 三点模式（vr_position）不动主链。
2. **checkpoint 推荐**：主线 **low_latency**（流式直灌前瞻失真最小）；对照 **sonic_v1_1**（腕增强+航向归一，直接对症 RH56E2 与遥操航向）。两套 obs config 都要在 harness 实现（差异 = step1/step5 + heading 变体，注册表名字齐备）。inference 全程 ONNX + onnxruntime，无 Isaac Lab、无 torch。
3. **锁腰**：参考腰恒 0（合成侧）+ sim 模型腰 weld/零行程（XML 侧）+ 不钳策略输出（接受 action 腰分量无效）；真机 mode≈6 兼容性说明：obs 腰恒 default(0)、指令被电机层忽略，与 sim 锁腰表现同构。
4. **腕/颈**：腕不旁路（参考直灌即跟踪，v1.1 对照腕增强）；若 02 实测腕跟踪差，启用输出侧 q_target 腕直发（注意 ±5Nm/±25Nm 限幅与 RH56E2 力臂预算）。颈完全旁路直发 PD（G1 29 无颈槽位，实锤）。
5. **02 试验台对接清单（含风险标注）**：
   - [ ] Python harness：onnxruntime 会话（enc `obs_dict`→`encoded_tokens` 64D；dec 994D→29D）+ 994D obs 装配（10 帧历史环形缓冲，偏差坐标）——**风险：obs 拼接顺序必须与 yaml 列序逐项对上，加载期有维度校验可抄（C++ 同款 throw）**。
   - [ ] 关节序映射模块（§2 两数组进常量 + 单测：随机向量往返置换）。**风险：仓内 yaml 残留的错序注释（WeakMotorJointIndex）曾误导预研，勿抄**。
   - [ ] 合成帧→重定向→直灌链（复用 tracker_arm_synth + provider body 路径；或 JSONL 回放）。
   - [ ] root_z 填充实验（0 vs 站立高度 vs 真参考 z）——**风险项，§1.3**。
   - [ ] MuJoCoRobot 场景切换 g1_29dof.xml（保持 pd_hz 200：sim_dt 0.005、策略 50Hz、decimation 4）。
   - [ ] 锁腰 XML 变体 + RH56E2 配重四档变体（§5/§7）。
   - [ ] 速度线方案 a/b 决策 + BSI→planner 指令映射层。
   - [ ] 模型下载（hf-mirror，enc+dec ≈200MB/变体；planner 774MB 按需）。
   - [ ] estop/模式机整合（VelocitySimSession 范式，BSI 急停优先权外层持有）。
   - [ ] [待验] 项集中复验：流式前瞻持尾行为、root_z 敏感性、橡胶手实际质量（`body.mass` 读数）、planner Python 复刻的 blend 保真度。

---

## 附：引用一览

- 克隆 `F:\tmp\wbc-groot`（HEAD 087f9ac, 2026-09-03）内文件均在 §信源 列出；行号引用散见各节。
- HF `nvidia/GEAR-SONIC`（hf-mirror API 2026-09-04）：文件表+大小（§4.1）、lastModified 2026-08-26。
- 论文：SONIC arXiv 2511.07820、AMO arXiv 2505.03738（编号承 research/00 已验部分；本研究接口结论全部代码级，不依赖论文页）。
- 本地锚点：`research/00-wbc-policy-candidates-bsi-upperbody.md`（§2.1 SONIC 节、§4 gap 清单——本票逐条重验后：① 锁腰温和域差成立；② 上身通道形态已定（v1 直灌+planner）；③ 腕旁路降级为"备选"（直灌即跟踪）；④ 手零质量假设修正为"橡胶手有碰撞质量、量级待加载实测"）。
