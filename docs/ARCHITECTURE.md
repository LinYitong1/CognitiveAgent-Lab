# CognitiveAgent Lab — 技术架构

> 版本：v1.2 ｜ 状态：**已按评审意见修订**（v1.1 经架构复审 + QA 验收标准检查两轮独立复审，v1.2 修复其指出的 P0/Major 问题）
> 决策记录（ADR）追加在文末附录；v1.0→v1.1、v1.1→v1.2 变更记录见文末。

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
| 可观测 | 结构化事件日志（DB 表 + JSONL 文件） | 每步可回放、可重放续传 |

### 2.1 运行时依赖与必要性（完整清单，除此之外不加依赖）

| 依赖 | 必要性（一句话） |
|------|------------------|
| fastapi | Web 框架：任务 API 与 SSE 端点的路由、校验、OpenAPI 文档 |
| uvicorn | ASGI 服务器：运行 FastAPI 应用（含 SSE 长连接） |
| pydantic | 数据模型即契约：请求/响应/工具参数/事件负载的校验与序列化 |
| pydantic-settings | 配置管理：从环境变量/.env 加载密钥与运行参数 |
| pytest | 测试框架：unit/integration/e2e 分层测试体系 |
| pytest-asyncio | 异步测试支持：运行 async 端点与 Agent 主循环测试 |
| httpx | HTTP 客户端：TestClient 对拍 + `http_request` 工具实现 |
| openai | LLM 接入：真实 tool-calling，支持自定义 `base_url` 切换兼容端点 |
| pyright | 静态类型检查：G-5a 门禁，退出码 0 才可合入 |
| pytest-cov | 覆盖率采集：G-2 门禁的 pytest 集成插件（`--cov` 参数提供方） |

**依赖红线**：上表为全部允许依赖（pyright 与 pytest-cov 仅用于开发期检查与测试度量，置于 dev 分组）；引入任何新依赖必须先经 Architect 更新本表并递增版本号。

## 3. 分层架构

```
┌───────────────────────────────────────────────────────────────┐
│  web/            任务创建表单 · 执行轨迹时间线（公开事件流）        │  Frontend Agent
├───────────────────────────────────────────────────────────────┤
│  src/api/        FastAPI 路由层                                  │  只做校验与调度
│    POST /tasks                    创建任务(goal)                 │
│    GET  /tasks/{id}               任务状态+步骤+结果              │
│    GET  /tasks/{id}/events        SSE 公开事件流（支持断线重连）    │
│    POST /tasks/{id}/resume        恢复中断任务（受恢复锁约束）      │
│    POST /tasks/{id}/cancel        取消任务                       │
│    POST /tasks/{id}/tool-calls/{tool_call_id}/confirm           │
│                                   uncertain 非幂等调用人工确认    │
├───────────────────────────────────────────────────────────────┤
│  src/services/   编排层（事务边界、checkpoint、恢复锁）            │
├───────────────────────────────────────────────────────────────┤
│  src/agent/      Agent 核心（真实 LLM 驱动）                      │  Backend Agent
│    loop.py       主循环：plan → act → observe                   │
│    llm.py        LLMClient(统一封装, env 配置)                   │
│    registry.py   工具注册表(schema 自动生成 + 幂等/风险声明)       │
├───────────────────────────────────────────────────────────────┤
│  src/tools/      工具实现（Pydantic 输入+executor，安全规范见 §6） │
│    calc.py http_request.py file_write.py …                     │
├───────────────────────────────────────────────────────────────┤
│  src/storage/    SQLite 持久化（含恢复锁/乐观并发版本号）          │
│  src/models/     共享 Pydantic schema                           │
└───────────────────────────────────────────────────────────────┘
```

**依赖方向**（强制，code-review 门禁项）：`api → services → agent → tools/storage`，`models` 被所有层引用，禁止反向 import。

### 3.1 SSE 端点（GET /tasks/{id}/events）

