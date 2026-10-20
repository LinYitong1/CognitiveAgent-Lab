# M1 接口契约 — Agent 核心循环 + 工具安全（冻结版）

> 作者：Architect Agent ｜ 状态：**冻结**（用户已批准 M0 并授权 M1；本文档为 Backend 实现的唯一契约依据）
> 上游依据：`docs/ARCHITECTURE.md` v1.2（§4/§5/§5.1/§6/§7、ADR-004/005/006）、`docs/ROADMAP.md` v1.2（M1 节）、`docs/ACCEPTANCE_CRITERIA.md` v1.2（M1-1/M1-1b/M1-2/M1-3/M1-4/M1-5）、`src/config.py`（M0 交付，**复用其 Settings，不修改既有字段**）
> 依赖白名单：ARCHITECTURE §2.1（fastapi/uvicorn/pydantic/pydantic-settings/pytest/pytest-asyncio/httpx/openai/pyright/pytest-cov），M1 不新增。
> 冻结含义：接口签名、事件格式、安全规则按本文实现；实现内部细节（私有函数、内部异常类型）Backend 可自定。**任何签名/格式变更必须回提 Architect 更新本文档**。

---

## 1. 模块接口

### 1.0 共享模型（`src/models/`，被 agent/tools/tests 共同引用；tools 不 import agent，经 models 传递类型）

```python
# src/models/llm.py
from pydantic import BaseModel

class ToolCallRequest(BaseModel):
    """LLM 返回的一次工具调用（统一结构，隔离供应商格式）。"""
    remote_id: str                    # 供应商侧 ID（OpenAI tool_call.id；FakeLLM 自造如 "fake-0"），用于 tool message 回传匹配
    tool_name: str
    arguments: dict[str, object]      # 工具参数（registry 用 input_model 校验）

class LLMResponse(BaseModel):
    """LLMClient.chat 的统一返回。"""
    content: str = ""                 # 模型文本（内部推理——不写入任何事件/JSONL，见 ADR-006）
    tool_calls: list[ToolCallRequest] = []
    finish_reason: str = "stop"       # "tool_calls" | "stop" | 其他供应商值
```

```python
# src/models/events.py
from datetime import datetime
from enum import Enum
from pydantic import BaseModel

class AgentEventType(str, Enum):
    status = "status"
    tool_call = "tool_call"
    tool_result = "tool_result"
    error = "error"
    final = "final"

class AgentEvent(BaseModel):
    """公开事件（完整枚举，无 thought——ARCHITECTURE §3.1 / ADR-006）。"""
    type: AgentEventType
    seq: int                          # 任务级单调递增，从 1 开始
    ts: datetime                      # UTC
    payload: dict[str, object]
```

**事件 payload 契约**（字段名冻结；摘要字段统一截断至 512 字符）：

| type | payload 字段 |
|------|--------------|
| `status` | `{"status": "running", "reason": str}`（M1 仅开场一条；终态由 final 承载） |
| `tool_call` | `{"tool_call_id": str, "tool_name": str, "args_summary": str}` |
| `tool_result` | `{"tool_call_id": str, "ok": bool, "result_summary": str}` |
| `error` | `{"message": str}`（不可恢复错误；≤512 字符） |
| `final` | `{"status": "completed" \| "failed", "result_summary": str}` |

```python
# src/models/tool_result.py
from pydantic import BaseModel

class ToolResult(BaseModel):
    """工具执行的统一返回——工具异常不抛出到 loop 外（M1-3 判据），一律转结构化结果。"""
    ok: bool
    result: str = ""                 # 成功时的结果文本（回传 LLM）
    error: str = ""                  # 失败原因（回传 LLM）；安全拒绝统一前缀 "BLOCKED: "
```

```python
# src/models/agent_result.py
from pydantic import BaseModel
from src.models.events import AgentEvent

class AgentResult(BaseModel):
    task_id: str
    status: str                      # "completed" | "failed"
    result: str                      # 最终答案（completed）或失败原因（failed）
    steps: int                       # 实际消耗的 LLM 调用轮数
    events: list[AgentEvent]         # 完整事件序列（内存副本，与 JSONL 一致）
```

### 1.1 `src/agent/llm.py` — LLMClient（真实实现）与替换点

