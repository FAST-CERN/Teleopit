# BSI desktop acceptance checklist (ticket 07 桌面门)

**入口**：`run_sim.py --config-name pico4_sim_bsi` + `bsi_dds mock`（dds-probe env）。
**脚本**：`idle:3,forward:5,left:3,forward:5,right:3,idle:3,forward:5,idle:3`（~50s）。

两命令分终端对发：

```bash
# 终端 1 (teleopit env) — 仿真 + pico4 摇杆 + BSI 融合
C:/Users/user/.conda/envs/teleopit/python.exe scripts/run/run_sim.py --config-name pico4_sim_bsi controller.policy_path=ckpt/track_g1.onnx

# 终端 2 (dds-probe env) — mock BSI 指令流
C:/Users/user/.conda/envs/dds-probe/python.exe -m bsi_dds.cli mock --script "idle:3,forward:5,left:3,forward:5,right:3,idle:3,forward:5,idle:3"
```

| # | 观察项 | 期望 |
|---|---|---|
| 1 | FORWARD 段 | 机器人平滑前进，lin_x 收敛 ~0.6 m/s |
| 2 | LEFT 段 | 原地左转（ang_z +0.6），无 lin_x |
| 3 | RIGHT 段 | 原地右转（ang_z -0.6） |
| 4 | idle 段 | 1.0s 内开始减速，1.5s 内站住 |
| 5 | 意图切换 | 前→左→前… 平滑过渡，无跳变 |
| 6 | 摇杆抢夺 | 摇杆非零 → 机器人立即跟随摇杆（整包） |
| 7 | 摇杆释放 | 摇杆回零 → 回到脑控 |
| 8 | 急停（键盘 E） | 0.3s 渐 0 → STANDING，站住；锁存保留（不自动解锁） |
| 9 | 急停解锁 | 锁存期 V/Y 被拒；按 E 再释放锁存（仍 STANDING），再 V 进 VELOCITY |
| 10 | BSI 哑音（键盘 C / 左手 Y） | 下一周期衰减归 0，模式不变 |
| 11 | 哑音解除 | 下一周期恢复，无重连延迟 |
| 12 | 静默（mock Ctrl-C） | 1s 后站住（IDLE） |
| 13 | V/X 键 | BSI 不干预状态机，V/X 行为不变 |
| 14 | H 帮助文本 | E/C/Y 键位齐全（estop 仅键盘 E，右手 menuButton 被 pico 占用） |
