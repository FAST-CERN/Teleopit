# t06 Pico 实机四线验收（2026-09-02，收图）

同日同法 A/B：Round S（soft 基线）与 Round H（hard 验收）各一场，工作参数一致
（4M / pacer on k=1.5 / gop30 / HD720 SBS@30）。e2e = 时间码照片法（用户读数）；
E/budget = 服务端 `[Pacer]` 每 300 帧遥测（`avg recv+encode` / `avg pace budget`）；
JB = APK `[HttpSignaling] stats`（cum + Δtarget/Δframes 瞬时斜率）；CPU/带宽 = 机器人侧
`sample.sh`（/proc stat ticks + /proc/net/dev wlan0 tx，2s 采样，CLK_TCK=100）。

## 四线判定

| 线 | S（soft） | H（hard） | 判定 |
|---|---|---|---|
| ① 编码段 A/B（E） | 22.4→25.1ms（会话内漂升） | **20.2-20.3ms（稳定）** | ✅ |
| ② CPU（占单核%） | **135.0%** | 88.9% + child 11.5% = **100.4%** | ✅ −34.6 点 |
| ③ e2e（照片法） | ~100ms | ~100ms | ✅ 同日持平（见归因） |
| ④ 画质 + outbound | 峰值 6.8Mbps（1.7× 目标超冲）、宽摆 1.8-6.8 | 主观无差异；**3.15M 均值、2.3-3.6 窄带** | ✅ 双过 |

红利观测（不设线，均兑现）：**JB inst 中位 17.7→11.8ms（−6ms）**；pace budget
6.6-9.1→**12.0ms**（摊平窗口重开论点落地）；H 臂 E 零漂移（软编会话内 22→25 漂升）。
纯编码耗时（budget 反演，margin=3ms）：S 晚段 ≈23.7ms → H ≈18.3ms（隔离测量 t02/t05
为 13-15ms，实载差 = REMB 实内容 + CPU 争用，量级合理）。

## ③ 线归因（用户裁决 2026-09-02：无线归因过线）

85ms 线 = 旧基线日（8-31，192.168.10.x）80ms + 5 容差。本场机器人网络已改为
192.168.5.x 且**机器人以 WiFi 受管客户端接入**（wlan0 直发，实测 Pico↔机器人 RTT
≈19ms；旧日大概率机器人走有线）。两臂同读 ~100ms = 共模 +20ms 落在传输段——本场
JB（11.8-17.7ms）反低于旧日（35-48ms），排除编码/缓冲段。**e2e 绝对值复测记欠账**：
机器人回有线接入后复测一轮照片法即可（预计收回 ~8-10ms）。

## 事件与部署事实

- **网络变更事故**：机器人 IP 192.168.10.13→192.168.5.5 后 APK 无法连接——
  `WebRtcHttpSignalingClient.DefaultUrl` 硬编码旧 IP（`Assets/Scripts/PicoBridge/
  Camera/WebRtcHttpSignalingClient.cs:45`），无运行时注入口。**临时修复**：IL2CPP
  `global-metadata.dat` 字面量等长改写 `192.168.10.13`→`192.168.5.250`（2 处）+
  debug 重签重装；机器人 `sudo ip addr add 192.168.5.250/24 dev wlan0` 别名（重启丢，
  需重加）。**根治欠账**：pico-bridge 侧把 URL 做成可配置（UI/intent），Unity 许可证
  续期后重构建。
- 采样器 `sample.sh` 初版 bug：awk 默认 OFMT 把 epoch 打成 `1.78832e+09`（%.6g 截断）
  → 循环秒退/不终止；`printf "%.3f"` 修复。S 臂首场 CPU/带宽数据因此缺失，换电后
  补采（S7 窗）。
- 中途 G1 换电池一次：/tmp 清空（采样器重推）、IP 幸存 DHCP 同址、别名需重加。
- ZED 早间异常枚举一次（Intel VID 8086:0b3a/0b5b，无 2b03）——ZED SDK 仍 open OK
  30fps 0 错，重启后恢复 2b03 枚举；无需处理。

## 工件

`stats_S.txt`/`stats_H.txt`（APK stats 行）、`samples_S7.csv`/`samples_H1.csv`（CPU/
带宽原始采样）、`parse_stats.py`/`sample.sh`（工具）。全量 logcat（~20MB×2）留
`tmp_nvenc_t06/`（未跟踪）。S 臂完整服务端日志 `tmp_nvenc_t06/launch_zed_S.log`。
