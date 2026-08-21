---
id: bsi-realhw-06
title: "真机运行拓扑确认（运行位置 / DDS 网络 / 接口绑定）"
labels: [wayfinder:task]
status: closed
assignee: "claude/main"
blocked-by: []
created: 2026-08-21
---

## Question

桌面/网络工作，不碰机器人本体：

1. **运行位置**：mp 运行时跑哪——机载 Orin vs 拖链 PC（核查现有 sim2real 部署惯例 + 决定 BSI 场景的运行位；BSI 订阅进程跟随运行位）。
2. **DDS/网络拓扑**：解码器机器 →（domain 0）→ 控制机；`g1_bridge_sdk` 走机器人自身总线——画清谁在哪发/订什么。
3. **接口绑定验证**：在目标机器上复用 `--interface` / `CYCLONEDDS_URI` 经验验证组播加入。

产出：拓扑图/文 + 验证记录（供 04 设计与后续 plan 引用）。

## Resolution

**2026-08-21 事实核查 + D1 定案：板载 Orin。**

**拓扑（三机两总线）**：

```
[BSI 解码器机器]              [G1 板载 Orin]                          [G1 本体]
 EEG 解码 → bsi_dds           mp Sim2RealRuntime                      LowState/LowCmd
 Publisher 发                 ├ robot_control 进程                    (unitree 内部 DDS, HG)
 domain 0 bsi/cmd_discrete    │  ├ BSI 订阅器 + MergedTwistProvider        ↑ eth0
 (WiFi 同网段)     ──WiFi──→  │  ├ 速度 ONNX → send_positions ──────→ g1_bridge_sdk
                              │  └ L1+R1 遥控器（急停底，已存在）
                              └ pico_input / reference 等按配置；Pico HMD 视频（WiFi）
```

- **机器人总线**：`g1_bridge_sdk` 经 Orin `eth0`（`real_robot.network_interface: "eth0"`，pico4_sim2real.yaml:126）与 G1 内部 DDS（HG）收发。
- **BSI 总线**：解码器机器与 Orin 同 WiFi 网段，domain 0 点对点；订阅器住 robot_control 进程（04 决）。
- **运行位置依据**：仓库惯例即板载（tutorials pico-sim2real："Run Teleopit directly on the G1 onboard computer"，板载 `--network-interface eth0`）；Orin 端 cyclonedds 0.10.5 实测正常（installation.md §3）；PC↔Orin WiFi 跨机机制当日已验证（SPDP 组播绑定 → `--interface`/`CYCLONEDDS_URI`）。

**上真机前验证清单**（按序执行，全过 = 拓扑就绪；结果回填本票）：

1. **解码器机器对齐**：确认其 IP/网卡/cyclonedds 版本——若 `.197`（跑 11.x、XTypes hash 不匹配、当日调试中断处）即解码器机器，须对齐本仓锁定（cyclonedds 0.10.x + 同一 bsi_dds commit）；否则 participant 互见但 **0 数据静默丢弃**（installation.md §6）。
2. **Orin 本机栈**：`bsi-dds doctor --duration-s 3` 出 OK；组播 join 在实际链路网卡（`ip maddr | grep 239.255.0.1`）。
3. **跨机端到端**：解码器发 → Orin `bsi-dds echo --interface <wlan0|实际网卡>` 收到流；0 数据则按 §6 四层排（ping → 组播到卡 → doctor → trace 看 type hash）。
4. **Orin 跑 mp 栈**：`run_sim2real.py --config-name pico4_sim2real` 在 Orin 起得来（eth0 桥接正常）；BSI 就绪后换 pico4_sim2real_bsi。
5. **同进程双 DDS 共存**：robot_control 内 BSI cyclonedds（domain 0/wlan0）与 g1_bridge_sdk 的 unitree DDS（eth0）并存互不干扰——各绑各的网卡，验证发现流量不串。

**遗留发现（已裁定，2026-08-21 用户）**：`run_velocity_sim.py:204` 硬编码 KeyboardTwistProvider 为**设计而非缺陷**——该入口本就用于键盘控制验证；不开 fix ticket。

**验证结果回填（2026-08-22 真机会话，详见 `docs/knowledge/research/2026-08-22-bsi-realhw-l1-l3-acceptance.md`）**：

1. 解码器机器对齐：**挂起**（机器当日离线）。
2. Orin 本机栈：**过**（doctor 9.9Hz 0 gaps；wlan0 组播 join 239.255.0.1）。
3. 跨机端到端：**机制过**——PC（dds-probe env，Ethernet0 默认配置）顶替解码器发 mock，Orin echo 收到 IDLE/FORWARD 流；Windows 按名钉接口报 DDS_RETCODE_ERROR，默认配置可用。解码器机器自身对齐待其在线。
4. Orin 跑 mp 栈：**过**（基线 IDLE 起栈 + LowState 流动 + L1 起立 exercised；需 `controller.policy_path=ckpt/track_g1.onnx` override）。
5. 双 DDS 共存：**过**（探针 + 整场 L1-L3 约 1h 双总线并行无串扰）。附带根因修复：bashrc `CYCLONEDDS_HOME` 会造成同进程双 libddsc 实例 → BSI Topic 创建 BAD_PARAMETER，已修 `e5dbd4a`。
