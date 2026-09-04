---
id: 07-pico-bridge-mode-mutex
title: "pico-bridge 模式互斥切换：上半身默认 vs 全身 body tracking，panel 二态 + 远程 set_body"
labels: [wayfinder:prototype]
status: open
assignee: claude
blocked-by: []
---

## Question

t06 主观轮诊断出 body 流「发但空」三因（panel `EnableAutomaticTrackingStreams` 无脑全开流覆盖 scene 默认；手套挡头显相机 → body 数据无效；app 从未调 `StartBodyTracking`）。需要一个**互斥的臂源模式切换**，让操作员在头盔内一键选「上半身 tracker 模式」（默认）或「全身 body 模式」（摘手套+拿手柄时用），替代现在流全开互相干扰的状态。

2026-09-04 21:22 grilling 定案（全部按推荐 settled）：

- **切换形态**：panel 二态按钮（SN 绑定状态一并显示，吸收 t03 panel 欠账）+ 接收端远程 `set_body` 下发——接收端为权威（`arm_source` 三态：`tracker` / `body` / `auto`？定案=三态，默认 tracker）。
- **全身模式开启**：app 调 `StartBodyTracking(BODY_JOINT_SET_BODY_FULL)`；骨长 = 比例表 × `human_height`（`BodyTrackingBoneLength` 为逐段长度结构体，非枚举——已核实）。
- **版本闸**：pc_receiver 0.2.4 + Teleopit 侧 gate 抬到 (0,2,4)。
- **回归**：需重编 APK（Unity 许可周滚签注意 StopDate）+ t03 冒烟（SN 绑定、69Hz、valid 语义）不回退。

验收：panel 切换生效且流互斥；tracker 模式行为与 cb46907 回归后一致；body 模式在摘手套+手柄场景能出有效 body 帧。

## Resolution

代码面全落地（2026-09-04 晚，pico-bridge `8f105fc` + Teleopit `2fa7dcd`；APK 已出待装机）：

- **设备端模式互斥**：`PicoBridgeManager.armStream`（Trackers 默认 / Body）独占 `sendBody`/`sendMotion`（至多一开）；Body 模式调 `StartBodyTracking(BODY_JOINT_SET_BODY_FULL_START)`+骨长=比例表×`operatorHeight`（11 段人体测量分数，1.0–2.2m 夹紧），离开时 `StopBodyTracking`；panel 无脑全开 body/motion 的行为删除（「发但空」根因）；初始模式在 Start 应用（Trackers 默认=两流皆关直到 receiver/panel 请求，保 cb46907 回归契约）。
- **远程**：`BridgeControl tracking/set_body {enabled,height}` 切 Body；`set_motion(true)` 现在同时离开 Body 模式。
- **panel**：代码自建 pill 行（Trackers/Body + SN 绑定显示 `L:1 R:2`，断连标 `!`）挂在 server-URL 行下——零 prefab YAML 手术；点击 Trackers=开 motion，点击 Body=开 body。
- **接收端 0.2.4**：`PicoBridge(arm_source=…)`/CLI `--arm-source {tracker,body,auto}` + `--operator-height`；body 连接即推 set_body（motion off）；**auto** 先请求 trackers、回退窗（默认 15s）内无 valid 侧则粘性回退 body；`set_body_enabled()` 运行时切换；CHANGELOG 回填 0.2.3。
- **Teleopit**：`arm_source='body'` 传 `arm_source`/`operator_height_m`（=cfg `input.human_height`）给 in-process bridge，网关抬 (0,2,4)（tracker 模式保持 0.2.3 签名兼容）；teleopit env 已重装 0.2.4。
- **测试**：receiver 118 过（+7 runtime-control，1 预置 aiortc 败）；Teleopit 620 过（+3 provider，4 预置败不变）。
- **APK**：`F:\Chufan_Rui\teleop\t02-verify\pico-bridge-t07a.apk`（62,069,240B，热缓存构建 Success）。

**不带真机的验证（2026-09-04 晚补齐，pico-bridge `e31f5bb`）**：

1. **APK 内容**：`global-metadata.dat` 含 `ArmSourceControl`/`set_body`/`operatorHeight`/`DescribeSides`——新代码确实入包。
2. **编辑器 prefab 冒烟**（`PicoBridge.Editor.PicoBridgeT07Smoke.Run`，headless executeMethod）：真 panel prefab 上构建 pill 行成功；默认双流皆关（cb46907 契约）；接收端格式 JSON 驱动互斥全对（set_body on/off+height 1.82 解析、set_motion(true) 离开 Body、pill 高亮刷新）——**`[T07SMOKE] PASS (17 checks)`**。
3. **真 TCP 回环**（`test_arm_source_loopback.py`，假设备=裸 socket 说线协议）：body 连接即收 `[set_motion(false), set_body(true,1.66)]`、tracker 只收 `set_motion(true)`、auto 0.5s 无 valid 回退推 set_body——3/3 过。

