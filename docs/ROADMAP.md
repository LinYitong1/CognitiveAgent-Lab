# CognitiveAgent Lab — 开发路线图

> 版本：v1.0 ｜ 前置条件：`docs/ARCHITECTURE.md` 获用户批准后启动 M0
> 节奏：每个里程碑结束由 QA 按 ACCEPTANCE_CRITERIA 执行可验收命令，通过才进入下一个。

## M0 — 项目脚手架（半天）

- 建立 `src/ tests/ web/ docs/handoff/` 目录结构与空 `__init__`。
- venv 安装依赖：`fastapi uvicorn pydantic pydantic-settings pytest pytest-asyncio httpx openai`。
- `pyproject.toml` + `.env.example` + `.gitignore`（含 `.env`、`logs/`、`*.db`）+ git 初始化。
- CI 脚本 `scripts/check.sh`：`pytest + 覆盖率` 一键运行。
- **验收**：`pytest` 空跑通过；`uvicorn` 能起服务返回 health check。

## M1 — Agent 核心循环（2-3 天）｜ Backend + Architect

- `agent/llm.py`：LLMClient（env 配置、超时、重试）。
- `agent/registry.py`：工具注册（Pydantic → JSON schema 自动生成）。
- `agent/loop.py`：主循环（plan→act→observe、步数上限、异常捕获）。
- 首批 3 个工具：`calc`（安全表达式计算）、`http_request`（GET 限定白名单域）、`file_write`（沙箱目录内写文件）。
- 集成测试：FakeLLM 注入预设 tool-call 序列驱动循环。
- **验收**：FakeLLM 集成测试全绿；真实 key 下 `examples/run_agent.py` 完成多步任务并打印轨迹。

## M2 — 持久化 + API（2 天）｜ Backend，QA 同步写测试

- `storage/`：Task/Step/TaskEvent 三表 + repository。
- 任务中断/恢复：`POST /tasks/{id}/resume`。
- `api/`：任务 CRUD + SSE 事件流端点。
- **验收**：杀进程重启后 resume 续跑；SSE 能实时收到事件；API 集成测试全绿。

## M3 — 前端可视化（1-2 天）｜ Frontend

- 任务创建表单、任务列表、执行轨迹时间线（SSE 驱动）、状态面板。
- **验收**：浏览器创建任务并看到实时轨迹与最终结果；无 console 报错。

## M4 — 端到端与加固（1-2 天）｜ QA 主导

- e2e 测试（真实 LLM，无 key 自动 skip）；错误注入测试（工具失败、LLM 超时）。
- 覆盖率达标（核心模块 ≥ 80%）；`scripts/check.sh` 全绿。
- **验收**：ACCEPTANCE_CRITERIA 全清单逐条通过，产出验收报告。

## 里程碑外的持续机制

- 每个 PR/任务过 code-review Skill 门禁（QA 执行）。
- 架构变更走 architecture-review Skill + ARCHITECTURE.md 版本递增。
- 交接文档落 `docs/handoff/`，跨会话可追溯。

## 明确不做（Scope 外）

- 多 Agent 协作框架、RAG、接入 R 代码/认知模型/实验数据、重构既有游戏项目、用户认证体系。
