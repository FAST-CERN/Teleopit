---
id: 06-e2e-acceptance
title: "Pico 实机验收：四线 A/B 对照，达标收图"
labels: [wayfinder:task]
status: open
assignee: ""
blocked-by: [05-deploy-smoke, "aiortc-pacer-map/t03"]
---

## Question

外部闸：aiortc-pacer 图 ticket 03（e2e 双线验收）CLOSED 后方可执行（排序决策 2——两图归因干净）。

开关切 `hard`，Pico 实机四线验收（见 map Destination）：

1. 编码段 A/B：硬编 vs 软编基线（01 票已量，同法对照）；
2. CPU：编码占用下降可观测（01 软编基线 vs 硬编运行时）；
3. e2e 不劣化：时间码照片法 + APK stats（沿用 zed-fpv/pacer 工具链），≤ pacer-t03 基线 +5ms；
4. 主观画质不降 + **实际 outbound 码率对照**（x264 无 VBV 3-4× 过冲 vs NVENC CBR 收敛——pacer t04 发现的正面对证）。

数据全进 Resolution；四线全过 → 收图（Decisions 补一行，map status: closed）。任何一线不过 → 回流定位（01/03 对应层）而非放宽线。
