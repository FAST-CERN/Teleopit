---
id: 04-implementation-merge
title: "teleimager 实现硬编路径并合入 zed-bridge 分支（TDD）"
labels: [wayfinder:task]
status: open
assignee: ""
blocked-by: [03-implementation-design]
---

## Question

按 03 定案实现（TDD，RED→GREEN，沿用 t04 先例的 conftest 测试基建）：

- 子进程编码器脚本（系统 python3 + gi）；
- `_encode_frame` 硬编 wrapper + 配置开关 `encoder: soft|hard`（默认 soft，软编路径行为零变化）；
- REMB 映射 / PLI→force-IDR / 崩溃恢复按 03 定案；
- 启动锚断言（aiortc 版本 + 挂点存在性）；
- 本地（Windows 侧无 NVENC）测试全绿 + 可行的部分实机测试；
- 合入 teleimager `zed-bridge` 分支。
