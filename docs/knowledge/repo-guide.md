# Teleopit 仓库导览（面向工程师）

> 返回 [`knowledge/` 索引](README.md)。架构全景见 [`architecture.md`](architecture.md)；
> 硬性规则以根 [`AGENTS.md`](../../AGENTS.md) 为准。本文回答三个问题：
> **仓库长什么样、每个文件干什么、代码怎么用**。

---

## 1. 项目是什么

Teleopit 是人形机器人（Unitree G1）全身遥操作框架：

- **输入**：BVH 动捕文件（离线）或 Pico 4 VR（实时人体追踪）；
- **重定向**：GMR（General Motion Retargeting，自包含 IK）把人形动作映射为 G1 参考轨迹；
- **执行**：train_mimic 导出的 TemporalCNN ONNX RL 策略（167D 观测）跟踪参考——
  MuJoCo 仿真（sim2sim）或 Unitree SDK 真机（sim2real）；
- **可选扩展**：LinkerHand L6/O6 灵巧手、OpenNeck 主动视觉云台、
  主机侧高层策略（host high-level-policy）部署、HDF5 录制与回放、
  train_mimic 训练包。

技术栈：Python 3.10+，Hydra/OmegaConf 配置，MuJoCo + mink + QP，
PyTorch/ONNX Runtime 推理，ZeroMQ/msgpack IPC。许可 Apache-2.0。

## 2. 仓库顶层结构

```
Teleopit/
├── teleopit/            核心推理包（pip install -e . 安装的主体）
├── train_mimic/         训练包（rsl-rl + mjlab，与推理包同仓不同依赖组）
├── scripts/             可执行入口：run / setup / view / render / dev
├── tests/               pytest 测试套件（43 个文件）
├── docs/                Docusaurus 用户文档站 + knowledge/（开发者参考）
├── assets/robots/       机器人模型（gitignored，运行时下载）
├── ckpt/                策略 checkpoint（gitignored，运行时下载）
├── data/                BVH 样例 / 数据集（数据部分 gitignored）
├── third_party/         可选硬件 SDK 子模块（g1_bridge / linkerhand / somehand / unitree_sdk2）
├── AGENTS.md            开发硬性规则 + 技术契约（最权威文档）
├── CHANGELOG.md         版本记录
├── pyproject.toml       包定义 + 依赖组（dev/sim2real/train/pico4/openneck/recording/review/dexhand）
└── README.md            项目门面 + Quick Start
```

> **资产不入 Git**：机器人 mesh、数据集、checkpoint、demo 媒体全部经
> `scripts/setup/download_assets.py` 从 ModelScope 下载（两个仓库：
> `BingqianWu/Teleopit-models` 模型类、`BingqianWu/Teleopit-datasets` 数据类）。
> 推送前跑 `python scripts/dev/check_large_tracked_files.py`。

## 3. 核心包 `teleopit/` 文件级导览

### 3.1 包根

| 文件 | 功能 |
|---|---|
| `interfaces.py` | **核心契约**：`RobotState` 数据类 + `InputProvider`/`RealtimeInputProvider`/`Retargeter`/`Controller`/`Robot`/`MessageBus` Protocol。所有组件只依赖这些抽象 |
| `pipeline.py` | `TeleopPipeline`——薄仿真运行时门面，把 input→retarget→obs→controller→robot 组装起来；负责 `default_dof_pos` 传播（`robot_cfg.default_angles → controller_cfg.default_dof_pos`，缺了机器人站不住） |
| `constants.py` / `math_utils.py` | 公共常量与数学工具 |

### 3.2 `bus/` — 进程内消息总线

| 文件 | 功能 |
|---|---|
| `in_process.py` | `InProcessBus`：零拷贝 pub/sub，离线核心模块间通信 |
| `topics.py` | 主题常量（`mimic_obs` / `robot_state` / `action` / `hand_left` / `hand_right`） |

### 3.3 `inputs/` — 人体运动输入

