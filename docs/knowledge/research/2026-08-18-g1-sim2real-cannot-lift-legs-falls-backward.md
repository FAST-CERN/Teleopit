# 调查报告：G1 实机 sim2real "抬不起腿 + 往后倒"（仿真正常）

- 日期：2026-08-18
- 调查对象：Teleopit（fork: `https://github.com/FAST-CERN/Teleopit.git`，上游：`https://github.com/BotRunner64/Teleopit.git`，`git remote -v` 已核对）
- 现象：MuJoCo sim2sim（Pico 全身动捕）正常；实机 Unitree G1 上 (1) 腿部抬升不足/无力，(2) 机器人容易向后倒。
- 所有仓库内引用均已逐行核对；网络引用给出 URL。GitHub issue 属一手社区资料但非本仓库官方声明，已按来源分级标注。

---

## 结论摘要

综合代码与官方资料，最可能的原因（按可能性排序）：

1. **机型/`mode_machine` 不匹配或腰部未解锁**【有代码证据 + 官方一手资料】。本仓库 C++ bridge 把 `lowcmd.mode_machine` 硬编码为 `5`（`third_party/g1_bridge_sdk/src/g1_bridge.cpp:34,228,305`），而 Unitree 官方部署代码要求 `lowcmd.mode_machine` 必须与 `lowstate.mode_machine` 相等，命令才会被执行；社区复现中 29dof 带假手/锁腰机型出现过需要 `6` 的情况（见"可能原因清单"第 9 条引用的 issue）。机型不符时腿会"有趋势但使不上力"，与"抬不起腿"高度吻合。
2. **实机 kp/kd 明显低于官方示例刚度，且 sim 里力矩上限是"永远够用"的理想化条件**【有代码证据 + 官方一手资料】。`real_robot.kp_real`（`teleopit/configs/pico4_sim2real.yaml:128-137`）用 mjlab 训练刚度（hip_pitch 40.2 / knee 99.1 / ankle 28.5），低于 Unitree 官方 low-level 示例的腿部 kp（60/60/60/100）。训练时 kp 乘 0.5~2.0 随机化已于 2026-05-26 移除（commit `5da1bdf`），策略对低增益鲁棒性有限；实机还有电池电压跌落、关节摩擦/温升等仿真没有的软化因素，叠加后表现为"腿软"。
3. **观测与实机数据来源差异**【有代码证据】。sim 的角速度/线速度来自 MuJoCo 理想传感器（`teleopit/robots/mujoco_robot.py:96-106,184-200`），实机来自 LowState IMU 且**无 base_pos/base_lin_vel**（`teleopit/sim2real/unitree_g1.py:61-70`，`RobotState.base_pos=None` → `VelCmdObservationBuilder` 用 `[0,0,0]` 兜底，`teleopit/controllers/observation.py:248-250`）。实机 `ref_anchor_height`、FK 参考姿态等项与 sim 存在系统性偏差，策略在 sim 里没见过这种偏差。
4. **控制链路频率/时序差异**【有代码证据】。sim 内 PD 200 Hz 与 policy 50 Hz 在同一进程同步执行（`teleopit/sim/loop.py:63-73,300-321`）；实机 Python 50 Hz 写共享缓冲、C++ 线程 200 Hz 独立发布（`teleopit/sim2real/unitree_g1.py:95-116`），观测→命令之间天然多出一段拍延迟，且无观测-命令对齐机制。仓库自己的 `standalone_standing.py --obs-delay-ms/--command-delay-ms` 诊断参数（`scripts/run/standalone_standing.py:504-515`）就是作者为这类问题准备的。
5. **状态机进入流程 / Kp ramp 阶段暴露问题**【有代码证据】。`STANDING` 进入后 kp 从 10% 起 2 s 线性升满（`teleopit/sim2real/safety.py:63-76`，`teleopit/configs/pico4_sim2real.yaml:59-60`）；ramp 未完成或刚进 `MOCAP` 时增益仍偏低，若此时参考已要求抬腿，实机必然"抬不起来、重心后坐"。注意 `MOCAP ↔ ARMS` 切换也会重启 0.5 s ramp（`teleopit/sim2real/mp/runtime.py:2291-2294`）。

