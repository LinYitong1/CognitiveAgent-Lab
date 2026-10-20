# Backend 交接文档 — M1：Agent 核心循环 + 工具安全

> 交付人：Backend Agent ｜ 依据：docs/handoff/architect-m1-contract.md（冻结版）、ARCHITECTURE.md v1.2 §4/§5/§6/§7、ACCEPTANCE_CRITERIA v1.2 M1 节
> 日期：2026-10-20 ｜ 上一份交接：docs/handoff/backend-m0-scaffold.md

## 改动文件清单

| 文件 | 说明 |
|------|------|
| `src/models/llm.py` | ToolCallRequest / LLMResponse（契约 §1.0） |
| `src/models/events.py` | AgentEventType 五值枚举 / AgentEvent（seq 从 1 单调递增） |
| `src/models/tool_result.py` | ToolResult（ok/result/error，安全拒绝 `BLOCKED: ` 前缀） |
| `src/models/agent_result.py` | AgentResult（task_id/status/result/steps/events） |
| `src/models/tool_spec.py` | **ToolSpec**（idempotency/risk_level Literal 强制 + effective_idempotency）。位置决策见下"契约偏离记录" |
| `src/agent/llm.py` | LLMClientProtocol（FakeLLM 替换点）+ LLMClient（AsyncOpenAI 封装，base_url/timeout/max_retries 从构造参数）+ LLMProtocolError |
| `src/agent/registry.py` | ToolRegistry：register 校验（名称/重复/BaseModel/async executor）、get_schemas 导 OpenAI tools 格式、execute 三失败路径全返回 ToolResult 不外抛 |
| `src/agent/loop.py` | AgentLoop.run_task：on_event 回调、tool_call_id=`call_{seq:04d}`、步数上限、三终止路径、final 必发、事件先落盘；AssertionError 穿透（防测试盲区） |
| `src/agent/events.py` | EventLog：JSONL 追加 + 逐事件 flush；mkdir 容错（shim 环境跨进程 PermissionError） |
| `src/agent/__init__.py` | build_registry(settings)：注册三工具（agent→tools 合法方向） |
| `src/tools/calc.py` | AST 白名单求值器（无 eval/exec）；Constant 显式排除 bool；六函数元数校验；Pow 指数 ≤1000（BinOp 与 pow() 共用 _power）；深度 = max(AST 节点深度, 括号嵌套深度) ≤20；数学错误（除零/out of range/domain）非 BLOCKED |
| `src/tools/http_request.py` | 六步安全链路；resolver/connector 双注入点；手写最小 HTTP/1.1 客户端实现 resolve-then-connect（连接 IP=已校验 IP、Host 头保留原域名、HTTPS SNI=原域名、默认 ssl context 未关校验）；重定向手动逐跳 ≤3 全链路重校验；10s/1MB 上限 + truncated 标注；HttpRequestToolSpec 覆写 GET→idempotent |
| `src/tools/file_write.py` | 五步规则（`..` 段级拒 → realpath+is_relative_to → lstat 各级无 symlink → 字节复核 ≤1MB → 沙箱内建目录写入）；mkdir 容错 |
| `examples/run_agent.py` | CLI：缺 key → stderr + exit 2；stdout 首行 `task_id: <id>`；结束打印 status/result；退出码 0/1/2 |
| `tests/integration/fake_llm.py` | FakeLLM（脚本驱动 + received_messages 记录）/ ExplodingLLM |
| `tests/integration/test_loop.py` | 4 测试：multistep（事件序列/seq/tool_call_id/JSONL/产出文件）、step_limit、tool_failure_not_fatal、llm_error_fails_task |
| `tests/unit/test_calc.py` | 5 测试（求值/名称注入/属性与 lambda/深度与长度/数学错误） |
| `tests/unit/test_http_request.py` | 11 测试（含参数化共 15 用例：白名单放行+resolve-then-connect 证据/私有 IP/云元数据/IPv6/非白名单先于 DNS/混合记录/重定向私有/重定向循环超限/DNS rebinding/1MB 截断/幂等声明覆写） |
| `tests/unit/test_file_write.py` | 5 测试（沙箱成功/穿越/symlink/前缀混淆/超限） |
| `pyproject.toml` | 追加 pytest markers 注册（loop/max_steps/tool_failure/tool_security，供 -k 命中） |