- **公开事件类型**（收敛，完整枚举）：`status | tool_call | tool_result | error | final`。**不再存在 `thought` 事件**：模型内部推理不持久化到公开事件流（DB 事件表、JSONL、SSE 均不落 thought）。
- **事件负载**：
  - `tool_call`：`tool_call_id`、`tool_name`、参数摘要（截断长度上限，默认 512 字符）。
  - `tool_result`：`tool_call_id`、成功/失败标志、结果摘要（截断长度上限，默认 512 字符）。
  - `status`：任务状态变更（含迁移原因）。
  - `error`：不可恢复/需注意的错误信息。
  - `final`：任务终止时**必发一条**（含最终状态与结果摘要），客户端以此判定流结束。
- **事件序号**：每任务 `seq` 单调递增（从 1 开始，由 storage 层在写入时原子分配）；SSE 消息的 `id:` 字段携带该 `seq`。
- **断线重连**：端点支持 `Last-Event-ID` 请求头；重连后从该 `seq+1` 续传。事件**先落库（TaskEvent 表）再推送**，因此任意已持久化事件均可重放，不依赖内存缓冲。
- 终态（completed/failed/cancelled）后端点发送 `final` 后正常关闭流；客户端重连到已终态任务时，服务端重放全部事件并以 `final` 结束。

## 4. Agent 主循环设计（核心）

```
初始化: Task(goal) → LLM(系统提示+工具清单)
循环 (≤ MAX_STEPS=25, 每步超时可配):
  1. LLM 返回 tool_call(s) 或 final_answer
     （模型可能附带内部推理文本，但不写入任何公开事件/持久化事件流）
  2. 为每个调用分配稳定 tool_call_id → 持久化 checkpoint
     → registry 校验参数 → executor 执行工具 → 捕获异常
  3. 每次状态变更写 TaskEvent(type ∈ {status, tool_call, tool_result, error}, seq)
  4. tool 结果作为 tool message 回传 LLM
终止: final_answer | 达到步数上限 | 不可恢复错误
      → Task.status = completed/failed + 发送 final 事件（必发）
```

- **真实 LLM**：工具选择由模型 tool-calling 决定，运行时无法预测下一步——这是与"静态规则模拟"的本质区别，e2e 测试断言行为不可硬编码。
- **状态持久化**：Task/Step/ToolCall/TaskEvent 四表，每次状态变更即写库；进程重启后 `resume` 按 §5.1 恢复语义从 checkpoint 续跑。
- **防护**：最大步数、单工具超时、工具异常不致命（错误回传 LLM 自纠）。

## 5. 数据模型（关键表/模型）

- `Task`: id, goal, status(`pending|running|completed|failed|paused|cancelled`), result, version(乐观并发控制/执行 fencing token), created_at, updated_at
- `Step`: id, task_id, seq(任务内步骤序号), tool_call_id（**无 thought 字段**——模型内部推理不采集，不持久化）
- `ToolCall`: tool_call_id(稳定调用 ID), task_id, seq(任务级事件序号，与 TaskEvent.seq 同一序号空间，storage 写入时原子分配), tool_name, tool_args, status(`pending|running|succeeded|failed|uncertain`), result, error, idempotency(该调用**生效**幂等性的快照，见 §6.4), created_at, updated_at
- `TaskEvent`: id, task_id, seq, type(`status|tool_call|tool_result|error|final`), payload(JSON), ts

任务状态机合法迁移：

```
pending → running → (completed | failed | paused | cancelled)
pending → cancelled                       （未启动任务直接取消）
paused  → running                         （resume，受恢复锁约束，见 §5.1）
paused  → cancelled                       （等待确认中的任务可取消，见 §5.1 cancel 语义）
running → cancelled                       （见 §5.1 cancel 语义）
```

`completed / failed / cancelled` 为终态，不可再迁移。

事件序号 `seq`：每任务独立、单调递增、写入时由 storage 原子分配；同一任务内事件先落库再推送（SSE `id:` 携带，支持 `Last-Event-ID` 重放）。

### 5.1 任务恢复与幂等性

**稳定调用 ID**：每次工具调用在派发前分配全局唯一的 `tool_call_id`（事件序号或 UUID，实现二选一、全程不变）。该 ID 是恢复、幂等判定、SSE 事件对齐与人工确认的唯一锚点。

**工具调用状态机**：

