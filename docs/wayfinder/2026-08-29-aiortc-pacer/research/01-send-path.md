# aiortc 发送路径与 pacing 挂点研究（ticket 01）

- 地图：`2026-08-29-aiortc-pacer`
- 日期：2026-08-29
- 研究问题（ticket 01）：aiortc 从 encoder 产包到 socket send 的完整调用链；在哪里插入 pacing 可 (a) 不破坏 NACK/RTX，(b) 不阻塞 asyncio，(c) patch 面最小（teleimager monkey-patch 可行性）。
- 方法：一手源码逐行核实。本机 aiortc 1.15.0（conda `teleopit` env）+ **Jetson 实机 1.14.0 远程核实（含 md5 比对，五个相关文件全部字节一致，见 §1）**；teleimager 源码（`F:\Chufan_Rui\teleop\teleimager`，zed-bridge 分支）；上游历史经 readthedocs changelog 全文 + GitHub discussion #965 原文。标【事实】= 源码/原文直接可见；标【推导】= 算术；标【推断】= 分析判断。

---

## 0. 六问速答（对应 ticket 需核实 1-6）

| # | 问题 | 一句话结论 | 详见 |
|---|---|---|---|
| 1 | 发送循环结构与 await 点 | `_run_rtp` 是单一长活协程：每帧一次 `recv()` + executor 编码（真挂起点），随后 `for payload` 循环逐包 `serialize → SRTP protect → sendto`，**句法上是逐包 await，但整条链无一处真实挂起**——帧内突发对事件循环是原子的；逐包 sleep 可行且应当插在这里 | §2 |
| 2 | 主线有无 pacing/速率控制 | **没有**。全 CHANGELOG（0.6.0→1.15.0）无任何 pacer 条目；discussion #965 明言「aiortc does not implement a leaky-bucket pacer or anything like that」，无 related PR | §8 |
| 3 | NACK 重传与主循环关系 | 重传在**另一个任务**上执行（DTLS pump 任务 `__run` → `_handle_rtcp_packet` → `_retransmit` → 直达 transport），完全绕过 `_run_rtp`；主循环挂点 pacer **管不住也不该管**重传（重传快是对的） | §3 |
| 4 | 发送变慢时上游队列行为 | 采集→publisher→BGR track 三级都是「丢旧保新」（maxsize=1），**但 relay→sender 一级是默认 `buffered=True` 的无界 `asyncio.Queue`：发送端持续慢于 30fps 时既不反压也不丢帧，而是无界堆积**（每帧 VideoFrame ≈5.3MB）→ pacer 必须带帧内追赶语义，或改 `buffered=False` | §4 |
| 5 | 挂点对比 | 三选一：**A. 替换 `_run_rtp`（推荐，~90-110 行）**；B. encoder 包装层（**不可行**——`encode()` 在 executor 线程同步返回整帧 payload 列表，无逐包 yield 边界）；C. transport 层（~30-50 行，但会把 NACK 重传和 RTCP SR 一起 pace，需解析才能豁免） | §5 |
| 6 | 实机版本 + pin | 实机 = **1.14.0**（python3.10，`/home/unitree/miniconda3/envs/teleimager`）；本机 = 1.15.0；两版发送路径五个文件 md5 完全一致。建议 pin 精确版本 + patch 启动时做源码锚点断言 | §8 |

---

## 1. 版本事实