## 契约偏离记录（提请 Architect 确认）

1. **ToolSpec 位置**：契约 §1.2 列于 `src/agent/registry.py`，但 §2 要求工具模块构造 ToolSpec、§4 禁止 tools import agent——三者矛盾。按 §4 "共享类型一律走 src/models/"，ToolSpec 落 `src/models/tool_spec.py`（签名不变），ToolRegistry 留 agent 层。
2. **AgentLoop 可选参数 task_id**：CLI 须在任务开始前打印 task_id（§1.5）而 task_id 生成在 run_task 内（§1.3）——增加 `__init__(task_id: str | None = None)` 可选参数，冻结签名 `run_task(goal)` 不变。
3. **build_tool_spec(settings) 代替模块级 TOOL_SPEC 常量**：http_request/file_write 需绑定 settings（白名单/沙箱根）；calc 忽略 settings 保持统一签名。
4. **http_request 链路 4 用契约允许的等价物**：未实现 SafeTransport(httpx.AsyncBaseTransport)，改用手写最小 HTTP/1.1 客户端 + `asyncio.open_connection(ip, port, ssl=ctx, server_hostname=原域名)`——原生支持连接地址与 SNI 分离，无 verify=False。
5. **calc 深度定义**：括号不产生 AST 节点（契约示例 `"("*25+...` 纯 AST 深度无法拒绝），深度检查取 max(AST 节点嵌套深度, 括号嵌套深度)。
6. **-k 选择器经 pytest marker 实现**：测试函数名保持契约冻结名，`@pytest.mark.tool_security / max_steps / tool_failure / loop` 保证 `-k` 命中（已在 pyproject 注册）。
7. **测试文件名** `tests/integration/test_loop.py`（契约 §3.2 原文），非任务描述中的 test_agent_loop.py。

## 运行方式（QA 验收所需）

```bash
# 本会话（沙箱拦截 unlink）等效口径——所有 pytest 命令加：
.venv/bin/python -m pytest --capture=no -p no:cacheprovider

# M1-1 / M1-4 / M1-3 选择器（已验证命中：4/1/1 passed）
.venv/bin/python -m pytest tests/integration -k loop
.venv/bin/python -m pytest tests/integration -k max_steps
.venv/bin/python -m pytest tests/integration -k tool_failure

# M1-5（已验证命中：25 passed，覆盖 calc+http+file 三文件）
.venv/bin/python -m pytest tests/unit -k tool_security

# M1-1b（无 key 双通道清理，已验证 4 passed）
env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY CALC_AGENT_ENV_FILE=/dev/null \
  .venv/bin/python -m pytest tests/integration

# M1-2（真实 LLM，需用户 key 环境）
.venv/bin/python examples/run_agent.py "计算 (123*456)/7 并把结果写入 out.txt"
# stdout 首行 task_id: <id>；事件 logs/agent-<task_id>.jsonl；产出 data/out.txt

# 缺 key 冒烟（exit 2 + stderr）
env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY .venv/bin/python examples/run_agent.py "test"

# 分层 / 类型
.venv/bin/python -m scripts.check_layers
.venv/bin/python -m pyright src/
```

## 自验记录（真实退出码）

| 命令 | 退出码 | 结果 |
|------|--------|------|
| `pytest --capture=no -p no:cacheprovider`（全量） | **0** | 30 passed（1 M0 + 4 loop + 5 calc + 5 file + 15 http） |
| `pytest tests/integration --capture=no -p no:cacheprovider` | **0** | 4 passed |
| `pyright src/` | **0** | 0 errors, 0 warnings |
| `scripts.check_layers` | **0** | 无反向 import |
| 无 key 全量（env -u ×2 + CALC_AGENT_ENV_FILE=/dev/null） | **0** | 30 passed |
| M1-1b 精确命令（无 key + tests/integration） | **0** | 4 passed |
| 缺 key 冒烟 `run_agent.py "test"` | **2** | stderr 报错含 CALC_AGENT_ENV_FILE 提示 ✓ |
| 选择器 `-k loop / max_steps / tool_failure / tool_security` | **0** | 4 / 1 / 1 / 25 passed |