---

## 两条部署路径的差异对照

（sim 路径：`run_sim.py` → `TeleopPipeline` → `SimulationLoop`/`PolicyStepRunner` + `MuJoCoRobot`；real 路径：`run_sim2real.py` → `Sim2RealRuntime`/`_RobotControlWorker` + `UnitreeG1Robot` + `g1_bridge_sdk`）

| 环节 | Sim（pico4_sim.yaml） | Real（pico4_sim2real.yaml） | 差异/风险 |
|---|---|---|---|
| 输入 | `input.provider=pico4`（`teleopit/configs/pico4_sim.yaml:5`） | 同左（`teleopit/configs/pico4_sim2real.yaml:4` defaults） | 输入侧一致 |
| Retargeting (GMR) | 同一 `RetargetingModule`，进程内 | 独立 reference worker 进程 + ZMQ（`teleopit/sim2real/mp/runtime.py:857-`） | real 多一级 IPC 延迟与 stale 判断（`stale_reference_hold_s=0.08`，`pico4_sim2real.yaml:55`） |
| 观测构建 | `VelCmdObservationBuilder`，同一 167D | 同一 builder（`teleopit/sim2real/mp/runtime.py:1439-1452`） | builder 相同，但**输入数据源不同**（见下两行） |
| 关节状态 | MuJoCo qpos/qvel，理想无噪（`teleopit/robots/mujoco_robot.py:176-210`） | LowState `motor_state[i].q/dq`（`third_party/g1_bridge_sdk/src/g1_bridge.cpp:249-256`） | 实机有编码器偏置/噪声；训练时 joint_pos 噪声 ±0.01、joint_vel ±0.5（`train_mimic/tasks/tracking/tracking_env_cfg.py:71-78`） |
| IMU | MuJoCo gyro/velocimeter 理想值（`mujoco_robot.py:96-106,188-200`） | LowState IMU quaternion/gyroscope（`g1_bridge.cpp:257-263`） | 训练 ang_vel 噪声 ±0.2（`tracking_env_cfg.py:66-70`）；实机 IMU 需实测偏差 |
| base_pos | 有（MuJoCo `qpos[0:3]`） | **无**（`unitree_g1.py:61-70` 未填 `base_pos`） | obs 中 `ref_anchor_height` 用参考、robot anchor FK 用 `[0,0,0]` 兜底（`observation.py:247-252`） |
| 动作缩放 | `robot.action_scale` 数组（`g1.yaml:27-31`），经 `propagate_controller_defaults` 继承（`teleopit/runtime/factory.py:72-78`） | 同左（sim2real 也走 `_build_policy_components`，`mp/runtime.py:1439-1452`） | 一致（同一配置文件），排除 |
| clip | `clip_range=[-10,10]`（`controller/rl_policy.yaml:6`） | 同左 | 一致 |
| default 关节角 | `robot.default_angles`（`g1.yaml:21-25`，KNEES_BENT pose） | 同左，`default_dof_pos` 自动传播（`factory.py:66-70`） | 一致；但注意它来自 mjlab `KNEES_BENT_KEYFRAME`，若实机锁腰则 waist 三关节固定，策略仍按可动处理 |
| PD 增益 | `kps/kds`（`g1.yaml:9-19`），MuJoCo builtin PD（`mujoco_robot.py:119-133`） | `real_robot.kp_real/kd_real`（`pico4_sim2real.yaml:128-137`），直接下发 SDK | 数值相同（都来自 mjlab），但**执行体不同**：sim 是力矩限幅内的理想 PD，实机是电机固件 PD + 电池/温度/摩擦 |
| 力矩限幅 | XML forcerange ±88/139/50/25/5 Nm（`assets/robots/unitree_g1/g1_29dof.xml:272-300`） | 无前馈力矩（`tau=0`，`g1_bridge.cpp:301`），完全靠 kp 剪切 | 实机缺重力前馈时低 kp 直接表现为"软" |
| 控制频率 | policy 50 Hz + PD 200 Hz，同进程 decimation=4 同步（`sim/loop.py:63-73`；`runtime_components.py:300-321`） | policy 50 Hz Python 循环（`mp/runtime.py:1209`）+ C++ 200 Hz 发布线程（`g1_bridge.cpp:273-318`），异步解耦 | 实机观测-命令非同拍，等效多 1~2 拍延迟 |
| Kp ramp | 无（sim 一开始就是满增益 builtin PD） | `STANDING` 进入后 kp 10%→100% 2 s（`safety.py:63-76`；`pico4_sim2real.yaml:59-60`）；MOCAP→ARMS/返回 STANDING 0.5 s（`mp/runtime.py:2228-2233,2291-2294`） | real 独有的低增益窗口 |
| 关节限位 | XML `range`（硬约束） | `clip_to_joint_limits` 用 `joint_pos_lower/upper`（`safety.py:111-115`；`pico4_sim2real.yaml:142-155`） | 数值同源（GR00T），行为一致 |
| 状态机 | 键盘 Y/A/B/X（`sim/session.py:316-348`） | Unitree 遥控器 Start/Y/X + L1+R1 急停（`mp/runtime.py:1480-1525,1378-1382`） | 操作流程差异，见原因 12 |
| 模式切换 | 不涉及 | `enter_debug_mode` 逐个 release 运动模式（`unitree_g1.py:127-153`） | 若 G1 处于 ai_sport 之外的模式（如 damping），需要遥控器 L2+R2/L2+A 配合 |
| `mode_machine` | 不适用 | 硬编码 `MODE_MACHINE=5`（`g1_bridge.cpp:34,228,305`），从未读取 `lowstate.mode_machine`（`get_mode_machine` 存在但无人调用） | **机型不符时命令被静默丢弃/半执行** |

