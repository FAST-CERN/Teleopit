---
id: 06-e2e-acceptance
title: "Pico 实机验收：四线 A/B 对照，达标收图"
labels: [wayfinder:task]
status: closed
assignee: ""
blocked-by: [05-deploy-smoke]
---

## Question

外部闸已解除（2026-08-31：aiortc-pacer 图 5/5 票全关，t03 验收 e2e 全档 ~80ms——见 map Decisions 闸门解除条目；剩余依赖仅本图 05）。

开关切 `hard`，Pico 实机四线验收（见 map Destination）：

1. 编码段 A/B：硬编 vs 软编基线（01 票已量，同法对照）；
2. CPU：编码占用下降可观测（01 软编基线 vs 硬编运行时）；
3. e2e 不劣化：时间码照片法 + APK stats（沿用 zed-fpv/pacer 工具链），≤ **85ms**（基线 80ms + 5ms 容差）；
4. 主观画质不降 + **实际 outbound 码率对照**（x264 无 VBV 3-4× 过冲 vs NVENC CBR 收敛——pacer t04 发现的正面对证，量化欠账在此补上）。

红利观测（不设线，2026-08-31 决策）：avgJitterBuffer 对照 pacer-only 残余下限 ~30-48ms——「硬编重开摊平窗口（W: ~4.5ms → ~17-20ms）」论点的数据落点。

数据全进 Resolution；四线全过 → 收图（Decisions 补一行，map status: closed）。任何一线不过 → 回流定位（01/03 对应层）而非放宽线。

## Resolution

**2026-09-02 真机验收完成，用户裁决收图**（四线全过；③ 线按无线归因判不劣化，详下）。同日同法 A/B，工作参数 4M/pacer on/gop30/HD720 SBS。数据详表与事件记录：`research/06-acceptance/06-e2e-acceptance.md`。

| 线 | S（soft） | H（hard） | 判定 |
|---|---|---|---|
| ① E（`[Pacer]` 同法） | 22.4→25.1ms（漂升） | 20.2-20.3ms（稳定） | ✅ |
| ② CPU 占单核 | 135.0% | 88.9%+child 11.5%=100.4% | ✅ −34.6 点 |
| ③ e2e 照片法 | ~100ms | ~100ms | ✅ 同日持平（无线归因） |
| ④ 画质/outbound | 峰 6.8M（1.7× 超冲） | 无差异；3.15M 窄带 2.3-3.6 | ✅ |

红利全兑现：**JB inst 中位 17.7→11.8ms**、pace budget 6.6-9.1→12.0ms（摊平窗口重开论点实锤）、H 臂 E 零漂移。

**③ 线归因**（用户裁决）：85ms 线源于旧网络日 80ms 基线；本场机器人改 WiFi 接入（wlan0 直发，Pico↔机器人 RTT 实测 ~19ms），两臂共模 +20ms 落传输段——本场 JB 反低于旧日（11.8 vs 35-48ms），排除编码/缓冲段。**欠账**：机器人回有线后复测照片法（预计收回 ~8-10ms）。

**部署事件**（同日）：机器人 IP 变更致 APK 连不上——`DefaultUrl` 硬编码旧 IP，IL2CPP metadata 等长改写 `.250` + debug 重签 + 机器人 wlan0 别名临时修复；根治欠账 = pico-bridge URL 可配置化重构建（Unity 许可证续期后）。采样器 awk OFMT 截断 bug 修一；G1 换电池一次（/tmp 清空、别名重加）。