```python
from typing import Any, Protocol
from src.config import Settings
from src.models.llm import LLMResponse

Message = dict[str, Any]   # OpenAI chat 消息 JSON 格式（user / assistant(tool_calls) / tool 三种形态，见下）

class LLMClientProtocol(Protocol):
    """AgentLoop 的依赖类型（鸭子类型：任何实现该签名的对象可注入——FakeLLM 替换点，M1-1 依据）。"""

    async def chat(self, messages: list[Message], tools: list[dict[str, Any]]) -> LLMResponse: ...


class LLMClient:  # 实现 LLMClientProtocol
    def __init__(self, settings: Settings, timeout: float = 60.0, max_retries: int = 2) -> None:
        """内部构造 openai.AsyncOpenAI：
        - api_key=settings.openai_api_key（key 为空时**不在此抛错**——由调用方（run_agent / M2 服务层）显式校验）
        - base_url=settings.llm_base_url or None（兼容端点切换，ADR-002）
        - timeout 与 max_retries 透传给 SDK（网络错误/超时重试由 openai SDK 承担）
        """

    async def chat(self, messages: list[Message], tools: list[dict[str, Any]]) -> LLMResponse:
        """调用 chat.completions.create(model=settings.llm_model, messages=..., tools=...)，
        将供应商响应转为 LLMResponse：
        - 每个原生 tool_call → ToolCallRequest(remote_id=原生 id, tool_name=func.name, arguments=json.loads(func.arguments))
        - arguments JSON 解析失败 → 抛 LLMProtocolError（内部异常类型，loop 视为不可恢复错误 → failed）
        - SDK 重试耗尽后抛出的异常原样上抛，由 loop 捕获终止（见 §1.3 终止语义）
        """
```

**Message 三种形态**（loop 构造，client/FakeLLM 透传）：

```python
{"role": "system", "content": str}                                    # 开场一条
{"role": "user",   "content": goal}
{"role": "assistant", "content": str, "tool_calls": [原生 tool_call]}  # 每轮回传（content 可为 ""）
{"role": "tool", "tool_call_id": remote_id, "content": ToolResult 序列化文本}
```

tool message 的 `content` 契约：`ok=True` 时为 `result`；`ok=False` 时为 `f"ERROR: {error}"`（FakeLLM 测试据此断言 M1-3"错误回传 LLM"）。

### 1.2 `src/agent/registry.py` — ToolSpec / ToolRegistry

```python
from typing import Any, Awaitable, Callable, Literal
from pydantic import BaseModel
from src.models.tool_result import ToolResult

class ToolSpec(BaseModel):
    """工具注册声明（ARCHITECTURE §6.4：idempotency / risk_level 必填，缺失即构造失败）。"""
    name: str
    description: str
    input_model: type[BaseModel]                       # 参数校验模型（model_json_schema 自动导出）
    idempotency: Literal["idempotent", "non-idempotent"]
    risk_level: Literal["low", "medium", "high"]
    executor: Callable[[BaseModel], Awaitable[ToolResult]]

    def effective_idempotency(self, args: dict[str, Any]) -> Literal["idempotent", "non-idempotent"]:
        """调用级有效幂等性（ARCHITECTURE §6.4）：默认返回声明值；
        http_request 的 ToolSpec 覆写本方法——method == "GET" 时返回 "idempotent"。
        M1 不被 loop 消费（恢复是 M2），但必须实现并可测（M2 将把生效值快照进 ToolCall 表）。"""


class ToolRegistry:
    def register(self, spec: ToolSpec) -> None:
        """校验并登记：name 非空且不重复；input_model 必须是 BaseModel 子类；
        executor 必须是 async callable。任何校验失败抛 ToolRegistryError（启动期错误，非运行期）。"""

    def get_schemas(self) -> list[dict[str, Any]]:
        """导出 OpenAI tools 格式（供 LLMClient.chat 的 tools 参数）：
        [{"type": "function", "function": {"name", "description",
          "parameters": input_model.model_json_schema()}}]"""

    async def execute(self, name: str, args: dict[str, Any]) -> ToolResult:
        """运行期唯一入口，异常不外抛（M1-3）：
        - 未知工具        → ToolResult(ok=False, error=f"unknown tool: {name}")
        - 参数校验失败    → ToolResult(ok=False, error=f"invalid arguments: {校验错误摘要}")
        - executor 抛异常 → ToolResult(ok=False, error=f"tool execution failed: {异常摘要}")
        - 正常            → executor 返回的 ToolResult"""
```

