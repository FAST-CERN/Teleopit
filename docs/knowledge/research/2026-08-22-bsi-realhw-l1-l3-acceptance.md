# BSI 真机 L1-L3 验收记录（2026-08-22）

bsi-realhw 图（`docs/wayfinder/2026-08-21-bsi-realhw/`）的真机验收会话。规格来源：ticket 07 Resolution。代码基线：master `0dc97db` + 当日四个现场补丁（见文末）。

现场：G1 板载 Orin（`unitree@192.168.10.13`，`~/eeg_humanoid/teleop/Teleopit`，conda env `teleopit`）。BSI 解码器机器当日离线，意图源由 Orin 本机 `bsi_dds.cli mock` 代替；跨机机制由 PC（dds-probe env）顶替验证。

## 前置：ticket 06 五步清单

1. 解码器机器对齐：**挂起**（机器离线，外部依赖）。
2. Orin 本机栈：**过**。`bsi-dds doctor --duration-s 5` 输出 `OK: stream alive at 9.9 Hz, 0 gaps`；wlan0 组播 join `239.255.0.1`（users 2）。CYCLONEDDS_URI 用 `~/cyclonedds_orin.xml`（钉 wlan0）。
3. 跨机端到端：**机制过**（PC 顶替解码器）。PC dds-probe env（Ethernet0，默认配置）跑 mock，Orin `bsi-dds echo`（wlan0 钉死）收到 `IDLE/FORWARD` 流。Windows 按名钉接口（"Ethernet0"）会 `DDS_RETCODE_ERROR`，默认配置可用。解码器机器本身的栈对齐并入第 1 步待办。
4. Orin 起 mp 栈：**过**。基线 `pico4_sim2real` 起到 `robot control ready | mode=IDLE`；LowState 在 eth0 流动（diag `wait_for_state=True`）；LowCmd 在 L1 起立时 exercised。起栈需要 `controller.policy_path=ckpt/track_g1.onnx` override（Orin 的 ckpt/ 里已有）。
5. 同进程双 DDS 共存：**过**，两层证据。探针 `/tmp/coexist_probe.py`（先建 G1Bridge(eth0)、后建 BSI 订阅器，即 runtime 真实构造顺序）接收完好；随后整场 L1-L3 约 1 小时双总线并行（wlan0 domain 0 BSI + eth0 unitree HG），无串扰。

## L1 静态站立安全门：过（01:12-01:20，3/3 行）

* 上电 STANDING（kp ramp 2s）站立 60s，无漂移，零 threshold。
* no-op 三连：站立下 Pico 左 grip（E）、Pico B（域外守卫）、遥控器 Y（mocap 配置门）均无副作用。
* damping 演练：L1+R1 → 瘫 → 扶正 → START 回站；恢复后 X 被锁存拒绝，E 解锁后 X 才进 VELOCITY，X 再按经 ramp 平滑回站。

## L2 看护慢速门：过（01:24-01:36，7/7 行，挂悬吊，config `pico4_sim2real_bsi_l2`）

X 起步；BSI forward 直行 ≥5m 目视 ~0.3 m/s；摇杆抢夺/回零交还 ≤2 周期；left/right → idle 压制不动 + 行进中按 B 无副作用；静默 1s 站住；行进中 E：0.3s 渐0 站定 + 锁存 + 拒入 + 解锁恢复；推搡测试：站住不倒。全程零 threshold。

jsonl 客观证据（`velocity_cmd_l2.jsonl`，18831 行）：全文件轴最大值 lin_x=**0.300**、lin_y=**0.000**、ang_z=**0.000**——ForwardOnlyCap 压制与 0.3 限幅逐样本成立。

## L3 自由四态门：条件过（02:09 收工，config `pico4_sim2real_bsi`，摘悬吊）

mock 脚本 `idle:8,forward:10,left:6,forward:10,right:6,idle:8,forward:15,idle:10`。四态方向正确切换平滑、抢夺/交还、E 急停 + 解锁、静默站住，均过。

**未过项：摇杆行走中触发一次过速保护**（`SAFETY: joint 9 velocity 10.23 rad/s exceeds 10.00 -> DAMPING`）。仅超线 2.3%，摇杆阶跃瞬态特征。根因（代码取证）：

