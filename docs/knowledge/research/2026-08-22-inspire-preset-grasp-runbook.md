# Inspire 预制抓取——Orin 部署与 Task 7 真机验收 runbook（2026-08-22）

> 配套：plan `docs/superpowers/plans/2026-08-22-inspire-preset-grasp.md`（Task 1-6 已合并 master）；
> 上位机操作权威文档 `F:/teleop/manus_server/Windows/ManusHapticServer/docs/teleop-deploy.md`（2026-08-08 真机验收过的完整手册，本文不重复其内容）。
> PC=192.168.10.43(Ethernet0)，Orin=unitree@192.168.10.13(wlan0)，手=Modbus .210(l)/.211(r):6000。

## 铁律（唯一 publisher）

`rt/inspire_hand/ctrl/{l,r}` 任何时刻只能有一个 publisher：
- **取数阶段**：manus C++ 上位机发布，Teleopit 主栈**不起**。
- **验收阶段**：Teleopit 发布，manus 前端「控制输出」开关必须**关**（或退进程）。
- 换 publisher 前后可用 `tmp_echo_ctrl.py` 静默监听确认无残留帧。

## 已完成的部署（2026-08-22 03:5x）

| 项 | 状态 |
|---|---|
| master → myfork/GitHub | `4e23d8c`（Task1-6 六提交 + dds_types import 修复） |
| Orin Teleopit | `git diff c634555 4e23d8c -- teleopit/ tests/` patch 已 apply（`/tmp/orin_inspire_preset_grasp.patch`）；`inspire_dds_types.py` 修复版已 scp 覆盖；**import 冒烟 OK**（teleopit env, unset CYCLONEDDS_HOME） |
| Orin driver | `inspire_test` env 跑 `driver_double_wlan0.py`（单命令起双手 worker） |
| manus 上位机 | 用户启动（WPF 前端 + C++ 后端；操作见 teleop-deploy §4 L1→L2） |
| PC 录制器 | `tmp_echo_ctrl.py`（dds-probe env；只读订阅 ctrl/l+r 打 CSV） |

注意：Orin 的 patch **不含 docs/**（Orin 无 plan 文件，git apply 会因缺文件失败）；再同步时一律 `git diff <old>..<new> -- teleopit/ tests/`。Orin 工作树既有的本地改动（openneck calib / pico4_sim2real.yaml / third_party 子模块）与本次改动零重叠，勿动。

## 取数（Task 7 Step 1）

```bash
# PC（已验证可跑；内联 pin Ethernet0，勿用 file:// URI——该版本 cyclonedds 不认）
C:/Users/user/.conda/envs/dds-probe/python.exe tmp_echo_ctrl.py 300 > ../ctrl_capture_session1.csv
```

操作：前端开「重定向」+「控制输出」→ 左手 全张开 3-5s → 自然抓握 3-5s → 右手同样。
判读：CSV `elapsed,side,mode,angle_set,force_set,speed_set`；张开/抓握各取稳定段（连续 ≥30 帧不动的尾段）均值。
回填规则：`angle[5]`（拇指转）**强制 1000** 不取实测；`speed_set` 若实测恒 0/空 → 预设 speed 留空（模式自动落 0b0101，与 C++ 已验收模式一致）。

## 回填（Task 7 Step 2 → 重部署）

1. PC 改 `teleopit/configs/pico4_sim2real_bsi.yaml` `hands.inspire_ftp.presets`（左手/右手若差异大，先记数待议——v1 单表两侧共用）。
2. `git commit` + `git push myfork master`。
3. 同步 Orin（单文件即可）：
   ```bash
   scp teleopit/configs/pico4_sim2real_bsi.yaml unitree@192.168.10.13:/tmp/ && \
   ssh unitree@192.168.10.13 "cp /tmp/pico4_sim2real_bsi.yaml ~/eeg_humanoid/teleop/Teleopit/teleopit/configs/"
   ```

## 验收三行（Task 7 Step 3）

前置：manus「控制输出」关；Orin 起 Teleopit 主栈（tmux B）：

```bash
cd ~/eeg_humanoid/teleop/Teleopit && conda activate teleopit && unset CYCLONEDDS_HOME
export CYCLONEDDS_URI=file:///home/unitree/cyclonedds_orin.xml
python scripts/run/run_sim2real.py --config-name pico4_sim2real_bsi controller.policy_path=ckpt/track_g1.onnx
```

| # | 操作 | 通过判据 |
|---|---|---|
| ① | STANDING：扣左/右扳机 | 对应手 grasp（实测回填角），再扣回 open；拇指转全程不动 |
| ② | VELOCITY 行走中扣扳机 | 无响应、手保持（hold） |
| ③ | L1+R1 → DAMPING | 双手立即张开 |

首帧观察点： Teleopit 首条 ctrl 是 force+angle 组合（0b1101 或回填后 0b0101），留意首帧是否过握（teleop-deploy §6 force-first 写序坑；force 值低=300 缓解）。

## 工具速查

- 录制/监听：上文 `tmp_echo_ctrl.py`（仓库根，scratch，勿提交）
- Orin 只读检查：`ssh -o BatchMode=yes unitree@192.168.10.13 "…"`（driver 进程 `ps aux | grep driver_double`）
- Teleopit 测试权威在 PC（Orin 无 pytest）：`python -m pytest tests/test_inspire_preset_grasp.py -q`
