---
id: 07-zed-half-enumeration-rca
title: "查因：ZED-M 半枚举态（Intel 桥芯 VID / 仅 HID / SDK 时开时不开）"
labels: [wayfinder:research]
status: open
assignee: claude
blocked-by: []
---

## Question

**第 4 次复发，升级为查因票**（用户 2026-09-02 决定入图）。历史：USB2 口仅 HID 枚举 ×2（重插即修）→ 09-02 当日两度出现**半枚举态**——UVC 以 Intel 桥芯 VID（8086:0b3a/0b5b）而非 STEREOLABS VID（2b03:f682）出现在 USB3 总线、HID 单独落 USB2 总线；此态下 ZED SDK **时开时不开**（10:40 open OK 30fps 零错；15:58 CAMERA STREAM FAILED ×5）。两次都发生在 G1 断电/换电池之后。

收集证据，回答：**根因是线缆/口物理层、断电后固件加载竞态、还是 USB3 口电源预算**？判据性观察：

1. `dmesg`（历史注：无 sudo 可能读不到——若可读则抓插入全程枚举日志：VID 呈现顺序、firmware download 有无失败）；
2. 复现矩阵：冷启动 vs 热插拔 × 同口/换口 × 原线/换线（每格记录 lsusb -t 形态 + SDK open 结果）；
3. 半枚举态下 `v4l2-ctl --list-devices` / 直接 UVC 打开（绕过 ZED SDK 判定 UVC 层是否完好）；
4. 交叉对照：ZED_Diagnostic_Results.json（01 票用过）在半枚举态的输出。

产出：`research/07-*.md` 根因结论 + 预防动作（选口/换线/上电时序/开机自检脚本进 run_stack）。

## Progress

- 2026-09-04 Phase 1 只读取证完成（零插拔零写入）：**票面前提勘误**——8086:0b3a/0b5b 是机器人上常驻的两台 RealSense（D435i/D405），非 ZED 桥芯；半枚举态=ZED UVC（2b03:f682）缺席。**根因形状**：USB 物理层信号完整性退化（决定性证据=USB2 侧速度完美预测 SS 成链；Aug 27 以来冷启 14/15 半枚举、三假设中固件竞态证伪/电源预算非主因）。详见 `research/07-zed-half-enumeration-rca.md`。
- 2026-09-04 用户裁决：**D3 热重启判定先行**；今晨 10:24 重插史实已确认（第 5 次复发闭环）；9/2 拓扑变更史实未确认；备用线在手情况未确认。
- 下一步：等下次冷启落半枚举态 → 重启前远程取证 → `sudo reboot` → 判定 SS 是否成链 → 定 run_stack 自检/自动恢复形态 → D1/D2 或闭环。

## Resolution
