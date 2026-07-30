---
sidebar_position: 6
---

# 在 Unitree G1 上部署主机策略

该工作流在主机工作站上运行 LeRobot 策略服务，在 G1 onboard 计算机上运行
Teleopit motion tracker。两个仓库使用相互独立的 Python 环境，只通过严格的
ZeroMQ/msgpack 消息通信。

```text
主机工作站（lerobot-teleopit）
  ReplayPolicy 或 ACT -> policy server
                              |
                              | 通过 TCP 传输 float32 state/action + JPEG
                              v
G1 onboard 计算机（Teleopit）
  RealSense + G1 state -> 异步 client -> 已验证的 30 Hz action plan
  -> 按时间戳对齐的 receding-horizon 替换
  -> 50 Hz 插值 -> motion tracker -> G1 关节角目标
                 -> LinkerHand O6 / OpenNeck
```

这是与 Pico 遥操作相互独立的运行时。该工作流不应启动 PicoBridge、GMR 或
`run_sim2real.py`。在 Pico 控制与主机策略控制之间切换时，需要先停止一个运行时，
再启动另一个。

## 1. 网络消息与手部标定

当前 client/server 代码和协议测试定义 request 与 response 结构。活跃开发期间，
任何结构变更都必须同时修改 Teleopit 和 `lerobot-teleopit`；不支持旧网络 envelope。

两个仓库唯一共享的数据文件为：

```text
lerobot-teleopit/src/lerobot_teleopit/hand_calibration.json
Teleopit/teleopit/high_level_policy/hand_calibration.json
```

`hand_calibration.json` 定义 LinkerHand O6 的 raw open/close 值和 range tolerance。
当前 `describe` 响应将 68D observation 标识为 `teleopit-g1-state`，将 canonical 50D
action 标识为 `teleopit-g1-reference`。action 布局和使用物理角度的 OpenNeck 命令由
当前代码与测试约束。

canonical action 布局为：

```text
[0:3]    session-local root x/y 与绝对 z
[3:7]    session-local root quaternion，wxyz
[7:36]   G1 29D reference joint positions，弧度
[36:48]  左/右 LinkerHand O6 closure，[0, 1]
[48:50]  OpenNeck yaw/pitch，物理角度
```

主机发送的是 reference motion，而不是 G1 电机命令。Teleopit 会把 body slice 送入
现有 motion tracker，由它为本地 G1 控制器生成关节角目标。

## 2. 准备主机

在工作站上使用独立的 `lerobot-teleopit` 环境。首次网络测试应先运行
ReplayPolicy，再使用 ACT：

```bash
cd /path/to/lerobot-teleopit
uv run teleopit-policy-server \
  --dataset-root data/lerobot/teleopit_v3 \
  --repo-id local/teleopit_v3 \
  --episode 0 \
  --chunk-size 15 \
  --bind tcp://0.0.0.0:5555
```

使用 ACT 时，改用主机仓库中的 checkpoint 命令。只在可信的机器人网络上放行 TCP
端口 `5555`。该协议有意不提供远程关机或电机控制 endpoint。

## 3. 准备 Onboard 运行时

在 Teleopit 自己的环境中安装 Teleopit 与硬件依赖：

```bash
pip install -e '.[openneck]'
git submodule update --init --recursive
pip install -e third_party/linkerhand-python-sdk
bash scripts/setup/setup_g1_bridge.sh
```

需要根据 onboard 平台单独安装 `pyrealsense2`。在 Arm 系统上，conda-forge 包通常
最可靠。

启动前开启两个 LinkerHand CAN 接口：

```bash
sudo /usr/sbin/ip link set can0 up type can bitrate 1000000
sudo /usr/sbin/ip link set can1 up type can bitrate 1000000
```

使用 OpenNeck 0.2.0 完成校准；如果校准文件不在运行目录中，请设置
`neck.config_path`。

## 4. 启动 Teleopit

运行专用 onboard 入口，并设置主机 IP、底层 tracking policy 和 G1 网卡：

```bash
python scripts/run/run_high_level_policy_sim2real.py \
  controller.policy_path=ckpt/track_g1_neck_o6.onnx \
  high_level_policy.endpoint=tcp://192.168.1.10:5555 \
  high_level_policy.task="pick up the object" \
  real_robot.network_interface=eth0
```

协议接受 1 到 50 帧的 action chunk。当前 ACT 主机会返回完整的 checkpoint horizon
（生产 checkpoint 为 50 帧）；ReplayPolicy 最多返回 `--chunk-size` 配置的帧数，
最后一段可以更短。

Teleopit 每隔 `high_level_policy.replan_steps` 个 30 Hz source frame 提交最新的合格
observation，默认间隔为三帧。该 stride 不得超过主机 `describe` 响应中的
`max_action_horizon`。隔离的 client 同一时间只允许一个 REQ/REP exchange，但该请求
在途时 active plan 会继续执行。ACT 主机使用回显的 onboard 单调时间戳聚合相互重叠的
prediction；Teleopit 使用同一时间戳，在正确的 source-frame 位置替换 active plan。

生产相机契约固定为 30 Hz 的 RGB `uint8[480,640,3]`。
`camera.source=test-pattern` 只用于受控集成测试；部署时应使用
`camera.source=realsense`。

## 5. 操作流程

始终把 Unitree 遥控器拿在手中。该运行时只有 `IDLE`、`STANDING`、`POLICY` 和
`DAMPING` 四个正式机器人模式。

