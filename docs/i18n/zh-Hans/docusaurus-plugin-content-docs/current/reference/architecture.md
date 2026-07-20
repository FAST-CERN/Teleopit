---
sidebar_position: 1
---

# 架构

面向开发者的系统内部结构和技术约束。

## Pipeline

```text
InputProvider（BVH 文件 / Pico4）
    -> Retargeter（GMR）
    -> ObservationBuilder（167D）
    -> Controller（双输入 TemporalCNN ONNX）
    -> Robot（MuJoCo 仿真或 Unitree G1）
```

离线/在线推理由 `teleopit/runtime/` 和 `teleopit/pipeline.py` 装配。硬件状态机通过 `teleopit/sim2real/mp/` 中的进程隔离运行时执行。训练由 `train_mimic/` 提供。

由主机提供服务的模仿策略使用第二条相互独立的部署路径：

```text
lerobot-teleopit 主机环境
  policy server -> 严格的 ZeroMQ/msgpack 消息
                       |
Teleopit onboard 环境
  RealSense/state -> 非关键 client worker -> 已验证的 action scheduler
  -> 现有 50 Hz motion tracker -> G1 关节角目标
  -> 专用 LinkerHand O6 与 OpenNeck worker
```

主机与 onboard 环境共享语义数据和一份相同的 `hand_calibration.json`；它们不会导入
对方的 Python 包。当前 client/server 代码和协议测试定义网络结构，因此活跃开发期间
两个仓库必须同步修改。Pico 遥操作和主机策略部署也分别使用不同的运行脚本与进程装配。

## 代码结构

```text
configs / scripts
    -> runtime
    -> interfaces + pipeline state machines
    -> adapters（inputs / retargeting / controller / robot / recording）

train_mimic/scripts
    -> train_mimic/app.py
    -> single task registry / env builder / runner cfg
    -> mjlab / rsl_rl

train_mimic/scripts/data
    -> train_mimic/data/dataset_builder.py
    -> dataset_lib / motion_fk / convert_pkl_to_npz
```

## 核心模块边界

| 模块 | 职责 |
|------|------|
| `teleopit/interfaces.py` | 稳定协议：InputProvider、Retargeter、Controller、Robot、ObservationBuilder |
| `teleopit/runtime/` | 配置解析、路径规范化、组件装配、CLI 校验 |
| `teleopit/pipeline.py` | 离线仿真的轻量 facade |
| `teleopit/sim2real/mp/` | 进程隔离的 sim2real 状态机、IPC 和机器人控制循环 |
| `teleopit/high_level_policy/` | 主机策略协议、session-local 坐标变换、验证与 30-to-50 Hz scheduler |
| `teleopit/controllers/observation.py` | ObservationBuilder |
| `teleopit/controllers/rl_policy.py` | 接受观测维度与运行时 builder 匹配的双输入 ONNX |
| `train_mimic/app.py` | 共享的训练/播放/benchmark 装配 |
| `train_mimic/tasks/tracking/config/` | 单一任务注册（`General-Tracking-G1`） |
| `train_mimic/data/dataset_builder.py` | 唯一官方数据集构建入口 |

## 技术规格

| 项目 | 规格 |
|---|---|
| 训练任务 | `General-Tracking-G1` |
| 推理观测 | `velcmd_history`（167D） |
| ONNX 签名 | 双输入 `obs`（167D）+ `obs_history` |
| Actor/Critic | TemporalCNN（2048、1024、512、256、128） |
| 训练采样 | 默认 `rewind`；也支持 `uniform`；播放使用 `start`；benchmark 固定精确 clip 并禁用 clip 末尾重采样 |
| 训练 `window_steps` | `[0]` |
| 数据格式 | 可递归发现的最小 HDF5 shard（`shard_*.h5`） |
| 主机策略 observation | JPEG RGB + `observation.state(68)` |
| 主机策略 action | 30 Hz 的 `float32[T,50]` canonical reference |
| 主机策略 body 控制 | 36D root/joint reference 通过现有 50 Hz motion tracker |

## 约束

- 必须显式提供 `controller.policy_path`，且文件必须存在
- 离线 BVH 运行必须显式提供 `input.bvh_file`
- `viewers` 是唯一的 viewer 配置入口
- 观测/ONNX 维度不匹配会在启动时立即报错
- sim2real 也要求双输入 ONNX，且观测维度必须与运行时 builder 匹配
- 主机策略消息 envelope 或 schema 不匹配时会被拒绝，机器人保持在 `STANDING`
- 主机 action chunk 在 onboard 完成验证与插值；主机不能绕过 motion tracker 或发送电机命令
- 策略 entry 保持为 `STANDING` 内部流程：通过一次 Kp ramp 保持经过验证的候选第一帧，然后要求一个新 host session 提供完整通过验证的 chunk；正式接管模式只有 `POLICY`

## 公共接口

**稳定运行模式：** 离线 sim2sim、离线 sim2real playback、Pico4 sim2sim、G1
sim2real、独立的主机策略 G1 sim2real

**稳定训练入口：** `train.py`、`play.py`、`benchmark.py`、`save_onnx.py`

**稳定数据入口：** `build_dataset.py`、`precompute_dataset.py`
