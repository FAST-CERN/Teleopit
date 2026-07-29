---
sidebar_position: 3
---

# 用 VR 遥操真实 G1

本教程把已经跑通的 Pico 仿真遥操迁移到真实 Unitree G1。动作输入没有变化；新增加的
关键环节是 G1 网络、DDS bridge 和安全的模式切换。

:::danger 始终把 Unitree 遥控器拿在手里
动作异常时立即按 `L1+R1` 进入 `DAMPING`。第一次运行时清空机器人周围空间，并安排
一名操作者随时扶住或停止机器人。
:::

## 开始之前

下面每一项都满足后再继续：

- [在仿真中进行 VR 遥操](pico-sim2sim)已经稳定运行；
- 已按照[安装说明](../getting-started/installation)安装 `pico4` 依赖并编译
  `g1_bridge_sdk`；
- `track.onnx`、机器人资源和 GMR 资源都已下载；
- 运行 Teleopit 的电脑通过有线网络连接 G1 DDS；
- 没有其他程序正在向机器人发送控制命令。

Teleopit 可以运行在通过网线连接 G1 的外部电脑上，也可以运行在机器人 onboard
电脑上。Pico 始终直接连接运行 Teleopit 的那台电脑。

## 1. 找到 G1 使用的网卡

列出 Linux 网卡：

```bash
ip -br link
```

外部电脑使用连接 G1 的有线网卡，例如 `enp130s0`；onboard 电脑通常使用 `eth0`。

运行参数写成：

```text
real_robot.network_interface=enp130s0
```

这个网卡只负责 Unitree DDS。如果 Pico 自动发现选择了错误的 Wi-Fi 或网口地址，
需要另外设置 `input.bridge_advertise_ip`。

## 2. 先单独检查站立运控

在接入 Pico 之前，先运行真机流程使用的同一套站立运控：

```bash
python scripts/run/standalone_standing.py \
    --policy track.onnx \
    --network-interface enp130s0 \
    --dry-run
```

`--dry-run` 会检查机器人状态接收和运控时序，但不发送电机命令。在安全的硬件环境中
确认无误后，再去掉 `--dry-run`：

```bash
python scripts/run/standalone_standing.py \
    --policy track.onnx \
    --network-interface enp130s0
```

如果这一步失败，请停在这里并查看[独立站立检查](standalone-standing)。Pico 无法
解决 G1 bridge 或运控模型本身的问题。

## 3. 启动 Pico 真机遥操

外部电脑示例：

```bash
python scripts/run/run_sim2real.py \
    --config-name pico4_sim2real \
    controller.policy_path=track.onnx \
    real_robot.network_interface=enp130s0
```

onboard 电脑示例：

```bash
python scripts/run/run_sim2real.py \
    --config-name pico4_sim2real \
    controller.policy_path=track.onnx \
    real_robot.network_interface=eth0
```

启动进程并不会立刻让 Pico 接管机器人。

## 4. 主动、逐步地交出控制权

1. 按遥控器 `Start` 进入 `STANDING`。
2. 等待机器人稳定，同时确认 Pico 追踪有效。
3. 操作者以中立姿态站好，周围留出足够空间。
4. 按遥控器 `Y` 进入 `MOCAP`。
5. 先从小幅慢动作开始。
6. 需要回到站立时按遥控器 `X`。

| 控制 | 作用 |
|------|------|
| Unitree 遥控器 `Start` | 进入 `STANDING` |
| Unitree 遥控器 `Y` | 开始全身 VR 控制（`MOCAP`） |
| Unitree 遥控器 `B` | 暂停或恢复当前动捕会话 |
| Pico/controller `A` | 暂停或恢复当前动捕会话 |
| Pico/controller `B` | 在全身 `MOCAP` 和仅手臂 `ARMS` 之间切换 |
| Unitree 遥控器 `X` | 结束 VR 控制并返回 `STANDING` |
| Unitree 遥控器 `L1+R1` | 紧急停止（`DAMPING`） |

进入 `MOCAP` 之前，Teleopit 会连续检查多帧 Pico 数据。检查失败时，机器人会继续
留在 `STANDING`。

### 暂停和恢复

暂停会保持当前参考姿态，不会让机器人回到 `STANDING`。恢复时，系统会根据操作者
当前姿态重新建立实时对齐。恢复前请站稳，并尽量保持在暂停姿态附近。需要结束 VR
会话时使用遥控器 `X`。

### Pico 或视频中断时会怎样？