| 文件 | 功能 |
|---|---|
| `bvh_provider.py` | `BVHInputProvider`：离线 BVH 文件（支持 lafan1 22 关节 30fps、hc_mocap 50 关节降采样） |
| `udp_bvh_provider.py` | `UDPBVHInputProvider`：实时 BVH UDP 包 |
| `pico4_provider.py` | `Pico4InputProvider`：进程内 `pico_bridge.PicoBridge` 实时身体追踪 + 控制器/手部快照 |
| `pico_video.py` | 可选相机预览回推到 Pico 头显 |
| `realtime_frame_cache.py` / `realtime_packet.py` | 实时帧缓存与打包（时间戳对齐采样） |
| `human_frame_validation.py` | 人形帧校验（fail-fast，不静默修补） |
| `rot_utils.py` | 输入空间四元数变换（Pico→重定向配置的输入变换在此，**不是**公开坐标系契约） |

### 3.4 `retargeting/` — GMR 重定向

| 文件/目录 | 功能 |
|---|---|
| `core.py` | `RetargetingModule` + `extract_mimic_obs()`：把 provider 的人形帧交给 GMR 得 `(base_pos, base_rot, joint_pos)` |
| `export_pkl.py` | 重定向结果导出 pkl |
| `gmr/` | **自包含 GMR 引擎**：`motion_retarget.py`（主流程）、`kinematics_model.py`、`neck_retarget.py`、`data_loader.py`、`params.py`、`ik_configs/`（每对 robot_body×human_bone 的四元数偏移 `R_offset`）、`assets/`（gitignored，运行时下载）。新 BVH 格式的偏移标定用 `scripts/dev/compute_ik_offsets.py` |

### 3.5 `controllers/` — 观测与策略

| 文件 | 功能 |
|---|---|
| `observation.py` | `VelCmdObservationBuilder`：参考(94D) + 机器人状态 → 167D `velcmd_history` 观测（构成见 `AGENTS.md`） |
| `rl_policy.py` | `RLPolicyController`：单/双输入（`obs`+`obs_history`）ONNX 推理；启动即校验观测定义 vs ONNX 签名，不匹配立即抛错 |
| `reference_processing.py` | 参考预处理（平滑 / 速度推断等） |

### 3.6 `robots/` + `sim/` — 仿真执行

| 文件 | 功能 |
|---|---|
| `robots/mujoco_robot.py` | `MuJoCoRobot`：MuJoCo 仿真封装（get_state/set_action/step/reset） |
| `sim/loop.py` | `SimulationLoop`：**主循环**——策略 50Hz / PD 200Hz（decimation=4）、实时墙钟节拍、多 viewer、播放控制 |
| `sim/session.py` / `mocap_mujoco.py` / `runtime_components.py` | 仿真会话与组件装配 |
| `sim/reference_timeline.py` / `reference_motion.py` / `reference_utils.py` / `realtime_utils.py` | 实时参考时间轴：缓冲 / 延迟 / 暖启动 / EMA 速度平滑 |
| `sim/viewer_subprocess.py` | 每窗口一个子进程的 viewer（GLFW 单窗口/进程限制的解法） |

### 3.7 `runtime/` — 装配与入口支撑

`factory.py`（组件工厂）、`cli.py`（命令行助手）、`assets.py` / `external_assets.py`
（资产路径解析与 ModelScope 仓库映射 `MODEL_REPO_ID`/`DATASET_REPO_ID`）、
`reference_config.py`、`mocap_session.py`（`STANDING/MOCAP/ARMS` 模式状态机）、
`offline_playback.py`（键盘播放控制）、`arm_mocap.py`、`console.py`、
`terminal_keyboard.py`。

### 3.8 `sim2real/` — 真机执行与可选外设

| 文件/目录 | 功能 |
|---|---|
| `unitree_g1.py` | Unitree G1 真机接口（unitree SDK） |
| `remote.py` | Unitree 遥控器语义（`Start→STANDING`、`Y→MOCAP/POLICY`、`B→暂停`、`X→STANDING`、`L1+R1→DAMPING`） |
| `safety.py` / `reference_processor.py` | 安全约束与参考处理 |
| `mp/` | **进程隔离运行时**：`runtime.py`（supervisor）、`high_level_policy_runtime.py`、`high_level_policy_worker.py`（隔离客户端 worker）、`ipc.py`/`messages.py`/`shm.py`（ZMQ + 共享内存 IPC） |
| `hands/` | LinkerHand 驱动插件：`base.py`（接口）、`linkerhand_l6.py` / `linkerhand_o6.py`、`pico_landmarks.py`（Pico 26 关节→21 landmark，Teleopit 自有，不 import somehand.pico_input）、`worker.py` |
| `neck/` | OpenNeck 云台：`openneck.py`（物理角 `move_deg()`）、`mapper.py`（HMD 头姿相对 Spine3 映射，死区 + pitch_gain）、`worker.py` |