```
pending → running → (succeeded | failed | uncertain)
```

- `succeeded/failed`：执行器正常返回（含工具自身的失败）。
- `uncertain`：调用已发出但结果未知（如进程在执行中途被 kill、超时后无法确认是否已产生副作用）。

**checkpoint 语义**：checkpoint = 某工具调用进入 `running` **之前**持久化的完整上下文（任务状态 + 已完成步骤 + 待执行调用及其 tool_call_id）。恢复时以最后 checkpoint 为起点重建循环上下文。

**幂等性分级**：工具注册表必须为每个工具声明 `idempotency: idempotent | non-idempotent`（见 §6.4）。恢复策略按状态 + 幂等性矩阵执行：

| 调用状态 | 幂等工具 | 非幂等工具 |
|----------|----------|------------|
| `succeeded` | 直接复用已存结果，**不重执行** | 直接复用已存结果，**不重执行** |
| `failed` | 由 LLM 决定是否换参数重试（**新调用 ID**） | 由 LLM 决定是否换参数重试（**新调用 ID**） |
| `uncertain` | **可自动重试一次**（原调用 ID 重新入 running，事件流携带同一 tool_call_id + attempt 序号，前端按最新一轮渲染；重试仍 uncertain 则置 paused） | **禁止自动重试**：任务置 `paused`，等待用户确认 |

**恢复触发方式**：恢复为**手动触发**（`POST /tasks/{id}/resume`）；服务重启后**不自动扫描**中断任务。

**人工确认 API**（uncertain 非幂等调用专用）：

```
POST /tasks/{id}/tool-calls/{tool_call_id}/confirm
body: { "action": "retry" | "skip" }
```

- `retry`：用户确认该调用未产生副作用（或副作用可接受），以**新调用 ID** 重新执行并记录确认人/时间。
- `skip`：将该调用标记 `failed`（error="skipped-by-user"），结果回传 LLM 由其决定后续步骤。
- 任务确认后由 `paused → running`，继续受恢复锁约束。

**任务取消（cancel）**：

```
POST /tasks/{id}/cancel
```

- 语义：**停止派发新调用**；所有 `pending` 调用标记 `failed`（error="cancelled"）；**进行中的 `running` 调用标记 `uncertain`**（因为无法确认其是否已产生副作用）。
- 适用状态：`running | paused | pending`。对 `paused`（等待 uncertain 确认中）与 `pending`（未启动）任务，cancel 同样合法——无 `running` 调用时直接进入终态；`pending` 调用同样标记 failed(cancelled)。
- 取消后任务进入终态 `cancelled`，发送 `final` 事件（含状态与已完成部分的结果摘要）。
- 对被标记 `uncertain` 的非幂等调用，结果摘要中明确提示"副作用未知，已取消"，便于用户后续人工处置。**声明**：`cancelled` 为终态，其中的 uncertain 调用不提供系统内继续执行路径（confirm API 仅服务 paused 任务）；处置仅指用户在系统外核查副作用。

**并发恢复控制**：

- 同一任务**同时只允许一个活跃执行**。
- 实现方式：Task 行的 `version` 字段做乐观并发控制——resume 请求在事务内校验并递增 version；`POST /tasks/{id}/resume` 对已持有恢复锁（version 与请求方不一致 / 已有活跃执行心跳）的任务返回 `409 Conflict`，**拒绝双重恢复**。
- 活跃执行须周期性心跳（更新 `updated_at`）；心跳过期的持有方可被新 resume 抢占（仍走 version 乐观锁，保证只有一个赢家）。
- **fencing（防僵尸执行方）**：活跃执行持有其获取的 version 值作为**执行 token**；每次派发工具调用与每次状态写库都必须携带该 token 做条件更新（`UPDATE … WHERE id=? AND version=?`，CAS 语义）。写库影响行数为 0 即检测到已被抢占（version 已被新持有方递增），旧执行方**立即自行终止派发并不再写库**（自杀）——即便心跳延迟导致其被误判死亡，也无法再产生双活跃执行的副作用。

**测试要求**：以上恢复语义的验收项见 `docs/ACCEPTANCE_CRITERIA.md` M2（M2-5/M2-6/M2-7）。

