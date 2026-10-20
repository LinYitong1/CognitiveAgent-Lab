# CognitiveAgent Lab — 开发路线图

> 版本：v1.2（按架构复审 + QA 验收标准检查两轮报告修订） ｜ 前置条件：`docs/ARCHITECTURE.md`（v1.2）获用户批准后启动 M0
> 节奏：每个里程碑结束由 QA 按 ACCEPTANCE_CRITERIA（v1.2）执行可验收命令，通过才进入下一个。

## M0 — 项目脚手架（半天）

- 建立 `src/ tests/ web/ docs/handoff/` 目录结构与空 `__init__`（tests 下分 `tests/unit/ tests/integration/ tests/e2e/`）。
- venv 安装依赖（与 ARCHITECTURE.md §2.1 一致，除此之外不加）：`fastapi uvicorn pydantic pydantic-settings pytest pytest-asyncio httpx openai pyright pytest-cov`（后两项为 dev 分组）。
- `pyproject.toml` + `.env.example`（含 `CALC_AGENT_ENV_FILE`，见 ARCHITECTURE §7）+ `.gitignore`（含 `.env`、`logs/`、`*.db`）+ git 初始化。
- `/health` 端点 + 对应 pytest 测试（满足 M0-2 "≥ 1 collected"）。
- **`scripts/check_layers.py`（Backend 实现，Architect 提供校验规则）**：分层依赖检查——校验 `api→services→agent→tools/storage` 单向、`src/models/` 仅被引用，禁止反向 import（G-4 门禁依据）。
- CI 脚本 `scripts/check.sh`：**G-1 + G-2 + G-3 + G-4 + G-5a + G-5b 全量**，各子项**逐项独立执行、显式 `if` 判定退出码（不依赖 `set -e` 链）、输出分项报告**，聚合退出码 = 任一分项失败即非 0——与 E2E-4 口径一致，失败可归因。
- **验收**：M0-1 ~ M0-4 + G-4（`python -m scripts.check_layers` 退出码 0，M0 即生效）。

## M1 — Agent 核心循环 + 工具安全（2-3 天）｜ Backend + Architect

- `src/agent/llm.py`：LLMClient（env 配置、超时、重试；支持 `CALC_AGENT_ENV_FILE` 路径覆盖）。
- `src/agent/registry.py`：工具注册（Pydantic → JSON schema 自动生成）+ **强制声明 `idempotency` 与 `risk_level` 字段**（缺失即注册失败）+ 调用级有效幂等性覆写规则（ARCHITECTURE §6.4）。
- `src/agent/loop.py`：主循环（plan→act→observe、步数上限、异常捕获；分配稳定 `tool_call_id`；内部推理不落事件流）。
- 首批 3 个工具（含**安全实现**，规范见 ARCHITECTURE.md §6）：
  - `calc`：AST 白名单节点解析（禁 eval/exec/名称解析），限表达式长度与运算深度；幂等声明 idempotent。
  - `http_request`：仅 http/https、域名白名单（**默认白名单含 example.com**，E2E-1 前置）、DNS 解析后 IP 私有/保留段阻断（含 169.254.169.254）、**resolve-then-connect（校验通过的 IP 直接建连，禁二次解析）**、重定向逐跳重新校验、超时与响应大小上限；幂等声明 non-idempotent（GET 覆写为 idempotent）。
  - `file_write`：`data/` 沙箱、realpath 后前缀校验、拒绝 `..` 与各级目录符号链接、文件大小上限；幂等声明 non-idempotent。
- `examples/run_agent.py`（**M1 交付物**）：命令行入口——经 pydantic-settings 自读 .env（缺 key 显式报错退出非 0，不得静默通过）、启动时打印 task_id、产出文件落 `data/` 沙箱。
- 集成测试：FakeLLM 注入预设 tool-call 序列驱动循环；**必须覆盖无 key 环境**（`env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY CALC_AGENT_ENV_FILE=/dev/null pytest tests/integration`）。
- 单元测试：工具安全攻击用例（表达式注入、SSRF 私有 IP/云元数据/重定向绕过/DNS rebinding fake resolver、路径穿越/符号链接）。
- **验收**：M1-1 / M1-1b / M1-2 / M1-3 / M1-4 / M1-5（见 ACCEPTANCE_CRITERIA v1.2）。

## M2 — 持久化 + API + 恢复语义（2-3 天）｜ Backend，QA 同步写测试

- `src/storage/`：Task/Step/ToolCall/TaskEvent 四表 + repository；Task.version 乐观并发控制。
- **恢复语义实现（实现于 `src/services/` 编排层——事务边界、checkpoint、恢复锁归属该层，勿散落 api/agent 层以免 G-4 违规）**，规范见 ARCHITECTURE.md §5.1：
  - checkpoint：工具调用进入 running 前持久化完整上下文（任务状态 + 已完成步骤 + 待执行调用）。
  - 恢复策略矩阵：succeeded 复用不重执行；failed 由 LLM 决定换参重试（新调用 ID）；uncertain 幂等工具自动重试一次（同 ID + attempt 序号）；**uncertain 非幂等工具禁止自动重试 → 任务置 paused**。
  - 确认 API：`POST /tasks/{id}/tool-calls/{tool_call_id}/confirm`（retry / skip）。
  - cancel API：`POST /tasks/{id}/cancel`（适用 running/paused/pending；停止派发，进行中调用标记 uncertain，终态 cancelled——含 `paused→cancelled`、`pending→cancelled` 迁移）。
  - 恢复锁 + **fencing**：同一任务同时只允许一个活跃执行，并发 resume 返回 409；活跃执行持有 version 执行 token，派发/写库走 CAS 条件更新，被抢占即自行终止。