| 位置 | 版本 | 路径 | 核实方式 |
|---|---|---|---|
| 本机（结构基准） | **1.15.0** | `C:\Users\user\.conda\envs\teleopit\lib\site-packages\aiortc\`（`__init__.py:53`） | `python -c "import aiortc; print(aiortc.__version__)"` |
| **Jetson 实机（活体 env）** | **1.14.0** | `/home/unitree/miniconda3/envs/teleimager/lib/python3.10/site-packages/aiortc/` | SSH `unitree@192.168.10.13` BatchMode key 认证成功，直接用 env 内 python 执行同命令（`conda run` 因非交互 PATH 不可用，改绝对路径） |

**【事实】两版发送路径代码字节级一致**（md5 比对，2026-08-29）：

| 文件 | md5（两机一致） |
|---|---|
| `aiortc/rtcrtpsender.py` | `fdd2ecba52baa30f814a77cdde5df6d9` |
| `aiortc/contrib/media.py`（MediaRelay） | `acd6d9d78d7911e25e31f45b4b070719` |
| `aiortc/rtcdtlstransport.py` | `66fca41e9996f270fdcc201cbda4cd86` |
| `aiortc/codecs/h264.py` | `b3396167dcef7f276c176117a464f9c8` |
| `aiortc/rtp.py` | `534c1b1020c7cf60efe4531abaeee6f5` |

⇒ 本文所有 `file:line` 引用（以本机 1.15.0 标注）**在实机 1.14.0 上逐行相同**（关键锚点已在实机 grep 复核：`rtcrtpsender.py:274/276/318/332/349/357/377/401`、`contrib/media.py:537/579/628`、`h264.py:25/255` 全部命中）。1.15.0 的变更（changelog：datachannel 谈判、ICE 凭据、SCTP 加固、PyAV 17）不触碰媒体发送路径——与 md5 一致互为印证。

> 注：此前 `research/videoserver-ref-comparison.md` 引用的 aiortc 副本在 `Python314\site-packages`（同为 1.15.0）；本 ticket 统一以 conda `teleopit` env 与实机为准，两副本内容相同。

---

## 2. 发送路径调用链（ticket 第 1 点）

### 2.1 ASCII 调用链图

线程/任务边界与每个 await 点如下（除非注明，行号均为 `aiortc/rtcrtpsender.py`，两版一致）：

```
━━━ 线程边界 0：teleimager 主进程（_webrtc_pub 30fps 节拍线程） ━━━
  ZEDBridgeCamera(TripleRingBuffer) → _webrtc_pub 循环              image_server.py:1589-1612
    │  publisher.send(bgr)  ← queue.Queue(maxsize=1)，满则丢旧       image_server.py:570-579
    ▼
━━━ 线程边界 1：WebRTC_PublisherThread（专有线程 + 专有事件循环） ━━━
  run()/_main() 5ms 轮询搬运：push_frame(bgr, loop)                  image_server.py:550-559
    │  av.VideoFrame.from_ndarray + PTS(90kHz 墙钟)                  image_server.py:342-353
    │  call_soon_threadsafe(_put)：满则 get_nowait 丢旧再 put       image_server.py:364-373
    ▼
  BGRArrayVideoStreamTrack._queue   asyncio.Queue(maxsize=1)         image_server.py:314
    ▲ recv(): await _queue.get()        ← 真挂起点(队列空时)          image_server.py:318-322
    │
  MediaRelay.__run_track（每个源 track 一个任务，贪心 30fps 拉取）    contrib/media.py:618-637
    │  await track.recv()（BGR track）← 真挂起点(队列空时)
    │  对每个 subscriber：proxy._queue.put_nowait(frame)             contrib/media.py:628
    ▼                  【注意：buffered=True 默认 → 无界队列，见 §4】
  RelayStreamTrack._queue  asyncio.Queue()（无界）                    contrib/media.py:537
    ▲ recv(): await _queue.get()        ← 真挂起点(队列空时)          contrib/media.py:547-548
    │
━━━ 任务边界：RTCRtpSender._run_rtp（每个 sender 一个 Task） ━━━
  while True:                                     ← :364
    enc_frame = await _next_encoded_frame(codec)  ← await 点① :371
        ├─ data = await self.__track.recv()      ← await 点①a :298（真挂起，仅当队列空）
        └─ payloads, timestamp = await loop.run_in_executor(   ← await 点①b :318-320
               None, encoder.encode, data, force_keyframe)
               ═══ 跳出事件循环 → executor 线程池 ═══
               H264Encoder.encode()（同步函数，返回整帧 payload 列表）
                 codecs/h264.py:290-296 → _encode_frame 生成器（被同步耗尽）
                 → _packetize（FU-A/STAP-A，PACKET_MAX=1300，h264.py:25）
               ═══ future 完成后回到事件循环 ═══
    for i, payload in enumerate(enc_frame.payloads):   ← :377
        构造 RtpPacket（seq/timestamp/ssrc/marker）      :378-385
        abs_send_time = 当前 NTP 时间                    :388-390
        __rtp_history[seq % 128] = packet               :397-399
        packet_bytes = packet.serialize(ext_map)  同步   :400（rtp.py:727）
        await self.transport._send_rtp(packet_bytes)    ← await 点② :401 ★pacer 插这里★
            │  RTCDtlsTransport._send_rtp        rtcdtlstransport.py:706-716
            │    data = _tx_srtp.protect(data)   同步（pylibsrtp C 扩展）  :713
            │    await self.transport._send(data)         ← await 点②a :714
            │      RTCIceTransport._send = aioice Connection.send  rtcicetransport.py:271
            │        await self.sendto(data, 1)           ← await 点②b aioice/ice.py:696
            │          await protocol.send_data(data,addr)← await 点②c aioice/ice.py:709
            │            self.transport.sendto(data,addr) 同步！asyncio.DatagramTransport  :320
            │            ═══ OS UDP socket（非阻塞）→ WiFi ═══
        （循环回 :377 发下一包，帧内零间隔、零真实挂起）
    统计更新 packet/octet_count、seq+1                :403-407
  退出：CancelledError/ConnectionError/MediaStreamError → track.stop() → __rtp_exited.set()  :408-424

