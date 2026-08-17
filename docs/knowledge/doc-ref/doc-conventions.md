# 文档结构约定（doc-conventions）

本仓库文档的**结构与维护约定**。硬性规则见根 [`../../AGENTS.md`](../../AGENTS.md)；本文是它的展开。新 Agent 先读 [`../README.md`](../README.md)。

## 1. 目录布局

```
doc/
  README.md            文档总索引 + 权威源表
  STATUS.md            唯一项目状态源
  knowledge/           长期参考（工程合同、构建流程、决策、UI 风格、本约定）
  plan/
    README.md          plan 路由（→ backend/ + frontend/）
    backend/           后端计划：phase-0..11 + README
    frontend/          前端计划：phase-F0..F7 + README
  progress/
    README.md          progress 路由（→ backend/ + frontend/）
    backend/           后端进度：phase-0..11 + README
    frontend/          前端进度：F0..F7 + O1..O5 + R + postprocess + LAN + README
  todo/
    todolist.md        唯一待办 / 未采纳点子汇总
  review/              历次架构评审（一轮一文件 architecture-review-<日期>.md，
                       候选单一事实源，见 AGENTS.md 规则 10）
```

各组件另有就近的运维 `docs/`：`Windows/ManusHapticServer/docs/`（部署 / 排障 / 协议示例 / 测试报告）、`Windows/ManusHapticFrontend/docs/`。

## 2. 分层规则

- **plan ↔ progress 一一对应，按组件分子目录**：`plan/<组件>/phase-X.md` 写「打算怎么做」，`progress/<组件>/phase-X.md` 写「实际做了什么」（组件 = `backend` / `frontend`）。
- **进度记录强制**（AGENTS.md 规则 1）：未在 `progress/<组件>/` 记录的阶段视为未完成。同一阶段多次迭代**追加**到同一文件（按日期分段），不新建。
- **plan 只做计划**；代码 / CMake / `sdk_audit.md` 等实现产物在阶段启动时才落地，不放进 `plan/`。

## 3. 单一事实源（去重靠链接，不复制）

| 事实 | 唯一归属 |
|---|---|
| 项目状态 | [`../STATUS.md`](../STATUS.md) |
| 关键决策 / 偏离 | [`decisions.md`](decisions.md) |
| 开发 / 构建环境 | [`build-flow.md`](build-flow.md) |
| SDK 审计 | [`../../Windows/ManusHapticServer/sdk_audit.md`](../../Windows/ManusHapticServer/sdk_audit.md) |
| 测试结果 | [`../../Windows/ManusHapticServer/docs/test-report.md`](../../Windows/ManusHapticServer/docs/test-report.md) |
| 协议规范 | [`manus_haptic_lan_server_ai_build_guide.md`](manus_haptic_lan_server_ai_build_guide.md) §7/§8 |
| 待办 / 点子 | [`../todo/todolist.md`](../todo/todolist.md) |
| AI agent team 结构 | [`agent-team.md`](agent-team.md) |

其余位置**只链接**，不抄写具体值（测试数字、版本号、机器路径等）——避免一处改、多处漂移。

## 4. 命名

- **后端**：`phase-0.md` … `phase-11.md`（plan 侧带主题后缀，如 `phase-1-skeleton.md`）。
- **前端**：构建 `phase-F0..F7`；优化 `phase-O1..O5`；重构 `phase-R`；收尾 `phase-postprocess`；扩展 `phase-LAN`。O / R / postprocess / LAN 为上线后增量，**无 plan 文档**。

## 5. 链接

- 用**相对路径**；移动文件时必须同步更新所有指向它的链接（grep 旧路径全仓库扫一遍）。
- 父 README 是路由器（指向各子目录），子文档回链父 README。

## 6. 语言

代码、路径、协议字段保持英文；中文用于后端 / 规则文档叙述；前端 / UI 文档中英混用。

## 7. 不进 Git / 不进 doc/

- 不进 Git：MANUS SDK、DLL、token、`CMakeUserPresets.json`、build 目录（见 `.gitignore`）。
- Agent 流程产物（`doc/superpowers/` 的 spec / plan）**gitignored**，不提交；其结论应落入上述 `doc/` 文件，而非留在一次性流程文件里。
