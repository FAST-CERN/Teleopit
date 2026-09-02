---
id: 02-unity-build-env
title: "Unity 构建环境复活：Personal 许可重签 + 2022.3.62f3 出包验证"
labels: [wayfinder:task]
status: open
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
