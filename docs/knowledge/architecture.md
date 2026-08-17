# 软件架构（architecture）

> 返回 [`knowledge/` 索引](README.md)。
> 本文是 Teleopit 的**架构地图**：用最少的篇幅让一名新工程师看懂「这个系统由什么组成、
> 数据怎么流动、在哪里扩展」。技术细节契约以根 [`AGENTS.md`](../../AGENTS.md) 为准；
> 用户视角的架构页在[用户文档站](../docs/reference/architecture.md)。

---

## 1. 系统一句话

Teleopit 是一个轻量、可扩展的人形机器人全身遥操作框架：把 **BVH 动捕文件或 Pico 4 VR
实时人体追踪**重定向为 Unitree G1 参考轨迹，由 **train_mimic 导出的 TemporalCNN ONNX
RL 策略**（167D `velcmd_history` 观测）跟踪执行——可在 **MuJoCo 仿真**跑（sim2sim），
也可上 **Unitree G1 真机**（sim2real，经 unitree SDK）；外加可选的
**LinkerHand 灵巧手**、**OpenNeck 主动视觉云台**、**主机侧高层策略**部署通路。

```mermaid
graph LR
    subgraph Input["输入层"]
        BVH["BVHInputProvider<br/>(离线 BVH 文件)"]:::in
        UDP["UDPBVHInputProvider<br/>(实时 BVH 包)"]:::in
        PICO["Pico4InputProvider<br/>(pico_bridge VR)"]:::in
    end
    subgraph Core["离线核心管线（in-process）"]
        RET["RetargetingModule<br/>+ GMR（IK 重定向）"]:::core
        REF["ReferenceTimeline<br/>(实时参考缓冲)"]:::core
        OBS["VelCmdObservationBuilder<br/>(167D)"]:::core
        CTRL["RLPolicyController<br/>(双输入 ONNX)"]:::core
    end
    subgraph Exec["执行层"]
        SIM["MuJoCoRobot<br/>(PD 200Hz / 策略 50Hz)"]:::exec
        G1["UnitreeG1<br/>(unitree SDK 真机)"]:::exec
    end
    subgraph OptWorkers["可选进程隔离 worker（sim2real）"]
        HANDS["hands/<br/>LinkerHand L6/O6"]:::opt
        NECK["neck/<br/>OpenNeck"]:::opt
        MP["mp/<br/>参考重定向 worker"]:::opt
    end
    subgraph HLP["主机高层策略通路"]
        CLIENT["high_level_policy/<br/>client + scheduler"]:::hlp
        HOST["宿主机策略服务<br/>(独立仓库 lerobot-teleopit)"]:::ext
    end

    BVH & UDP & PICO --> RET --> REF --> OBS --> CTRL
    CTRL --> SIM
    CTRL --> G1
    PICO -. "只读快照" .-> HANDS & NECK
    PICO --> MP --> REF
    CLIENT <-->|"ZeroMQ REQ/REP<br/>+ msgpack"| HOST
    CLIENT -->|"36D 参考进 motion tracker"| OBS

    classDef in fill:#2a2a35,stroke:#888,color:#eee
    classDef core fill:#1f3b5e,stroke:#5b8def,color:#eaf2ff
    classDef exec fill:#1f5e44,stroke:#4caf7d,color:#e6fff2
    classDef opt fill:#3a3520,stroke:#c9a227,color:#fff7e0,stroke-dasharray:5 4
    classDef hlp fill:#3a1f5e,stroke:#b388ff,color:#f4eaff
    classDef ext fill:#5e1f1f,stroke:#ef5b5b,color:#ffeaea
```

---

## 2. 逻辑视图（分层）

核心抽象全部定义在 [`teleopit/interfaces.py`](../../teleopit/interfaces.py) 的
`typing.Protocol` 上：`InputProvider` / `RealtimeInputProvider` / `Retargeter` /
`Controller` / `Robot` / `MessageBus`。实现可自由组合。

