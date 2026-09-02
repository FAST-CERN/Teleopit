# t05 Teleopit 上半身合成设计决议：HMD+2 tracker → ARMS 上肢参考

- 地图：`2026-09-02-upperbody-mocap`（ticket 05，grilling 六问全决）
- 日期：2026-09-02（grilling 会话，用户逐问裁决；事实依据=t01 研究产物 + 本仓代码现状）
- 消费方：06 实装据此动手；03/04 契约按 §5 细化。

---

## 0. 六问决议速答

| # | 问题 | 决议 |
|---|---|---|
| 1 | 合成目标形态 | **完整合成 body 等价帧**（方案 A）：HMD+2 tracker → 24×7 关节，从 `_accept_pico_frame` 的 body 口喂入；GMR/mink、去重、地面对齐、闸门**零改动**。腕直达 ik（方案 B）弃——欠定肘求解风险+06 验收混入求解器变量 |
| 2 | 肩/肘位姿 | 肩锚=**HMD 刚体常数表**（颈-肩距/肩宽/胸前偏移，配置化；T-pose 残差标定为可选项非必选）；肘=**中点+外偏**：`肘=mid(肩,腕)+外偏向量·k`（k 首版 0.05m 配置）；上臂朝向←肩→肘、前臂朝向←肘→腕、腕朝向←tracker 四元数。swivel 角模型=06 不过线时的升级对局（不预实装） |
| 3 | tracker→腕安装偏移 | **静态测量配置**：手套手背底座几何一次测量，YAML 左右各 `[x,y,z]`（tracker 系，米），`p_腕 = p_tracker − R_tracker·offset`；06 验收含 ±2cm 灵敏度扫掠；不够准再上姿势标定 |
| 4 | 坐标变换 | **全链复用现有约定**（t01 §4）：app 端 tracker 套 AppendBody 同款翻转（−Z/−Qz/−Qw）→ bridge 透传 → 合成器在 Unity 系（翻转后）工作、输出 24×7 [x,y,z,qx,qy,qz,qw] → `_convert_body_joints_to_frame` wxyz 重排 + `_INPUT_TO_TELEOPIT_MATRIX` 原路径。**零新变换** |
| 5 | 失效语义 | **hold 0.3s → 整帧 invalid**：单只 tracker isValidPose=false → 该腕 hold-last ≤0.3s（帧继续产出，HMD 动→参考龄新鲜→机器人保持位姿）；超窗 `body.active=False` → 断粮 → 0.25s 超龄 → 出 MOCAP（总 ~0.55s）→ 重入走现有 10 帧闸。丢 HMD=TCP 帧流停=天然断粮，零新逻辑。**新闸门语义=0** |
| 6 | 时间对齐 | **同帧保证由 03 结构给**：Head+Motion 同 TCP 帧同 `timeStampNs`；合成随帧逐帧跑。有效更新率=tracker 50Hz（HMD 微动使帧帧相异，不触发全等去重；即便 HMD 也静止→去重拒重复→~50Hz 有效，仍远超 0.25s 龄闸）；`pico_input_hz=120` 采样由 `sample_frame` 插值填，不设特殊处理 |

## 1. 架构与接口签名（06 实装依据）

```
Unity app (03)          pico_bridge (04)         Teleopit (05/06)
─────────────           ───────────────          ───────────────
Head + Motion ──TCP──→  MotionFrame 透传 ──→ provider._accept_pico_frame
（哑传感器）             (+Head 同帧)                │ body 失活且 arm_source=tracker
                                                    ↓
                                        TrackerArmSynthesizer.synthesize(frame)
                                                    │ BodyFrame(24×7, active=True)
                                                    ↓ 复用: 去重→坐标变换→地面对齐→缓存
                                        GMR/mink(pico_bridge_to_g1.json 不动)
                                                    ↓
                                        compose_arm_reference(idx 15–28 不动)
```

```python
# teleopit/inputs/tracker_arm_synth.py（新文件）
@dataclass(frozen=True)
class SynthConfig:
    neck_shoulder_m: float            # HMD 系肩锚常数（颈-肩垂距）
    shoulder_width_m: float           # 肩宽（左右展开）
    chest_offset_m: tuple[float,...]  # 胸前偏移（HMD 系）
    elbow_lateral_m: float = 0.05     # 中点+外偏 k
    tracker_offset: dict[str, tuple[float,float,float]]  # {"left"/"right": tracker 系}
    hold_s: float = 0.3               # 单腕 hold 窗

class TrackerArmSynthesizer:
    def __init__(self, config: SynthConfig) -> None: ...
    def synthesize(self, frame) -> BodyFrame | None:
        """吃 pico_bridge 帧（head+motion）；双 tracker 有效（含 hold 窗内）→
        24×7 BodyFrame（Unity 系，未做 _convert 的原始 pico 序）；否则 None
        （= body inactive，下游走现有断粮链）。"""
```

- provider 侧最小缝合：`arm_source: body|tracker` 配置项（默认 `body`，零行为变化）；`tracker` 模式下 body 失活即调合成器替换 `frame.body`，其余不动。
- 下半身/颈关节：合成帧下半身=站立常数位姿（pelvis/hip/knee/foot），Neck/Head=HMD 派生——重定向只用臂+torso 任务，下半身仅作根锚（ik 表 pos_w 谱见 t05 功课：腿/根 pos 任务在，但站立常数下解即站姿，与 compose_arm_reference 只取臂 idx 15–28 自洽）。

## 2. 06 实装清单（据此排 TDD）

1. `tracker_arm_synth.py` 合成器（§1 接口）：纯函数核（位姿进→24×7 出）+ hold 状态机；单测=合成几何不变量（肘在中点外偏、腕=tracker−R·offset、24 关节名齐全）+ hold 转移（有效→hold→invalid→恢复）。
2. provider 缝合：`arm_source` 门控 + 合成 body 注入（单测=mock bridge 帧，body 口吃合成帧走通去重/变换/缓存）。
3. e2e：mock Motion 帧驱动 sim ARMS 跟随（06 四线验收载体）。

## 3. 风险与对局（沿 map Not-yet-specified §4 分支）

| 风险 | 触发 | 对局 |
|---|---|---|
| 肘启发式精度不足（ARMS 姿态不像） | 06 跟随稳定线/主观线不过 | 升 swivel 角模型（接口已按纯函数核设计，替换肘策略不动其余）；再败→双 tracker 融合权重 |
| 肩锚常数个体差异 | 跨操作员主观线掉 | T-pose 一次性残差标定（可选项实装） |
| 安装偏移测不准 | 06 ±2cm 灵敏度曲线陡 | 上姿势标定（残差最小二乘） |
| 遮挡瞬时翻转频繁 | hold 0.3s 仍频繁进出 MOCAP | hold 窗调大（配置）或升单臂冻结（未选方案，留 06 后配置升级位） |
| 合成帧与 body tracking 帧并存 | 误同时开 | `arm_source` 互斥门控，默认 body |

## 4. 给统一 policy 图的快照（map 要求留好输入约定）

合成输出=现有 `HumanFrame`（24 关节 dict，Teleopit 系）——统一 policy 的上半身 obs 即以此为准：`body` 段臂四关节（Shoulder/Elbow/Wrist ×2）位姿，频率 50Hz 有效、120Hz 插值采样。换源对该约定透明。
