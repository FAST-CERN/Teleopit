---
id: 06-url-configurable-rebuild
title: "pico-bridge URL 可配置化重构建（退役等长补丁 + .250 别名）"
labels: [wayfinder:task]
status: open
assignee: ""
blocked-by: []
---

## Question

NVENC 图部署事故留的根治欠账（用户 2026-09-02 决定移入本图）：`WebRtcHttpSignalingClient.DefaultUrl` 硬编码服务器地址（`Assets/Scripts/PicoBridge/Camera/WebRtcHttpSignalingClient.cs:45`），机器人网段一变 APK 即失联；现行临时方案 = IL2CPP 字面量等长改写 + debug 重签 + 机器人 `192.168.5.250` 别名（重启即丢、每次换电重加）。本图多场真机会话持续踩此摩擦，根治之：

1. 在 `feat/stereo-fpv` 分支上把流地址做成可配置：app 内输入面板（Pico 系统键盘）+ 持久化（PlayerPrefs/最近地址），默认值保持当前 `.250` 以兼容过渡期；已有 `Configure(streamUrl)` 注入口，缺的是 UI/存储接到它；
2. Unity 重构建 APK（许可证续期前提）+ 安装验证（自签或原 keystore，注意与补丁版 debug 签名不同需卸载重装）；
3. 退役清单：机器人 `.250` 别名停用、hex-patch APK 退役、`jetson-teleimager-deploy-topology` 记忆更新。

验收：机器人重启（无别名）后 app 手输 `192.168.5.5:60001` 直连成功出图。

## Resolution
