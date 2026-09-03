---
id: 03-unity-motion-collection
title: "Unity 采集实装：Motion 数据面上行（2 tracker + SN 绑定 + panel 开关）"
labels: [wayfinder:prototype]
status: open
assignee: ""
blocked-by: ["01-tracker-sdk-semantics", "02-unity-build-env"]
---

## Question

`PicoTrackingCollector.AppendMotion()` 从占位变实装（原型票，做出可装的 APK 供人上手）：

1. 采集循环：按 01 的语义读 2 个 tracker 位姿（SN 绑定左右手），入 `Motion` JSON 字段——结构定稿（与占位 `{"joints":[],"len":0}` 兼容升级，含 per-tracker SN/状态/位姿），坐标约定对齐现有 body/hand 处理；
2. SN 绑定 UX：panel 加绑定/显示（或配置文件固定 SN），连接丢失的降级（字段置空 vs 发占位）；
3. `PicoBridgeManager` 加 `sendMotion` 开关（默认值讨论：默认关，与 sendBody 同风格?）；
4. 出包装机（HITL：Pico 侧 APK 安装、tracker 与手套固定）；
5. 顺手项（开票后定）：硬编码 `/offer` URL 改可配置——若做，清 1080p 图同款欠账。

验收：真机 TCP 流里 `Motion` 字段带 2 tracker 位姿、72Hz 帧率不塌、与 Head/Controller 同帧串流。

**欠账带入**（04 已闭挂此）：装机后真机 Motion 流录一段 JSONL → `from_tracking_payload` 回放，确认 `trackers` 解析通过（04 Resolution §6）。

## Progress (2026-09-03, pico-bridge `fdefb58` = 0.2.3)

代码面全部落地，**装机验收待 HITL**：

1. `AppendMotion()` 实装：side-first `Motion.{left,right}{sn,p,valid}` + `poseSpace:"pico_tracker_local"`，位姿套 AppendBody 翻转（−Z/−Qz/−Qw）；未绑定/断连侧整键不发（接收端报 inactive）。**契约以 t04 接收端为准**（t01 research §6 的数组形 sketch 被 t04 side-first 取代）。
2. SN 绑定 = `MotionTrackerBinding`：启动 `CheckMotionTrackerNumber(TWO)` → `RequestMotionTrackerCompleteAction` 枚举 + 连接事件增量维护；新见 SN **自动绑第一个空位（先左后右）**并持久化 `persistentDataPath/motion_tracker_binding.json`——单只开机指认=先开左。绑错纠正：adb 推正确 JSON 或删文件重绑。
3. `sendMotion` 开关：manager 字段+默认关（已有），真机开启走 **BridgeControl `{channel:"tracking",type:"set_motion",payload:{enabled}}`**（panel 按钮推迟到 sbs-1080p WIP 合流后的小票）；pc_receiver 侧 `--motion-trackers` / `bridge.set_motion_enabled()`，连接即推状态（video policy 同款）。
4. Mock 对齐 side-first + `PicoBridgeMockDump`（批处理 dump JSONL）；已验证 mock → `PicoFrame.from_tracking_payload` 端到端（sn/pose/valid/运动性）。109 测试过（1 个 aiortc 预置失败，t04 起就有）。
5. APK 已出：`F:\Chufan_Rui\teleop\t02-verify\pico-bridge-t03.apk`（59.2 MiB，Build Success）。
6. 顺手项（URL 可配置）**已被 af50f5f 清掉**，本票无剩余顺手项。

### HITL 验收 runbook（下次会话）

```bash
# 1. 装机（Pico USB 或 adb over wifi）
adb install -r F:\Chufan_Rui\teleop\t02-verify\pico-bridge-t03.apk
# 2. Pico 系统设置配对 2 只体感追踪器（如未配对）
# 3. 接收端（teleopit env，pc_receiver 目录）
python -m pico_bridge --motion-trackers --print-tracking --record
# 4. 头盔内启动 app（连接收端后自动收 set_motion）
# 5. 绑定指认：只开左 tracker → logcat 看 "[PicoBridge] Motion tracker SN … bound to LEFT" → 再开右
adb logcat -s Unity
```

验收点：① Motion 流 72Hz 不塌、与 Head 同帧；② t01 §5 冒烟——平移/抬举核对翻转方向；③ valid=false 出现在遮挡时；④ `--record` JSONL → `from_tracking_payload` 回放（04 Resolution §6 欠账）。