### 3.9 `high_level_policy/` — 主机策略协议

| 文件 | 功能 |
|---|---|
| `protocol.py` | 严格 msgpack/ZeroMQ REQ/REP 协议（float32 数组，无 pickle）；与宿主仓库 `lerobot-teleopit` **必须同步修改** |
| `client.py` | 严格客户端：在飞请求 ≤1，滚动时域重规划 |
| `scheduler.py` | 机载调度器：时间戳对齐、chunk 校验、50Hz 限速、看门狗 |
| `config.py` / `hand_calibration.py`(+json) | 配置与 LinkerHand O6 开合标定（**唯一与宿主仓库共享的数据文件，须逐字节一致**） |

### 3.10 `recording/` 与 `debug/`

`recording/hdf5.py`（sim2real HDF5 录制：`schema.json` + `episodes.jsonl` + 每 episode HDF5 + MP4）、
`recording/pico_motion.py`（Pico 动作 NPZ 录制）；`debug/rollout_trace.py`（rollout 调试追踪）。

### 3.11 `configs/` — Hydra 配置

| 文件 | 场景 |
|---|---|
| `default.yaml` | 离线 sim2sim（BVH） |
| `online.yaml` / `pico4_sim.yaml` | 实时 sim2sim（Pico） |
| `sim2real.yaml` / `pico4_sim2real.yaml` | 真机（BVH 回放 / Pico 实时） |
| `pico4_record.yaml` / `sim2real_record.yaml` | 录制 |
| `high_level_policy_sim2real.yaml` | 主机策略部署 |
| `robot/`、`controller/`、`input/` | 组配组：机器人 XML/PD 增益/默认角、策略路径、输入源 |

## 4. `scripts/` 入口导览

| 脚本 | 用途 |
|---|---|
| `run/run_sim.py` | **离线 sim2sim**（BVH→MuJoCo，最常用入口） |
| `run/run_online_sim.py` | 实时 sim2sim（Pico） |
| `run/run_sim2real.py` | G1 真机（BVH 回放或 Pico） |
| `run/run_high_level_policy_sim2real.py` | 主机策略部署运行时（独立：不起 PicoBridge/GMR/参考 worker） |
| `run/record_pico_motion.py` | 交互式 Pico 录制 → G1 动作 NPZ 片段（训练数据源头） |
| `run/standalone_standing.py` | 独立站立 |
| `setup/download_assets.py` | **资产下载**（`--only robots gmr ckpt bvh`） |
| `setup/prepare_modelscope_assets.py` / `upload_hf_assets.py` / `setup_g1_bridge.sh` | 发布资产 / g1_bridge SDK 构建 |
| `view/view_recording.py` | 录制回放审阅（视频+MuJoCo 叠加+曲线） |
| `view/view_dataset.py` | 数据集查看 |
| `render/render_sim.py` | BVH→三段 MuJoCo 视频（mocap / retarget / sim2sim） |
| `dev/compute_ik_offsets.py` | 新 BVH 格式 IK 偏移标定 |
| `dev/bench_policy_onnx.py` / `bench_dds.py` | ONNX / DDS 基准 |
| `dev/test_*.py` | pico_bridge / linkerhand / openneck / g1_bridge 硬件连通测试 |

## 5. `train_mimic/` 训练包导览

| 文件/目录 | 功能 |
|---|---|
| `app.py` / `benchmarking.py` | 训练/播放/基准共享助手（OmniXtreme 式基准：MPJPE、根位姿/速度误差、成功率） |
| `tasks/tracking/` | 唯一支持任务 `General-Tracking-G1`：`tracking_env_cfg.py`（环境）、`mdp/`（奖励/采样）、`rl/`（TemporalCNN + runner + ONNX 导出封装） |
| `data/` | `dataset_builder.py` / `dataset_lib.py`（MotionLib）/ `motion_fk.py` / `preprocess.py` |
| `scripts/train.py` / `play.py` / `benchmark.py` / `save_onnx.py` | 训练 / 播放 / 基准 / ONNX 导出入口 |
| `scripts/data/build_dataset.py` | NPZ → 最小 HDF5 shards（不做 precompute） |
| `scripts/data/precompute_dataset.py` | 最小数据集 → 预计算训练集（训练 `motion_file` 必须指向它） |