**仍需真机**（SDK 原生行为无法离机模拟）：`StartBodyTracking` 返回码与实际骨架质量、panel 在头盔内的视觉排版、tracker 绑定/频率回归。

**HITL 第一轮（2026-09-04 晚，用户在机）**：

- ✅ 装机 t07a（62,069,240B）。
- ✅ **t03 冒烟回归**：69.5Hz 中位（基线 69.4）、零 >1s 间隙、SN 自动绑 1→LEFT/2→RIGHT、遮挡 valid 语义活。
- ✅ **panel**：Trackers/Body pill + `L:1 R:2` SN 显示在头盔内正常（用户确认）。
- ✅ **set_body 远程链**：设备日志 `set_body=True height=1.75` 解析、互斥生效（sendMotion=false/sendBody=true、AppendBody 每帧跑）。
- ✅ **body 数据线**：OS 切全身动捕后 1514 帧 Body 关节、**len=24**（`tracking_20260904_231338.jsonl`）。
- **三层模式栈定案**：臂源=OS tracker 工作模式（独立追踪↔全身动捕，**人工切换**——SDK 无静默口，`CheckMotionTrackerNumber` 仅弹引导面板）→ app 流互斥（已验）→ receiver 权威推送（已验）。
- ⚠️ **未决**：① body 请求期间（OS 尚在独立模式）出现规整 ~2.06s 断连抖动，未归因（OS 模式不匹配相关？切模式后未复测连接稳定性）；② auto 真机轮未跑；③ Rerun `--viz` 显示未验（本机无 viewer 二进制）。

**操作台账（本轮新坑，后续轮受益）**：
- adb=`C:/Program Files (x86)/Android/android-sdk/platform-tools/adb.exe`；接收端必须以 `teleopit` env 的 **python.exe** 形态跑（防火墙有放行），console-script exe 会被 RST（111）。
- **换 tracker 单元**后：先在系统设置配对新单元，再 `pm clear com.picobridge.app` 清旧 SN 绑定，然后**先开左后开右**重新指认。
- 头盔未佩戴时 PICO 会冻结/回收 3D app（am start 后进程消失）——装机轮需佩戴。
- **多接收端发现竞争**：app 锁定首个发现包（Jetson `.5` 的幽灵广播曾抢占 → 连接被拒死循环）；force-stop app 重发现即可解。Jetson 侧当时无广播进程，来源待查。

**标定可视化增补（2026-09-04 深夜，用户需求：tracker 重绑扎后安装朝向需重标，可视化须标明方向；pico-bridge `763f480`）**：

- `MotionTrackerVisualizer`（设备端常驻）：每个 tracker 位姿处渲染小 Cube + **RGB 三轴杆（带箭头尖端）**，轴向=**`pico_tracker_local`**（与 `tracker_synth_config.tracker_offset` 写入坐标系严格一致——对屏量出 `offset = p_tracker − p_腕`（gizmo 轴分量）直接贴 YAML，零换算）。
- FOV 反馈：valid=侧色（左橙/右绿）；丢追=**灰色 ghost 冻在末位姿**（操作员可见丢在哪、往哪收）；断连=隐藏。panel SN 行补 `?` 后缀=光学 invalid（`!`=蓝牙断连语义不变）。
- 编辑器冒烟扩到 22 检查全过；APK **t07b**（62,071,856B）已出待装机。

**HITL runbook（待人工，续）**：

1. 装机：`adb -s PA8A10MGJ2280107D install -r F:\Chufan_Rui\teleop\t02-verify\pico-bridge-t07a.apk`
2. **t03 冒烟回归**（不得回退）：接收端 `--motion-trackers --print-tracking`；tracker 免 power-cycle 自动绑 SN 1/2；~69Hz；遮挡→valid=false 语义活。
3. **panel 检查**：server-URL 行下出现 Trackers/Body pill 行+SN 显示；默认 Trackers 亮。
4. **body 轮**：摘 MANUS 手套+双手柄；接收端重启用 `--arm-source body --operator-height <身高>`；确认 Body 帧有效（joints len=24、头显内可见骨架视觉）；panel 点 Body 亦可本地切。
5. **auto 轮（可选）**：tracker 关机状态下 `--arm-source auto` → 15s 后日志出现 fallback、Body 帧起。
6. Rerun side-first 顺带验（t08 遗留）：`--viz` 时 Track-L/Track-R 徽章+左右 puck（本机需装 rerun viewer）。