---

## 可能原因清单

### 1. 实机 kp/kd 低于官方建议刚度，且无重力前馈【有代码证据 + 官方一手资料】

- **机制**：`real_robot.kp_real` = mjlab 训练刚度：hip_pitch 40.2、hip_roll 99.1、hip_yaw 40.2、knee 99.1、ankle 28.5（`teleopit/configs/pico4_sim2real.yaml:128-137`；与 `g1.yaml:9-19` 相同，注释明确"passed directly to SDK — no scaling"）。前馈力矩恒为 0（`g1_bridge.cpp:301` `mc.tau() = 0.0f`），全部支撑力矩靠 `kp*(q_des-q)` 产生。Unitree 官方 low-level 示例腿部 kp 为 60/60/60/**100**/40/40、knee 100（`third_party/unitree_sdk2_python/example/g1/low_level/g1_low_level_example.py:18-32`，官方 C++ 示例同值）。本仓库 knee=99.1 与官方 100 相当，但 **hip_pitch 40.2 vs 官方 60**、**ankle 28.5 vs 官方 40**。抬腿动作需要髋屈肌群克服整腿重力 + 躯干反作用力，hip_pitch kp 偏低 1/3 会直接表现为"抬不到目标高度"。
- **为什么仿真没事**：MuJoCo builtin PD 在力矩上限 ±88/139 Nm 内是理想的（`mujoco_robot.py:119-133`），没有电池电压跌落、电机温升、减速箱摩擦；同样 kp 在 sim 里输出力矩"心想事成"，实机则达不到。且训练时的 PD 增益随机化（lower body kp×0.5~2.0）已于 2026-05-26 被移除（commit `5da1bdf`，diff 删除了 `motor_params_implicit_lower_body_pd`），策略对低增益的适应性有限。
- **验证**：
  1. 用 `scripts/run/standalone_standing.py --no-policy` 发零动作站立目标，观察是否下沉/抖动——这是纯 PD 支撑测试，排除策略因素；
  2. 临时把 `real_robot.kp_real` 的 hip_pitch 提到 60、ankle 提到 40（对齐官方示例值）再试 STANDING→MOCAP；
  3. 对比 LowState 中 `q` 与下发的 `q_des`（可在 Python 侧打印 `robot.get_state().qpos` vs `target_dof_pos`），若存在持续 0.1 rad 级别的稳态误差，即为 kp 不足。