━━━ 并行任务 A：RTCRtpSender._run_rtcp（每 0.5+rand() 秒发 SR/SDES） ━━  :426-473
    await asyncio.sleep(0.5 + random.random())       :434  ← 真挂起
    → _send_rtcp → await transport._send_rtp(payload)  :482（与媒体同路但 RTCP 分支 protect_rtcp）

━━━ 并行任务 B：RTCDtlsTransport.__run（DTLS/SRTP 收包泵） ━━━  rtcdtlstransport.py:546,567-579
    _recv_next(): await self.transport._recv()       :633/:640 ← 真挂起（等对端 UDP）
    收到 SRTCP → unprotect_rtcp → _handle_rtcp_data :661-667
      → 路由到 sender._handle_rtcp_packet :610
        ├─ NACK → await self._retransmit(seq)        :274-276  ┐
        │    __rtp_history 查表 → wrap_rtx → serialize            │ §3
        │    → await transport._send_rtp(bytes)     :349        ┘ 重传不经 _run_rtp
        ├─ PLI/FIR → _send_keyframe()：仅置 __force_keyframe=True  :277-281, 351-355
        └─ REMB(APP) → encoder.target_bitrate = bitrate           :282-292
```

### 2.2 关键结构性事实

1. **【事实】帧内逐包链路零真实挂起**：await 点② → ②a → ②b → ②c 四层 await 的被调协程体内全部是同步代码（SRTP protect 是同步 C 扩展调用，`send_data` 体内是同步 `transport.sendto`，aioice/ice.py:319-320），没有任何一处 `await future/sleep/IO`。⇒ **一帧的 7~26 个包从事件循环角度看是原子连发**：突发期间同循环其它任务（信令、RTCP 泵、relay）一个都插不进来。帧与帧之间事件循环只在两处真正让出：编码 executor 往返（①b）与队列空等待（①a）。
2. **【事实】编码在 executor 线程**：`_next_encoded_frame` 用 `run_in_executor(None, encoder.encode, ...)`（:318-320）跑 `H264Encoder.encode()`（`codecs/h264.py:290-296`），后者是**同步函数**，一次性返回 `(payloads: list[bytes], timestamp)` —— `_encode_frame` 生成器（h264.py:248-288）在 executor 线程里被 `_packetize` 同步耗尽，不存在「encoder 逐包 yield 给 asyncio」的边界。teleimager 的 patch `jetson_software_encode_frame`（`image_server.py:114-154`）替换的正是这个生成器，同样在 executor 线程同步执行。
3. **【事实】启动/停止**：`send()` 用 `asyncio.ensure_future` 拉起 `_run_rtp`/`_run_rtcp` 两个任务（:227-228）；`stop()` 先等 started 事件、cancel 任务、再等 exited 事件（:231-242）。**替换 `_run_rtp` 的 patch 必须保留首尾的 `__rtp_started.set()`（:359）与 `__rtp_exited.set()`（:424）及异常兜底（源码注释 :410-413 警告漏设会让 `stop()` 永久挂起）**——这是 patch 正确性的硬约束。
4. 【事实】`abs_send_time` 头扩展在循环内逐包打时间戳（:388-390），pacer 插 sleep 后无需移动它——它本来就贴着每包的发送动作。

### 2.3 突发体量（推导）

帧字节 ≈ bitrate ÷ 30fps ÷ 8；aiortc 实际打包粒度 `PACKET_MAX = 1300`（`codecs/h264.py:25`，FU-A 每包净载 ≤1298B；ticket 里写的 1400B 是线上 MTU 名义值，源码事实是 1300）：

| 码率 | 字节/帧 | 包/帧（ceil(÷1298)） | 帧间隔内匀摊包距 |
|---|---|---|---|
| 2M | 8,333B | 7 | 33.33ms/7 ≈ **4.76ms** |
| 4M | 16,667B | 13 | 33.33ms/13 ≈ **2.56ms** |
| 8M | 33,333B | 26 | 33.33ms/26 ≈ **1.28ms** |

每包线上开销 ≈ 12B RTP 头 + 扩展 ~1-4B + SRTP tag ~10B ⇒ 线上速率比名义码率高 ~2-3%，可忽略。当前零间隔下发完一帧 26 包的墙钟时间是「Python 逐包 serialize+protect+sendto」的纯 CPU 串行和（每包微秒级，总几十 µs）——**突发几乎瞬时打满 WiFi 瞬时队列**，这正是接收端 jitter buffer 观察到的大到达抖动来源（与 map.md 背景数据 8M/4M/2M → 150/112/78ms 的剂量关系吻合）。

---

## 3. NACK/RTX 重传与主循环关系（ticket 第 3 点）

**【事实】重传完全绕过 `_run_rtp`**，走的是另一个任务：

```
DTLS 收包泵任务 __run（rtcdtlstransport.py:546, 567-570）
  └─ _recv_next 收到 SRTCP（:661-667）→ _handle_rtcp_data（:600-610）
      └─ await sender._handle_rtcp_packet(packet)（:610）
          └─ NACK 分支: for seq in packet.lost: await self._retransmit(seq)（rtcrtpsender.py:274-276）
              └─ _retransmit（:332-349）：
                   __rtp_history[seq % 128] 查表（RTP_HISTORY_SIZE=128，rtp.py:13）
                   → 若协商了 RTX: wrap_rtx 换 payload_type/seq/ssrc（:338-345，独立 _rtx_ssrc 与独立 RTX 序号）
                   → packet.serialize → await self.transport._send_rtp(...)（:349）直达 transport