* `max_stick_scale` 只配了 `lin_vel_x: 0.5`，而该轴乘的是 cmd 上限 2.0 → 摇杆前进满杆 **1.0 m/s**（操作员反馈"略快"即此）；
* `ang_vel_z` / `lin_vel_y` 未配置 = 默认 stick_scale 1.0 → 转向满杆 ±1.0 rad/s、侧移 ±0.5 m/s，无压制。

修复（`8850b26` + `5df7f2b`）：`max_stick_scale: {lin_vel_x: 0.3, lin_vel_y: 0.4, ang_vel_z: 0.4}` → 前进满杆 0.6 m/s（与 BSI speeds.forward 对齐）、侧移 0.2、转向 0.4 rad/s。**摇杆段需按当日停机规程改日补验**；BSI 侧行为已验。

**其他现场问题**：OpenNeck 机械损坏，已失能。Orin 本地 `pico4_sim2real.yaml` 的 `neck.enabled` 仍为 true，修复期间建议关掉。机械修复后 `openneck.json` 的 7 行标定值（Orin 本地未提交改动）可能需要重新标定。

## 时序指标（jsonl 离线分析 + 探针）

| 指标 | 线 | 实测 | 判定 |
|---|---|---|---|
| 意图 → 融合 cmd | ≤1.0s | 探针 0.22s（3 包去抖后首响应）；EMA 收敛到 0.6 约 1s | 过 |
| E → cmd0 | ≤0.8s | 0.00s（E 按下时 cmd 已为零；0.3s 渐0 路径有单测覆盖，行进中 E 的 file 内样本未捕获，记为待补） | 过（附注） |
| 摇杆抢夺 | ≤2 周期 | 单样本 20ms 整包切换（Δ0.16-0.72） | 过 |
| 误标签孤包不切换 | 不切换 | 单测覆盖（3 包去抖）；现场未注入 | 附注 |
| 静默 ≤1s 开始衰减 | ≤1s | 探针验证（发布端停后 ~1s 内精确归零）；现场 Ctrl-C 发生在 idle 段，file 内不可观测 | 附注 |

数据备注：`velocity_cmd.jsonl` 含 Orin 中途重启（monotonic 归零，span 出现负值），按会话分段处理；L3 主段（219s）74% 样本 muted=True——操作员在用 Pico Y 哑音键切换 BSI/摇杆源，mute 功能获得现场锻炼。

## 当日代码变更（全部已 patch 到 Orin）

| commit | 内容 |
|---|---|
| `e5dbd4a` | `bsi_factory.sanitize_bridge_coexistence_env`：桥在进程内时 pop `CYCLONEDDS_HOME`，杜绝双 libddsc 实例（见下） |
| `f045252` | `velocity_safety_verdict` 支持 per-joint 数组（严格 `>`，违规日志报关节号和各自上限）+ 阈值边界钉测 + 30-45° 带降为 WARNING |
| `8850b26` | 摇杆 stick-scale 与 BSI 包络统一（0.3/0.4/0.4） |
| `5df7f2b` | 配置合同钉测同步 |

Orin 经 `git am` 应用（哈希不同、内容相同），与本仓 GitHub master 需在下次维护窗口归一（注意 Orin 本地 neck 两文件改动要保留）。

## 环境坑（根因记录）

**robot_control BSI 订阅器 `Topic` 创建 `DDS_RETCODE_BAD_PARAMETER`**：Orin bashrc 155 行 `export CYCLONEDDS_HOME=~/cyclonedds_ws/install/cyclonedds` 使 cyclonedds-python 按该路径**另载第二份 libddsc**（`libddsc.so.0.10.2`），与 g1_bridge_sdk 自带的 `libddsc.so`（先载）形成同进程双 CycloneDDS 实例，句柄串门。干净 shell（无 bashrc）里 python 复用已载实例，故只在实际登录 shell 崩。修复：临时 `unset CYCLONEDDS_HOME`；持久 `e5dbd4a`。诊断脚本 `/tmp/diag_dds.py`（maps 抓双份加载）。

## 遗留

* 06-1 解码器机器对齐（cyclonedcs 0.10.x + bsi_dds commit 同锁），机器在线后做。
* 摇杆段补验（stick-scale 修复后，L3 场景重走摇杆行进 + 抢夺）。
* per-joint 限速数值回填（机制已上，现用标量 10.0；值从 G1 官方表或真机遥测来，用户已定先后次序）。
* OpenNeck 机械修复 + 可能的重标定；修复前关 `neck.enabled`。
* Orin 与 GitHub master 哈希归一（内容已同）。
