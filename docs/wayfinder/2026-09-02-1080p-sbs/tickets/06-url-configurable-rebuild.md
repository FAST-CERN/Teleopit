---
id: 06-url-configurable-rebuild
title: "pico-bridge URL 可配置化重构建（退役等长补丁 + .250 别名）"
labels: [wayfinder:task]
status: closed
assignee: "claude-code"
blocked-by: []
---

## Question

NVENC 图部署事故留的根治欠账（用户 2026-09-02 决定移入本图）：`WebRtcHttpSignalingClient.DefaultUrl` 硬编码服务器地址（`Assets/Scripts/PicoBridge/Camera/WebRtcHttpSignalingClient.cs:45`），机器人网段一变 APK 即失联；现行临时方案 = IL2CPP 字面量等长改写 + debug 重签 + 机器人 `192.168.5.250` 别名（重启即丢、每次换电重加）。本图多场真机会话持续踩此摩擦，根治之：

1. 在 `feat/stereo-fpv` 分支上把流地址做成可配置：app 内输入面板（Pico 系统键盘）+ 持久化（PlayerPrefs/最近地址），默认值保持当前 `.250` 以兼容过渡期；已有 `Configure(streamUrl)` 注入口，缺的是 UI/存储接到它；
2. Unity 重构建 APK（许可证续期前提）+ 安装验证（自签或原 keystore，注意与补丁版 debug 签名不同需卸载重装）；
3. 退役清单：机器人 `.250` 别名停用、hex-patch APK 退役、`jetson-teleimager-deploy-topology` 记忆更新。

验收：机器人重启（无别名）后 app 手输 `192.168.5.5:60001` 直连成功出图。

## Resolution

2026-09-02 用户实机验收**成功**（pico-bridge `af50f5f`，feat/stereo-fpv 已推；Unity 2022.3.62f3 批量构建管线 `PicoBridgeStereoBuild.RebuildPrefabAndBuildApk` 直跑通，许可有效——「8/31 过期」记忆过时）。

交付四件：
1. **URL 可配置**：面板 Server 行 `192.168.[A].[B]` 双八位组框 + Connect（控制器拼装 `https://192.168.A.B:60001/offer`），PlayerPrefs 持久化（`pico_bridge.teleimager_url`），`WebRtcHttpSignalingClient.SetServerUrl/Awake 加载`；DefaultUrl 更新为 `.5`。**hex 补丁 APK + `.250` 别名正式退役**。
2. **Resolution 药丸**（720p/1080p）：持久化（`..._resolution`）+ 随 offer body 发送 → 配 04 的 managed bridge 现场切换成功。
3. **沉浸加载环**：`StereoImmersiveLoadingSpinner`（三段 dash 环，Sprites/Default 无字体依赖，Bootstrap 自装、Controller 驱动）——无帧即转，首帧即隐；也盖住 04 的换档间隙。
4. 面板全英文化（TMP 字体无 CJK 字形——中文渲染为 □）。

过程教训：UI 层级改动必须走 `PicoBridgeSceneUiTemplate`（AGENTS.md 规则，runtime 脚本禁建 UI）；APK 签名与 hex 补丁版不同需卸载重装。残留小项（用户后续 UI grill）：面板底部包不住 UI、透明度 bar 过窄长、加载环样式微调。