- `src/api/`：任务 CRUD + SSE 事件流端点（公开事件 `status|tool_call|tool_result|error|final`；`id:` 携带每任务单调递增 seq；`Last-Event-ID` 断线续传，事件先落库再推送；final 必发）。
- `cli.replay` 回放命令（**M2 可观测性交付物**，E2E-2 依赖）：`python -m cli.replay <task_id>` 按时间序打印完整轨迹。
- 测试：M2-2 ~ M2-8（含 kill -9 中断恢复、uncertain 非幂等置 paused、并发 resume 409、SSE 重连、cancel 含 paused/pending 取消路径）。
- **验收**：M2-1 ~ M2-8（见 ACCEPTANCE_CRITERIA v1.2）。

## M3 — 前端可视化（1-2 天）｜ Frontend

- 任务创建表单、任务列表、执行轨迹时间线（SSE 驱动公开事件流 `status|tool_call|tool_result|error|final`，以 `final` 判定流结束，支持 Last-Event-ID 断线重连）、状态面板。
- **验收**：浏览器创建任务并看到实时轨迹与最终结果；无 console 报错（手动浏览器验收即满足；Playwright 引入前须 Architect 更新依赖清单）。

## M4 — 端到端与加固（1-2 天）｜ QA 主导

- e2e 测试（真实 LLM，无 key 自动 skip——用 `CALC_AGENT_ENV_FILE=/dev/null` 绕开 .env）；错误注入测试（工具失败、LLM 超时、进程中断、恢复抢占 fencing）。
- 覆盖率达标（核心模块 ≥ 80%，G-2 自 M1 生效）；`scripts/check.sh` 全绿（G-1~G-4 + G-5a/G-5b 分项独立判定）。
- 可选增强：引入 `gitleaks` 或 `detect-secrets` 密钥扫描（引入前须 Architect 更新依赖清单）。
- **验收**：ACCEPTANCE_CRITERIA v1.2 全清单逐条通过，产出验收报告。

## 里程碑外的持续机制

- 每个 PR/任务过 code-review Skill 门禁（QA 执行）。
- 架构变更走 architecture-review Skill + ARCHITECTURE.md 版本递增。
- 交接文档落 `docs/handoff/`，跨会话可追溯。

## 明确不做（Scope 外）

- 多 Agent 协作框架、RAG、接入 R 代码/认知模型/实验数据、重构既有游戏项目、用户认证体系。

## 变更记录

### v1.0 → v1.1

1. M0：依赖清单补 `pyright`（G-5a 门禁）；补 `/health` 测试（M0-2 ≥ 1 collected）；check.sh 补独立 G-3/G-5a/G-5b 判定。
2. M1：标题改为"Agent 核心循环 + 工具安全"；补三工具安全实现任务（calc AST 白名单、http_request SSRF 防护、file_write 沙箱）与注册表幂等/风险字段；补无 key 集成测试与工具安全攻击用例。
3. M2：标题改为"持久化 + API + 恢复语义"；补恢复语义实现（checkpoint、恢复策略矩阵、confirm/cancel API、恢复锁/乐观并发）；SSE 补 seq/Last-Event-ID/final 语义与测试。
4. 路径表述统一为 `src/` 前缀（src/agent/、src/storage/、src/api/ 等）与 `tests/unit|integration|e2e`。

### v1.1 → v1.2（按架构复审 + QA 验收标准检查报告修订）

1. **[P0-1]** M0 安装清单补 `pytest-cov`（dev 分组，G-2 门禁依据），与 ARCHITECTURE §2.1 白名单同步。
2. **[P0-2]** M0 交付物补 `scripts/check_layers.py`（Backend 实现、Architect 提供规则）；check.sh 定义改为 **G-1~G-4 + G-5a/G-5b 全量**、逐项独立执行 + 分项报告（显式 if 判定，不依赖 set -e 链），与 E2E-4 口径一致；M0 验收补 G-4。
3. **[P0-3 联动]** check.sh 分项输出要求使 G-1 失败可归因（聚合退出码 + 分项报告）。
4. **[M-3]** M1 http_request 任务补 resolve-then-connect（校验通过的 IP 直接建连，防 DNS rebinding TOCTOU）；攻击用例补 fake resolver rebinding 用例。
5. **[M-4]** M2 恢复锁任务补 fencing（version 执行 token + CAS 条件更新 + 被抢占自行终止）；M4 错误注入补"恢复抢占 fencing"场景。
6. **[M-5]** M2 cancel 任务补适用状态（running/paused/pending，含 `paused→cancelled`、`pending→cancelled` 迁移）。
7. **[P1-6 联动]** M0 `.env.example` 含 `CALC_AGENT_ENV_FILE`；M1 无 key 测试命令与 LLMClient 改用 `CALC_AGENT_ENV_FILE=/dev/null` 绕开 .env。
8. **[P1-7 联动]** M1 交付物补 `examples/run_agent.py`（自读 .env、缺 key 显式报错、打印 task_id、产出落 data/ 沙箱）；http_request 默认白名单注明含 example.com（E2E-1 前置）。
9. **[Minor]** M2 恢复语义实现明确归属 `src/services/` 编排层；`cli.replay` 明确为 M2 可观测性交付物；uncertain 幂等重试补"同 ID + attempt 序号"。
