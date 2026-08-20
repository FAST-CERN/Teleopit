---
id: 01-build-environment
title: "构建环境就绪：fork、Unity 安装、上游 APK 原样构建"
labels: [wayfinder:task]
status: closed
assignee: "claude-main"
blocked-by: []
---

## Question

能否在本 Windows 机构建闭环：fork BotRunner64/pico-bridge 到 FAST-CERN、安装 Unity 2022.3.62f3 + Android Build Support（OpenJDK/SDK/NDK）、从 `feat/stereo-fpv` 分支原样构建出上游等价 APK，并经 adb 安装到 Pico 4 启动成功？

具体子步骤（agent 可独立完成前半，后半需人戴头显）：

1. `gh repo fork BotRunner64/pico-bridge --org FAST-CERN`（或手动），本地克隆改 remote，建 `feat/stereo-fpv` 分支。
2. 安装 Unity Hub + Editor 2022.3.62f3 + Android Build Support 模块（约 8–10GB，磁盘放 F 盘）。
3. 用该 Unity 版本打开 ../teleop 下的 pico-bridge 工程，Android 出包（签名用 debug keystore 即可）。
4. adb 安装到 Pico 4，启动 app，确认 TCP 连接 PC receiver 后追踪面板正常（复用上游 README Quick Start 验证法）。

验收：构建产物可安装可运行，且与 GitHub Releases 的官方 APK 行为一致（追踪可用，mono 视频预览可用）。

Resolution 时记录：fork 仓库 URL、Unity 安装路径、构建命令/参数、遇到的上游工程坑（License、包还原、gradle 设置）。

## Resolution

**2026-08-20 完成，全链验证通过**（连接成功 + test-pattern 彩条显示 + 追踪流动）。

- **Fork**：https://github.com/FAST-CERN/pico-bridge （FAST-CERN 是用户账号非组织，直接 fork）；本地 `F:\Chufan_Rui\teleop\pico-bridge`，origin 指向 fork，upstream 指向 BotRunner64，工作分支 `feat/stereo-fpv` 已推送。
- **Unity 安装**：Hub 装在 `F:\Chufan_Rui\UnityHub`，编辑器 2022.3.62f3c1 + Android Build Support（OpenJDK/SDK/NDK 全模块）装在 `F:\Chufan_Rui\Unity\Hub\Editor\2022.3.62f3c1`，共约 12GB。首次安装因 ECONNRESET 全失败，重试一次即成功（Unity CDN 偶发）。
- **License**：Unity Personal（ULF），需人工在 Hub 登录激活，有效期至 2026-08-31，**注意续期**。
- **构建命令**（上游自带 CLI 构建入口，无坑）：
  ```
  Unity.exe -batchmode -quit -nographics -projectPath . \
    -executeMethod PicoBridge.Editor.PicoBridgeBuild.BuildAndroidApkFromCommandLine \
    -picoBridgeBuildPath "F:\...\pico-bridge-stereo-fpv.apk" -logFile build.log
  ```
  产物 `Builds/pico-bridge-stereo-fpv.apk`（62MB，debug 签名，一次通过）。
- **安装到 Pico 4**（SN PA8A10MGJ2280107D, PICO A8110）：头显需开开发者选项 + USB 调试，且 **USB 模式必须选"传输文件"**（仅充电模式不枚举 ADB 接口）；官方 Releases 版签名不同，需先 `adb uninstall com.picobridge.app` 再装。
- **adb 路径**：Unity 自带 SDK `F:\Chufan_Rui\Unity\Hub\Editor\2022.3.62f3c1\Editor\Data\PlaybackEngines\AndroidPlayer\SDK\platform-tools\adb.exe`。
- **PC receiver 坑**：wheel 0.2.1 的 `PicoBridge()` 构造**不启动**服务，必须显式 `.start()`，否则静默无监听（TCP 63901 + UDP 发现广播都不会发）——头显"发现不了 PC"首选查这个。`pip` 默认装到了 `C:\Python314` 用户目录，运行要用 `C:/Python314/python.exe`。
