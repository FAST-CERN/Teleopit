# doc/ — 文档索引

本仓库实现 **Manus Haptic 局域网串流系统**：C++ 后端服务器（`Windows/ManusHapticServer`）+ .NET 10 / WPF 前端（`Windows/ManusHapticFrontend`）。`doc/` 是所有设计、计划与进度记录的落脚点。

> **新 Agent 先读这几份即可上手：**
> 0. [`knowledge/architecture.md`](knowledge/architecture.md) — **架构地图**（系统全景图 + 分层 + 模块 + 数据流，先看这张图建立整体认识）
> 1. 根目录 [`../AGENTS.md`](../AGENTS.md) — 工作区硬性规则（**强制**）
> 2. [`knowledge/manus_haptic_lan_server_ai_build_guide.md`](knowledge/manus_haptic_lan_server_ai_build_guide.md) — 工程合同（目标 / 架构 / 协议 / 分阶段）
> 3. [`knowledge/build-flow.md`](knowledge/build-flow.md) — 如何构建后端与前端

## 目录结构

| 目录 | 内容 | 何时看 |
|---|---|---|
| [`knowledge/`](knowledge/) | 参考资料：工程合同、构建流程、决策、UI 风格、设计规范 | 动手前查「为什么 / 怎么构建 / 长什么样」 |
| [`review/`](review/) | 历次架构评审：一轮一文件，候选定性/证据/执行状态表（AGENTS.md 规则 10 单一事实源） | 实施评审候选前 / 重跑评审前 |
| [`plan/`](plan/) | 分阶段**计划**：每阶段的目标 / 门禁 / 交付物 / 拟改文件 / 验收 | 启动某阶段前 |
| [`progress/`](progress/) | 分阶段**进度记录**（强制）：改了什么、跑了什么命令、结果 | 确认某阶段是否真做完 / 回顾实现 |

> **`plan/` ↔ `progress/` 一一对应**：`plan/<组件>/phase-*.md` 写「打算怎么做」，`progress/<组件>/phase-*.md` 写「实际做了什么」（组件 = `backend` / `frontend`）。未在 progress 记录的阶段视为未完成（见 AGENTS.md 规则 1）。

## 文档分工
- 根 `doc/`（本目录）管**设计 / 构建 / 分阶段**。
- 各组件 `docs/`（如 `Windows/ManusHapticServer/docs/`）管**该组件运维**（部署、排障、协议示例、测试报告）。

## 权威源（单一事实源，其余位置只链接）
| 事实 | 唯一归属 |
|---|---|
| 项目状态 | [`STATUS.md`](STATUS.md) |
| 关键决策 / 偏离 | [`knowledge/decisions.md`](knowledge/decisions.md) |
| 开发 / 构建环境 | [`knowledge/build-flow.md`](knowledge/build-flow.md) |
| SDK 审计 | [`../Windows/ManusHapticServer/sdk_audit.md`](../Windows/ManusHapticServer/sdk_audit.md) |
| 测试结果 | [`../Windows/ManusHapticServer/docs/test-report.md`](../Windows/ManusHapticServer/docs/test-report.md) |
| 协议规范定义 | [`knowledge/manus_haptic_lan_server_ai_build_guide.md`](knowledge/manus_haptic_lan_server_ai_build_guide.md) §7/§8 |
| 待办 / 未采纳点子 | [`todo/todolist.md`](todo/todolist.md) |
| 发布说明 | [`release-notes/`](release-notes/)（每版本一文件，如 [`release-notes/v0.2.0.md`](release-notes/v0.2.0.md)） |
| AI agent team 结构 | [`knowledge/agent-team.md`](knowledge/agent-team.md) |

## 关键入口

> 项目状态：[`STATUS.md`](STATUS.md)；关键决策 / 偏离：[`knowledge/decisions.md`](knowledge/decisions.md)。

### 后端（C++ / ManusHapticServer）
- 计划：[`plan/backend/README.md`](plan/backend/README.md) — Phase 0–12 总览 + 门禁链 + 技术决策 + 本机 SDK 速查
- 进度：[`progress/backend/README.md`](progress/backend/README.md) — 进度记录约定
- 工程合同：[`knowledge/manus_haptic_lan_server_ai_build_guide.md`](knowledge/manus_haptic_lan_server_ai_build_guide.md)（§3 技术决策 / §7 控制面协议 / §8 数据面协议 / §11 分阶段）

### 前端（.NET 10 / WPF / ManusHapticFrontend）
- 计划：[`plan/frontend/README.md`](plan/frontend/README.md) — Phase F0–F7
- 进度：[`progress/frontend/README.md`](progress/frontend/README.md) — F0–F7 + O1–O5 优化 + R 重构 + postprocess 收尾

### 构建
- [`knowledge/build-flow.md`](knowledge/build-flow.md) — 后端 / 前端构建命令、依赖、standalone exe 交付物、常见坑

## 命名与约定
- **后端（`backend/`）**：`phase-0.md` … `phase-12.md`。
- **前端（`frontend/`）**：构建阶段 `phase-F0.md` … `phase-F7.md`；优化阶段 `phase-O1.md` … `phase-O5.md`；重构 `phase-R.md`；收尾 `phase-postprocess.md`；扩展 `phase-LAN.md`。
- **迭代**：同一阶段多次迭代**追加**到同一文件（按日期分段），不新建。
- **语言**：后端 / 规则文档以中文为主，前端 / UI 文档中英混用；代码、路径、协议字段保持英文。
- **不进 Git**：MANUS SDK、DLL、token、`CMakeUserPresets.json`、build 目录（见 `.gitignore`）。