- **修复**：提高 `kp_real`（或按官方 Gearbox 分组：hip_pitch/hip_yaw/waist_yaw 用 60，hip_roll/knee 用 100，ankle/waist_PR 用 40）；如需更大头部空间，考虑加入重力前馈 `tau`（当前 bridge 不支持，需扩展 `set_target`）。

### 2. `mode_machine` 硬编码 5，机型不匹配时命令半执行【有代码证据 + 官方一手社区资料】

- **机制**：`g1_bridge.cpp:34` 定义 `MODE_MACHINE = 5` 并在 `:228,:305` 直接写入每条 LowCmd；代码从不读取 `lowstate.mode_machine`（`get_mode_machine` 在 `:130,:372` 暴露但全仓库无调用）。Unitree 官方 `unitree_rl_lab` 维护者明确："lowcmd 的 mode_machine 必须与 lowstate 中该值相等，命令才可执行"（issue #6 评论，https://github.com/unitreerobotics/unitree_rl_lab/issues/6）；issue #114 中 29dof 假手机型需要把 5 改成 **6** 才有响应（https://github.com/unitreerobotics/unitree_rl_lab/issues/114）；官方 SDK 示例则是从 lowstate 读回该值再填入 lowcmd（`g1_low_level_example.py:121-123,138`）。
- **为什么仿真没事**：仿真根本没有 DDS/mode_machine 概念。
- **实机表现**：部分关节（尤其与机型差异相关的腰部/腕部）命令被丢弃，其余关节正常——机器人"想动但使不上劲"，重心向后坐倒。
- **验证**：连接机器人后运行 `python -c "import g1_bridge_sdk; b=g1_bridge_sdk.G1Bridge('<iface>'); b.wait_for_state(3); print(b.get_mode_machine())"`，把打印值与 `g1_bridge.cpp:34` 的 5 对比；或 `cyclonedds xml < cyclonedds.xml; cyclonedds subscribe rt/lowstate` 观察 `mode_machine` 字段。
- **修复**：把 bridge 改为像官方示例一样从 lowstate 读回 `mode_machine` 并回填 lowcmd（`g1_bridge.cpp` 的 `lowstate_callback` 已缓存该值，只需在 `publish_loop` 中使用）。

### 3. 机型不匹配（23/29/43 DoF、锁腰、假手）【官方一手资料】

- **机制**：G1 有 23/29/43 DoF 多种配置（官方 G1 Developer Guide，https://support.unitree.com/home/en/G1_developer；QRE 镜像文档 https://docs.quadruped.de/projects/g1/html/g1_overview.html）。本仓库策略、XML、`NUM_JOINTS=29`（`teleopit/constants.py`）全部按 29dof **含可动腰**建模；官方电机顺序表中 29dof 的 12/13/14 号为 WAIST_YAW/ROLL/PITCH（`unitreerobotics/unitree_mujoco` 的 `g1_joint_index_dds.md`，https://github.com/unitreerobotics/unitree_mujoco/blob/main/unitree_robots/g1/g1_joint_index_dds.md）。若实机是"29dof 但腰部锁定"或 23dof+腕部锁定机型，Teleopit 仍会向 waist（甚至不存在的自由度）下发命令并把这些关节的参考当作可控——腰部位姿错乱会直接改变质心，向后倒。
- **为什么仿真没事**：仿真用的就是 29dof XML。
- **验证**：同第 2 条读取 `lowstate.mode_machine`（官方表格：不同机型不同值，`unitree_rl_lab` issue #6/#114 中 23dof≈5、29dof 锁腰≈6 的经验值仅作参考）；同时手动轻推各 waist 关节确认是否可动。
- **修复**：机型不符时改用匹配的 XML/policy 组合（仓库目前只提供 29dof 与 29dof+neck+O6 两种，`CHANGELOG.md:8`），或锁定 waist 参考为实测值。

### 4. 关节顺序/命名映射错误【有代码证据——基本可排除，但有一处需实测确认】