## 6. 工具安全规范

### 6.1 calc — 安全表达式计算

- 基于 **AST 的安全表达式解析**（Python `ast` 模块）：只允许白名单节点——数字常量、二元运算（`+ - * / % **`）、一元运算（`+ -`）、白名单函数调用（`abs / min / max / round / sqrt` 等）。
- **禁止** `eval` / `exec` / 名称解析（Name 节点一律拒绝，函数名只匹配白名单 Call）。
- 限制表达式长度（默认 ≤ 256 字符）与运算深度（AST 深度默认 ≤ 32）。

### 6.2 http_request — SSRF 防护

- 协议：仅允许 `http` / `https`。
- **域名白名单**（可通过配置项扩展，默认含示例域名）。
- **IP 校验**：DNS 解析后对实际 IP 做校验，阻断私有/内网/保留地址：
  - IPv4：`127.0.0.0/8`、`10.0.0.0/8`、`172.16.0.0/12`、`192.168.0.0/16`、`169.254.0.0/16`，及云元数据地址 `169.254.169.254`。
  - IPv6：`::1`、`fc00::/7`、`fe80::/10`。
- **resolve-then-connect（防 DNS rebinding TOCTOU）**：校验通过后**必须绑定该已校验 IP 直接建连**（HTTP `Host` 头保留原域名），**禁止连接时对域名二次解析**——否则攻击者可在校验与连接两次解析之间切换 DNS 应答绕过上述阻断。
- **重定向**：禁止自动跟随未校验的重定向——每一跳都重新走"域名白名单 + IP 校验"全流程，校验不过即阻断；最大跳数上限（默认 3）。
- 超时上限与响应大小上限（默认 10s / 1MB，超限截断并标记）。
- 幂等性声明：**non-idempotent**（其中 GET 请求视为幂等，注册表以方法参数区分）。

### 6.3 file_write — 沙箱写入

- 写入范围限制在 workspace 的 **`data/` 沙箱目录**内。
- 路径处理：**先规范化（`realpath`）再校验前缀**——规范化结果必须以沙箱根目录前缀开头，否则拒绝；显式拒绝含 `..` 的路径穿越。
- **拒绝符号链接**：写入前用 `lstat` 检查目标路径**各级目录**不含符号链接，发现即拒绝。
- 文件大小上限（默认 1MB）。
- 幂等性声明：**non-idempotent**。

### 6.4 工具注册表新增字段

`src/agent/registry.py` 的注册声明在原有（name、description、Pydantic 参数 schema）基础上**必须**包含：

| 字段 | 取值 | 说明 |
|------|------|------|
| `idempotency` | `idempotent \| non-idempotent` | 恢复语义判定依据（§5.1），缺失即注册失败 |
| `risk_level` | `low \| medium \| high` | 安全审计与 code-review 关注分级（如 file_write/http_request 为 medium 及以上） |

**调用级有效幂等性**：恢复判定（§5.1 矩阵）采用**调用级有效幂等性** = 工具注册表的默认声明，可按参数规则覆写——如 `http_request` 默认声明 non-idempotent，但方法为 GET 时覆写为 idempotent。派发调用时把生效值快照写入 `ToolCall.idempotency` 字段，恢复时以该快照为准（不重新计算）。

## 7. 配置与密钥

`.env`（gitignore）→ `pydantic-settings` 读取：

```
OPENAI_API_KEY=…          # 或 ANTHROPIC_API_KEY
LLM_BASE_URL=…            # 可选，兼容端点
LLM_MODEL=gpt-4o          # 默认模型
CALC_AGENT_MAX_STEPS=25
CALC_AGENT_ENV_FILE=.env  # pydantic-settings 的 env_file 路径覆盖（默认 .env）
HTTP_ALLOWED_HOSTS=…      # http_request 域名白名单（逗号分隔，默认含 example.com）
DATA_SANDBOX_DIR=data/    # file_write 沙箱根
```

