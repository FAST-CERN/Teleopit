---
id: bsi-dds-06
title: "BSI_DDSInterface 仓库骨架 + submodule 挂载（task）"
labels: [wayfinder:task]
status: open
assignee: ""
blocked-by: [bsi-dds-01]
created: 2026-08-21
---

## Question

执行类 ticket（map 内唯一）：创建 BSI_DDSInterface 仓库并挂入 Teleopit third_party。

工作清单：

1. **新仓库**（GitHub FAST-CERN org 下，本地路径约定 `F:\Chufan_Rui\teleop\bsi_dds_interface` 同其他 fork）：Python 包骨架——`pyproject.toml`、包结构（`bsi_dds/`：协议模块、DDS 收发模块、进程管理模块、`cli`）、README（双端使用说明：上位机发布端 + 下位机订阅端）。
2. **DDS 栈选型落地**：T1 协议 ticket 决定 IDL 形态后装依赖（cyclonedds + idl 生成 vs cyclonedds-python）。
3. **协议文件落库**：T1 产出的 IDL/schema + 协议文档进该仓库（单一来源）。
4. **mock 发布器**：CLI 命令按可脚本序列发四态标签（验收演示 T7 的测试源）。
5. **submodule 挂载**：`git submodule add` 到 `third_party/BSI_DDSInterface`；**submodule git 行为文档**（init/update/克隆流程，与 vendored 惯例的差异，写进仓库 README + 本仓 AGENTS.md 或 docs/knowledge/repo-guide）。
6. Teleopit 侧冒烟：submodule 下 `import bsi_dds` 可用（CI/测试环境注意 submodule checkout 前置条件——现有测试会不会被缺 submodule 弄红，需要防护）。

完成即 resolve，答案记录：仓库 URL、包名、导入方式、mock CLI 用法。
