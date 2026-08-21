---
id: bsi-realhw-01
title: "仿真 14 行桌面 checklist 目视验收"
labels: [wayfinder:task]
status: closed
assignee: "user"
blocked-by: []
created: 2026-08-21
---

## Question

跑毕 `docs/knowledge/research/2026-08-21-bsi-desktop-checklist.md` 的 14 行验收表（双终端：teleopit env `run_sim` pico4_sim_bsi 配置 + dds-probe env `bsi_dds mock` 发 `idle:3,forward:5,left:3,forward:5,right:3,idle:3,forward:5,idle:3` ~50s），逐行记录观察结果回填该文档。

边界（Q2=c）：bug 视作 cosmetic/低优先——暴露即各自开 fix ticket，但**不阻塞本门**；门 = 14 行跑完并记录。estop 行（8/9）按 3866473 后的锁存语义观察。

产出：填好的 checklist 表 + fix ticket 列表（若有）。

## Resolution

**2026-08-21 user-reported 通过**：目视验收跑毕 + 真实 BSI 活信号接入复核，均过；未报 bug → 无 fix ticket。逐行观察记录未落盘（checklist 文档保持规格原样，文首加验收结果行）。量化部分由 03 承接。