**`CALC_AGENT_ENV_FILE` 语义**：pydantic-settings 的 env_file 路径从该变量读取（默认 `.env`）。**设为 `/dev/null` 即完全绕开 .env 文件**——用于无 key 环境验收（M0-3/M1-1b/E2E-3）与测试 fixture，无需移动/删除真实 `.env`（环境变量仍优先于 env_file，二者双通道清理后才构成有效"无 key"判据）。

**红线**：任何密钥出现在代码/测试/日志中即 code-review Blocker。

## 8. 可观测性

- 每次状态变更产出结构化 `TaskEvent`（DB，类型 ∈ `status|tool_call|tool_result|error|final`，见 §3.1）+ 同步 JSONL 追加（`logs/agent-<task_id>.jsonl`，含 seq）。**thought 不落任何观测通道。**
- SSE 端点实时推送公开事件给前端时间线；`id:` 携带 seq，`Last-Event-ID` 支持断线续传（事件先落库再推送，可重放）。
- 任务终止必发 `final` 事件（最终状态 + 结果摘要），客户端以 `final` 判定流结束。
- 回放命令：`python -m cli.replay <task_id>` 按时间序打印完整轨迹。

## 附录：ADR

- **ADR-001 采用自研单循环而非框架**：需求（拆解/工具/状态/日志）均为单 Agent 语义，LangGraph 等引入的图编排与多 Agent 抽象是纯开销，违背约束 3。
- **ADR-002 openai SDK 优先**：自定义 `base_url` 覆盖国内外多数兼容端点；LLMClient 抽象隔离供应商，换 anthropic 只动一个文件。
- **ADR-003 SQLite 起步**：单文件、零部署；存储层走 repository 模式，迁移 Postgres 只换实现。
- **ADR-004 断点恢复与幂等性语义**（v1.1，v1.2 修订）：为每次工具调用定义稳定 `tool_call_id` 与 `pending→running→(succeeded|failed|uncertain)` 状态机；checkpoint 在调用进入 running 前持久化完整上下文；恢复策略按"状态 × 幂等性"矩阵执行——succeeded 复用、failed 由 LLM 换参重试（新调用 ID）、uncertain 幂等工具可自动重试一次（同 ID + attempt 序号）、uncertain 非幂等工具禁止自动重试并置 paused 等待用户确认（confirm API）；cancel 停止派发并将进行中调用标记 uncertain（paused/pending 任务亦可取消）；同一任务同时只允许一个活跃执行（version 乐观并发控制，双重恢复返回 409）。**v1.2 补 fencing**：活跃执行持有 version 值作为执行 token，派发与写库均为携带 token 的 CAS 条件更新，写库零行命中即被抢占、旧执行方自行终止——即便心跳延迟导致误判死亡，也不会出现双活跃执行副作用。该语义是"安全恢复"与"危险重放"的分界线，宁可暂停等人，不可静默重复副作用。
- **ADR-005 工具安全边界**（v1.1，v1.2 修订）：calc 走 AST 白名单节点解析，禁 eval/exec/名称解析，限表达式长度与运算深度；http_request 仅 http/https + 域名白名单 + DNS 解析后 IP 私有/保留段阻断（含 169.254.169.254 云元数据）+ **resolve-then-connect（校验通过的 IP 直接建连，禁止二次解析，防 DNS rebinding TOCTOU）** + 重定向逐跳重新校验 + 超时与响应大小上限；file_write 限定 data/ 沙箱、realpath 后前缀校验、拒绝 `..` 与各级目录符号链接、文件大小上限；注册表强制声明 `idempotency`（调用级有效幂等性 = 默认声明可按参数覆写，如 GET 覆写）与 `risk_level`。Agent 可自主执行不可信输入衍生的调用，安全边界必须在工具执行器内强制，而非依赖 LLM 自觉。
- **ADR-006 公开事件模型（去 thought 化）**（v1.1）：公开事件类型收敛为 `status | tool_call | tool_result | error | final`；模型内部推理不持久化到任何公开通道（DB 事件表/JSONL/SSE）。理由：① thought 属于模型内部中间产物，暴露既无稳定契约价值也有内容风险；② 收敛后的事件类型可被前端与测试精确断言；③ tool_call/tool_result 以 `tool_call_id` 对齐、负载带截断上限，保证流的可解析与可重放。SSE `id:` 携带每任务单调递增 seq，`Last-Event-ID` 断线从 seq+1 续传（事件先落库再推送，可重放）；final 事件任务终止必发，作为客户端判定流结束的唯一信号。