### 1.3 `src/agent/loop.py` — AgentLoop 主循环

```python
from collections.abc import Callable
from src.config import Settings
from src.agent.llm import LLMClientProtocol, Message
from src.agent.registry import ToolRegistry
from src.models.agent_result import AgentResult
from src.models.events import AgentEvent

class AgentLoop:
    def __init__(
        self,
        client: LLMClientProtocol,          # FakeLLM 注入点（鸭子类型，无需继承）
        registry: ToolRegistry,
        settings: Settings,
        on_event: Callable[[AgentEvent], None] | None = None,   # 可选事件回调（M1 测试断言用；M2 换成 storage 写库 + SSE 推送）
    ) -> None: ...

    async def run_task(self, goal: str) -> AgentResult: ...
```

**主循环语义（冻结）**：

1. **task_id**：`task-{uuid4().hex[:12]}`；开场产出 `status(running)` 事件（seq=1）。
2. **seq 分配**：任务内单调递增计数器（从 1 起），**每条事件一个 seq**；`tool_call_id = f"call_{seq:04d}"`（取该 tool_call 事件的 seq——事件序号即稳定调用 ID，ARCHITECTURE §5.1 允许的二选一之"事件序号"方案；同一 ID 全程不变，M2 直接沿用为 ToolCall 表主键）。
3. 每轮（一轮 = 一次 LLM 调用，步数计数 `steps += 1`）：
   - `client.chat(messages, registry.get_schemas())`；
   - 响应含 `tool_calls` → 逐个：发 `tool_call` 事件（分配 tool_call_id）→ `registry.execute()` → 发 `tool_result` 事件（同 tool_call_id、ok、摘要）→ 结果以 tool message（用 `remote_id`）追加进 messages；assistant 消息（含原生 tool_calls）同时追加；
   - 响应无 `tool_calls`（finish_reason=stop）→ `result = content`，任务 **completed**；
   - **模型文本 content 不产出任何事件**（ADR-006）。
4. **终止语义**：
   - `steps >= settings.calc_agent_max_steps` 且无最终答案 → **failed**，`result = "max steps exceeded"`，发 `error` 事件再发 `final`；
   - 不可恢复异常（`client.chat` 上抛的重试耗尽异常、LLMProtocolError）→ **failed**，`result = 异常摘要`，发 `error` + `final`；
   - 工具失败（ToolResult.ok=False）→ **不终止**，错误回传 LLM 自纠（M1-3）。
5. **final 必发**：任何终止路径（completed / failed）最后一条事件必为 `final`（含最终状态与 result 摘要）——M1-1 断言依据。
6. **事件先落盘再继续**：每条事件产出后立即追加 JSONL（§1.4），再进入下一步（"先落库再推送"的 M1 等价物）。

**系统提示词**（run_task 开场构造，要素冻结、措辞 Backend 可调）：你是多步任务执行 Agent；可用工具以 tools 参数提供；需要外部能力时调用工具；工具失败时会收到 `ERROR:` 前缀的 tool 结果，应换参数重试或改变策略；目标达成后直接给出最终答案文本、不再调用工具。

### 1.4 `src/agent/events.py` — 事件日志（JSONL）

```python
from pathlib import Path
from src.models.events import AgentEvent

class EventLog:
    """JSONL 事件日志（ARCHITECTURE §8 的 M1 形态：无 DB，仅文件）。"""

    def __init__(self, task_id: str, log_dir: str | Path = "logs") -> None:
        """路径：logs/agent-<task_id>.jsonl；log_dir 不存在则自动创建（mkdir parents=True, exist_ok=True）。"""

    def append(self, event: AgentEvent) -> None:
        """以 "a" 模式打开、单次 write(event.model_dump_json() + "\\n")、即时 flush——
        保证 kill -9 后已写事件不丢（M2 断点恢复的事件回放基础）。"""
```

### 1.5 `examples/run_agent.py` — CLI 入口行为契约

```
用法：python examples/run_agent.py "<goal>"     # goal 为必填位置参数
```

行为契约（逐条冻结）：

