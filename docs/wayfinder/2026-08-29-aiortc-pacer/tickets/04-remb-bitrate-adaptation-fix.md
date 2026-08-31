---
id: 04-remb-bitrate-adaptation-fix
title: "REMB 码率自适应修复：接回补丁断开的码控闭环"
labels: [wayfinder:fix]
status: open
assignee: claude
blocked-by: []
---

## Question

`jetson_software_encode_frame`（teleimager 对 aiortc `H264Encoder._encode_frame` 的替换，`src/teleimager/image_server.py:114-116`）只保留了「分辨率变化才重建 codec」的条件，丢掉了上游的**码率漂移重建条件**——aiortc 原版在 `abs(target_bitrate − codec.bit_rate) / codec.bit_rate > 0.1` 时同样置空 codec 重建（`aiortc/codecs/h264.py:250-260`，本机 teleopit env 已逐行核实；机器人 env aiortc 版本未 pin，动手前以实机源码为准复核这一段）。

后果：Pico 端 REMB 反馈压低 `encoder.target_bitrate` 后，运行中 libx264 的 `bit_rate` 仍是建 codec 时一次性写入的旧值（`image_server.py:123`）——**码控闭环断开**，`cam_config_zed.yaml` 的 min floor 在补丁路径下不生效。zed-fpv ticket 06 实测 8M 档 NACK 风暴（~1.5% 丢包、buffer 150-165ms）时码率毫不回退，与此吻合（归因为推断，修后复测可证）。来源：`research/videoserver-ref-comparison.md` §3.2。

修复（≈3 行，补回漂移条件）：

```python
if self.codec and (
    frame.width != self.codec.width
    or frame.height != self.codec.height
    or abs(self.target_bitrate - self.codec.bit_rate) / self.codec.bit_rate > 0.1
):
    self.codec = None
```

要点：

1. 重建复用补丁现有 init 分支，重建路径天然 `force_keyframe = True` 出 IDR（GOP 30 下每秒已有 IDR，可接受；10% 迟滞防抖，与上游语义一致）。
2. 验收：
   - a. 不戴头显可做：PC 浏览器 / python 接收脚本连 `/offer`，人为降带宽 → `getStats` outbound bitrate 跟随 `target_bitrate` 下降（改前：不跟随）。
   - b. 2M 默认档回归：e2e 不劣于 ~120ms 基线（zed-fpv ticket 06）。
   - c. 8M 档复测：拥塞时码率回退、buffer 不再爬到 150ms+；与 pacer 的贡献分离，同步记 `packetsLost`/NACK 次数（stats 已有）。
3. 部署：按 deploy-topology 流程——scp 前先 import 定位活体 checkout、双 checkout 双推、`teleimager` env 冒烟。
4. 顺序：**先于 ticket 02/03 的复测合入**（本票不阻塞 02/03，但 03 的剂量曲线复测应在 04 合入后跑，否则 8M 档 pacer vs 码控归因混杂）。

产出：patch + 改前/改后对照数据（记入本 ticket Resolution）。

## Progress（2026-08-29）

修复+单测+部署+验收 a 完成；b/c 待 Pico 会话。

- **实现**：teleimager `zed-bridge` `6e738ac`（漂移条件）+ `e1a0e56`（重建审计日志 `[H264 Patch] codec rebuild: old -> new`）；TDD 4 测试全绿（teleimager 首批 pytest）。
- **部署**：双 checkout md5 与本地一致 + 双 env 功能冒烟通过；备份 `image_server.py.bak-t04`。
- **验收 a ✅ PASS**（PC .43 aiortc 1.15 接收端 ↔ Jetson teleimager env aiortc 1.14；合成噪声源 2560x720@30 走 zed IPC——当日 ZED 视频接口未枚举、待物理重插；server 临时 default 8M/min 2M/max 12M/GOP 30，测后已还原 2M）：
  - 自然锯齿：8M→4.5M（15:46:43，REMB 下压）后 AIMD 回升；60Mbps UDP 洪泛未劣化链路（sink 满速收、视频零丢）→ REMB 爬满 12M 顶（15:48:41）。
  - 确定性下压（接收端把 REMB estimator 桩钉 3M）：15:51:54 服务端审计行 `codec rebuild: 7758000 -> 3000000`（**与强制同秒**），46s 稳持、接收端零丢包、入流 28Mbps→1.2-5.3Mbps；T+66 恢复 estimator，同秒 `3000000 -> 8379296`，8s 内爬回 11.94M。
  - 反事实：单测证明无修复时 codec 钉死旧码率；zed-fpv t06 实测 8M 档无回退。
- **新发现（影响 t02/t03）**：x264 ABR 未设 VBV/bufsize，噪声内容下 8M 目标实际跑出 15-28Mbps（3-4× 过冲）——当年「8M NACK 风暴」的真实码率可能远超 8M；t03 复测必须记录实际 outbound 码率（或评估给编码器补 VBV 约束）。

**验收 b ✅（Pico 真机 16:23–16:25）**：2M 档 decodeFps≈30、avgJitterBuffer 79.6–82.7ms（基线 78ms 持平）、57s 零新增丢包。服务端审计行显示连接后 REMB 自然爬升至 ~10M——内容简单时实际码率低、buffer 不涨，**burst 大小跟实际码率走而非配置码率**（因果链又添一证）。

**验收 c 阻塞 + 新缺陷钉死（两轮真机复现，16:44 与 16:56 会话）**：大幅运动后端到端延迟升至 **~5s 且钉死不恢复**（仅重连可清零）。证据链（17:02 实时抓现行 + 17:04 干预验证）：

- bridge 新鲜（pub 30fps、0 drop）✓；aiortc DEBUG tap 显示发送端正以 30fps/32.1ms 帧距实时发包 ✓；Pico jitter buffer 仅 93ms、fps≈29、仅丢 4 包 ⇒ **排除接收端 buffer 与无线侧**
- 用户退出重进沉浸（重连）→ frames 归零、buffer 立即回 50–79ms ✓
- **根因：aiortc `relay.subscribe(buffered=True)` 无界订阅队列（t01 §4 预言的堆积风险当场兑现）**——运动瞬态（大帧 + REMB 爬升后高 target 下的重建/IDR 风暴 + x264 无 VBV 过冲）把队列灌到 ~150 帧；此后输入=输出=30fps，**常驻队列永不排空**（消费端不可能超 30fps），延迟钉死 5s 直到重连清零
- REMB 救不了：排队不产生丢包 → 接收端估计器无感 → 16:56:47 后零重建
- 前史 unification：16:29 那次「自愈」= App Slow-frame watchdog 重连；16:45 会话的开场重连同理——所谓自愈都是重连清队列

## Resolution

（待 b/c：b=2M 回归不劣于 ~120ms；c=8M 复测码率回退 + packetsLost，与 t03 剂量曲线合并——均需 Pico 会话）

（待填）