## 变更记录

### v1.0 → v1.1（按评审意见修订，修复 4 项关键 + 3 项次要）

1. **断点恢复安全语义**（评审关键问题 1）：§5 数据模型新增 `ToolCall` 表与稳定 `tool_call_id`、调用状态机（含 `uncertain`）；新增 §5.1"任务恢复与幂等性"（checkpoint 语义、按幂等性分级的恢复策略矩阵、uncertain 非幂等工具禁止自动重试并置 paused 等待用户确认、confirm API、cancel 语义、并发恢复控制/乐观锁、M2 测试要求指向）。
2. **工具安全边界**（评审关键问题 2）：新增 §6"工具安全规范"——calc AST 白名单、http_request SSRF 防护（IP 黑名单段、重定向逐跳校验）、file_write 沙箱与符号链接拒绝；§6.4 注册表新增 `idempotency`/`risk_level` 字段；§3 registry 描述同步。
3. **事件模型去 thought 化 + SSE 机制**（评审关键问题 3）：§3.1 SSE 端点公开事件类型收敛为 `status|tool_call|tool_result|error|final`；`Step.thought` 从数据模型删除（标注不采集）；tool_call/tool_result 负载定义（tool_call_id + 截断摘要）；seq 单调递增、`id:` 携带、`Last-Event-ID` 续传、事件先落库再推送；final 必发；§4 主循环与 §8 可观测性同步修正。
4. **运行时依赖清单**（评审次要问题 3）：§2.1 新增"运行时依赖与必要性"表格（fastapi/uvicorn/pydantic/pydantic-settings/pytest/pytest-asyncio/httpx/openai/pyright），声明除此之外不加依赖。
5. API 端点清单新增 `POST /tasks/{id}/cancel` 与 `POST /tasks/{id}/tool-calls/{tool_call_id}/confirm`；任务状态机新增 `cancelled` 终态。
6. 新增 ADR-004 / ADR-005 / ADR-006。
7. 技术栈、其余章节随上述变更做一致性同步（无选型变更）。

### v1.1 → v1.2（按架构复审 + QA 验收标准检查两轮报告修订）

1. **[P0-1]** §2.1 依赖白名单增补 `pytest-cov`（G-2 覆盖率门禁的 pytest 集成插件，dev 分组），消除 G-2 命令与依赖红线矛盾。
2. **[M-3]** §6.2 补 resolve-then-connect：校验通过的 IP 直接用于建连（Host 头保留原域名），禁止二次解析，闭合 DNS rebinding TOCTOU 缺口；ADR-005 同步修订。
3. **[M-4]** §5.1 并发恢复控制补 fencing：活跃执行持有 version 值作为执行 token，派发/写库均走 CAS 条件更新，零行命中即被抢占、自行终止；ADR-004 同步修订。
4. **[M-5]** §5 任务状态机补 `paused → cancelled`（等待确认中可取消）与 `pending → cancelled`（未启动任务直接取消）；cancel 语义节明确适用状态与 cancelled 终态下 uncertain 调用无系统内继续执行路径的声明。
5. **[P1-6 联动]** §7 新增 `CALC_AGENT_ENV_FILE` 配置（env_file 路径覆盖，`/dev/null` 即绕开 .env），为无 key 验收命令（M0-3/M1-1b/E2E-3）提供双通道清理的文档依据；`HTTP_ALLOWED_HOSTS` 注明默认含 example.com（E2E-1 前置）。
6. **[Minor]** §6.4 补"调用级有效幂等性"规则（默认声明可按参数覆写，ToolCall.idempotency 为生效值快照）；§5.1 uncertain 幂等重试补"同 tool_call_id + attempt 序号，前端按最新一轮渲染"；明确恢复为手动触发（重启不自动扫描）；§5 补 Step.seq / ToolCall.seq 字段语义说明。
7. 版本号 v1.1 → v1.2，本变更记录追加。