```mermaid
graph TB
    subgraph L4["入口 / 装配层"]
        CLI["scripts/run/*.py<br/>+ teleopit/runtime/factory"]:::layer
    end
    subgraph L3["管线层（纯逻辑）"]
        PIPE["TeleopPipeline (pipeline.py)"]:::layer
        SESS["sim/session + mocap_session<br/>(模式状态机 STANDING/MOCAP/ARMS)"]:::layer
        LOOP["SimulationLoop (sim/loop.py)<br/>PD 200Hz / 策略 50Hz"]:::layer
    end
    subgraph L2["领域层"]
        IN["inputs/ 各 provider"]:::pure
        RET2["retargeting/ + gmr/"]:::pure
        CTRL2["controllers/<br/>observation.py + rl_policy.py"]:::pure
        BUS["bus/InProcessBus<br/>(零拷贝 pub/sub)"]:::pure
    end
    subgraph L1["设备 / IO 层"]
        MJ["robots/mujoco_robot.py"]:::io
        S2R["sim2real/<br/>unitree_g1 + remote + safety"]:::io
        WRK["sim2real/hands|neck|mp workers"]:::io
    end
    subgraph EXT["独立边界"]
        HLP2["high_level_policy/<br/>strict msgpack/ZMQ 协议"]:::ext
        TRAIN["train_mimic/<br/>训练包（rsl_rl + mjlab）"]:::ext
    end

    CLI --> PIPE & SESS --> LOOP
    LOOP --> IN & RET2 & CTRL2 & BUS
    LOOP --> MJ & S2R
    S2R --> WRK
    PIPE -.组装.-> L2
    HLP2 -. "36D 参考汇入同一<br/>ObservationBuilder" .-> CTRL2
    TRAIN -. "导出 ONNX ckpt" .-> CTRL2

    classDef layer fill:#1f3b5e,stroke:#5b8def,color:#eaf2ff
    classDef pure fill:#2c2c38,stroke:#999,color:#eee
    classDef io fill:#1f5e44,stroke:#4caf7d,color:#e6fff2
    classDef ext fill:#3a1f5e,stroke:#b388ff,color:#f4eaff
```

**分层原则**

- **接口即协议**：核心组件之间只依赖 `interfaces.py` 的 Protocol，不依赖具体实现。
- **离线核心零外部进程**：sim2sim 全链路（输入→重定向→观测→策略→MuJoCo）在单进程内
  经 `InProcessBus`（零拷贝）通信。
- **真机外设是可选 worker**：手 / 颈 / 参考重定向走进程隔离（`sim2real/mp|hands|neck`），
  localhost ZMQ + 共享内存视频环；**任何可选 worker 失败都不得中断 G1 主控**
  （AGENTS.md 反复强调的非关键性约束）。
- **主机策略边界严格**：外部主机策略边界只走 msgpack/ZeroMQ，无 pickle；
  Teleopit 不依赖 LeRobot/Transformers。

---

## 3. 关键数据流

### 3.1 主跟踪链路（BVH/Pico → G1）

```mermaid
sequenceDiagram
    participant IN as InputProvider<br/>(BVH 文件 / Pico 实时帧)
    participant RT as RetargetingModule<br/>+ GMR IK
    participant TL as ReferenceTimeline<br/>(实时缓冲/对齐)
    participant OB as VelCmdObservationBuilder
    participant PL as RLPolicyController<br/>(ONNX 50Hz)
    participant RB as MuJoCoRobot / UnitreeG1

    IN->>RT: 人形骨架帧（bone_names/parents/quats）
    RT->>RT: IK + R_offset 标定 → (base_pos, base_rot, joint_pos)
    RT->>TL: 参考帧入时间轴（实时: 缓冲+延迟+EMA 平滑）
    TL->>OB: 对齐到 policy_time 的参考
    OB->>OB: ref(94D) + robot 状态 → 167D velcmd_history
    OB->>PL: obs + obs_history（双输入）
    PL->>RB: action(29 offsets)
    RB->>RB: target = clip(a,±10)×scale + default_dof_pos<br/>PD 200Hz（decimation=4）
```

观测构成（167D）与动作语义的权威定义见 `AGENTS.md`「Inference Observation」
与「Sim2Sim Pipeline」。

### 3.2 主机高层策略通路（独立部署形态）

```mermaid
sequenceDiagram
    participant CAM as 相机/状态采集
    participant CW as 隔离 client worker<br/>(sim2real/mp)
    participant HOST as 宿主机策略服务<br/>(lerobot-teleopit 仓库)
    participant SCH as onboard scheduler
    participant TRK as motion tracker<br/>(同一 ObservationBuilder/Controller)

    CAM->>CW: JPEG RGB + G1 joints(29) + O6 读数(12) + OpenNeck(2) + 参考根(7)
    Note over CW: 每 replan_steps 帧提交最新观测<br/>同时在飞请求 ≤1（滚动时域）
    CW->>HOST: ZMQ REQ (msgpack, float32)
    HOST-->>CW: action float32[T,50]（T∈[1,50]）
    CW->>SCH: 回显单调时间戳 + chunk
    SCH->>SCH: 校验（形状/有限性/会话/四元数/限位/陈旧度）<br/>+ 50Hz 限速
    SCH->>TRK: body[0:36] 去局部化后作 36D 参考
    Note over TRK: 永不直接下发电机命令
```

