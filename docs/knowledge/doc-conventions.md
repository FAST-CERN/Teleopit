# 文档结构约定（doc-conventions）

本仓库文档的**结构与维护约定**。硬性规则见根 [`AGENTS.md`](../../AGENTS.md)；
本文是它在文档层面的展开。参考来源：姊妹项目 manusmeta_server 的约定快照
（[`doc-ref/doc-conventions.md`](doc-ref/doc-conventions.md)），按 Teleopit
实际情况适配——Teleopit 是单一 Python 包仓库，没有后端/前端双组件的
plan↔progress 阶段体系，因此只保留适用的部分。

## 1. 目录布局

```
docs/
  docs/                     用户文档站（Docusaurus，英文源）
    getting-started/          安装
    tutorials/                各工作流教程（sim2sim / sim2real / VR / 训练…）
    reference/                架构、配置字段、资产、姊妹项目
  i18n/zh-Hans/             用户文档中文翻译（从英文页翻译，不独立创作）
  knowledge/                开发者长期参考（本目录）
    README.md                 本目录索引 + 权威源表
    architecture.md           架构地图
    repo-guide.md             面向工程师的仓库导览
    doc-conventions.md        本文件
    doc-ref/                  约定参考来源（只读快照，不维护）
  docusaurus.config.ts / sidebars.ts   文档站配置
```

根级另有：`AGENTS.md`（硬性规则）、`README.md`（项目门面 + Quick Start）、
`CHANGELOG.md`（版本记录）。

## 2. 分层规则

- **三层分工**（详见 [`README.md`](README.md)「与仓库既有文档的关系」）：
  1. `AGENTS.md` = 硬性规则与技术契约（最权威）；
  2. `docs/docs/` = 用户文档（教程 / 参考，中英同步）；
  3. `docs/knowledge/` = 开发者内部知识（架构 / 导览 / 约定）。
- **用户文档中英同步**（AGENTS.md 提交策略）：中文页是英文页的翻译，
  先改英文再翻译，绝不独立创作中文内容。
- **knowledge/ 不重复 docs/docs/**：架构地图若与用户文档站架构页重叠，
  knowledge 版面向开发者、可以引用代码路径与内部模块；用户版面向使用者。
  具体数字 / 命令以 `AGENTS.md` 与代码为准。

## 3. 单一事实源（去重靠链接，不复制）

| 事实 | 唯一归属 |
|---|---|
| 仓库硬性规则 | 根 [`AGENTS.md`](../../AGENTS.md) |
| 版本历史 / 迁移 | 根 [`CHANGELOG.md`](../../CHANGELOG.md) |
| 架构地图 | [`architecture.md`](architecture.md) |
| 仓库结构导览 | [`repo-guide.md`](repo-guide.md) |
| 用户教程 / 配置参考 | `docs/docs/` |
| 资产仓库映射 | `AGENTS.md`「External Assets」 |

其余位置**只链接**，不抄写具体值（命令、维度、默认参数、ModelScope 路径）。

## 4. 命名

- knowledge/ 下文件用小写连字符：`architecture.md`、`repo-guide.md`。
- 用户文档站遵循 Docusaurus `sidebar_position` frontmatter（见现有页面）。

## 5. 链接

- 用**相对路径**；移动文件时同步更新指向它的所有链接。
- 本 README 是 knowledge/ 的路由器，子文档回链本 README。

## 6. 语言

- 代码、路径、命令、标识符、配置字段保持英文；
- `docs/knowledge/` 内部文档以中文叙述（开发者内部知识）；
  用户文档站（`docs/docs/`）为英文，中文版在 `docs/i18n/zh-Hans/` 翻译。

## 7. 不进 Git / 不进 knowledge/

- 不进 Git：机器人 mesh、数据集、checkpoint、demo 媒体、
  `teleopit/retargeting/gmr/assets/`（运行时下载，见 `.gitignore` 与 `AGENTS.md`）。
- `doc-ref/` 是外部约定的只读快照，**不随本仓库演进维护**，仅作出处参考。
