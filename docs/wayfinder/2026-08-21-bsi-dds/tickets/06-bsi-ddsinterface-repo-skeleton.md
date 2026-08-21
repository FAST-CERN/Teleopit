---
id: bsi-dds-06
title: "BSI_DDSInterface 仓库骨架 + submodule 挂载（task）"
labels: [wayfinder:task]
status: closed
assignee: "claude/main"
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

## Resolution

**2026-08-21 完成（工作清单 6 项全落地）**：

1. **仓库**：`https://github.com/FAST-CERN/BSI_DDSInterface`（private），
   本地 `F:\Chufan_Rui\teleop\bsi_dds_interface`。Python 包 **`bsi_dds`**
   （pip 名 `bsi-dds`）：`protocol.py`（协议常量单一来源）、
   `idl/`（IDL 绑定）、`dds_io.py`（Publisher/Subscriber）、
   `proc.py`（StreamMonitor 健康监测）、`cli.py`（mock/echo/doctor）。
   README 双端使用说明（上位机发布端 + 下位机订阅端）。
2. **DDS 栈**：cyclonedds 0.10.2（pip wheel，含 ddsc 运行库）。
   **绑定不靠 idlc 生成**：idlc 的 Python 后端在 Windows 上静默无输出
   且对 0 起始枚举崩溃，改为**手写落库**，严格照 unitree 仓 idlc v0.11
   模板（dataclass + @final + autoid sequential + IdlEnum），
   README 记录 Linux 重新生成的等价性要求。
3. **协议落库**：`idl/bsi_cmd_discrete.idl`（OMG IDL，C++ 上位机可复用）
   + `bsi_dds/protocol.py` + `docs/protocol.md`（ticket01 决议全文），
   三处同步的维护规则写入 README。
4. **mock 发布器**：`bsi-dds mock --script forward:2,idle:1,left:2,...`
   可脚本四态序列，10Hz；另有 `echo`（订阅端回显生效意图）和
   `doctor`（本机回环自检，实测 9.3Hz/0 gaps）。
5. **submodule 挂载**：`third_party/BSI_DDSInterface` @ `ae9b26d`，
   branch `bsi-dds-06`。submodule git 行为文档落在
   `docs/knowledge/repo-guide.md`（vendored vs submodule 对照表 +
   init/update/bump 工作流 + 空目录不报错→测试须 skip 的约定）
   和 AGENTS.md。**修正 map 记忆**：submodule 并非本仓首例
   （.gitmodules 已有 unitree/linkerhand/somehand 三个），vendored 的
   只有 g1_bridge_sdk。
6. **Teleopit 冒烟**：`tests/test_bsi_dds.py`（submodule 未 checkout 或
   cyclonedds 缺失时整文件 skip，主套件不红；dds-probe 环境全过）；
   `scripts/dev/test_bsi_dds.py` 回环冒烟（submodule 内 import，
   19/20 样本）；全套件 414 passed，3 个失败均为预先存在
   （hdf5_recorder ×2 + dataset_v2 资产相关，master 基线同样失败）。

**验证数据**：子仓 19/19 测试过（含真 DDS 回环 + 静默回落 IDLE +
u32 seq 回绕 gap 计数）；`bsi-dds doctor` 本机回环 9.3Hz/0 gaps。

**答案速查**：仓库 `github.com/FAST-CERN/BSI_DDSInterface`（private）；
包名 `bsi_dds`（`pip install -e third_party/BSI_DDSInterface` 或
sys.path 指向该目录）；`from bsi_dds import DiscreteCommandPublisher,
DiscreteCommandSubscriber`；mock：`bsi-dds mock --script
forward:2,idle:1,left:2,idle:1,right:2,idle:1`。
