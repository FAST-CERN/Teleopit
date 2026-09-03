---
id: 02-unity-build-env
title: "Unity 构建环境复活：Personal 许可重签 + 2022.3.62f3 出包验证"
labels: [wayfinder:task]
status: closed
assignee: ""
blocked-by: []
---

## Question

重编 APK 的前置（HITL，人在场操作）：

1. Unity Personal 许可 term 已于 2026-08-31 过期（`C:\ProgramData\Unity\Unity_lic.ulf` StopDate，`AlwaysOnline=false`）——Unity Hub 重新登录签发，确认 `UnityPersonal` entitlement 恢复且 StopDate 续期；
2. 打开 pico-bridge 工程（`F:\Chufan_Rui\teleop\pico-bridge`，Unity 2022.3.62f3 + PICO SDK，branch `feat/stereo-fpv`）无报错升级/无包缺失；
3. **出最小改动验证包**：menu `PicoBridge > Validate` 过 + Android IL2CPP 构建出 APK 即算过线（不要求装机）；
4. 记录：构建耗时、输出路径、构建日志留档 `research/02-build-env/`。

产出事实（后续票依赖）：可出包结论 + StopDate 新值 + 任何 SDK/Gradle 版本坑。

## Resolution

**closed 2026-09-03**，全部四项过线，记录在 `research/02-build-env/`（notes.md + validate.log + build-trimmed.log）：

1. 许可：Hub 已于 09-02 22:10 重签，`UnityPersonal` entitlement 恢复，**StopDate = 2026-09-07**（Personal 每周滚签，Hub 定期跑即续）；批处理模式许可验证通过。
2. 工程零报错打开：编辑器 `2022.3.62f3c1`（中国版，Hub 装于 `F:\Chufan_Rui\Unity\Hub\Editor\`）与 ProjectVersion 精确匹配；程序集零错误零警告。
3. Validate 过（"All project settings look good!"）+ Android IL2CPP 出包 Success：`pico-bridge-t02.apk` 59.2 MiB @ `F:\Chufan_Rui\teleop\t02-verify\`。player 构建 41s（热缓存；冷首包会更久）。
4. 已留档：构建命令、耗时分解、产物路径、日志。

**坑（t03/t04 出包须读）**：批处理 executeMethod 成功后 Unity.exe 挂死不退出——判定成功看日志 `Build Finished, Result: Success.` + APK 落盘，然后 taskkill + 手删 `Temp/UnityLockfile`。

**边界说明**：验证包出在干净树 `7e83469`（sbs-1080p 的 spinner/ExitHint WIP 已 stash，stash 名 `sbs-1080p UI-grill spinner/ExitHint WIP (mid-edit, unverified)`，归 sbs-1080p 图处置）。
