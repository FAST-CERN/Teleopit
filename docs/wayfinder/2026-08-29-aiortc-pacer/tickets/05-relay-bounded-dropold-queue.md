---
id: 05-relay-bounded-dropold-queue
title: "relay 订阅队列有界化：运动瞬态后延迟钉死 ~5s 的根因修复"
labels: [wayfinder:fix]
status: closed
assignee: claude
blocked-by: []
---

## Question

真机实锤（见 t04 Progress 2026-08-29 段）：aiortc `MediaRelay.subscribe(buffered=True)` 的订阅者队列**无界**（`aiortc/contrib/media.py`，t01 §4 :537/:628）。运动瞬态把队列灌到 ~150 帧后，输入=输出=30fps，**常驻队列永不排空**（消费端不可能超 30fps）→ 端到端延迟钉死 ~5s，唯一出口是断线重连。REMB 对发送端内部排队无感（不丢包不回退），救不了。

修复：teleimager 内 monkey-patch（照 `jetson_software_encode_frame` 先例风格），把订阅者队列改为**有界 + 丢旧保新**（maxsize≈3）：

1. 读 `aiortc/contrib/media.py` 确认 subscribe/queue 的确切结构（buffered=True 分支 vs False 分支），选 patch 面（自定义 relay 子类 / 包一层 track / 直接改 queue 语义），patch 面最小者优先。
2. 丢旧保新语义必须与上游 `_webrtc_buffer`/track 的「最新帧」语义一致——排队溢出时丢**最旧**帧，接收端最多看到一次跳帧（Pico libwebrtc 会以丢帧/PLI 处理，GOP 30 下自愈 ≤1s）。
3. 验收（下次硬件会话）：同一运动复现场景（t04 Progress 记录的流程）下，运动结束后 ≤5s 内 e2e 回到 <200ms，无需重连；logcat 无 fps 长时间归零。
4. 单机可先验（无头显）：PC aiortc 接收端 + 人为让发送端短暂过载（低优先级，能做就做）。
5. 部署：双 checkout 双推 + 冒烟（deploy-topology 流程）。

与 pacer（t02）正交：本票管「队列永不满仓」，pacer 管「出队后怎么匀速发」。两票完成后 t03 剂量曲线复测才有效。

## Progress（2026-08-29）

实现完成（teleimager `zed-bridge` `560db62`），**部署挂起**（当日硬件提前下线，Jetson 已断电；机器人上线后按 deploy-topology 双推 + 冒烟）：

- **实现**：`_DropOldestQueue`（`collections.deque(maxlen=N)`，N=`TELEIMAGER_RELAY_MAXQUEUE` 环境变量默认 3）+ monkey-patch `MediaRelay.subscribe`，把 buffered 订阅者的无界 queue 换成丢旧保新队列；溢出计数日志（首帧 + 每 30 帧一条）。None 结束哨兵恒为最后一项、必然通过。
- **TDD 红**（stash 见证，未打补丁）：`tests/test_relay_bounded_queue.py` 滞后量不变量——「消费瞬间的帧距生产端头部 ≤ maxlen+slack」未打补丁 MAXLAG=50（100 帧全序列积压），断言失败。
- **绿**：打补丁 MAXLAG=3、服务 51/100 帧（49 帧被丢旧）、REMB 回归 4/4。
- **环境债**：本机（Windows/teleopit env）pytest 跑 asyncio 用例会挂死（连 faulthandler 都冻结，杀僵尸无效，原因未明）——asyncio 侧红绿用 standalone 脚本（`/tmp/dbg_relay2.py` 逻辑已写进 ticket 语境）见证；pytest 文件保留正确断言，机器人 Linux 侧待验证。
- **待办**：①双推 image_server.py + tests ✅（2026-08-31，与 t02 同批，md5 一致）；②机器人 env 冒烟 ✅（2026-08-31：teleimager env 无 pytest → 新增 `tests/standalone_relay_check.py`（`053fc7b`）镜像 pytest 断言；滞后不变量 **MAXLAG=1**（served 3/100、丢旧 90 帧计数日志正常）、保序直通 1→10 全绿——「Linux 侧待验证」债清偿）；③硬件验收（票面第 3 条：运动复现场景 ≤5s 回 <200ms 无需重连）——**唯一剩余项**。

## Resolution

**2026-08-31 真机验收 PASS，票闭。**

票面第 3 条场景（剧烈晃动 ~5s 后骤停）：延迟秒级追回、**无需重连**、无 fps 长时间归零（rx 侧仅 16 丢包 + decodeFps 一次 1.6 即刻恢复 30）。服务器侧同步证据：本轮 log **零 overflow 计数行**——8M/pacer-on 下发送端全程跟得上，队列根本没满过；t05 的有界丢旧在真机是**未触发的安全网**（兜底在 PC standalone 见证 MAXLAG=1）。附带：18:03-04 外部拥塞段（PC 下载）avgJB 飙到 127-167ms 也没钉死，下载停止后 18:07 重连即恢复——旧「5s 钉死仅重连可清」的病象全消。
