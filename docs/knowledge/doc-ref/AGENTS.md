# AGENTS.md — 工作区约束（适用于所有 AI Agent）

本仓库按 `doc/knowledge/manus_haptic_lan_server_ai_build_guide.md`（工程合同）实现 `Windows/ManusHapticServer`。分阶段计划见 `doc/plan/`，阶段进度记录见 `doc/progress/`。项目当前状态见 `doc/STATUS.md`，文档结构约定见 `doc/knowledge/doc-conventions.md`。

## 硬性规则
1. **进度记录（强制）**：每个阶段的全部新增/修改都必须在 `doc/progress/<组件>/phase-*.md` 记录（后端 `backend/phase-<N>.md`、前端 `frontend/phase-*.md`）——改了哪些文件、跑了什么命令（含退出码）、结果与偏离。**未记录视为未完成**（Phase 0 只读审计也要记）。同名文件按日期追加，不新建。
2. **从 Phase 0 SDK 审计开始**；未确认的 MANUS API/字段/结构体**不得猜测**。SDK 版本差异隔离到 `manus_sdk_adapter.cpp`，领域/协议层不依赖 MANUS 类型。
3. **默认只 `--mock`**；真实 Haptic 每次需人批准且人在场，首测 ≤0.1 强度 / ≤50ms。
4. **不提交** MANUS SDK、DLL、token、`CMakeUserPresets.json`、build 目录（见 `.gitignore`）。
5. **每阶段必须** configure + build + test；失败先修复，**不跳阶段**（门禁见 `doc/plan/backend/README.md`）。
6. **SDK callback 只做有界复制并立即返回**；回调内不做网络 I/O、阻塞日志、编码、UDP 发送，不再调 `CoreSdk_*`/Haptic。TCP handler 不直接调 Haptic SDK（经串行 executor）。
7. **不修改**本仓库既有的非 MANUS 模块（目前无 PICO/Unity，N/A）。
8. **构建环境**：`cl/cmake/ninja` 仅在 "Developer PowerShell for VS 2026"；所有构建从该终端发起。SDK 在 `thirdparty/ManusSDK/`（git-ignored）。vcpkg 在 `F:/teleop/vcpkg/vcpkg-2026.06.24`；`vcpkg install` 需 github 代理开启。详细构建流程见 `doc/knowledge/build-flow.md`。
9. **对话语言**：所有对话、解释、进度记录用**中文**；代码、路径、协议字段、命令、标识符保持英文。
10. **架构评审候选**（单一事实源 [`doc/review/architecture-review-*.md`](doc/review/)）：实施任何评审候选前必须（a）读评审文档对应条目（证据与定性以它为准，已处置候选勿再提出）；（b）先走 grilling 式逐题决策（边界/兼容性/语义/归属/命名/测试/交付逐项确认）再动手，D21/D22 均由此产出；（c）实施完成后回写评审文档执行状态表 + [`doc/knowledge/decisions.md`](doc/knowledge/decisions.md) 记 D 编号。

## 流程
每阶段：①查 `doc/plan/<组件>/phase-*.md` → ②实现 → ③configure/build/test → ④把过程与结果写入 `doc/progress/<组件>/phase-*.md` → ⑤报告真实命令、退出码、结果。