- **机制**：仓库的 canonical 顺序 `G1_JOINT_NAMES`（`teleopit/constants.py:9-39`）为 L 腿 6 → R 腿 6 → waist 3 → L 臂 7 → R 臂 7，与官方 `g1_joint_index_dds.md` 29dof 表**逐位一致**（0-5 左腿、6-11 右腿、12-14 腰、15-21 左臂、22-28 右臂）；bridge 侧 `lowstate_callback` 按 `i=0..28` 顺序读 `motor_state[i]`（`g1_bridge.cpp:253-256`），policy 输出按同一顺序写 `motor_cmd[i]`（`g1_bridge.cpp:294-302`）。MuJoCo XML 的 joint/actuator 声明顺序也是同一顺序（`assets/robots/unitree_g1/g1_29dof.xml:76-248,272-300`）。**结论：顺序映射在代码层面一致，静态可排除。**
- **唯一需实测的点**：`mode_pr=0`（PR 模式，`g1_bridge.cpp:33`）下 4/5 号电机解释为 ANKLE_PITCH/ROLL；若实机固件处于 AB 模式语义，同样数值会被解释为 ANKLE_B/A。官方文档说明 PR 为默认且与 URDF 对应（https://support.unitree.com/home/en/G1_developer/basic_motion_routine），且 bridge 固定写 `mode_pr=0`，一般无风险。
- **验证**：dry-run 时打印 `robot.get_state().qpos`，让机器人摆一个明显不对称姿势（如只弯左膝），确认 `qpos[3]`（左膝）变化而 `qpos[9]`（右膝）不动。
- **修复**：无需修复；若发现互换，检查固件 PR/AB 设定。

### 5. `default_dof_pos`/`action_scale` 不一致【有代码证据——可排除】

- **机制**：sim 与 real 走同一个 `_build_policy_components` → `propagate_controller_defaults`（`teleopit/runtime/factory.py:66-78`），`controller.action_scale=null`、`default_dof_pos=null`（`controller/rl_policy.yaml:5,7`）时自动继承 `robot.action_scale` 与 `robot.default_angles`（`g1.yaml:21-31`）。`RLPolicyController.get_target_dof_pos` 统一执行 `clip*scale+default`（`teleopit/controllers/rl_policy.py:149-157`）。`g1.yaml:1-3` 还注明 action_scale 按 `0.25*effort/stiffness` 从 mjlab `g1_constants.py` 重算，并警示 `deploy.yaml` 的 `waist_yaw` 旧值有错。用 mjlab 公式复算（`https://github.com/mujocolab/mjlab` 的 `g1_constants.py` + `utils/actuator.py`）：5020→14.25/0.91、7520_14→40.2/2.56、7520_22→99.1/6.31、4010→16.8/1.07、ankle/waistPR(2×5020)→28.5/1.81；对应 action_scale 0.4386/0.5475/0.3507/0.0745/0.4386，与 `g1.yaml` 数组完全一致。**排除。**
- **验证**（若仍怀疑）：启动时打印 `controller.action_scale`、`controller.default_dof_pos`，与 `g1.yaml` 对比值；两套运行入口各打一次对比。

### 6. 观测差异：base_pos 缺失、IMU 偏差、坐标系约定【有代码证据】

- **机制**：
  - sim 的 `RobotState.base_pos` 来自 MuJoCo（`mujoco_robot.py:181`）；real 的 `UnitreeG1Robot.get_state` 不填（`unitree_g1.py:61-70`）。`VelCmdObservationBuilder.build` 中 `robot_base_pos` 为 None 时用 `[0,0,0]`（`observation.py:247-250`），随后用它做 robot anchor FK。sim 中该值真实、real 中恒 0——obs 里与 root 位置相关的项（如 `ref_anchor_height` 的相对关系、`ref_anchor_lin_vel_b` 投影）在两路径下语义不完全相同。
  - 实机 IMU 有安装角/漂移；训练只加了 ±0.2 rad/s 角速度噪声与 ±0.05 重力噪声（`tracking_env_cfg.py:66-70,117-120`）。若 HMD/机器人初始朝向对齐（`align_motion_qpos_yaw`，`observation.py:54-63`）在实机上有固定偏差，参考姿态整体偏转，策略持续输出纠偏力矩。
  - `anchor_body_name` 默认 `torso_link`（`factory.py:115`），实机腰部锁定时 torso_link FK 仍按 29dof 计算，与真实位姿有差。
