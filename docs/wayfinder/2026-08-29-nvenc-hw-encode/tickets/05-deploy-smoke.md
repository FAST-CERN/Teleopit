---
id: 05-deploy-smoke
title: "双 checkout 部署 + teleimager env 冒烟"
labels: [wayfinder:task]
status: open
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