1. **sys.path 注入**：`sys.path.insert(0, str(Path(__file__).resolve().parents[1]))`（examples/ 不是包，保证 `import src...` 可用；始终从项目根运行）。
2. **配置**：`get_settings()`（src/config.py，M0 交付——自读 .env，受 `CALC_AGENT_ENV_FILE` 路径覆盖；**不得修改该模块**）。
3. **key 显式校验（M1-2 判据）**：`settings.openai_api_key` 与 `settings.anthropic_api_key` 均为空 → 向 stderr 打印明确错误（含 `.env` 路径与 `CALC_AGENT_ENV_FILE` 当前值的提示）→ **`sys.exit(2)`**。禁止静默通过。
4. 组装：`LLMClient(settings)` + `ToolRegistry`（注册 calc/http_request/file_write）+ `AgentLoop`。
5. **stdout 输出顺序（冻结，供验收脚本提取）**：
   - 任务开始前：`task_id: <task_id>`（单独一行，M1-2 的 `TASK_ID=` 提取依据）；
   - 结束后：`status: <completed|failed>` 与 `result: <摘要>`（截断 512 字符）。
6. **退出码**：completed → 0；failed → 1；缺 key → 2。
7. 事件 JSONL 落盘（由 loop 经 EventLog 完成）；产出文件（file_write）落 `data/` 沙箱。

---

## 2. 三个工具的输入 schema 与安全边界

通用约定：executor 签名 `async def execute(args: <X>Input) -> ToolResult`；**所有安全拒绝返回 `ToolResult(ok=False, error="BLOCKED: <原因>")`，不抛异常**（错误返回契约，M1-3）；`BLOCKED:` 前缀冻结（测试断言依据）。

### 2.1 `calc`（src/tools/calc.py）

```python
from typing import Literal
from pydantic import BaseModel, Field

class CalcInput(BaseModel):
    expression: str = Field(min_length=1, max_length=200)   # 长度上限 200 字符

TOOL_SPEC = ToolSpec(
    name="calc",
    description="计算算术表达式，支持 + - * / % ** 与函数 abs/min/max/round/sqrt/pow",
    input_model=CalcInput,
    idempotency="idempotent",
    risk_level="low",
    executor=execute,
)
```

**AST 白名单（完整清单，白名单外一律拒绝）**：

| 类别 | 允许 |
|------|------|
| 顶层 | `ast.Expression` |
| 常量 | `ast.Constant` 且 `value` 类型为 `int \| float`（`bool` 是 int 子类，**显式排除**；字符串/None 拒绝） |
| 二元运算 | `ast.BinOp` 且 op ∈ {`Add`, `Sub`, `Mult`, `Div`, `Mod`, `Pow`} |
| 一元运算 | `ast.UnaryOp` 且 op ∈ {`UAdd`, `USub`} |
| 函数调用 | `ast.Call` 且：`func` 为 `ast.Name` 且 `id` ∈ {`abs`, `min`, `max`, `round`, `sqrt`, `pow`}；参数个数为该函数合法元数；参数为白名单表达式（允许嵌套 Call，受深度限制约束） |

**拒绝清单**（非穷尽，规则=凡不在白名单即拒绝）：`ast.Name`（作为非函数名出现）、`ast.Attribute`、`ast.Subscript`、`ast.Lambda`、`ast.Compare`、`ast.BoolOp`、`ast.IfExp`、`ast.Tuple/List/Set/Dict`、各种推导式、字符串常量、`ast.Call` 的 `keywords`（关键字参数）与 `starargs`。**全程禁用 `eval`/`exec`/`compile` 字符串执行**——求值必须自实现 AST 递归求值器。

**限制**：表达式长度 ≤ 200（Field 约束）；AST 深度 ≤ 20（自根向下的节点嵌套深度，递归计数）；运算量护栏：`Pow` 的指数绝对值 > 1000 或结果为复数/inf → `ToolResult(ok=False, error="calc: result out of range")`；除零 → `error="calc: division by zero"`（不 BLOCKED，属数学错误）。

### 2.2 `http_request`（src/tools/http_request.py）

```python
from typing import Literal
from pydantic import BaseModel

class HttpRequestInput(BaseModel):
    url: str
    method: Literal["GET"] = "GET"        # M1 仅 GET

TOOL_SPEC = ToolSpec(
    name="http_request",
    description="向白名单域名发起 HTTP GET 请求并返回响应文本（重定向逐跳校验，上限 3 跳）",
    input_model=HttpRequestInput,
    idempotency="non-idempotent",          # 调用级覆写见 §2.2 末尾
    risk_level="medium",
    executor=execute,
)
```

