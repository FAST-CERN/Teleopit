# t02 构建环境复活 — 记录（2026-09-03）

## 1. Unity Personal 许可

- `C:\ProgramData\Unity\Unity_lic.ulf` 于 09-02 22:10 由 Hub 重签（上一次 term 08-31 到期）。
- Entitlement：`UnityPersonal` (EDITOR) ValidTo 9999 ✓；`StopDate = 2026-09-07T15:10:30`；`UpdateDate = 2026-09-03T14:10:30`（Hub 后台滚签，约每周续一次，**开 Unity 前让 Hub 跑一下即可**）；`AlwaysOnline=false`。
- 批处理模式许可验证通过（两次运行均 `Successfully resolved entitlement details`；启动期有一条良性 `Access token is unavailable` 噪声）。

## 2. 编辑器与工程

- 编辑器：`F:\Chufan_Rui\Unity\Hub\Editor\2022.3.62f3c1\Editor\Unity.exe`（**2022.3.62f3c1 中国版**，branch `2022.3/china_unity/release`）。工程 `ProjectVersion.txt` 精确匹配，零升级弹窗。
- 工程：`F:\Chufan_Rui\teleop\pico-bridge` @ `feat/stereo-fpv` = `7e83469`（= 0.2.2，干净树；sbs-1080p spinner WIP 已 stash：`sbs-1080p UI-grill spinner/ExitHint WIP (mid-edit, unverified)`）。
- 项目载入 13.7s（validate 轮）/ 48.8s（build 轮，scene 因 stash 回退重导入 42s）；程序集编译零错误零警告。

## 3. Validate + IL2CPP 出包

命令（可复用，t03/t04 出包同款）：

```
Unity.exe -batchmode -nographics -projectPath F:\Chufan_Rui\teleop\pico-bridge \
  -executeMethod PicoBridge.Editor.PicoBridgeBuild.BuildAndroidApkFromCommandLine \
  -picoBridgeBuildPath <out.apk> -logFile <log>
```

- `PicoBridge/Validate Project Settings`（批处理 `…SceneSetup.ValidateSettings`）：**All project settings look good!**（IL2CPP / minSDK≥29 / internet / appId 全过）→ `validate.log`。
- Android IL2CPP 构建：**Build Finished, Result: Success.**；player 构建本体 **41.0s**（其中 IL2CPP+Gradle 后处理 34.9s，**热缓存**——af50f5f 出包时代的 Library 缓存仍有效；冷缓存首包会显著更久）；墙钟 ~2min。
- 产物：`F:\Chufan_Rui\teleop\t02-verify\pico-bridge-t02.apk`，**62,052,008 bytes ≈ 59.2 MiB**。构建段日志 → `build-trimmed.log`。

## 4. 环境坑（后续票受益）

- **批处理退出挂死**：两次运行 executeMethod 均成功返回、APK 已落盘，但 Unity.exe 不自行退出（疑似 PICO SDK 后台线程），需 `taskkill //PID <pid> //F` + 手删 `Temp/UnityLockfile`。判定成功看日志（`Build Finished, Result: Success.`）+ APK 文件，**别等进程退出**。
- `-nographics` 下 IL2CPP Android 构建完全可用（日志仅 GI/MF 硬解两条良性警告）。
- PICO SDK 以本地目录包嵌入（`Packages/PICO-Unity-Integration-SDK`），无 UPM 拉取依赖，无网络要求。

## 5. 结论

**可出包**。t03 实装后按 §3 命令重出增量包即可（同树热缓存，预计分钟级）。
