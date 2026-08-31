---
id: 05-deploy-smoke
title: "双 checkout 部署 + teleimager env 冒烟"
labels: [wayfinder:task]
status: closed
assignee: ""
blocked-by: [04-implementation-merge]
---

## Question

按 deploy-topology 流程（跨会话记忆 `jetson-teleimager-deploy-topology`）：

1. import 定位活体 checkout；
2. 双推：`/home/unitree/teleimager` + `eeg_humanoid/teleop/xr_teleoperate/teleop/teleimager`（子进程脚本落位按 03 定案）；
3. md5 核对双副本一致；
4. `teleimager` env 冒烟：硬编开关开 hard，fake/真源跑若干秒，确认子进程拉起、AU 流动、控制行生效、软编开关切回无损；
5. 停机窗口内完成，直播恢复前把开关回 soft（若 06 尚未到闸）。

## Resolution

2026-08-31 全五步过，停机窗口内完成（21:10-21:31，bridge 全程停止、ZED UVC @5000M 健康）。

**步骤 1-3（定位 + 双推 + md5）**：双 env import 定位确认活体 = `teleimager` env→`/home/unitree/teleimager`、`xr_tele` env→`eeg_humanoid/.../teleimager`；推 9c0014a 的 `image_server.py` + `_nvenc_child.py`（LF 规范化取自 git 索引，避 CRLF 噪音）至双副本 `src/teleimager/`，md5 `99874ec3`/`e6d1a4a1` 四份一致。

**冒烟 A（raw 直驱 `_nvenc_child.py`，`/usr/bin/python3`）**：R 握手 `{force_idr_prop: 'force-IDR', vbv_set: true}`；B 4M→2M 运行时改码率生效（同帧重复源 AU 28.7→13.6 KiB 线性跟随，无 `bitrate/vbv-size set failed` 打印）；I 强制 IDR 出 `[SPS,PPS,IDR]`。**t03 Q6 欠账清：vbv-size=bitrate/30 初值 set 成功 + 运行时随码率跟随无失败**。

**冒烟 B（wrapper 类 `_NvencSubprocessEncoder`，即 t04 合入代码路径）**：首 AU `[7,8,5]`、E p50 13.3ms/p95 19.2ms（t02 带载 15.2ms 前提在合入路径复现）；REMB 同帧源 4M 9.2→8M 15.3 KiB、5% 迟滞不发送；force keyframe 出 IDR；SIGKILL 子进程→244ms 恢复续流 `[7,8,5]`；stop 无残孤。注：每帧独立随机噪声把编码器打到 QP 地板（AU ~213 KiB 饱和、对码率不敏感）——B 码率正向观测须用同帧重复源，属源特性非缺陷。

**栈级（步骤 4-5）**：`TELEIMAGER_ENCODER=hard` + `run_stack.sh 4 1`（真源 ZED）→ 日志锚 `encoder=hard: NVENC subprocess via /usr/bin/python3`、子进程拉起；PC 侧 aiortc 收流 30s：**30.1fps 满帧率、9109 包 0 丢、帧到达摊平中位 16ms/p95 21ms（pacer 窗口内）、goodput 2.96Mbps、NVENC 零错误零重启**。unset env 重启 → `encoder=soft: in-process libx264`、无子进程、PC 收流 30.1fps 0 丢——**开关切回无损**。收尾栈停、端口下、无残孤。

副产物：`tests/pacer_ab_receiver.py` 加 `PACER_AB_SERVER` env 覆写（跨 LAN 指向 Jetson）。冒烟脚本存 `/tmp/nvenc_t05/`（机器人）与本地 `tmp_nvenc_t05/`（未跟踪）。Frontier：06 e2e 验收（四线）依赖全闭。