**安全链路（顺序冻结，任一步不过即 BLOCKED）**：

1. **URL 解析**（`urllib.parse.urlsplit`）：scheme ∈ {`http`, `https`}；hostname 非空；**拒绝 userinfo**（URL 含 `@`）；端口缺省或为合法端口。
2. **域名白名单**：`hostname`（小写化）∈ `settings.allowed_hosts`（精确匹配，不做通配/DNS 反查——M1 简化为精确字符串匹配）。
3. **DNS 解析 + 全量 IP 校验**：`getaddrinfo` 解析出的**全部**地址逐一校验（用 `ipaddress` 模块），**任一违规即整条拒绝**（防多记录 rebinding）。拒绝：`is_private / is_loopback / is_link_local / is_reserved / is_multicast / is_unspecified`——显式覆盖 IPv4 `127.0.0.0/8`、`10.0.0.0/8`、`172.16.0.0/12`、`192.168.0.0/16`、`169.254.0.0/16`（含云元数据 `169.254.169.254`）与 IPv6 `::1`、`fc00::/7`、`fe80::/10`。
4. **resolve-then-connect（防 DNS rebinding TOCTOU，ADR-005）**：校验通过后**锁定首个通过校验的 IP 直接建连**，禁止连接时二次解析。实现要点（httpx 路径，Backend 可用等价物）：
   - 实现为 `SafeTransport(httpx.AsyncBaseTransport)`：内嵌真实 `httpx.AsyncHTTPTransport`；`handle_async_request` 前完成链路 1~3，然后把 `request.url` 的 host 重写为已校验 IP、`Host` 头设为原域名，交内层 transport 发送；
   - **HTTPS**：TLS 握手的 SNI/证书校验必须以**原域名**为 server_hostname（Python `ssl` 支持 serverhostname 与实际连接地址分离；若所选 httpx/httpcore API 无法分离，改用自定义 `ssl.SSLContext` 关闭自动主机校验后**手动**比对证书 SAN/CN 与原域名——禁止 `verify=False` 裸奔）；
   - **DNS 解析步骤抽象为可注入的 resolver**：`resolver: Callable[[str, int], list[ipaddress.IPv4Address | IPv6Address]]`，默认 `getaddrinfo` 封装——FakeResolver 注入点是 M1-5 rebinding 用例的测试通道。
5. **重定向**：`follow_redirects=False`；收到 301/302/303/307/308 → 提取 `Location`（相对 URL 按 RFC 3986 以当前 URL 解析为绝对）→ 新 URL **重新从第 1 步走完整链路**；最大 3 跳，超限或任一跳校验失败 → `BLOCKED: redirect ...`。
6. **超时与大小上限**：总超时 10.0s（`httpx.Timeout(10.0)`）；响应体流式读取、累计 ≤ 1MB，超限截断并在结果中标注 `truncated: true`（常量写死，不入 Settings——ARCHITECTURE §7 未列）。

**成功返回**：`ToolResult(ok=True, result=...)`，result 含状态码、Content-Type、body 文本（截断至 1MB）。**幂等覆写**：`TOOL_SPEC.effective_idempotency(args)` 覆写——`args["method"] == "GET"` → `"idempotent"`（覆写规则实现位置：本文件 ToolSpec 子类化覆写方法，registry 不感知工具特例）。

### 2.3 `file_write`（src/tools/file_write.py）

```python
from pydantic import BaseModel, Field

class FileWriteInput(BaseModel):
    path: str = Field(min_length=1)                # 相对沙箱根的路径
    content: str = Field(max_length=1_048_576)     # 1MB 字符上限（Pydantic 层第一道）

TOOL_SPEC = ToolSpec(
    name="file_write",
    description="把文本内容写入 data/ 沙箱目录内的文件（覆盖已存在文件）",
    input_model=FileWriteInput,
    idempotency="non-idempotent",
    risk_level="medium",
    executor=execute,
)
```

**安全规则（顺序冻结）**：

