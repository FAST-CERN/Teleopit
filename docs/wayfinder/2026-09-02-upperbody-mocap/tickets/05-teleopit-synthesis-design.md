---
id: 05-teleopit-synthesis-design
title: "Teleopit 上半身合成设计：HMD+2 tracker → ARMS 可吃的上肢参考"
labels: [wayfinder:grilling]
status: open
assignee: ""
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