| 控制 | 动作 |
|------|------|
| Unitree remote `Start` | 进入 `STANDING` |
| Unitree remote `Y` | 请求主机策略接管 |
| Unitree remote `B` | 暂停或恢复 `POLICY` |
| Unitree remote `X` | 返回 `STANDING`，或取消等待中的请求 |
| Unitree remote `L1+R1` | 紧急切换到 `DAMPING` |

按下 `Y` 后，Teleopit 会创建一个 entry session，以当前 root XY/yaw 建立锚点，并请求
该 session 的第一份 chunk。等待期间机器人在形式上仍处于 `STANDING`；没有单独的
“policy starting”状态。运行时会验证 chunk 的结构、有限值、四元数和绝对硬件范围，
同时接受 root、yaw 和关节 reference 的时间跳变。第一份有效 chunk 会直接进入
`POLICY`。entry 不会对齐候选 reference、运行 Kp ramp、暂停/恢复 host 请求，也不会
创建或 reset 第二个 session。scheduler 的 50 Hz 输出 limiter 从 session 开始时捕获的
机器人实测 reference 起步。失败或超时会让机器人保持普通 standing reference。

在 `POLICY` 内，较新的 response 通常会在 active plan 的 horizon 结束前替换它。如果
推理耗时更长，Teleopit 会在配置的 `hold_s` grace period 内保持该计划最后一条 body、
hand 和 neck target，同时本地 50 Hz 控制循环继续运行。超过该 grace period 会触发
action watchdog，并进入普通的可恢复暂停。

暂停会冻结 body reference，并保持最后一条 LinkerHand 和 OpenNeck 命令。恢复时会请求
新的 action chunk，并在等待期间继续保持暂停姿态。按 `X` 会停止策略 session；运行时
返回 `STANDING` 时会张开手并让辅助硬件回中。

Watchdog、主机/网络、相机或 policy client 故障也会进入同一个普通暂停状态，并保持
当前 body、hand 和 neck 命令。输入路径恢复后按 `B`；Teleopit 会继续保持暂停姿态，
直到收到新的有效 action chunk，再恢复 `POLICY`。运行时不会自动进入 `STANDING`；
`X` 仍是手动切换到 `STANDING` 的操作。

## 6. Onboard 验证与 Watchdog

当修正量不超过 `max_joint_projection_rad` 时，Teleopit 会先把 G1 关节 reference 裁剪到
配置的真机关节位置范围，并把 OpenNeck yaw/pitch 命令裁剪到配置的角度范围；如果任一帧
违反其余契约，则拒绝整个 chunk。它不会对错误的主机结果进行补齐或删减。检查包括：

- 精确且有限的 `float32[T,50]`、当前 session，以及递增的 source sequence；
- 归一化 root quaternion 与时间连续的符号；
- 绝对 root 高度限制；
- 按 `real_robot.joint_pos_lower/upper` 裁剪 G1 关节位置，并拒绝更大的修正量；
- LinkerHand closure `[0,1]`；
- 将 OpenNeck yaw/pitch 裁剪到配置的角度范围；
- observation/result 时效、source timestamp 和 action horizon。

reference 连续性不是接收条件。entry、chunk 内部和 chunk 之间的 root translation、root
yaw 与 G1 关节 reference 跳变都会被接受，因为录制的 pause/resume 转换可能有意地不
连续；50 Hz 输出 limiter 会衔接这些已接受的跳变。单个 entry session 的第一份有效
chunk 会立即开始实时执行。格式错误、过期、非关节字段超出绝对范围（已裁剪的 OpenNeck
角度除外）或关节修正量过大会终止 entry。

通过验证的 30 Hz body reference 会在本地插值到 50 Hz 并执行 rate limit。回显的
source timestamp 用于选择每份 response 中的当前位置，因此主机延迟可以跳过已经过去的
source frame，较新的 chunk 也可以替换执行中的计划。配置的 root displacement/XY
speed、yaw rate 和 joint rate 是输出限制，而不是 chunk 拒绝阈值。plan horizon 结束后，
最后一条有效 reference 会继续保留 `hold_s`。如果网络交换超时、watchdog 到期，或必要的
camera/client worker 退出，Teleopit 会保持在 `POLICY`，进入普通的可恢复暂停状态，并保持
最后一条 body、hand 和 neck 命令。无效或过期 response 会被拒绝，不会替换当前仍然有效的
plan。故障恢复后按 `B` 请求恢复；在收到新的有效 chunk 前，执行仍保持暂停。只有 `X`
会把模式切换到 `STANDING`。

默认安全范围位于 `high_level_policy_sim2real.yaml` 的
`high_level_policy.safety` 下。只有在检查录制数据、G1 关节限位和已安装的 OpenNeck
校准后，才应调整这些值。

## 7. 故障排查

**按 `Y` 后始终不进入 `POLICY`：** 检查主机 endpoint、防火墙、server 日志、
`describe` schema、消息 envelope、task、checkpoint manifest、`replan_steps` 和 entry
日志。Teleopit 会保持 `STANDING`，直到单个 entry session 返回第一份有效 chunk。

**第一份 entry chunk 被拒绝或 entry 超时：** 请检查日志中的契约错误、关节顺序、绝对
reference 约定、硬件范围以及 host/network 延迟。单纯的 reference 跳变不会导致 chunk
被拒绝。

**策略短暂运行后进入暂停：** 检查 timeout、推理延迟、stale result、worker 退出和
安全拒绝日志。底层 50 Hz tracker 不会等待主机推理；当前 plan 会继续执行，随后使用配置的
最终 reference grace period。恢复故障输入路径后按 `B` 继续。

**Pico 无法连接：** 该运行时有意不启动 Pico。请先停止它，再改用 Pico 专用的
`run_sim2real.py --config-name pico4_sim2real` 工作流。