1. **字符串级拒绝 `..`**：path 含 `..` 路径段（`Path.parts` 逐段比较，非子串误判）或为绝对路径（`os.path.isabs`）→ `BLOCKED: path traversal`。
2. **realpath + 组件边界前缀校验**：目标 = `sandbox_root / path`；对已存在的最深目录做 `os.path.realpath` 规范化后，用 `Path.is_relative_to(sandbox_real)`（**组件边界**，防 `data-evil/` 字符串前缀歧义）；不通过 → `BLOCKED: outside sandbox`。
3. **符号链接拒绝（TOCTOU 缓解）**：从沙箱根到目标文件的**每一级目录**用 `os.lstat` 检查 `stat.S_ISLNK`，发现即 `BLOCKED: symlink in path`；目标文件本身若为符号链接同样拒绝。
4. **大小上限**：`len(content.encode("utf-8")) ≤ 1MB`（Pydantic max_length 管字符数，executor 复核字节数）→ 超限 `BLOCKED: content too large`。
5. **写入**：自动创建沙箱内父目录（`mkdir parents=True, exist_ok=True`，仍受上述校验约束）；覆盖写。sandbox_root = `settings.data_sandbox_dir`（默认 `"data"`，相对项目运行根）。

**成功返回**：`ToolResult(ok=True, result=f"wrote {相对路径} ({字节数} bytes)")`。

---

## 3. FakeLLM 测试约定与 M1 测试清单

### 3.1 FakeLLM 实现约定（tests 侧，不进 src/）

```python
# tests/integration/fake_llm.py（或 conftest 提供）
class FakeLLM:                       # 鸭子类型实现 LLMClientProtocol，无需继承
    def __init__(self, script: Sequence[LLMResponse]) -> None:
        """script：按轮次预设的 LLMResponse 序列（文本 final / tool_calls）；
        同时记录每轮收到的 messages（received_messages: list[list[Message]]）供断言。"""

    async def chat(self, messages, tools) -> LLMResponse:
        """按调用次序弹出 script 下一项；耗尽 → AssertionError("FakeLLM script exhausted")
        ——用于断言实际 LLM 调用轮数与预期一致。"""
```

**注入方式**：`AgentLoop(client=FakeLLM([...]), registry=build_registry(), settings=Settings(calc_agent_max_steps=N))`；`on_event` 回调或读返回的 `AgentResult.events` / JSONL 做事件断言。registry 用真实实现（真工具、真安全校验），只替换 LLM——M1-1 的"集成"含义即真实 loop + 真实工具 + 假 LLM。

### 3.2 M1 必备测试清单（测试名与断言要点冻结；`-k` 选择器与 ACCEPTANCE M1 各条对应）

**tests/integration/test_loop.py**

| 测试名 | 对应验收 | 断言要点 |
|--------|----------|----------|
| `test_loop_completes_multistep_task` | M1-1（`-k loop`） | FakeLLM 脚本：[tool_call calc("1+2*3"), tool_call file_write("out.txt","…"), final("done")]；断言 `status=="completed"`、`result=="done"`、`steps==3`；事件序列 == `[status, tool_call, tool_result, tool_call, tool_result, final]`（无 thought）；seq 从 1 连续递增；tool_call/tool_result 的 `tool_call_id` 成对相等且形如 `call_0002`；JSONL 存在且逐行与 `AgentResult.events` 一致；`data/out.txt` 内容正确 |
| `test_loop_step_limit` | M1-4（`-k max_steps`） | FakeLLM 恒返回 tool_call；`Settings(calc_agent_max_steps=3)`；断言 `status=="failed"`、`result` 含 `max steps`；最后两条事件为 `error` + `final`（**final 必发**）；LLM 恰被调用 3 次（FakeLLM 脚本长度=3，第 4 次会耗尽） |
| `test_loop_tool_failure_not_fatal` | M1-3（`-k tool_failure`） | 脚本：[tool_call file_write("../evil.txt","x")（穿越，必 BLOCKED）, final("recovered")]；断言第一步 `tool_result` 事件 `ok==False` 且摘要含 `BLOCKED`；FakeLLM 第二轮收到的 messages 含 tool message 且 content 以 `ERROR:` 开头（错误回传 LLM）；任务最终 `completed`（不悬挂） |
| `test_loop_llm_error_fails_task` | M1-3 补充 | FakeLLM 的 chat 抛 RuntimeError（模拟重试耗尽）；断言 `status=="failed"`、事件末尾 `error`+`final` |

**tests/unit/test_calc.py**（M1-5 之一）

