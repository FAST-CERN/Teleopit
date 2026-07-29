---
sidebar_position: 1
slug: /
---

# Teleopit

Teleopit 是一套面向 Unitree G1 的**全身具身遥操作系统**。操作者戴上
Pico 4 或 Pico 4 Ultra 后，可以实时控制机器人的全身动作；接入可选的
LinkerHand 后，还能控制手势；接入可选的 OpenNeck 后，头部动作可以直接控制
机器人相机的朝向。

同一套运控策略会先在 MuJoCo 中运行。你可以先在仿真里确认动作和控制方式，再连接
真实机器人。

## 从这里开始

第一次使用 Teleopit 时，建议按这个顺序：

1. 根据自己的目标[安装 Teleopit](getting-started/installation)，并完成该页面最后的
   安装检查。
2. 从下面四条路径中选择一条继续。

| 我想做什么 | 对应教程 |
|------------|----------|
| 在 MuJoCo 中检查运控策略 | [在仿真中运行运控](tutorials/offline-sim2sim) |
| 不连接真机，先尝试 Pico VR 遥操 | [在仿真中进行 VR 遥操](tutorials/pico-sim2sim) |
| 使用 Pico VR 控制真实 G1 | [用 VR 遥操真实 G1](tutorials/pico-sim2real) |
| 训练并导出自己的运控策略 | [训练运控策略](tutorials/training) |

:::warning 连接真机之前
请先把 Pico 仿真遥操跑通。真机运行时始终把 Unitree 遥控器拿在手里；
`L1+R1` 是进入 `DAMPING` 的紧急停止方式。
:::

## 想了解实现细节？

主线教程只保留完成任务所需的内容。运行流程和技术规格见
[系统架构](reference/architecture)，下载文件与资源分组见
[资源参考](reference/assets)，Hydra 参数见[配置说明](configuration/overview)。