```

- **并发关系**：`_run_rtp`（媒体发送）与 `__run`（RTCP 分发+重传）是同一事件循环上的两个独立 Task。它们只在真实挂起点交错。当前两边的发送链都不真实挂起（§2.2-1），所以互相之间只有微秒级 CPU 串行；pacer 在 `_run_rtp` 内插入 `asyncio.sleep` 后，**重传恰好在 pacer 睡眠窗口被事件循环调度执行——零额外延迟**。
- **pacer 管不住重传，也不该管**：
  - 管不住是结构性的：挂点 A（§5）只改 `_run_rtp` 的循环体，`_retransmit` 调用的是同一个 `transport._send_rtp` 但不经过被 patch 的代码路径。
  - 不该管是语义性的：重传的使命是抢时间（丢包恢复延迟直接叠加到该帧渲染延迟），libwebrtc 的 PacedSender 也对 RTX 单独走快速通道。【推断】重传不 pace 正是期望行为；8M 档 NACK 风暴时重传流量（~1.5% 丢包 ≈ 每 2 帧补 1 包）相对 26 包/帧的主流量是小头，不会重新制造突发。
- **RTCP SR 也不受影响**：SR 走 `_run_rtcp` 任务 → `_send_rtcp`（:475-484）→ `transport._send_rtp`（:482），同样独立于 `_run_rtp`。（PLI/FIR/REMB 只改标志位/属性，不发包，见 :277-292。）
- **历史缓冲与时限**：`RTP_HISTORY_SIZE = 128`（rtp.py:13）按包数计。8M 档 26 包/帧 ⇒ 覆盖 ~4.9 帧 ≈ 165ms 的可重传窗口，pacer 拉长线上时间不改变该窗口的包数语义。【推断】165ms > Pico 端典型 NACK 触发延迟（RTT+jitter buffer 起播预算内），重传命中率不受 pacing 影响。
- **若在 transport 层挂点（§5-C）则重传会被一起 pace**：`_retransmit` 与主循环共用 `transport._send_rtp`，该层收到的字节在 SRTP protect **之前**（protect 在 `_send_rtp` 内部做，rtcdtlstransport.py:710-713），理论上可解析 RTP 头按 `payload_type == rtx_payload_type` 豁免 RTX，但要动 `RtpPacket.parse` 且 RTX 协商与否因会话而异——复杂度不值。

---

## 4. MediaRelay + BGRArrayVideoStreamTrack 队列语义（ticket 第 4 点）

### 4.1 全链四级队列（事实）

| 级 | 结构 | 容量 | 满时行为 | 引用 |
|---|---|---|---|---|
| 1 | `queue.Queue`（thread）publisher 收帧 | maxsize=1 | 丢旧放新 | image_server.py:391, 570-579 |
| 2 | BGRArrayVideoStreamTrack `_queue`（asyncio） | maxsize=1 | `full() → get_nowait()` 丢旧再 `put_nowait` | image_server.py:314, 364-373 |
| 3 | MediaRelay `__run_track` 拉取（asyncio 任务） | —（贪心转发） | **不缓存**：从级 2 取到即转发 | contrib/media.py:618-637 |
| 4 | RelayStreamTrack `_queue`（每个订阅者一个） | **无界**（`asyncio.Queue()` 不带 maxsize） | **不丢不堵：`put_nowait` 永远成功** | contrib/media.py:537, 628；订阅调用 image_server.py:462（用默认参数，即 `buffered=True`，contrib/media.py:579） |

teleimager 的订阅代码是 `self._relay.subscribe(self._bgr_track)`（image_server.py:462）——**没有传 `buffered=False`，走的是默认无界缓冲**。

### 4.2 pacer 拖慢发送后会发生什么

- **发送端与 30fps 产帧率打平或更快**：级 4 队列稳态 0~1 帧，级 1/2 照常丢旧保新，无堆积。这是 pacer 的正常工作区。
- **发送端持续慢于 30fps**（设计失误或码率超额）：级 3 仍然以 30fps 贪心拉空级 2（relay 不知道下游慢），把帧灌进无界的级 4 ——**既不反压也不丢帧，队列线性增长**。每个 `av.VideoFrame`（2560×720 bgr24）≈ 5.3MB：哪怕每秒只净积压 1 帧，也是 5.3MB/s 内存 + 每帧 +33ms 端到端延迟的持续爬升，且**无任何日志报警**。【事实（代码语义）+ 推导（增长速率）】
- **为什么很容易踩进慢区**：sender 每帧周期 = `recv（级4 出队，通常即时）+ 编码（executor，毫秒级）+ 逐包 pace 发送`。若 pace 预算取满 33.3ms，周期 = 33.3ms + 编码 + 调度开销 > 产帧周期 33.3ms ⇒ 慢性落后 ⇒ 触发上一条的无界堆积。
- **两个防线（喂给 ticket 02）**：
  1. **pacer 必须用绝对时间表（leaky-bucket）而非固定 sleep**：`next_send = max(now, next_send + interval)` 模式；落后时（`next_send < now`）不睡、立即连发追赶；帧 deadline 到（下一帧已在级 4 等待）时放弃剩余间隔直接发完。等价于 libwebrtc PacedSender 的 debt/payback 语义。**pacing 速率系数 k 取 1.2~1.5**（帧在 22~28ms 内摊完），给编码与调度留余量。
  2. （可选加固）订阅改为 `self._relay.subscribe(self._bgr_track, buffered=False)`（contrib/media.py:579，1.3.0 起支持）：级 4 变为「最新帧 + Event」语义（contrib/media.py:530-539, 549-551, 630-631），发送端慢时中间帧在 relay 处自然跳过（还省编码 CPU），与上游三级「丢旧保新」语义全线对齐。代价：级 4 不再平滑突发到达，若上游瞬时两帧挤在一起会跳一帧——对 30fps 稳态输入无感。【推断：稳态无丢失，基于 recv 返回 `_frame` 最新值的代码语义】
- 附注【事实】：`recv()` 在 `_enabled=False` 时仍被主循环调用以防空转积压（:303-304 注释），patch 不破坏该行为。

---

## 5. 挂点对比表（ticket 第 5 点）

| 维度 | **A. 替换 `RTCRtpSender._run_rtp`**（照 `_encode_frame` patch 风格内置 teleimager） | B. encoder 包装层异步节流 | C. transport 层（包 `RTCDtlsTransport._send_rtp`） |
|---|---|---|---|
| 做法 | 模块级定义 `_run_rtp` 副本 + 帧内 leaky-bucket，`RTCRtpSender._run_rtp = ours` | 在 `_encode_frame`/`encode()` 外包异步节流 | 每 pc 实例包一层 `_send_rtp`（或子类 RTCDtlsTransport） |
| **可行性** | **可行**（同 `_encode_frame` 先例，image_server.py:154） | **不可行**：`encode()` 是同步函数且在 executor 线程执行（:318-320），一次性返回整帧 payload 列表，无逐包 yield/await 边界可插；在生成器里 sleep 只会阻塞 executor 线程且不影响真实发送时刻 | 可行但脏：`_send_rtp` 是三类流量的公共汇点（主循环媒体 :401 / NACK 重传 :349 / RTCP SR+BYE :482） |
| **patch 面估计** | **~90-110 行**（复制原方法 68 行 :357-424 + pacing ~15 行 + 锚点断言 ~10 行）加进 `image_server.py` 或独立模块 | 0（否决） | ~30-50 行 |
| 最大坑 | 私有属性**名字改写**：`__track/__rtp_history/__log_debug/...` 在外部函数体内必须写 `self._RTCRtpSender__xxx`（~10 处）；必须保留 `__rtp_started/__rtp_exited` 与异常兜底否则 `stop()` 挂死（:239-242, 410-424） | — | RTCP 可用 `is_rtcp(data)`（rtp.py:216）豁免；**NACK 重传无法与普通 RTP 区分**（protect 之前仅差 payload_type/ssrc，需逐包 `RtpPacket.parse`） |
| 对 NACK 的影响 | **零**（重传路径不经此代码，§3）——正是想要的不 pace 重传 | 无（根本没实现） | **会拖慢重传**（除非逐包解析豁免）；也拖 RTCP SR（RTT 测量用，可 `is_rtcp` 豁免） |
| asyncio 阻塞风险 | 无：`asyncio.sleep` 是真挂起；编码仍在 executor；突发反而变成让出点，循环响应性变好（§2.2-1） | 高（睡在 executor 线程） | 无（同 A） |
| 与 aiortc 升级耦合 | **高**（`_run_rtp` 任何改动即破）→ 用启动锚点断言兜底（§8） | — | 中（`_send_rtp` 签名稳定；1.14→1.15 该文件零改动） |
| 覆盖完备性 | 完整：pack/重打包帧、RTX 主 SSRC 发送全在循环内 | — | 完整但过度（连重传/SR 也覆盖） |
| 结论 | **推荐** | 否决 | 备选（若 A 的名字改写不可接受） |

其它考虑过并排除的挂点：feed 侧（publisher/_webrtc_pub 已是 30fps 节拍，问题在帧内不在帧间）；aioice 层（比 C 更深、更难豁免 RTCP）。

【推断】A 方案的 patch 面中约 2/3 是原样复制原方法体——这正是 monkey-patch 的固有税；换来的是零新依赖、scp 通道部署（map 边界决策 3）。若未来 pacer 需要与 REMB 码控修复（ticket 04）等更多内部改动叠加到 3 处以上，重评 fork。

---

## 6. pacing 参数提示（推导值，喂 ticket 02）

- **每帧包数**：`ceil(帧字节 / 1298)`（FU-A 净载；`PACKET_MAX=1300` 含 2B FU 头，h264.py:25, 132-137）。见 §2.3 表：2M→7 包、4M→13 包、8M→26 包（IDR 帧更大，SPS/PPS 走 STAP-A 聚合，实际 ±2 包）。
- **摊平包距**（k=1.0，即满帧间隔 33.33ms）：
  - 2M：4.76ms；4M：2.56ms；8M：**1.28ms**。
  - k=1.25（帧 26.7ms 内摊完，推荐下限）：3.81 / 2.05 / **1.03ms**。
- **asyncio.sleep 粒度风险**：Linux 上 asyncio 定时器粒度 ~1ms 量级，8M 档 k=1.25 时目标包距 1.03ms 已贴粒度下限——单个 sleep 可能睡过头 1-2ms。**无妨**：我们的敌人是 78-150ms 级的到达抖动，pacing 只需把突发摊到 ~30ms 量级平滑，毫秒级 sleep 抖动对 <40ms 预算的 jitter buffer 不可见；用绝对时间表（§4.2）自动吸收睡过头的误差，不累积。
- **不要给尾包（marker=1）后留 sleep**；帧内首包立即发（突发配额 1 包天然存在），剩余 N-1 包摊。
- **预算护栏**：帧 pace 总时长 ≤ `1/fps − 编码耗时 − 2ms 余量`；落后追赶（§4.2 防线 1）保证永不进入 §4.2 的无界堆积区。
- 【推断】附带收益：逐包 `abs_send_time`（:388-390）摊开后，Pico libwebrtc 的 REMB/到达时间估计不再把「瓶颈排队」误读为带宽富余（突发发送时 inter-arrival >> inter-send 导致估计偏高是 libwebrtc 已知偏置），8M 档 REMB 反馈应更贴近真值——此项待 ticket 03 用 stats 验证，不作为验收项。

---

## 7. fork-aiortc 触发判定（ticket 要求产出）

**判定：不触发 fork。monkey-patch（挂点 A）可行，维持 map 边界决策 3 的「teleimager 内置优先」。**

依据：
1. 目标插入点 `_run_rtp` 内层循环是纯方法体代码，Python 层可整体替换，有 `jetson_software_encode_frame` 同风格先例（image_server.py:114-154）与 `setattr` 改模块常量先例（image_server.py:103-106，改 `h264.MIN/DEFAULT/MAX_BITRATE`）。
2. patch 不需要触碰 C 扩展、SRTP、DTLS、ICE——pacer 是纯 Python 时序逻辑。
3. 版本风险有硬护栏：1.14.0 与 1.15.0 发送路径字节一致（§1）+ 启动锚点断言（§8）+ pin。

**重新评估 fork 的触发条件**（写进 ticket 02 的中止条款）：
- (a) patch 需改动 aiortc 内部 ≥3 处耦合点（如 pacer + REMB 修复 + 未来 TWCC 同时要动 `rtcrtpsender/rtcrtpreceiver/rate.py`）；
- (b) 上游 minor 版本反复改动 `_run_rtp` 导致锚点断言连续两次在升级中破；
- (c) 决定向上游提 pacer PR（那时按 fork→PR 流程走，git bundle 走 scp，map 边界决策 3 已预留该通道）。

---

## 8. 上游历史结论 + 版本 pin 建议（ticket 第 2、6 点）

### 8.1 主线无 pacer、无 related PR（事实 + 原文引用）

- **Discussion #965**（[Lack of congestion control in media stream, seeking guidance with pacer](https://github.com/aiortc/aiortc/discussions/965)，2023-05 起，后续回复延续到近年）：提问者报告的正是我们的症状——「the reports are showing a bursty rate rather than a relatively steady one」；研究者 @gehirndienst 的结论原话：
  > "aiortc does not implement a leaky-bucket pacer or anything like that. Instead, it directly transcodes the stream when a target bitrate estimation results in more than 10% bitrate difference."
  >
  > "aiortc uses an outdated and not fully implemented version of GCC algorithm… it uses deprecated REMB reports. Modern WebRTC uses TWCC."

  （"transcodes when >10% bitrate difference" 对应 `codecs/h264.py:251-257` 的漂移重建——teleimager patch 恰好丢掉了它，即 ticket 04 要修的。）维护者未在该讨论中承诺任何 pacer 计划；后续 @RayShing 的回复聚焦 loss-based BWE，同样无人提出 pacer。
- **CHANGELOG 全历史**（[aiortc changelog](https://aiortc.readthedocs.io/en/latest/changelog.html)，0.6.0→1.15.0 逐条核对）**无任何 pacing/pacer/发送平滑条目**。最接近的三条都不是媒体 pacer：1.4.0「`RTCSctpTransport` transmit packets sooner…datachannel latency」（SCTP 数据通道）；0.9.19「limit burst size instead」（SCTP 拥塞窗口）；1.2.0「Make H.264 encoder honour the bitrate from the bandwidth estimator」（就是漂移重建）。
- 与 libwebrtc 的差距参照：native WebRTC 有专门的 [PacedSender 模块](https://webrtc.googlesource.com/src/+/HEAD/modules/pacing/g3doc/index.md)（pacing queue + leaky bucket + RTX 快速通道）；aiortc 无对应物。
- 结论：**主线无 pacer、无 related PR、短期无冲突风险；自建 pacer 不会被上游演进重复或打断（1.14→1.15 媒体路径零改动为证）。**

### 8.2 版本 pin 建议

1. teleimager `pyproject.toml` 把 aiortc 从裸依赖改为**精确 pin**：`aiortc==1.15.0`（与本机一致；实机 1.14.0 可一并升到 1.15.0——两版发送路径字节一致，升级对该 patch 零风险，反而消除双版本漂移）。若不愿动机器人环境，则 pin `aiortc==1.14.0` 并同步本机 env——关键是**两端一个版本**。
2. pacer patch 模块加载时做**源码锚点断言**并 fail-fast（~10 行）：
   - `inspect.getsource(RTCRtpSender._run_rtp)` 含 `"enumerate(enc_frame.payloads)"` 与 `"self.transport._send_rtp"`；
   - `inspect.getsource(RTCRtpSender._retransmit)` 含 `"self.transport._send_rtp"`（确认重传旁路仍在）；
   - `inspect.getsource(RTCRtpSender.stop)` 含 `"__rtp_exited"`（或直接核对 `_run_rtp` md5）。
   断言失败 ⇒ 拒绝启动并报「aiortc 结构变化，pacer patch 需重放」——把 §5-A 的「升级耦合高」从隐性风险变成显式警报。
3. 【推断】上游若出 1.16+，先跑锚点断言再 scp；发送路径两年未见结构性改动（changelog 佐证），断言失效概率低。

---

## 9. 对 `videoserver-ref-comparison.md` 三条预答的核验结果

| 预答 | 核验 | 说明 |
|---|---|---|
| 1. `_run_rtp` 内层逐包 await、零间隔（rtcrtpsender.py:377-401） | **属实**（行号精确命中：for 循环 :377，send :401，无 sleep） | 需补一层精度：这些 await **全部不真实挂起**（链上 4 层协程体内皆同步代码，§2.2-1）⇒ 帧内突发对事件循环是原子的。该文档 §3.4 的推断「突发…更受同循环其它任务干扰」应修正为「突发期间其它任务**无法**插入（无挂起点）；干扰只发生在帧间（编码 executor 往返）」——此点对 pacer 反而有利：插 sleep 后突发段变成让出点 |
| 2. NACK 重传经 `_handle_rtcp_packet → _retransmit` 直达 transport、绕过主循环（:274-276、:332-349） | **属实**（行号精确命中；send 在 :349；执行任务 = DTLS 泵 `__run`，rtcdtlstransport.py:546/600-610） | 并补充：重传与主循环共享同一事件循环，pacer 的 sleep 窗口即重传的调度窗口，零额外延迟（§3） |
| 3. encoder yield 层挂点不可行（encode() 在 executor 同步返回，rtcrtpsender.py:318-320） | **属实**（:318-320 精确；`H264Encoder.encode` 签名同步返回 `(list[bytes], int)`，codecs/base.py:17-20、codecs/h264.py:290-296） | 细化：`_encode_frame` 确是生成器，但它 yield 的是 NAL 单元且被 `_packetize` 在 executor 线程内同步耗尽——没有跨 asyncio 边界的逐包 yield（§2.2-2） |

另核出该文档两处小出入（不属三条预答，顺带记录）：其引用 `PACKET_MAX=1300` 标在 h264.py:24，实际在 **:25**（:24 是 `MAX_FRAME_RATE = 30`）；其 §3.2 称 REMB 漂移重建在 `h264.py:251-260`，条件体实际是 **:251-257**（重建动作在 :269-281）——内容无误，仅行号偏移。该文档对 1.15.0 其余行号引用经本次逐条比对全部属实。

---

## 来源清单

本地源码（`C:\Users\user\.conda\envs\teleopit\lib\site-packages\aiortc\`，1.15.0）：
- `rtcrtpsender.py`（全文通读）、`rtcdtlstransport.py:530-755`、`rtcicetransport.py:260-369`、`codecs/h264.py`（全文）、`codecs/base.py`、`contrib/media.py`（全文）、`mediastreams.py`、`rtp.py:13,216-217,727+`、`rate.py`（归属确认：仅 `rtcrtpreceiver.py:19` 引用，接收端 REMB 生成）

实机源码（`unitree@192.168.10.13:/home/unitree/miniconda3/envs/teleimager/lib/python3.10/site-packages/aiortc/`，1.14.0）：关键锚点 grep 复核 + 五文件 md5 比对（2026-08-29）

teleimager（`F:\Chufan_Rui\teleop\teleimager\src\teleimager\image_server.py`，zed-bridge 分支）：`:98-109, 114-154, 308-373, 391, 458-474, 530-579, 1589-1612`

网络来源：
- https://github.com/aiortc/aiortc/discussions/965 （原文全文抓取）
- https://aiortc.readthedocs.io/en/latest/changelog.html （全历史逐条核对）
- https://webrtc.googlesource.com/src/+/HEAD/modules/pacing/g3doc/index.md （libwebrtc PacedSender 对照，仅作概念参照）

仓库文档：`docs/wayfinder/2026-08-29-aiortc-pacer/map.md`、`tickets/01-aiortc-send-path-research.md`、`research/videoserver-ref-comparison.md`