训练依赖走 `pip install -e ".[train]"`（rsl-rl-lib 5.2.0、mjlab 1.4.0）。

## 6. 代码使用

### 6.1 安装与资产

```bash
pip install -e .                                  # 基础（sim2sim）
pip install -e ".[dev]"                           # + pytest
pip install -e ".[pico4]"                         # + pico-bridge / sim2real 依赖
pip install -e ".[recording]"                     # + 录制
pip install -e ".[train]"                         # 训练栈

pip install modelscope
python scripts/setup/download_assets.py --only robots gmr ckpt bvh
```

Windows 注意：`proxsuite<0.7.3`（0.7.3 起无 Windows wheel，源码编译失败，
pyproject 已按平台 pin）。

### 6.2 最小 sim2sim（验证安装）

```bash
python scripts/run/run_sim.py \
    controller.policy_path=ckpt/track_g1.onnx \
    input.bvh_file=data/sample_bvh/aiming1_subject1.bvh
```

出现 MuJoCo viewer、G1 跟踪 BVH 动作即成功。多 viewer / 相机视图 / 键盘播放
等变体见 `AGENTS.md`「Multi-Viewer Support」「Offline Playback」与用户文档
`tutorials/offline-sim2sim.md`。

### 6.3 以库方式组合（编程接口）

所有组件实现 `teleopit/interfaces.py` 的 Protocol，可手工组装：

```python
from teleopit.pipeline import TeleopPipeline
# 或逐件组合：
#   input  = BVHInputProvider(path)              # 或 Pico4InputProvider(...)
#   retargeter = RetargetingModule(...)           # 内部用 GMR
#   controller = RLPolicyController(onnx_path)   # 启动即校验观测签名
#   robot   = MuJoCoRobot(xml_path, ...)
#   loop    = SimulationLoop(...)                 # 50Hz 策略 / 200Hz PD
```

注意两条硬约束（`AGENTS.md`）：`default_dof_pos` 必须从 `robot/g1.yaml` 的
`default_angles` 传播到控制器（否则膝肘失去站立偏移、无法平衡）；观测定义与
ONNX 签名不匹配必须立即失败，**不得**静默 pad/trim/clip。

### 6.4 测试

```bash
pytest tests/ -v
```

43 个测试文件覆盖：管线 / 接口 / 总线 / 控制器 / 观测 / 重定向 / 仿真循环 /
e2e / 多进程 sim2real / 高层策略协议 / 录制 / 数据集 / 训练脚本 / 各硬件 provider
（fake 注入）。

### 6.5 典型工作流路由

| 想做什么 | 入口 |
|---|---|
| 看策略跟踪 BVH | `scripts/run/run_sim.py` |
| 戴 Pico 实时操控（仿真） | `scripts/run/run_online_sim.py`（配 `online.yaml`/`pico4_sim.yaml`） |
| 上真机 | `scripts/run/run_sim2real.py`（先跑 `scripts/dev/test_g1_bridge.py` 等连通测试） |
| 主机策略部署 | `scripts/run/run_high_level_policy_sim2real.py` |
| 录训练数据 | `scripts/run/record_pico_motion.py` → `build_dataset.py` → `precompute_dataset.py` |
| 训练 / 导出 | `train_mimic/scripts/train.py` → `save_onnx.py` |
| 回放审阅录制 | `scripts/view/view_recording.py` |
| 支持新 BVH 格式 | `scripts/dev/compute_ik_offsets.py` 标定 `R_offset` → 写入 `gmr/ik_configs/` |

## 7. 开发规则速记（详见 `AGENTS.md`）

- **简洁策略**：最小实现满足当前需求；不加投机性开关 / 抽象层 / 兼容路径。
- **运行时校验策略**：逻辑不匹配 fail-fast；错误信息指明组件与修复路径。
- **提交策略**：不自动提交；大特性改动后 `AGENTS.md` 与 `README.md` 随代码一起更新；
  英文文档（`docs/docs/`）、中文文档（`docs/i18n/zh-Hans/`）与实现保持同步
  （中文是英文的翻译）。
- **可选组件非关键**：手 / 颈 / 视频 / 录制 worker 失败不得停 G1 主控。
- **主机协议双仓同步**：改 `high_level_policy/protocol.py` 必须同步改
  `lerobot-teleopit`；`hand_calibration.json` 两仓逐字节一致。
