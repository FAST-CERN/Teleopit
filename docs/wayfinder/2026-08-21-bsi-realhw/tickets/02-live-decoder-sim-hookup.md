---
id: bsi-realhw-02
title: "BSI 真实解码器接入仿真（活信号联调）"
labels: [wayfinder:task]
status: closed
assignee: "user"
blocked-by: []
created: 2026-08-21
---

## Question

BSI 团队把真实解码器发布端指向 DDS domain 0 `bsi/cmd_discrete`（Q3=a 解码已就绪）；Teleopit 侧验证活信号驱动仿真：

1. dds-probe env：`bsi_dds doctor` / `echo` 在解码器机器同网段可见活流（流率、接口）。
2. teleopit env：`run_sim` pico4_sim_bsi 配置在真实源下跑通四态行为（抽 14 行表中核心行验证）。
3. 网络绑定按 PC↔Orin 验证经验（`--interface` / `CYCLONEDDS_URI` 固定组播接口）。

仿真侧代码零改动（订阅端本就是真的）。产出：联调记录（流率、接口、掉包/静默观察、机器与网络拓扑）——回填本票并供 03/06 引用。

## Resolution

**2026-08-21 user-reported 通过**：真实解码器发布端已接 DDS domain 0，仿真被活信号驱动跑通（与目视验收同场）。流率/接口/掉包等量化观察未落盘——由 03（采数复校）与 06（拓扑）承接。仿真侧代码零改动，与 survey 预期一致。