## 契约 §5 自查清单

- [x] LLMClientProtocol 定义于 src/agent/llm.py；AgentLoop client 参数类型为该 Protocol（FakeLLM 鸭子类型注入已验证）
- [x] 五个共享模型置于 src/models/，字段与 §1.0 一致（ToolSpec 例外见偏离记录 1）
- [x] ToolSpec idempotency/risk_level 为 Literal（构造期失败）；effective_idempotency 已实现且 http_request GET→idempotent（测试 test_http_idempotency_declarations 承载）
- [x] ToolRegistry.execute 三失败路径均返回 ToolResult(ok=False)，无异常外抛
- [x] 事件只含五类型；tool_call_id=call_{seq:04d}；final 必发；content 不进事件（test_loop 逐条断言）
- [x] EventLog 逐事件 append+flush 至 logs/agent-<task_id>.jsonl，目录自动创建（容错）
- [x] calc：AST 白名单无 eval/exec/compile；拒绝清单全覆盖；长度 200/深度 20 生效
- [x] http_request：链路 1~6 顺序实现；resolve-then-connect（连接 IP==已校验 IP，resolver 恰一次）；resolver 可注入；HTTPS 证书以原域名校验、未 verify=False；重定向手动 ≤3
- [x] file_write：`..` 拒 → realpath+is_relative_to → lstat 各级 → 1MB；沙箱根取 settings.data_sandbox_dir
- [x] run_agent.py：缺 key → stderr+exit 2；首行 task_id；status/result 打印；退出码 0/1/2
- [x] build_registry 于 src/agent/__init__.py，注册三工具
- [x] 分层自查：check_layers 退出 0；tools 无 import src.agent；loop 无 api/services/storage import
- [x] 测试清单 §3.2 全部落地，四个 -k 选择器命中验证通过
- [x] M1-1b 复跑：无 key + CALC_AGENT_ENV_FILE=/dev/null 下 tests/integration 全绿
- [x] 未修改 src/config.py 字段；未新增依赖；未实现 M2 功能（无 SQLite/API 扩展/SSE/恢复语义）
- [x] 本交接文档

## 已知限制与环境怪癖（QA 必读）

1. **本会话沙箱拦截 unlink/rename** → 裸 `pytest`（FDCapture tempfile）、`--cov`、`compileall` 无法运行；自验与 QA 均用 `--capture=no -p no:cacheprovider` 等效口径（不影响测试语义与判据）。
2. **宿主安全代理对跨进程残留目录的 `mkdir(exist_ok=True)` 抛 PermissionError**（包装 EEXIST）——产品代码（file_write、EventLog）与测试已全部容错（`_ensure_dir`）；QA 会话若遇同类报错属环境现象，非代码缺陷。
3. 测试产物残留：`data/.test-sandbox/`（沙箱测试目录与符号链接，无法删除）、`logs/agent-*.jsonl`——均被 .gitignore 覆盖；`data/.test-sandbox/file_write-evil`、`data/.test-sandbox/rt-link`、`data/.test-sandbox/rt-target` 为调试残留，无害。
4. http_request 测试**不真正联网**（FakeResolver + FakeConnector 注入，契约 §3.1 通道）；真实外网请求路径留待 M1-2/E2E-1（QA 在用户 key 环境执行）。
5. M1-2 判据中 `data/out.txt`：run_agent 默认沙箱根为 `data`（settings.data_sandbox_dir），产出即 `data/out.txt`。

---

## 覆盖率退回修复（G-2，依据 qa-M1.md §三退回要求）

> 范围：**只补测试，不改产品代码**（QA 已逐行审计安全实现，动产品代码触发全量重验）。日期：2026-10-20。

### 新增用例清单

**tests/unit/test_http_request.py**（+19 用例，文件累计 34）：

