# knowledge/ — 长期参考文档

本目录存放 Teleopit 的**长期参考知识**：架构地图、文档约定、面向工程师的仓库导览。
面向最终用户的教程与配置参考在用户文档站（`docs/docs/`，Docusaurus，发布至
GitHub Pages），与本目录职责不同——**本目录给开发者看，docs/docs 给用户看**。

> 约定与结构规则见 [`doc-conventions.md`](doc-conventions.md)（参考自
> [`doc-ref/`](doc-ref/) 中的成熟约定并按本仓库情况适配）。

## 目录内容

| 文件 | 内容 | 何时看 |
|---|---|---|
| [`architecture.md`](architecture.md) | 系统架构地图：管线、分层、模块、数据流、线程/进程模型 | 动手前建立整体认识 |
| [`repo-guide.md`](repo-guide.md) | **面向工程师的仓库导览**：文件结构、各模块功能、代码使用方式 | 第一次进本仓库 / 查「某文件是干什么的」 |
| [`doc-conventions.md`](doc-conventions.md) | 本目录（及仓库文档）的结构与维护约定 | 新增 / 移动文档前 |
| [`doc-ref/`](doc-ref/) | 参考约定来源（姊妹项目 manusmeta_server 的文档约定快照，只读参考） | 想了解约定出处 |

## 权威源（单一事实源，其余位置只链接）

| 事实 | 唯一归属 |
|---|---|
| 仓库硬性规则（开发约束、提交策略） | 根 [`AGENTS.md`](../../AGENTS.md) |
| 版本历史 / 迁移说明 | 根 [`CHANGELOG.md`](../../CHANGELOG.md) |
| 架构地图 | [`architecture.md`](architecture.md) |
| 仓库结构与模块导览 | [`repo-guide.md`](repo-guide.md) |
| 用户教程 / 配置字段参考 | `docs/docs/tutorials/`、`docs/docs/reference/`（Docusaurus 用户文档站） |
| 资产下载 / ModelScope 仓库映射 | 根 [`AGENTS.md`](../../AGENTS.md)「External Assets」节 |
| 训练任务技术面 | 根 [`AGENTS.md`](../../AGENTS.md)「Training Task」节 |

> 其余位置**只链接**，不抄写具体值（命令、路径、维度、默认参数）——避免一处改、多处漂移。

## 与仓库既有文档的关系

Teleopit 已有三层文档，各有分工：

1. **根 `AGENTS.md`** — 开发硬性规则与技术细节契约（最权威，代码改动须与它同步）。
2. **`docs/docs/` + `docs/i18n/zh-Hans/`** — Docusaurus 用户文档站（教程、配置参考、架构页），
   面向使用者，中英对照。
3. **`docs/knowledge/`（本目录）** — 开发者内部知识：架构地图、仓库导览、文档约定。
   内容若与 `AGENTS.md` 冲突，以 `AGENTS.md` 为准。