| 测试名 | 断言要点 |
|--------|----------|
| `test_calc_evaluates_expression` | `"1+2*3"`→7；`"(123*456)/7"`→ 56088/7；`"sqrt(2)"`≈1.4142；`"pow(2,10)"`==1024；负号/一元负 |
| `test_calc_rejects_name_injection` | `"__import__('os').system('id')"`、`"open('/etc/passwd')"`、`"x"`、`"True"`、`"abc"` → `ok==False` 且 error 含 `BLOCKED`（或参数校验失败） |
| `test_calc_rejects_attribute_and_lambda` | `"''.join([])"`、`"(lambda: 1)()"`、`"[1,2][0]"`、`"a if b else c"` → 拒绝 |
| `test_calc_rejects_depth_and_length` | 长度 >200（Field 校验）；嵌套深度 >20（如 `"("*25 + "1" + ")"*25`）→ 拒绝 |
| `test_calc_math_errors` | `"1/0"` → ok=False（division by zero，非 BLOCKED）；`"pow(10,10000)"` → out of range |

**tests/unit/test_http_request.py**（M1-5 之一；resolver/transport 均为注入点）

| 测试名 | 断言要点 |
|--------|----------|
| `test_http_allows_whitelisted_public_host` | FakeResolver 返回公网 IP + mock 内层 transport → ok==True，且**实际连接目标 == 已校验 IP**（resolve-then-connect 生效证据） |
| `test_http_blocks_private_ip` | resolver 返回 `192.168.1.1` / `10.0.0.5` / `172.16.31.4` → BLOCKED |
| `test_http_blocks_cloud_metadata` | `169.254.169.254`、`http://169.254.169.254/latest/meta-data`（字面量 IP 直填）→ BLOCKED |
| `test_http_blocks_loopback_ipv6` | resolver 返回 `::1`、`fe80::1`、`fc00::1` → BLOCKED |
| `test_http_blocks_non_whitelisted_host` | hostname 不在 allowed_hosts → BLOCKED（URL 白名单先于 DNS） |
| `test_http_blocks_mixed_dns_records` | resolver 返回 `[93.184.216.34, 10.0.0.1]`（多记录含私有）→ 整条 BLOCKED |
| `test_http_blocks_redirect_to_private` | 首跳白名单公网 302 → `Location: http://10.0.0.1/x` → 第二跳 BLOCKED |
| `test_http_blocks_redirect_loop_and_limit` | 302 自指循环 → 跳数超 3 → BLOCKED |
| `test_http_dns_rebinding_fake_resolver` | FakeResolver 两次解析返回不同结果（校验时公网、若实现二次解析则为私有）→ 断言仅解析一次 + 连接 IP == 首次校验值（rebinding 无法得逞） |
| `test_http_response_size_truncation` | mock 响应 >1MB → 截断且标注 truncated |

**tests/unit/test_file_write.py**（M1-5 之一；沙箱根指到 tmp_path）

| 测试名 | 断言要点 |
|--------|----------|
| `test_file_write_success_in_sandbox` | 正常路径写入成功、文件存在、内容一致、result 含字节数 |
| `test_file_write_blocks_traversal` | `"../evil.txt"`、`"a/../../evil"`、绝对路径 `/tmp/x` → BLOCKED |
| `test_file_write_blocks_symlink` | tmp 沙箱内造符号链接目录/文件（`os.symlink`）→ BLOCKED: symlink |
| `test_file_write_blocks_prefix_confusion` | 与沙箱根同前缀字符串但非子目录（如根 `data`、路径解析到 `data-evil/`）→ BLOCKED（`is_relative_to` 组件边界证据） |
| `test_file_write_blocks_oversize` | content >1MB → BLOCKED |

**M1-1b（无 key）**：非单独测试，由**整个 `tests/integration` 套件**在 `env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY CALC_AGENT_ENV_FILE=/dev/null python -m pytest tests/integration` 下全绿证明（ACCEPTANCE M1-1b 命令）——集成测试只经 FakeLLM，构造 Settings 无 key 亦可（src/config.py M0 语义）。测试与 FakeLLM 中**不得出现任何真实形态 key**（G-3：占位用 `test-key-not-real` 形态）。

---

## 4. 边界声明（防止越界）

**M1 明确不做**（全部属 M2，提前实现即退回）：

