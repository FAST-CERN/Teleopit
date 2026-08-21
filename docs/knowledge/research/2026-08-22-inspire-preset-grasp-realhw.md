# Inspire 预制抓取——真机首验记录（2026-08-22 凌晨）

> 配套：plan `docs/superpowers/plans/2026-08-22-inspire-preset-grasp.md`、
> runbook `docs/knowledge/research/2026-08-22-inspire-preset-grasp-runbook.md`。
> 会话因机器人断连下电中止，**下周继续**（待办见文末）。

## 本次完成

### 取数回填（Task 7 Step 1）✅

- 工具：Windows C++ 上位机（`F:/teleop/manus_server`，teleop-deploy 流程）+ PC 只读订阅器
  `tmp_echo_ctrl.py`（dds-probe env，cyclonedds 0.10.2，内联 pin Ethernet0）。
- 249s 双侧 60Hz 捕获（`F:/Chufan_Rui/ctrl_capture_session1.csv`），稳定平台均值、两侧平均：
  - open = [1000]×6；grasp = [210,165,207,204,600,**1000**]（拇指转钉 1000）
  - force = 1000×6 照抄（C++ gold mode-0b0101 实测恒值）；speed 留空（实测恒 0 → 模式自动 0b0101）
- 提交 `088eaad`（yaml + 合同测试同步），已部署 Orin。

### 真机抓出并修复的 4 个缺陷（全部已推 GitHub）

| 提交 | 缺陷 | 发现方式 |
|---|---|---|
| `4e23d8c` | `inspire_dds_types` 顶层 import 在 cyclonedds 0.10.x 不存在 → 改 `cyclonedds.idl.types` 长路径（对齐 manus 原版逐字） | PC 录制器首跑 |
| `c2dfd70` | `_configured_open_hand_pose` 无条件按 linkerhand 解析 → `preset_toggle` 模式 hand worker 启动即崩 → 加 inspire_ftp 分支（open 预设取位） | Orin 首起栈即崩 |
| `0e97a13` | `DataWriter(Topic)` 单参 → 0.10.x 需 `DataWriter(participant, topic)`（对齐 manus dds_backend） | Orin 二起栈崩 |
| `b19c387` | **`HandRuntime.tick` 转发丢 `speed_set/force_set`** → toggle 帧落线为 mode=1 纯角度（锁定决策是 angle+force 0b0101）；rich 命令带字段、legacy 空字段保持 linkerhand 严格签名 | DDS 捕获分析（25+ toggle 全 mode=1） |

前三个是 cyclonedds 0.10.x API/版本坑（PC 无 cyclonedds 的测试铁律注定只能真机暴露）；第四个是 plan 未覆盖的 tick 桥接点。

### 验收进度（Task 7 Step 2）

| 行 | 状态 | 证据 |
|---|---|---|
| ① STANDING 扳机 toggle | **功能过，模式待复核** | `ctrl_acceptance2.csv`：25+ 次 grasp↔open 干净交替、左右独立；但当时 tick bug 未修，帧为 mode=1（修复后应 mode=5 带 force） |
| ② VELOCITY hold | **未测** | 换电重启后未走到行走段 |
| ③ DAMPING 张开 | **疑似过** | 208574s 双侧同时 mode=5 [1000×6]+force open_all 帧（等待下次连人确认触发语境） |

启动链路全验证：IDLE 门控 open_all → Teleopit(PC发布侧在 Orin)→DDS→driver(wlan0)→Modbus→双手物理张开 ✅

## 下周继续清单（按序）

1. **补部署**：`b19c387` 的 `teleopit/sim2real/hands/worker.py` 断连前 scp 失败，**Orin 上还是旧版**——
   ```bash
   scp teleopit/sim2real/hands/worker.py unitree@192.168.10.13:/tmp/
   ssh unitree@192.168.10.13 "cp /tmp/worker.py ~/eeg_humanoid/teleop/Teleopit/teleopit/sim2real/hands/"
   ```
   （或按 runbook 全量重 patch；Orin 现有其余文件均已是最新）
2. 起栈：tmux `inspire`（driver_double_wlan0，inspire_test env）+ tmux `teleop`（主栈，命令见 runbook）。
3. PC 监听：`tmp_echo_ctrl.py`（仓库根，scratch 勿提交）→ 验证 toggle 帧为 **mode=5 + force [1000×6]**。
4. 补 ②（行走中扣扳机零下发）与 ③ 连人确认；全过则勾 plan Task 7。
5. 全过后：Orin 上 `git checkout` 收编本地脏树（或继续 patch 制），结果补记本文。

## 经验沉淀

- cyclonedds-python **0.10.x** 为本仓已验证版本（PC dds-probe env 与 Orin teleopit env 同版）；新 DDS 代码一律对照 `manus_haptic_rt` 的 0.10.x 写法（`dds_backend.py`/`dds_types.py`），勿凭新版本记忆写。
- PC 侧 DDS 配置：内联 `CYCLONEDDS_URI` XML + `<NetworkInterface name="Ethernet0"/>`（本机 192.168.10.43）；`file://` URI 该版本不认。
- 机器人断电 → DDS writer 消失 → cyclonedds `take()` 返回 `InvalidSample`——订阅工具必须 isinstance 过滤（tmp_echo_ctrl.py 已防）。
- 唯一 publisher 铁律执行顺畅：取数（C++ 上位机）→ 验收（Teleopit）切换无冲突。