| 用例 | 覆盖分支（QA 报告行号） |
|------|--------------------------|
| `test_http_reads_chunked_body` | `_read_body` chunked 正常读取（162–178） |
| `test_http_chunked_truncation` | chunked 超 1MB 截断 + truncated 标注 |
| `test_http_reads_body_to_eof` | 无长度头读至 EOF（196–205）+ 请求行 path?query 拼接（153） |
| `test_http_eof_truncation` | EOF 模式超 1MB 截断 |
| `test_http_rejects_malformed_status_line`（参数化 3） | 空响应 / 状态行缺码 / 状态码非数字（231、234–235） |
| `test_http_rejects_malformed_content_length` | content-length 非数字 |
| `test_http_rejects_bad_urls`（参数化 5） | scheme 拒 ×2 / 无 hostname / userinfo（147）/ 端口超范围（131–132） |
| `test_http_connection_oserror` | 连接 OSError → 结构化错误回传 |
| `test_http_timeout` | 挂起连接 + monkeypatch TIMEOUT_SECONDS=0.05 → timed out（297–300） |
| `test_http_writer_cleanup_failure_ignored` | wait_closed 清理失败不影响结果（251–252） |
| `test_http_blocks_empty_dns_result` | DNS 空结果（147 附近） |
| `test_http_rejects_malformed_chunk_size` | chunk size 非十六进制（166–167） |
| `test_http_content_length_short_read` | 声明长于实际 → 提前 EOF 中断（188） |

**tests/unit/test_registry.py**（新建，6 用例；qa-M1.md §三建议项）：空名 / 重复名 / 非 async executor 拒绝、非 BaseModel input_model 构造期拒绝（pydantic 第一道防线，register issubclass 为不可达第二道防线）、idempotency/risk_level Literal 构造期校验、get_schemas 导出格式。

**测试类型标注修正**（非行为变更）：`test_loop.py` / `test_file_write.py` 的 sandbox fixture 返回类型 `Path` → `Iterator[Path]`（generator fixture 标注错误，`pyright src/ tests/` 顺带核查时发现）。

### 自验记录（真实退出码）

| 命令 | 退出码 | 结果 |
|------|--------|------|
| `pytest tests/unit/test_http_request.py --capture=no -p no:cacheprovider` | **0** | 34 passed |
| `pytest --capture=no -p no:cacheprovider`（全量回归） | **0** | **55 passed**（原 30 + http 19 + registry 6） |
| `pytest --cov=src --cov-report=term-missing --capture=no -p no:cacheprovider` | **0** | 55 passed；本会话 `--cov` 可跑（与 QA 会话观察一致，拦截非恒定） |
| `pyright src/`（G-5a 门禁） | **0** | 0 errors |
| `pyright src/ tests/`（顺带核查） | **0** | 0 errors（含 fixture 标注修正） |
| `scripts.check_layers`（src/ 未改，防御性复跑） | **0** | 无反向 import |

### 覆盖率数字（对照 G-2 判据 agent/ tools/ storage/ ≥ 80%）

| 目录 | stmt | miss | 行覆盖 | 修复前（qa-M1.md） | 判定 |
|------|------|------|--------|--------------------|------|
| **tools/** | 351 | 30 | **91.45%** | 78.35% | **达标**（http_request 68% → 93%） |
| **agent/** | 164 | 27 | **83.54%** | 81.71% | 达标（不回退，反而提升） |
| storage/ | 0 | 0 | — | — | 不适用（M1 无代码，M2 起生效） |

- http_request.py 未覆盖行仅剩 **84–88、97–106**（默认 resolver/connector，需真实网络）——qa-M1.md §三明示"可接受不覆盖"，留待 M1-2 实测覆盖。
- agent/ 剩余缺口：llm.py 46%（真实 LLM 调用路径，M1-2/E2E 覆盖）、events.py 17–19/24（EventLog.path property 与 mkdir 容错分支）、registry.py 7 行（register 防御性 except 与 get 查询）。
- calc.py 86%（未覆盖行多为防御分支：SyntaxError/RecursionError 捕获、深度越界后的一元/二元 fall-through 等）。

### 产品代码改动

**无**。`git status` 层面本轮仅新增/修改 `tests/` 下三个文件与本文档。