- SQLite 持久化与 Task/Step/ToolCall/TaskEvent 四表——M1 事件**只落 JSONL 文件**（§1.4）；
- API 端点扩展——`src/api/` 保持 M0 的 /health 原样；
- SSE 事件流、resume/cancel/confirm、恢复语义/fencing/checkpoint——loop 的 `tool_call_id`/事件格式为 M2 预留对齐，但**不实现任何恢复逻辑**；
- `cli.replay`、前端、Playwright。

**分层约束（G-4，`scripts/check_layers.py` 门禁）**：

- `src/agent/loop.py` 不得 import `src/api` / `src/services` / `src/storage`；
- `src/tools/` 不得 import `src/agent`（工具只依赖 `src/models` 与 `src/config`）；
- 注册组装（import 三个工具并 register）发生在 `src/agent/__init__.py` 暴露的 `build_registry(settings) -> ToolRegistry`（agent → tools 方向合法），`run_agent.py` 与测试统一经它获取 registry；
- 共享类型一律走 `src/models/`；配置一律走 `src/config.py`（M0 交付，不改字段——新配置项须回提 Architect）。

**依赖红线**：不新增任何 §2.1 白名单外依赖；测试 mock 用 monkeypatch/注入，不引入 mock 框架。

---

## 5. Backend 实现确认清单（实现完成后逐项自查）

- [ ] `LLMClientProtocol` 定义于 `src/agent/llm.py`，`AgentLoop.__init__` 的 client 参数类型标注为该 Protocol（FakeLLM 鸭子类型可注入）。
- [ ] `LLMResponse`/`ToolCallRequest`/`AgentEvent`/`ToolResult`/`AgentResult` 等共享模型置于 `src/models/`，字段与本契约 §1.0 完全一致。
- [ ] `ToolSpec` 的 `idempotency`/`risk_level` 为 Literal 类型（缺失/非法值在构造期即失败）；`effective_idempotency` 已实现且 http_request 覆写 GET→idempotent。
- [ ] `ToolRegistry.execute` 对未知工具/参数校验失败/executor 异常均返回 `ToolResult(ok=False)`，**无任何异常外抛**（M1-3）。
- [ ] `AgentLoop` 事件序列只含 `status|tool_call|tool_result|error|final`；`tool_call_id = call_{seq:04d}`；终态必发 `final`；模型 content 不进事件。
- [ ] `EventLog` 逐事件 append + flush 至 `logs/agent-<task_id>.jsonl`，目录自动创建。
- [ ] calc：AST 白名单实现（无 eval/exec/compile 字符串执行）；拒绝清单 §2.1 全覆盖；长度 200/深度 20 限制生效。
- [ ] http_request：安全链路 1~6 顺序实现；resolve-then-connect（连接 IP == 已校验 IP，无二次解析）；resolver 可注入；HTTPS 证书校验以原域名进行且未 `verify=False`；重定向手动逐跳 ≤3。
- [ ] file_write：`..` 拒绝 → realpath + `is_relative_to` 前缀 → lstat 各级目录无符号链接 → 1MB 上限；沙箱根取 `settings.data_sandbox_dir`。
- [ ] `examples/run_agent.py`：缺 key → stderr 报错 + exit 2；stdout 首行 `task_id: <id>`；结束打印 status/result；退出码 0/1/2。
- [ ] `build_registry(settings)` 于 `src/agent/__init__.py`，注册三工具。
- [ ] 分层自查：`bash scripts/check.sh`（含 G-4）+ `python -m scripts.check_layers` 退出码 0；`src/tools/` 无 `import src.agent`；loop 无 api/services/storage import。
- [ ] 测试清单 §3.2 全部落地，`-k` 选择器可被验收命令命中（loop / max_steps / tool_failure / tool_security 命名覆盖 calc+http+file 三文件）。
- [ ] M1-1b 复跑：`env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY CALC_AGENT_ENV_FILE=/dev/null python -m pytest tests/integration` 全绿。
- [ ] 未修改 `src/config.py` 既有字段；未新增白名单外依赖；未实现任何 M2 范围功能（§4）。
- [ ] 交接文档 `docs/handoff/backend-m1.md`：改动文件清单、运行方式、已知限制。

> 完成自查后提请 QA 按 ACCEPTANCE_CRITERIA v1.2 执行 M1-1 ~ M1-5 验收（M1-2 真实 key 项由用户环境执行）。
