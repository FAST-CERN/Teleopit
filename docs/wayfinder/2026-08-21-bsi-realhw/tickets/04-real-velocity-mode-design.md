---
id: bsi-realhw-04
title: "真机 VELOCITY 模式接线设计（ONNX 速度策略 sim2real）"
labels: [wayfinder:grilling]
status: closed
assignee: "claude/main"
blocked-by: [bsi-realhw-01, bsi-realhw-02, bsi-realhw-03]
created: 2026-08-21
---

## Question

Q8=A 定架：mp 运行时（`teleopit/sim2real/mp/runtime.py` `_RobotControlWorker`）新增 `RobotMode.VELOCITY` 分支，复用 sim 的 twist→ONNX→关节目标栈。待决设计点：

1. **状态机映射**：sim `VelocitySimSession` 的 V/X、E 急停锁存、STANDING↔VELOCITY 语义如何落到真机 RobotMode 机（现有 STANDING/MOCAP/POLICY）；estop latch 的真机等价物。
2. **指令源接入**：`MergedTwistProvider`（Pico 摇杆优先 + BSI，Q4 语义）+ `DdsIntentSource` 在 mp 运行时的构建位置（哪个进程、哪台机器）。
3. **策略复用与校验**：`build_velocity_policy_components` 直接复用的差异面（obs builder 输入改自 `UnitreeG1Robot.get_state()`）；`_multi_input` sim2real 校验门；pd_hz 200 / policy_hz 50 不变量。
4. **配置与入口**：真机 velocity yaml（自 pico4_sim_bsi 派生）+ `run_*` 入口脚本形态。

边界：locomotion-only，无上身并发（Q9）。产出：设计决策——后续 superpowers plan 的直接输入。

## Resolution

**2026-08-21 grilling 三问定案（D1/D2/D3）+ 事实定死（点 3）**，架构 = `Sim2RealRuntime` 内加模式（不建 runtime 变体）：

- **模式键（D1）**：Pico 控制事件 `TOGGLE_VELOCITY`，复用 TOGGLE_ARMS 管线（pico_input → CONTROL_EVENTS_TOPIC → robot_control 事件处理）；具体按钮配置化，实现时定。进入门 = 仅 STANDING（同 sim V 语义）；退出（X 语义）→ `standing_return_ramp` 回站；estop 锁存期拒绝进入（sim latch 语义照搬）。
- **指令源（D2）**：BSI 订阅器 + `MergedTwistProvider` 全住 **robot_control 进程**：`build_merged_bsi_provider`（lazy-import + 可注入 reader_factory，cyclonedds 保持可选）+ 摇杆半边加 `CONTROLLER_TOPIC` LatestSubscriber（PicoJoystickProvider 适配 ZMQ snapshot）。消费同 sim：每 policy step 一次 `get_cmd()`。DDS 故障→静默 1s→IDLE 即安全行为，无需进程隔离。
- **策略复用（事实定死，无决策）**：`TwistCmdObservationBuilder` 与真机 `RobotState` **完全接口兼容**（只用 qpos[:29]/qvel[:29]/quat/ang_vel；base_pos 缺失无关）；velocity 策略 `single_input_ok=True`，**无需** mimic 的 `_multi_input` 双输入门；policy_hz 50 / LowCmd 200Hz 两侧一致。
- **配置/入口（D3）**：新 `pico4_sim2real_bsi.yaml`（自 pico4_sim2real 派生，加 `controllers.velocity` + `command.provider: merged_bsi` + `command.bsi.*`/`command.joystick.*`），入口复用 `run_sim2real.py --config-name`；command 段缺省不构建。

**附带事实（喂 05）**：mp 路径 `joint_vel_limit` 未被执行（仅 standalone_standing 调用）；TOGGLE_ESTOP/TOGGLE_MUTE 事件今天被静默丢弃（优雅急停缝 90% 现成）；**L1+R1 遥控器 damping = Q5 的硬件级安全底，已存在**。

实现细节（按钮选键、pose B 来源、obs 实例化差异）交后续 superpowers plan。
