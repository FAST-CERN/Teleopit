# 项目状态（STATUS）

> 唯一的项目当前状态源。各 README 的「状态」段均回引此处，不另立数字。
> 最后更新：2026-08-14（晚）。本次更新：**架构评审候选 1+5 双合并进 trunk**——[PR #4](https://github.com/FAST-CERN/manusmeta_server/pull/4)（`dfebd5b`）**D21 TeleopStatusView**：`teleop_control` ack 读面收口为 `TeleopRuntime::status_view()` 一次冻结（「冻结即所见」）+ 同址 `to_json`，wire 逐字节不变，删 P1-A/P2-d live getter，加字段配方 9 落点→3，术语根 `CONTEXT.md`；[PR #5](https://github.com/FAST-CERN/manusmeta_server/pull/5)（`7e51895`）**D22 HandCommand 跨实现 golden fixture**：入库 855B 生产形状 bytes（`tools/gen_golden_fixture` 用生产编码器生成），C++ 逐字节锁编码器 + C# 经 csproj link 读同一文件锁解码器，协议变更走显式 regen + diff 审阅；**后端全量 151/1280 + 前端 76 全绿零回归**；**评审持久化**：候选单一事实源 [`review/architecture-review-2026-08-14.md`](review/architecture-review-2026-08-14.md)（新目录 `doc/review/`，一轮一文件；AGENTS.md 规则 10——实施前必读评审 + 必走 grilling；候选 2/3/4/6/7 + JSON golden 待做已入 todolist）；进度 [`progress/backend/teleop-status-view.md`](progress/backend/teleop-status-view.md) / [`progress/backend/handcommand-golden-fixture.md`](progress/backend/handcommand-golden-fixture.md)。前次：**P2-d err/status/current 透传**（D20）+ **P1-A 逐指 haptic 屏蔽**（D19）。再前次：**PR #2 merged（Phase 11+12）+ v0.2.0 released**（tag `v0.2.0` @ `97f8ac0`）+ P0 shutdown stop hook。

## 系统一句话
C++ 后端 + .NET/WPF 前端的 Manus Haptic 局域网串流系统；后端 Phase 0–6、前端 F0–F7 均已完成；Phase 7–12 机器人控制扩展（重定向 + DDS + 安全状态机 + 触觉 + 集成 + 前端运行时控制）已合并到 trunk 并发布 **v0.2.0**（2026-08-10）；真机验收 L1/L2/L3 + 手动触觉通过，自动触觉 P0/P1 收尾列入 v0.2.x。

## 后端（ManusHapticServer）
| 阶段 | 主题 | 状态 |
|---|---|---|
| Phase 0 | SDK 只读审计 → `sdk_audit.md` | ✅ |
| Phase 1 | 工程骨架 + 领域模型 + mock | ✅ |
| Phase 2 | UDP/TCP 协议编解码 + 单测 | ✅ |
| Phase 3 | 控制服务器（TCP/auth/心跳/UDP 单播） | ✅ |
| Phase 4 | Haptic 安全执行器（mock） | ✅ |
| Phase 5 | 真实 MANUS 适配器（真机验证） | ✅ |
| Phase 6 | 系统测试、部署与文档 | ✅ |
| **Phase 7** | **cyclonedds-cxx DDS 层**（ctrl / state·touch / Inspire IDL / Windows 网卡绑定） | ✅ 实机门禁通过（Orin 上行+typename） |
| **Phase 8** | **DexPilot 重定向**（Eigen+NLopt / 离线对齐 oracle） | ✅ |
| **Phase 9** | **安全状态机**（`runtime.py` 1:1 迁移 + 标定载入 + URDF hash 门禁） | ✅ |
| **Phase 10** | **触觉→振动**（TactileMapper + 接 `HapticExecutor` 内部 session） | ✅ 全量 819/107 绿（gold JSON sidecar D16 round-trip 验证） |
| **Phase 11** | **集成与实机验收**（`teleop_runtime` 装配 + wifi DDS 割接 + 分阶段门禁） | ✅ 代码完成 + loopback 系统测试 + 文档（PR #2 已合并）；实机 L1–L4 待操作员在场执行 |
| **Phase 12** | **前端运行时控制 teleop**（三运行时开关 + `HandCommand=4` UDP per-link FK + gold 法 3D 手 + 仿真/真机双验证） | ✅ Orin 真机 L1/L2/L3 + 手动触觉通过（11/12 DOF）；PR #2 已合并 + v0.2.0 released；自动触觉 P0/P1 + 左手 motor 1 收尾列入 v0.2.x |

测试：全量 Catch2 **1280 assertions / 151 cases** 绿（v0.2.0 基线 1215/128 + P1-A/P2-D 净增 + D21 TeleopStatusView +6/+26 + D22 golden fixture +1/+3），Debug 无回归；前端 dotnet **76 绿**（75 + D22 golden），0 警告（D21 前端零改动）。
详见 [`Windows/ManusHapticServer/docs/test-report.md`](../Windows/ManusHapticServer/docs/test-report.md)。

## 前端（ManusHapticFrontend）
| 阶段 | 主题 | 状态 |
|---|---|---|
| F0–F7 | Bootstrap → 端到端集成 + hardening | ✅ |
| O1–O5 | 主题 / 布局 / Haptic 面板 / 3D perf / Ergonomics 自适应 | ✅ |
| R | Phase 3 UI 重构 + 精修 | ✅ |
| postprocess | UI polish + app icon + standalone exe | ✅ |
| LAN | 局域网模式（Allow LAN clients + 独立 server.lan.json / open-firewall.ps1） | ✅ |
| Teleop 控制面板 | Phase 12：`Hand3DView`（HelixToolkit STL gold 法，双手双实例）+ `TeleopControlView`（3 开关 + LED + 进度条）+ `SendTeleopControlAsync`/`TeleopEventReceived` | ✅ 代码完成 + 双手 viz + Orin 真机驱动 L1/L2/L3 + 手动触觉通过（dotnet 70/70 绿；11/12 DOF）；PR #2 已合并 + v0.2.0；自动触觉/左 motor 1 收尾列入 v0.2.x |

详见 [`plan/frontend/README.md`](plan/frontend/README.md) 与 [`progress/frontend/README.md`](progress/frontend/README.md)。

## 真机验收（Phase 5）
连真实 Core + 双手套：RawSkeleton / Ergonomics / Gesture 数据流、安全 Haptic 首测（0.1 / 50ms）、手套断开重连、Core 重启退避——均通过。详见 test-report.md「真机验收」。

## 当前焦点
- **v0.2.0 已发布（2026-08-10）**：Phase 11 + Phase 12 经 [PR #2](https://github.com/FAST-CERN/manusmeta_server/pull/2)（merge commit `d304efa`，32 commits / 110 文件 / +9574 行）合并到 `feat/manus-haptic-server`；tag `v0.2.0` @ `97f8ac0`（release notes 定稿 commit）+ [GitHub Release](https://github.com/FAST-CERN/manusmeta_server/releases/tag/v0.2.0)（body = [`release-notes/v0.2.0.md`](release-notes/v0.2.0.md)，无构建产物——MANUS SDK 为 proprietary，public repo 不分发）。Phase 7–12（DDS / retarget / 安全状态机 / 触觉 / 集成 / 前端运行时控制）全链路进 trunk。
- **v0.2.x 后续收尾**（见 [`todo/todolist.md`](todo/todolist.md)「按优先级的执行顺序」）：✅ **P0 自动触觉 shutdown stop hook 已修（2026-08-10，defense-in-depth + TDD 2 case，全量 130 绿）**；✅ **P1-A 逐指 haptic 震动可选禁用代码完成（2026-08-10，分支 `feat/p1a-haptic-finger-disable`，后端 140/1222 + 前端 73 绿）——根治 P1-B 自动触觉操作姿态假触发（左手坏传感器→逐指屏蔽），决策 D19**；🟠 P1-A 真机/真 GUI 目视 + err-flag 寄存器展示（延后 P2）；🔧 P4 左手 motor 1 硬件排查 + force 零点漂移；P2 前端触觉/震动可视化 + 控制指令参数 + 触觉标定；右手现场重标定；真实控制台 Ctrl+C 退出码=0（Git Bash detached → 需真实控制台，deploy §2.4）。
- **中长期方向**：Linux 迁移（Qt+CMake）、其他灵巧手适配（见 [`todo/todolist.md`](todo/todolist.md)）。
- Phase 0–10 后端、F0–F7 + 优化 / 重构 / postprocess / LAN 前端 **均已完成**；Phase 11/12 详见 [`progress/backend/phase-11.md`](progress/backend/phase-11.md) + [`progress/backend/phase-12.md`](progress/backend/phase-12.md)。决策 D17/D18 见 [`knowledge/decisions.md`](knowledge/decisions.md)。

## Backlog
待办与未采纳点子汇总于 [`todo/todolist.md`](todo/todolist.md)（按优先级 P0–P4 排序 + 日常 backlog + 增强待办 + 待验收 + 未采纳点子）。发布说明见 [`release-notes/`](release-notes/)。