- 模式机：`IDLE → STANDING →(Y) POLICY ↔(B) 暂停 →(X) STANDING，L1+R1 → DAMPING`。
- 超时 / 看门狗 / 主机失败 → 与远程 `B` 相同的可恢复暂停态，不自动回 `STANDING`。

### 3.3 可选外设 worker（手 / 颈）

Pico 输入只读快照（`get_controller_snapshot()` / `get_hand_snapshot()` /
`PicoFrame.head`）分发给 hands / neck worker；手失败必须张开到配置开合位，
颈 / 手 / 视频任何失败都不许停 G1 主控。细节契约见 `AGENTS.md` 相应小节。

---

## 4. 并发 / 进程模型

```mermaid
graph TB
    subgraph MainProc["主进程（sim2sim 全部 / sim2real 主控）"]
        LOOPP["SimulationLoop<br/>策略 50Hz + PD 200Hz"]:::io
        BUSP["InProcessBus 零拷贝"]:::pure
        VIEW["viewer 子进程 ×N<br/>(mocap/retarget/sim2sim/camera)"]:::opt
    end
    subgraph Workers["sim2real worker 进程"]
        MPW["mp/ 参考重定向 worker<br/>(armed 仅 MOCAP 态)"]:::opt
        HW["hands worker (somehand)"]:::opt
        NW["neck worker (openneck)"]:::opt
        HLPW["high_level_policy client worker"]:::hlp
    end
    subgraph Ext["外部"]
        HOST2["宿主机策略服务"]:::ext
        ROBOT["Unitree G1 (SDK)"]:::io
    end

    LOOPP --> BUSP
    LOOPP -->|GLFW 单窗口/进程| VIEW
    MPW & HW & NW -->|"localhost ZMQ + shm 视频环"| LOOPP
    HLPW -->|"ZMQ/msgpack"| HOST2
    LOOPP --> ROBOT

    classDef io fill:#1f3b5e,stroke:#5b8def,color:#eaf2ff
    classDef pure fill:#2c2c38,stroke:#999,color:#eee
    classDef opt fill:#1f5e44,stroke:#4caf7d,color:#e6fff2
    classDef hlp fill:#3a1f5e,stroke:#b388ff,color:#f4eaff
    classDef ext fill:#5e1f1f,stroke:#ef5b5b,color:#ffeaea
```

**关键约束**

- **一个进程一个 GLFW 窗口**：所有 viewer 各自子进程，关完全部窗口即退出。
- **进程隔离保主控**：50Hz 机器人主循环不被推理 / 外设拖死；参考 worker 只在
  `MOCAP` 态 armed（冷启动帧不会污染 GMR 暖启动）。
- **软重置语义**：暂停 / 模式切换重置策略与参考对齐（yaw/XY 重锚定），但
  **保留 GMR IK 暖启动**，不做 qpos 插值。

---

## 5. 训练 ↔ 推理边界

`train_mimic`（rsl-rl + mjlab）训练 `General-Tracking-G1` 任务，导出双输入
TemporalCNN ONNX；推理侧（`teleopit`）只消费 ONNX，不依赖训练栈。数据管线：
Pico 录制 NPZ → `build_dataset.py` 最小 HDF5 shards → `precompute_dataset.py`
预计算训练集 → 训练 → `save_onnx.py`。命令与契约见 `AGENTS.md`「Dataset
Pipeline」「Training Task」。

---

## 6. 扩展指南

| 要做的事 | 落点 | 关键约束 |
|---|---|---|
| 接新输入源（新 VR / 动捕） | 实现 `InputProvider`（实时则加 `RealtimeInputProvider`） | 纯 Protocol，不侵入管线 |
| 换机器人 | `teleopit/robots/` 新 `Robot` 实现 + `configs/robot/*.yaml` | 训练任务与 XML 关节定义须一致 |
| 换策略 | `controllers/rl_policy.py` 走双输入 ONNX | 启动即校验观测定义 vs ONNX 签名，不匹配立即报错 |
| 加外设 worker | `sim2real/<dev>/worker.py` 模式 | 非关键：失败不得停 G1 主控 |
| 改主机协议 | `high_level_policy/protocol.py` + 宿主仓库同步改 | 两仓库必须同步更新，无兼容层 |
| 加观测字段 | `controllers/observation.py` + 训练侧同步 | 167D 是当前契约，改了须重训/对齐 ONNX |

---

## 7. 进一步阅读

- 硬性规则与技术契约：根 [`AGENTS.md`](../../AGENTS.md)
- 文件级导览：[`repo-guide.md`](repo-guide.md)
- 用户文档站架构页：`docs/docs/reference/architecture.md`
- 教程（各工作流实操）：`docs/docs/tutorials/`