- **为什么仿真没事**：sim 无这些系统性偏差。
- **验证**：dry-run 下让机器人静止站立，打印 167D obs 的 `robot_projected_gravity_b`（索引 154-156）是否接近 `[0,0,-1]`；打印 `robot_joint_pos_rel` 是否等于 `qpos-default_angles`；检查初始 quat 与参考 yaw 对齐结果。
- **修复**：若 IMU 偏差大，先做静止标定（本仓库无内置工具，可临时在 obs 构建前减去静态偏置）；确认 G1 摆放朝向与操作者朝向约定一致（教程要求 neutral pose + tracking valid 后再按 Y，`docs/docs/tutorials/pico-sim2real.md:114-124`）。

### 7. 控制频率/延迟/陈旧命令【有代码证据】

- **机制**：sim 中 policy 计算出的 target 立即在同一循环里被 200 Hz PD 消费（`runtime_components.py:300-321`）。real 中 Python 50 Hz `set_target` 只更新缓冲（`unitree_g1.py:95-116`），C++ 线程按自身节拍发布（`g1_bridge.cpp:273-318`），观测读取到命令生效之间无时间戳对齐；若 Python 循环超时（50 Hz 预算 20 ms），旧命令会被重复发布。Pico 参考链还多两级（reference worker → ZMQ → robot worker，`mp/runtime.py:846-1193`），`stale_reference_hold_s=0.08` 内的旧参考仍被消费（`mp/runtime.py:2010-2015`）。仓库作者专门给 `standalone_standing.py` 加了 `--obs-delay-ms/--command-delay-ms` 延迟注入诊断（`scripts/run/standalone_standing.py:504-515`，commit `f3b8568`）并给出分段计时 `--show-timing`（`:497`），说明这是已知风险点。动作延迟随机化训练也已于 2026-06-21 移除（commit `b83bccd`）。
- **为什么仿真没事**：sim 无网络/进程/DDS 延迟。
- **验证**：`standalone_standing.py --policy ckpt/track_g1.onnx --show-timing --obs-delay-ms 20 --command-delay-ms 20` 观察稳定性随延迟的退化曲线；sim2real 运行时开 `console.show_timing=true` 看 `loop_ms p95/p99` 与 `deadline_miss`。
- **修复**：把 policy 移到更快的机器/开启 CPU 绑核（曾尝试后回退，commit `f457f64`/`553842d`）；缩短参考链路；必要时降低 `stale_reference_hold_s`。

### 8. 网络接口/DDS 配置错误【有代码证据 + 上游一手 issue】

- **机制**：`real_robot.network_interface` 默认 `eth0`（`pico4_sim2real.yaml:126`），若填错接口，`wait_for_state(3.0)` 只 warning 不终止（`unitree_g1.py:47-48`），后续 `get_state` 返回全零——机器人收到基于全零状态的命令，行为完全不可预期。上游 issue #13 还记录了两套 DDS 库共存导致 `corrupted size vs. prev_size` 崩溃的案例（https://github.com/BotRunner64/Teleopit/issues/13）。
- **为什么仿真没事**：不涉及网络。
- **验证**：启动日志必须出现 `UnitreeG1Robot: state received`（`unitree_g1.py:50`）；dry-run 时打印 `qpos` 确认非全零且合理（站立位约 `[-0.312,0,0,0.669,-0.363,0,...]`）；运行 `python scripts/dev/bench_dds.py --interface <iface> --duration 10` 测吞吐。
- **修复**：`ifconfig` 找对接口（教程 `pico-sim2real.md:27-31`）；确认只有一套 CycloneDDS 库被加载。

### 9. G1 关节保护与增益组未解锁/未进入正确的低层模式【官方一手资料 + 社区经验】

