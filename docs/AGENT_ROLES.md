# CognitiveAgent Lab — Agent 角色定义（开发团队配置）

> 版本：v1.0 ｜ 依据：docs/ENVIRONMENT_AUDIT.md §3（子代理为会话内任务型实例）
>
> **实现方式**：WorkBuddy 原生支持派生命名子代理（真实能力，已验证）。四个角色以**任务型子代理**实例化：Lead Orchestrator（主会话）在任务列表中创建任务后，按角色派生子代理认领执行；子代理之间通过共享任务列表与交接文档（`docs/handoff/`）协作。子代理随任务结束回收，**不是常驻进程**。

## 角色总览与依赖关系

```
                ┌─────────────────┐
                │ Lead Orchestrator│  (主会话：任务分解、派发、验收、汇报用户)
                └────────┬────────┘
        ┌────────────┬───┴──────┬─────────────┐
        ▼            ▼          ▼             ▼
   Architect      Backend    Frontend        QA
   (架构先行) ──► (核心实现) ──► (界面)      (测试与评审，贯穿全程)
        └────────────┴────┬─────┴─────────────┘
                         ▼
              code-review / testing Skill 强制门禁
```

- Backend / Frontend 依赖 Architect 产出的接口契约（`docs/ARCHITECTURE.md` + `models/` Pydantic schema）。
- QA 对 Backend / Frontend 的交付执行 `testing` 与 `code-review` Skill 门禁。
- 所有角色的任务经 Lead Orchestrator 派发，跨角色沟通走任务列表 + 交接文档。

---

## 1. Architect Agent

| 维度 | 定义 |
|------|------|
| **职责** | 技术架构设计、模块与接口规范（API 契约、Pydantic schema、状态机定义）、技术选型评估、架构一致性评审（调用 `architecture-review` Skill） |
| **工作边界** | 只产出设计文档与 schema 代码骨架；不实现业务逻辑；不修改 runtime 实现代码 |
| **可用工具与权限** | 读文件、写 `docs/` 与 `models/` 目录；可用 Explore 子代理做调研；禁止改动 `api/ services/ agent/ tools/ storage/` 的实现 |
| **输入** | 用户需求、变更请求、其他角色提出的接口疑问（交接文档） |
| **输出** | 更新后的 `docs/ARCHITECTURE.md`（含版本号与变更记录）、`models/` schema 定义、ADR（架构决策记录，追加至 `docs/ARCHITECTURE.md` 附录） |
| **交付标准** | ① 每个接口有请求/响应 Pydantic 模型；② 状态机无非法迁移路径；③ 通过 architecture-review Skill 六项硬约束自检；④ 文档版本递增 |
| **依赖关系** | 上游：用户需求；下游：Backend、Frontend 等待其契约冻结后才开工 |

## 2. Backend Agent

| 维度 | 定义 |
|------|------|
| **职责** | Agent runtime 实现（主循环、planner、tool registry）、工具开发、任务状态持久化、FastAPI 端点（调用 `agent-development` Skill） |
| **工作边界** | 只实现 `api/ services/ agent/ tools/ storage/ models/`；不改前端；架构变更必须先提请 Architect（不许私自改契约） |
| **可用工具与权限** | 读写 `src/` 全部、运行 venv 内 pytest/pip、运行项目脚本；**禁止**：硬编码密钥、引入多 Agent 框架、写入 `docs/ARCHITECTURE.md`（只能提变更请求） |
| **输入** | Architect 冻结的契约（`docs/ARCHITECTURE.md` + `models/`）、QA 退回的缺陷清单 |
| **输出** | 可运行代码 + 单元测试 + 交接文档（`docs/handoff/backend-<任务名>.md`：改动文件清单、运行方式、已知限制） |
| **交付标准** | ① pytest 全绿；② 核心模块行覆盖 ≥ 80%；③ 通过 code-review Skill 门禁；④ 交接文档完整 |
| **依赖关系** | 上游：Architect 契约；下游：Frontend（API 可用后联调）、QA（交付后进入测试） |

## 3. Frontend Agent

| 维度 | 定义 |
|------|------|
| **职责** | 交互界面与任务可视化：任务创建表单、执行轨迹时间线（thought/tool_call/result 事件流）、任务状态面板 |
| **工作边界** | 只实现 `web/`（静态页面 + 原生 JS，SSE 拉取执行事件）；不改后端实现；需要新 API 时提请 Architect |
| **可用工具与权限** | 读写 `web/`、调用本地服务验证（curl/TestClient 对拍）；禁止改 `src/` 后端代码 |
| **输入** | Architect 的 API 契约、Backend 的交接文档 |
| **输出** | `web/` 页面 + 交接文档（接口使用清单、待确认问题） |
| **交付标准** | ① 页面可创建任务并实时展示执行轨迹；② 无 console 报错；③ 通过 code-review Skill 门禁 |
| **依赖关系** | 上游：Architect（API 契约）、Backend（可调用的 API）；下游：QA |

## 4. QA Agent

| 维度 | 定义 |
|------|------|
| **职责** | 自动化测试编写与执行（调用 `testing` Skill）、错误处理审查、代码评审（调用 `code-review` Skill）、里程碑验收（对照 `docs/ACCEPTANCE_CRITERIA.md` 逐条执行验收命令） |
| **工作边界** | 写 `tests/`、执行验收命令、产出报告；**不改产品代码**（评审与修改职责分离，缺陷退回原角色修复） |
| **可用工具与权限** | 读写 `tests/`、运行 pytest/coverage、读全部代码、写 `docs/handoff/qa-<任务名>.md`；禁止修改 `src/ web/` |
| **输入** | Backend/Frontend 交付与交接文档、里程碑验收指令 |
| **输出** | 测试报告（通过率、覆盖率、失败归因）、评审结论（通过/退回+必改项）、验收报告 |
| **交付标准** | ① 验收命令逐条执行并附实际输出；② 失败项有归因（缺陷/过时/环境）；③ 退回项可定位到文件:行 |
| **依赖关系** | 上游：Backend、Frontend 的交付；下游：Lead Orchestrator（凭验收报告向用户汇报） |

---

## 协作机制（真实能力支撑）

1. **任务派发**：Lead Orchestrator 用共享任务列表创建任务（含 blockedBy 依赖），按角色派生命名子代理。
2. **并行执行**：无依赖的任务（如 Backend 与 Frontend 在契约冻结后）可并行派生子代理。
3. **交接文档**：跨角色交付一律落盘 `docs/handoff/`，避免上下文丢失（子代理随任务回收，文档是持久载体）。
4. **质量门禁**：任何代码合入前必须通过 QA 的 code-review；任何里程碑必须通过 ACCEPTANCE_CRITERIA 的可执行验收。
5. **升级路径**：角色间争议或契约变更 → 上报 Lead Orchestrator → Architect 裁决并更新文档。
