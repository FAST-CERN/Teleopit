---
id: bsi-dds-07
title: "验收演示场景：mock BSI 序列驱动的量化指标与行为 checklist"
labels: [wayfinder:grilling]
status: closed
assignee: "claude/main"
blocked-by: [bsi-dds-02, bsi-dds-04]
created: 2026-08-21
---

## Question

「仿真内跑通 BSI→G1 行走」的验收标准是什么？

- **场景脚本**：mock 发布器发一段指令序列（如 idle→前→左转→前→idle + 中途摇杆抢夺 + 急停触发），MuJoCo 观察行为正确性 checklist（类似 task #6 的 12 项 HMD gate，但这里是桌面仿真 gate）。
- **量化指标**（pytest 可测）：指令→速度响应时间（收到 FORWARD 到 lin_x 达 0.5×目标的耗时）；idle/急停的减速时间；摇杆抢夺延迟（摇杆非零到 BSI 被压制的帧数）；误标签注入后的行为（防抖生效，不切换意图）。
- **通过线**：参考 Phase A 验收（跟踪误差 0.35 m/s、hand-off 跳变 0.25 rad）与 task #6 gate 的宽严程度定。
- **mock 序列可复用性**：同一脚本将来真机 Phase B 回放（BSI 录制数据重放）要不要预留格式。

产出：验收 checklist + 指标表（进 ticket resolution），演示在后续 plan 实现完成后执行。

## Resolution

**2026-08-21 grilling 锁定**：

**形态：双门制**（同 task #6 先例）——(a) pytest 量化门（provider/融合/急停层单测+集成测，注入时钟与假 reader 全自动断言）；(b) 桌面仿真 checklist（mock CLI 发序列+人看 MuJoCo viewer，~14 行表）。指标层测「数字对不对」，观察层测「看起来对不对」。

**场景脚本**（单段全元素 ~50s，两门共用）：
`idle:3 → forward:5 → left:3 → forward:5 → right:3 → idle:3 → forward:5（中途摇杆抢夺+急停+解锁）→ idle 收尾`

**量化指标表**（pytest 断言）：

| 指标 | 通过线 |
|---|---|
| 意图→速度响应（FORWARD 生效→输出达 0.3 m/s） | ≤1.0s（防抖 0.3s + 平滑半幅 ~0.6s） |
| idle/哑音自然减速（满幅→<0.1 m/s） | ≤1.5s |
| 急停强制减速 | ≤0.8s（0.3s ramp+余量） |
| 摇杆抢夺（摇杆非零→融合输出切换） | ≤2 个 get_cmd 周期 |
| 误标签防抖（forward 流插单包 left） | 意图不切换（孤包滤除，3 包门槛内） |
| 静默归零（停发→开始衰减） | ≤1s 开始（阈值与 T1 同源），1.5s 全零 |
| 哑音响应 | toggle 后下一周期衰减；解除下一周期恢复（无重连） |
| 跟踪误差（\|cmd\|>0.5 时） | 复用既有 0.35 m/s 门槛（velocity_session._record_metrics） |

**桌面 checklist**（~14 行，task #6 表格式，`docs/knowledge/research/` 记录）：四态行为×4、意图切换平滑、摇杆抢夺/释放回脑控、急停/解锁、哑音/解除、静默（mock Ctrl-C 后站住）、V/X 不受 BSI 影响、H 帮助文本新键位（E/C/menuButton/Y）核对。入口：run_sim pico4 配置 + `bsi_dds mock` CLI 对发。

**回放预留**：复用 mock 脚本格式（token:秒 逗号序列）——真机 Phase B 的「时间戳+意图」流转同格式即重放（echo/doctor 已有解析器），零新格式。

**执行时点**：本表是验收标准（规格即 gate）；演示在后续 superpowers plan 的 Teleopit 侧实现完成后执行，结果回填 `docs/knowledge/research/`（同 2026-08-20 visual-check 惯例）。
