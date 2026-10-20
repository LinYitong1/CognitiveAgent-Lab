# CognitiveAgent Lab — 技术架构

> 版本：v1.0（待用户批准） ｜ 状态：**草案 — 批准前不进行大规模编码**
> 决策记录（ADR）追加在文末附录。

## 1. 系统目标

构建能理解用户目标、自主拆解任务、选择工具、执行多步骤工作流、保存任务状态、并产出执行结果与可观测日志的 AI Agent 系统。**纯工程导向**：不接入 R 代码、认知模型或既有实验数据。

## 2. 技术栈（锁定）

| 层 | 选型 | 理由 |
|----|------|------|
| 语言 | Python 3.13 | 环境已具备（managed runtime） |
| Web 框架 | FastAPI | 原生 async、Pydantic 集成、自动 OpenAPI 文档 |
| 数据校验 | Pydantic v2 + pydantic-settings | 模型即契约；配置从环境变量加载 |
| 测试 | pytest + pytest-asyncio + httpx(TestClient) | 分层测试体系 |
| LLM 接入 | 官方 `openai` SDK（支持自定义 `base_url`，可切换兼容端点；预留 `anthropic` SDK 适配位） | **真实 tool-calling**，不做规则模拟 |
| Agent 编排 | **自研单主循环**（约 300 行核心代码） | 满足"真实 runtime"且不引入多 Agent 框架（约束 3） |
| 状态存储 | SQLite（`sqlite3` + 文件库） | 零部署、可持久化、够用；预留 Postgres 迁移位 |
| 前端 | 原生 HTML/JS 单页（`web/`）+ SSE | 任务可视化够用即可，不引 React 构建链 |
| 可观测 | 结构化事件日志（DB 表 + JSONL 文件） | 每步可回放 |

## 3. 分层架构

```
┌───────────────────────────────────────────────┐
│  web/            任务创建表单 · 执行轨迹时间线      │  Frontend Agent
├───────────────────────────────────────────────┤
│  src/api/        FastAPI 路由层                  │  只做校验与调度
│    POST /tasks          创建任务(goal)            │
│    GET  /tasks/{id}     任务状态+步骤+结果         │
│    GET  /tasks/{id}/events  SSE 执行事件流        │
│    POST /tasks/{id}/resume   恢复中断任务          │
├───────────────────────────────────────────────┤
│  src/services/   编排层                          │  事务边界
├───────────────────────────────────────────────┤
│  src/agent/      Agent 核心（真实 LLM 驱动）       │  Backend Agent
│    loop.py       主循环：plan → act → observe     │
│    llm.py        LLMClient(统一封装, env 配置)     │
│    registry.py   工具注册表(schema 自动生成)        │
├───────────────────────────────────────────────┤
│  src/tools/      工具实现（Pydantic 输入+executor）│
│    calc.py http_request.py file_write.py …      │
├───────────────────────────────────────────────┤
│  src/storage/    SQLite 持久化                    │
│  src/models/     共享 Pydantic schema             │
└───────────────────────────────────────────────┘
```

**依赖方向**（强制，code-review 门禁项）：`api → services → agent → tools/storage`，`models` 被所有层引用，禁止反向 import。

## 4. Agent 主循环设计（核心）

```
初始化: Task(goal) → LLM(系统提示+工具清单)
循环 (≤ MAX_STEPS=25, 每步超时可配):
  1. LLM 返回: [thought] + [tool_call(s)] 或 final_answer
  2. registry 校验参数 → executor 执行工具 → 捕获异常
  3. 每个动作写 storage: TaskEvent(type, payload, ts)
  4. tool 结果作为 tool message 回传 LLM
终止: final_answer | 达到步数上限 | 不可恢复错误 → Task.status = completed/failed
```

- **真实 LLM**：工具选择由模型 tool-calling 决定，运行时无法预测下一步——这是与"静态规则模拟"的本质区别，e2e 测试断言行为不可硬编码。
- **状态持久化**：Task/Step/Event 三表，每次状态变更即写库；进程重启后 `resume` 从最后 checkpoint 续跑。
- **防护**：最大步数、单工具超时、工具异常不致命（错误回传 LLM 自纠）。

## 5. 数据模型（关键表/模型）

- `Task`: id, goal, status(`pending|running|completed|failed|paused`), result, created_at, updated_at
- `Step`: id, task_id, seq, thought, tool_name, tool_args, status
- `TaskEvent`: id, task_id, seq, type(`thought|tool_call|tool_result|observation|error`), payload(JSON), ts

状态机合法迁移：`pending→running→(completed|failed|paused)`，`paused→running`。

## 6. 配置与密钥

`.env`（gitignore）→ `pydantic-settings` 读取：

```
OPENAI_API_KEY=…          # 或 ANTHROPIC_API_KEY
LLM_BASE_URL=…            # 可选，兼容端点
LLM_MODEL=gpt-4o          # 默认模型
CALC_AGENT_MAX_STEPS=25
```

**红线**：任何密钥出现在代码/测试/日志中即 code-review Blocker。

## 7. 可观测性

- 每步产出结构化 `TaskEvent`（DB）+ 同步 JSONL 追加（`logs/agent-<task_id>.jsonl`）。
- SSE 端点实时推送事件给前端时间线。
- 回放命令：`python -m cli.replay <task_id>` 按时间序打印完整轨迹。

## 附录：ADR

- **ADR-001 采用自研单循环而非框架**：需求（拆解/工具/状态/日志）均为单 Agent 语义，LangGraph 等引入的图编排与多 Agent 抽象是纯开销，违背约束 3。
- **ADR-002 openai SDK 优先**：自定义 `base_url` 覆盖国内外多数兼容端点；LLMClient 抽象隔离供应商，换 anthropic 只动一个文件。
- **ADR-003 SQLite 起步**：单文件、零部署；存储层走 repository 模式，迁移 Postgres 只换实现。