- **机制**：G1 出厂处于 "ai"（release/motion-control）模式，低层控制前必须通过 MotionSwitcher release（本仓库 `enter_debug_mode` 自动做，`unitree_g1.py:127-153`）**且**机器人本体需处于允许低层控制的状态（遥控器 L2+R2 进 debug、L1+A damping、L2+A 低层就绪——见官方 Quick Start https://support.unitree.com/home/en/G1_developer/quick_start 与 QRE 控制表 https://docs.quadruped.de/projects/g1/html/operation_1.2.html）。官方 `unitree_rl_gym` issue #65 记录了"机器人在错误的模式，腿臂想动但卡住"，补按 L2+A 后 sim2real 完全正常（https://github.com/unitreerobotics/unitree_rl_gym/issues/65）。若 release 未完全生效，部分关节会保持出厂增益/限幅，表现为"无力"。注：任务提示中提到的 "L1A joint limit protection" 在 Unitree 官方公开文档中检索不到该名称，未采信为本仓库相关原因（标记为未证实）。
- **为什么仿真没事**：无模式概念。
- **验证**：日志确认 `enter_debug_mode: check_mode -> code=0, name=` 为空（`unitree_g1.py:136-138`）；观察机器人 LED 是否为 debug 模式色（社区经验为黄色，https://github.com/unitreerobotics/unitree_rl_gym/issues/65）。
- **修复**：按官方流程 L2+R2 →（必要时 L2+A）→ 再启动 Teleopit 并按 Start。

### 10. Retarget 目标超出实机能力【有代码证据（部分）】

- **机制**：GMR 输出的参考关节角/参考速度不含可达性过滤（`teleopit/retargeting/core.py:143-145` 直通）。obs 中 `ref_joint_vel` 由相邻参考差分 ×50 Hz 得到（`mp/runtime.py:2128-2133`），Pico 120 Hz 输入重采样后速度峰值可能远超实机关节速度限制；策略在 sim 中可以"瞬移"跟踪，实机跟不上就表现为腿"抬不到位"。另外 `input.human_height=1.75`（`input/pico4.yaml:4`）若与操作者身高差大，参考腿高/髋角整体偏移。
- **为什么仿真没事**：MuJoCo 关节无速度限幅（只有力矩限幅），"跟不上"在 sim 中代价小。
- **验证**：录制参考（`viewers=retarget` 可视化，`pico4_sim2real.yaml:8`）或加 `reference_debug_log=true`（`:19`）检查 `ref_joint_vel` 峰值（>10 rad/s 即可疑）；让操作者做慢速小幅度动作再进 MOCAP，对比成功率。
- **修复**：确认操作者身高设置；开始 MOCAP 后先做小慢动作（教程明确要求，`pico-sim2real.md:115-117`）；必要时降低 `reference_velocity_smoothing_alpha`（现 0.35，`pico4_sim2real.yaml:16`）以更激进地平滑参考速度。

### 11. MOCAP 进入/平滑流程问题【有代码证据】

- **机制**：`Y` 进入 MOCAP 需要 10 帧连续有效参考（`mocap_switch.check_frames=10`，`pico4_sim2real.yaml:158-160`；判定逻辑 `mp/runtime.py:2238-2257`），切换时策略历史被清零重启（`_transition_to_mocap` → `_reset_policy_state`，`mp/runtime.py:2259-2273`），且 **MOCAP 进入不重启 Kp ramp**（只有返回 STANDING/ARMS 才 ramp，`mp/runtime.py:2223-2233`）——若操作者从 STANDING 进入后立刻要求大幅抬腿，策略冷启动 + 参考跳变叠加。PAUSED 恢复同样重置状态（`_resume_paused_mocap`，`mp/runtime.py:2401-2418`），恢复时若人已离开 held pose，参考跳变。
- **为什么仿真没事**：sim 侧同样逻辑，但 sim 无真实失稳后果，且键盘流程节奏不同。
- **验证**：进入 MOCAP 后先保持静止 2 s 再缓慢动作，对比直接大幅动作的成功率；日志确认 `mode -> MOCAP` 出现时间与摔倒时间间隔。
- **修复**：严格按教程操作（neutral pose → Y → 小幅慢速，`pico-sim2real.md:114-124`）；暂停恢复时贴近 held pose。

### 12. 其他已排查、可明确排除的项