Pico 输入和视频预览都不是关键控制进程。Pico 输入停止后，G1 控制循环会继续保持
最后一个安全命令，Unitree 遥控器仍然可用。RealSense 超时只会关闭或重连视频，
不会停止身体控制。此时请主动按遥控器 `X` 或 `L1+R1`，不要等待系统自动切换模式。

## 可选：LinkerHand 控制

没有连接 LinkerHand 时请跳过本节。先按照[安装说明](../getting-started/installation)
安装手部依赖，再启动两个 CAN 接口：

```bash
sudo /usr/sbin/ip link set can0 up type can bitrate 1000000
sudo /usr/sbin/ip link set can1 up type can bitrate 1000000
```

启动机器人之前先单独测试手：

```bash
python scripts/dev/test_linkerhand.py \
    --driver linkerhand_o6 \
    --hand-type both \
    --left-can can0 \
    --right-can can1
```

启用 O6 手势追踪时，在主命令后增加：

```text
hands.enabled=true
hands.driver=linkerhand_o6
hands.mode=vr_hand_pose
hands.linkerhand_o6.left_can=can0
hands.linkerhand_o6.right_can=can1
```

使用手柄扳机开合时设置 `hands.mode=gripper`。系统也支持 `linkerhand_l6`，此时使用
对应的 `hands.linkerhand_l6.*` CAN 参数。手部控制在所有机器人模式下都保持工作；
手部进程出错时会发送张开手的命令。

## 可选：OpenNeck 主动视觉

没有安装和标定 OpenNeck 时请跳过本节：

```bash
pip install -e '.[openneck]'
openneck calibrate
```

在主命令后增加：

```text
neck.enabled=true
neck.port=/dev/ttyACM0
```

OpenNeck 根据 Pico 头显相对操作者上半身的方向转动。它复用身体控制的 Pico 接收器，
不会再启动第二个 PicoBridge。

## 可选：在头显中预览 RealSense

安装 `pyrealsense2` 后，在主命令后增加：

```text
input.video.enabled=true
input.video.device=<可选的-realsense-序列号>
```

RealSense 超时后会在后台重连。相机失败不会停止 Pico 追踪或 G1 控制。

## 可选：录制和查看数据

录制需要安装 `recording` 依赖，并且 RealSense 能提供新鲜 RGB 帧：

```bash
python scripts/run/run_sim2real.py \
    --config-name sim2real_record \
    controller.policy_path=track.onnx \
    real_robot.network_interface=enp130s0 \
    recording.task="walk forward"
```

| 终端按键 | 作用 |
|----------|------|
| `R` | 开始一条 episode |
| `S` | 保存当前 episode |
| `D` | 丢弃当前 episode |
| `Q` | 关闭程序 |

如果连续一秒没有新鲜视频帧，当前 episode 会被丢弃，但机器人控制会继续。视频恢复后
需要手动开始新的 episode。

查看已保存数据：

```bash
pip install -e '.[review]'
python scripts/view/view_recording.py \
    --recording data/recordings/sim2real_hdf5
```

查看器会同步显示相机视频、G1 实测/参考姿态和可选的手部/颈部信号。录制目录和字段
定义见[数据集参考](../reference/dataset)。

## 常见问题

| 现象 | 处理方法 |
|------|----------|
| 收不到 `LowState` | 检查网线和 `real_robot.network_interface` |
| 无法导入 `g1_bridge_sdk` | 在当前环境重新运行 `scripts/setup/setup_g1_bridge.sh` |
| 按 `Start` 无法进入站立运控 | 停止其他 Unitree 模式和控制程序后重试 |
| 按 `Y` 无法进入 `MOCAP` | 保持 Pico 追踪有效且稳定，检查动捕验证日志 |
| 暂停后没有回到站立 | 这是正常行为；请使用遥控器 `X` |
| Pico 找不到 Teleopit | 把 `input.bridge_advertise_ip` 设为头显能访问的地址 |
| LinkerHand 不动 | 检查 `hands.enabled`、driver/mode、CAN 状态和独立手部测试 |
| Arm 设备上 RealSense 不可用 | 从 conda-forge 安装 `pyrealsense2` |

## 其他 G1 运行方式

主线教程以 Pico VR 为主。以下页面保留给较少使用的硬件检查和部署场景：

- [独立站立检查](standalone-standing)
- [在 Unitree G1 上回放 BVH](bvh-sim2real)
- [在 Unitree G1 上部署 Host Policy](high-level-policy-sim2real)
