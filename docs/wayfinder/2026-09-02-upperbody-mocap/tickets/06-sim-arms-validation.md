---
id: 06-sim-arms-validation
title: "sim ARMS 模式四线验收：合成输入喂现有重定向，双臂跟随过线"
labels: [wayfinder:prototype]
status: open
assignee: claude
blocked-by: []
---

## Question

端到端 sim 验证（本图终点票）：

- 实装 05 定案的合成模块，接 04 的 `frame.trackers`，喂现有 ARMS 管线（sim loop：STANDING→Y 入 MOCAP→B 切 ARMS，仅动上肢）；
- MeshCat/viewer 观察 + 指标采集，**四线**（数值开票时定稿）：
  1. **采集质量**：tracker 位姿到达率（hz≥X、丢帧率≤Y%）、采集→合成→参考端到端延迟（日志法，≤Z ms）；
  2. **跟随稳定**：sim 双臂跟踪合成参考无发散/无振荡/无 NaN，肘欠定不抖；
  3. **断连安全**：tracker 断连/超龄 → hold/回中语义按 05 设计生效，恢复后无跳变；
  4. **主观**：操作员戴手套+HMD 挥臂，sim 视图中跟随方向/幅度/手感可用。
- 手段：receiver 录制回放做可重复场景（若毕业）+ 真人佩戴现场各一轮。

过线 → 本图 CLOSED，产出合成帧格式快照移交统一 policy 图。