- **`joint_vel_limit` 触发**：该保护只在 `standalone_standing.py:311` 被调用，多进程 sim2real 主循环从未调用 `check_joint_velocity_safety`（全仓库 grep 仅两处命中），不会是"无声变软"的原因（但也意味着 sim2real 运行时没有这层保护）。
- **`clip_range` 双重缩放**：历史上出现过（commit `0a9bba7`），现 `compute_action` 返回原始输出、缩放只在 `get_target_dof_pos` 做一次（`rl_policy.py:140-157`），已排除。
- **`kd_damping`/`control_mode`/`msg_type` 配置键**：在 Python 代码中从未被读取（grep 无命中），是无效配置键，不影响行为（kd_damping 由 C++ 侧 `KD_DAMPING=8` 常量承担，`g1_bridge.cpp:38`）。
- **action scale 不一致**：见第 5 条，排除。
- **PD gains sim/real 数值不一致**：数值一致（同一来源），差异在执行体与增益绝对水平，见第 1 条。
- **关节顺序映射错误**：见第 4 条，静态排除。

---

## 推荐排查顺序

1. **确认 state 与机型**：启动日志必须有 `UnitreeG1Robot: state received`；随后 `python -c "import g1_bridge_sdk; ...print(b.get_mode_machine())"` 读实机 `mode_machine`，与 `g1_bridge.cpp:34` 的 5 对比。不一致 → 原因 2/3，改 bridge 回填 lowstate 值。
2. **纯 PD 站立测试（排除策略）**：`python scripts/run/standalone_standing.py --policy ckpt/track_g1.onnx --network-interface <iface> --no-policy` 观察零动作站立是否稳。软/沉 → 原因 1（kp 不足）或 9（模式未解锁）；稳 → 进入下一步。
3. **策略站立测试 + 分段计时**：去掉 `--no-policy` 加 `--show-timing`，看 `infer_ms/loop_ms/deadline_miss` 与 `qvel_norm`。超时多 → 原因 7/8。
4. **延迟敏感度注入**：`--obs-delay-ms 20 --command-delay-ms 20` 递增，若 20-40 ms 即失稳，说明策略对延迟敏感 → 原因 7，需要优化链路或在 sim 中复现后再调训练。
5. **对比 kp 版本**：把 `real_robot.kp_real` 的 hip_pitch 提到 60、ankle 到 40（官方示例值）重跑第 2/3 步，A/B 对比。改善 → 原因 1。
6. **静止时打印观测**：dry-run 打印 167D obs 的 `robot_projected_gravity_b`、`robot_joint_pos_rel` 与 `qpos`，验证 IMU 偏差与关节读数正常 → 原因 6/4。
7. **参考可视化**：`viewers=retarget` 打开参考窗口，确认 GMR 参考本身合理（速度峰值、腿高）→ 原因 10。
8. **规范 MOCAP 操作流程**：neutral pose → Y → 静止 2 s → 小幅慢速动作，统计失稳时机 → 原因 11。
9. **向上游求证**：以上都排除后，在上游 https://github.com/BotRunner64/Teleopit/issues 附 `--show-timing` 输出与现象视频（issue #13/#21 是同类 sim2real 讨论的先例）。

---

## 附：本报告引用的外部一手资料

- Unitree 官方 G1 低层示例（kp/kd、关节索引、mode_pr、MotionSwitcher 流程）：
  - https://github.com/unitreerobotics/unitree_sdk2_python（本仓库 `third_party/` 内副本 `example/g1/low_level/g1_low_level_example.py`）
  - https://github.com/unitreerobotics/unitree_sdk2/blob/main/example/g1/low_level/g1_ankle_swing_example.cpp
- Unitree 官方 G1 电机顺序表：https://github.com/unitreerobotics/unitree_mujoco/blob/main/unitree_robots/g1/g1_joint_index_dds.md
- Unitree 官方 G1 文档：https://support.unitree.com/home/en/G1_developer （Quick Start / Basic Services Interface / Basic Motion Routine / Motion Switcher Service Interface 各子页）
- mjlab（训练基座）G1 常数：https://github.com/mujocolab/mjlab/blob/main/src/mjlab/asset_zoo/robots/unitree_g1/g1_constants.py
- Unitree 官方部署仓库社区 issue（机型/mode_machine/模式问题）：unitree_rl_lab #6、#114、#44；unitree_rl_gym #65、#26、#89
- 上游 Teleopit issue：#13（DDS 崩溃/接口名）、#21（Pico 动捕反向/pico-bridge 版本）
