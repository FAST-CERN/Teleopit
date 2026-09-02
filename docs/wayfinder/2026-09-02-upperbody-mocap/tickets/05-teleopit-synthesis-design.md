---
id: 05-teleopit-synthesis-design
title: "Teleopit 上半身合成设计：HMD+2 tracker → ARMS 可吃的上肢参考"
labels: [wayfinder:grilling]
status: closed
assignee: claude
blocked-by: ["01-tracker-sdk-semantics"]
---

## Question

合成方案定案（grilling，产出设计决议供 06 实装）：

1. 合成目标形态：完整上半身 HumanFrame（造肩/肘关节位姿喂现有 GMR/mink `ik_match_table`）vs 只给腕任务（改 ik 表降肩肘权重）——复用度/求解稳定性权衡；
2. 肩位姿：人体测量常数相对 HMD（颈-肩距、肩宽）；肘位姿：启发式（腕-肩连线中点偏移? swivel 角?）——mink 对欠定肘的容忍度实测后定；
3. tracker→腕中心**安装偏移**：手套手背固定偏移的测量法与配置化（进 fog 的标定流程在此定形态）；
4. 坐标变换：复用 `_INPUT_TO_TELEOPIT_MATRIX` 还是 tracker 语义另立变换（01 结论输入）；
5. 失效语义：tracker 丢一/丢二/全丢、时间戳超龄（`mocap_switch` 10 帧有效 + ≤0.25s 参考龄闸门）→ hold/静默/回中；与 MOCAP 入场闸门的兼容；
6. 时间对齐：HMD 与 tracker 同帧保证（03 串流结构输入）；合成帧频率与 `pico_input_hz=120` 的关系。

产出：设计决议（含 ik 表改动清单、合成模块接口签名），06 据此实装。

## Resolution

2026-09-02 闭（grilling 六问全决），产物 `research/05-synthesis-design.md`。决议：

1. **形态=完整合成 body 等价帧**（方案 A）：24×7 从 provider 的 body 口喂入，GMR/mink/去重/地面对齐/闸门零改动；腕直达 ik（方案 B）弃（欠定肘+06 验收混入求解器变量）。**ik 表改动清单=空**。
2. **合成器住 Teleopit provider 层**（`tracker_arm_synth.py`）：03 保持哑传感器、04 只透传 MotionFrame；合成策略迭代/单测/录制回放全在本仓。
3. **肩锚=HMD 刚体常数表**（配置化，T-pose 残差标定可选）；**肘=中点+外偏**（k=0.05m 配置，朝向由连线派生）；swivel 为 06 升级对局不预实装。
4. **安装偏移=静态测量 YAML**（tracker 系 [x,y,z]，`p_腕=p_tracker−R·offset`）；06 含 ±2cm 灵敏度扫掠。
5. **坐标=全链复用**（t01 §4：app 翻转→bridge 透传→合成器 Unity 系→`_convert_body_joints_to_frame`+`_INPUT_TO_TELEOPIT_MATRIX` 原路径），零新变换。
6. **失效=hold 0.3s→整帧 invalid**：单丢腕 hold（帧继续产出→保持位姿）→超窗 body.active=False→断粮→0.25s 超龄出 MOCAP（总 ~0.55s）→10 帧闸重入；丢 HMD=TCP 断流天然处理。新闸门语义=0。
7. **时间=03 同帧结构保证**（Head+Motion 同 timeStampNs）；有效 50Hz、120Hz 采样插值填。

接口签名与 06 实装清单（合成器 TDD 三步：纯函数核+hold 状态机单测 / provider `arm_source` 缝合 / mock 帧驱动 sim）见 research §1–2；风险对局表见 research §3；统一 policy 图输入快照见 research §4。
