# QA 验收报告 — M1-2（真实 LLM 全链路）

> 验收人：QA Agent（docs/AGENT_ROLES.md §4）｜ 日期：2026-10-20
> 判据唯一依据：docs/ACCEPTANCE_CRITERIA.md **v1.2** M1 节 M1-2 条目 + 用户附加要求（calc ≥1、file_write ≥1、http_request 禁用 0 次、产出限 data/ 沙箱、单次运行不重试、不放宽标准）
> 被验收运行：task-3a3879b0db2b，2026-10-20 18:00 UTC（本地 19:00 GMT+1），qwen2.5:7b @ 本地 Ollama（127.0.0.1:11434/v1，ctx 8192），入口 `examples/run_agent_m12.py`
> 约束遵守情况：QA 未重跑 Demo、未修改任何产品代码与测试、未执行 git 写操作；全部命令为只读取证。
> 证据口径说明：凡标注"QA 实测"均为本会话独立执行；exit code 与 stdout 原文采信 Lead 运行记录，并以事件日志、Ollama 服务端日志、文件 mtime 三路独立证据交叉佐证（见 §1.4 / §四①）。

---

## 核查一：Demo 是否真的通过 AgentLoop 执行（防伪造）—— **PASS**

### 1.1 事件结构与源码产出格式一致性（QA 读源码逐项比对）

| 核对项 | 源码位置 | 事件日志实测 | 结论 |
|--------|----------|--------------|------|
| 字段结构 type/seq/ts/payload | src/models/events.py:21-27（AgentEvent） | 6 事件均为四字段，payload 为 dict | ✓ |
| 文件名 `logs/agent-<task_id>.jsonl` | src/agent/events.py:14 | logs/agent-task-3a3879b0db2b.jsonl | ✓ |
| tool_call_id 格式 `call_{seq:04d}` | src/agent/loop.py:119 | call_0002（seq2）、call_0004（seq4）——恰为各自 tool_call 事件的 seq | ✓ |
| 事件先落盘再继续 | src/agent/loop.py:60（`log.append` 先于 `events.append`/回调） | 日志文件 mtime 19:00:53 +0100 = seq6 final 时刻，逐事件追加落盘 | ✓ |
| payload 字段名 | loop.py:121-138 | tool_call{tool_call_id,tool_name,args_summary}、tool_result{tool_call_id,ok,result_summary}、final{status,result_summary}、status{status,reason} | ✓ |
| tool_call/tool_result 成对同 id | loop.py:119-138 | call_0002 成对（seq2/3）、call_0004 成对（seq4/5），ok 均为 true | ✓ |

### 1.2 事件序列合规（QA 实测）

```
$ jq -r '.type' logs/agent-task-3a3879b0db2b.jsonl
status → tool_call → tool_result → tool_call → tool_result → final
```

- seq 1-6 单调递增、无跳号、无重复 ✓
- **无 thought 类事件**（ADR-006）✓
- final 必发且 payload.status="completed"（loop.py:146-150 任何终止路径必发）✓
- 与 M1-1 集成测试断言的六元组序列形态完全一致（qa-M1.md §四人工核验的序列在真实 LLM 下复现）✓

### 1.3 时间戳合理性审计（QA 实测）——**符合本地 7B 推理延迟特征，排除 FakeLLM**

LLM 轮次间隔（事件 ts，UTC）：

| 轮次 | 时间点 | 间隔 | 对应 GIN 服务端耗时 |
|------|--------|------|---------------------|
| 启动→第1轮响应（calc call） | 18:00:24.583 → 18:00:35.851 | 11.27s | 11.137s |
| →第2轮响应（file_write call） | → 18:00:44.783 | 8.93s | 8.892s |
| →第3轮响应（最终文本） | → 18:00:53.555 | 8.77s | 8.682s |

- 每轮 8.7-11.3 秒，与 qwen2.5:7b Q4_K_M 在 Apple M3 上的推理延迟特征吻合（readiness 报告 R2 预估单轮 5-25s）；**FakeLLM 为内存脚本返回，会是毫秒级**——毫秒级与秒级相差 3 个数量级，不可伪造 ✓
- 工具执行耗时本身为毫秒级（calc 15.8ms：seq2→seq3；file_write 64.9ms：seq4→seq5），符合本地工具特征 ✓

### 1.4 Ollama 服务端独立证据（QA 实测）——**三路证据精确闭环**

```
$ grep -E "127.0.0.1.*(POST|chat)" /tmp/ollama-serve.log | tail
[GIN] 2026/10/20 - 18:56:18 | 200 | 14.129s | 127.0.0.1 | POST "/v1/chat/completions"
[GIN] 2026/10/20 - 18:56:20 | 200 |  2.489s | 127.0.0.1 | POST "/v1/chat/completions"
[GIN] 2026/10/20 - 19:00:35 | 200 | 11.137s | 127.0.0.1 | POST "/v1/chat/completions"
[GIN] 2026/10/20 - 19:00:44 | 200 |  8.892s | 127.0.0.1 | POST "/v1/chat/completions"
[GIN] 2026/10/20 - 19:00:53 | 200 |  8.682s | 127.0.0.1 | POST "/v1/chat/completions"
```

1. **19:00 时段（本地 +0100 = UTC 18:00）恰 3 次 chat 请求**，完成时刻 19:00:35 / 19:00:44 / 19:00:53 与事件 seq2 / seq4 / seq6 的 UTC 时间戳（18:00:35.851 / 18:00:44.783 / 18:00:53.555）逐轮对应；按各请求耗时回推发起时刻，均落在上一事件之后即刻（status 24.583 → 请求发起；seq3 35.866 → 请求发起；seq5 44.847 → 请求发起），时间线自洽（GIN 秒级截断，偏差 <1s 在精度内）✓
2. 服务端启动参数 `-c 8192`（llama-server 18:56:03 启动行）确认 **ctx 8192 生效**（readiness R1 缓解措施落实）✓
3. `curl -s http://127.0.0.1:11434/api/ps`：qwen2.5:7b（Q4_K_M，7.6B，4.99GB，`context_length: 8192`）仍加载中；**`expires_at: 19:05:53.55` = 最后一次请求 19:00:53.55 + 5min 空闲过期**——反证 19:00:53 之后无任何后续推理请求，与"单次运行"互证 ✓
4. 全部请求 HTTP 200，无 5xx/超时——LLMClient 的 SDK 网络层重试（max_retries=2，src/agent/llm.py:39）**未实际触发**，不存在隐藏重试 ✓

> **NOTE-1**：GIN 日志 18:56:18 / 18:56:20 有两次更早请求，为 Lead 按 readiness §5 进行的**运行前连通性冒烟**（早于正式运行 4 分钟）；logs/ 目录 19:00 时段仅存在 task-3a3879b0db2b 一个事件文件（其余 95 个 jsonl 均为 17:19-17:46 M1-1 测试产物），冒烟未经过 AgentLoop、不产生事件，与正式运行分离。不构成"重试"。

### 1.5 stdout 行为与入口源码一致性

run_agent_m12.py:59-72 输出顺序为 `task_id:` 首行 → `status:` → `steps:` → `result:`；Lead 记录 status=completed / steps=3 / exit 0 与源码路径一致（completed → return 0，:73）。steps=3 = 三轮 LLM 调用，与 GIN 三次请求一一对应 ✓。QA 未重跑，故 stdout 原文采信 Lead 记录，但 status/steps 均可由事件日志独立复算（final.status=completed；3 轮 LLM=3 次 GIN 请求），非孤证。

**核查一结论：PASS** —— 事件结构、tool_call_id、时间线、服务端请求记录四路证据互证，Demo 经真实 AgentLoop + 真实 LLM 执行，排除 FakeLLM/伪造可能。

---

## 核查二：是否存在虚假的工具执行成功记录 —— **PASS**

### 2.1 calc 结果独立复算（三方逐字符比对）

```
$ python3 -c "v=123*456/7; print(repr(v), repr(v)=='8012.571428571428', len('8012.571428571428'))"
8012.571428571428 True 17
```

| 比对方 | 值 | 一致性 |
|--------|-----|--------|
| QA 独立复算 repr(56088/7) | `8012.571428571428` | 基准 |
| 事件 seq3 result_summary | `8012.571428571428` | **逐字符一致** ✓ |
| data/out.txt 内容（cat 实读） | `8012.571428571428`（无换行，wc -c = 17） | **逐字符一致** ✓ |

QA 手工核算：123×456=56088，56088÷7=8012.571428…（循环小数 8012.571428571428…），float64 repr 为 8012.571428571428，与判据③"QA 复算 ≈8012.57 以 calc 实际输出格式比对"一致。

### 2.2 输出格式与工具实现源码核对（QA 读源码）

- calc.py:141：`text = repr(value) if isinstance(value, float) else str(value)`——float 走 **repr()**，`8012.571428571428` 正是 Python float repr 的真实格式（含 15 位有效数字、无尾随零），**不是人工随手写的"8012.57"** ✓
- file_write.py:87：`return ToolResult(ok=True, result=f"wrote {args.path} ({byte_count} bytes)")`——事件 seq5 的 `wrote out.txt (17 bytes)` 与该模板逐字一致，17 = len("8012.571428571428") 编码字节数 ✓

### 2.3 产出文件物证（QA 实测）

```
$ stat -f "mtime=%Sm size=%z" -t "%Y-%m-%d %H:%M:%S %z" data/out.txt
mtime=2026-10-20 19:00:44 +0100  size=17
```

- out.txt mtime **19:00:44 +0100 = 18:00:44 UTC**，落在 seq4（18:00:44.783 file_write 调用）与 seq5（18:00:44.847 完成）窗口内，精确吻合 ✓
- 17 字节与 seq5 result_summary 一致；无换行符（file_write 按 content 原样 write_bytes，模型 content 无 \n）✓

**核查二结论：PASS** —— 复算值、事件记录、落盘文件三方逐字符一致，且格式细节（float repr、字节计数、mtime）只能由真实执行链路产生，排除硬编码冒充。

---

## 核查三：越界文件写入或未授权工具调用 —— **PASS**（附 2 项 NOTE）

### 3.1 运行窗口文件变更审计（QA 实测）

```
$ find . -newermt "2026-10-20 18:55" ! -newermt "2026-10-20 19:05" -type f 2>/dev/null | grep -v ".venv\|.git/"
./.env
./.workbuddy/memory/2026-10-20.md
./data/out.txt
./examples/run_agent_m12.py
./logs/agent-task-3a3879b0db2b.jsonl
```

逐项定性：

| 文件 | mtime（QA 实测） | 定性 |
|------|------------------|------|
| data/out.txt | 19:00:44 | 预期内：沙箱产出 ✓ |
| logs/agent-task-3a3879b0db2b.jsonl | 19:00:53 | 预期内：事件日志 ✓ |
| examples/run_agent_m12.py | 19:00:04 | 预期内：Lead 运行前 20 秒创建的受限入口（运行准备，非运行时变更）✓ |
| .env | 18:55:39 | **运行前配置准备**（Ollama 端点 + 占位 key，见 NOTE-2），早于正式运行 25 分钟，非运行时写入 ✓ |
| .workbuddy/memory/2026-10-20.md | 18:56:46 | WorkBuddy 宿主工具自身记忆文件，非项目产品代码，环境噪音 ✓ |

**结论：src/、tests/、web/、docs/、scripts/ 在窗口内零变更；无越界写入。**

> **NOTE-2**：.env 为窗口内唯一预期外文件，QA 已核内容（密钥脱敏）：`OPENAI_API_KEY` 为占位值（.env 内注释明示"占位 key：Ollama 不校验，仅为满足 openai SDK 与 run_agent 非空校验"），`LLM_BASE_URL=http://127.0.0.1:11434/v1`、`LLM_MODEL=qwen2.5:7b`、`DATA_SANDBOX_DIR=data`——与 readiness §5 给出的配置模板一致，属 Lead 环境准备动作。.env 在 .gitignore 内不入库，且 G-3 密钥扫描范围为 src/ tests/ web/，不受影响。**无真实密钥落盘**。

### 3.2 http_request 禁用核查（QA 实测，双通道）

1. 事件日志：`grep -c "http_request" logs/agent-task-3a3879b0db2b.jsonl` → **0**（grep exit 1，无匹配）✓
2. 结构性缺席（源码核实）：run_agent_m12.py:30 `from src.tools import calc, file_write  # 有意不导入 http_request`；build_restricted_registry（:33-39）仅 register calc + file_write 两个 ToolSpec——**http_request 不进入 tools schema，模型在协议层面无从调用** ✓

### 3.3 沙箱落点确认（QA 读源码 + 实测）

- config.py:32 `data_sandbox_dir: str = "data"`（.env 亦配置 `DATA_SANDBOX_DIR=data`）
- file_write.py:50 `target = sandbox.joinpath(*rel_parts)`——path="out.txt" 解析为 `data/out.txt`，实测落点一致 ✓
- 沙箱五步安全校验（.. 拒绝、realpath 前缀、逐级 lstat 符号链接拒绝、字节数复核）在本次执行路径未触发任何 BLOCKED（seq5 ok=true，正常写入）✓

### 3.4 git 状态（QA 实测）

```
$ git status --porcelain
?? examples/run_agent_m12.py
$ git check-ignore -v data/out.txt logs/agent-task-3a3879b0db2b.jsonl
.gitignore:9:data/*      data/out.txt
.gitignore:8:logs/       logs/agent-task-3a3879b0db2b.jsonl
```

- 工作树唯一变更：未跟踪新文件 examples/run_agent_m12.py——**src/ 产品代码、tests/、examples/run_agent.py 全部零改动** ✓
- data/、logs/ 均被 .gitignore 覆盖（与 qa-M1.md 遗留 #6 登记一致）✓
- data/.test-sandbox/ 为 17:46 M1-1 测试产物残留，qa-M1 已登记无害，非本次运行产物

**核查三结论：PASS** —— 无越界写入、无未授权工具调用；http_request 0 次（事实 + 结构双确认）；产出严格落在 data/ 沙箱。

---

## 核查四：M1-2 正式判据判定 + 受限入口偏差意见

### 4.1 M1-2 判据 ①②③ 最终判定表

| 判据 | 验收要求 | QA 独立证据 | 判定 |
|------|----------|-------------|------|
| **① exit 0** | run_agent exit 0 | Lead 记录 exit=0；佐证链：final.status="completed"（事件 seq6）→ run_agent_m12.py:73 `return 0 if result.status == "completed" else 1` 唯一代码路径；6 事件完整、无 error 事件 | **PASS** |
| **② tool_call ≥2 且种类 ≥2** | 以 logs/agent-<task_id>.jsonl 统计 | `jq -r 'select(.type=="tool_call")\|.payload.tool_name' \| sort \| uniq -c` → **calc 1 次 + file_write 1 次 = 2 事件 / 2 种** | **PASS** |
| **③ out.txt 与 calc 结果一致** | QA 复算比对，禁硬编码 | 三方逐字符一致（§2.1）；格式为 Python float repr（calc 真实输出格式）；mtime 与事件窗口精确吻合 | **PASS** |

用户附加要求逐项：calc ≥1 ✓（1 次）｜file_write ≥1 ✓（1 次）｜http_request = 0 ✓（§3.2）｜产出在 data/ 沙箱内 ✓（§3.3）｜单次运行不重试 ✓（唯一 task 文件 + GIN 19:00 时段恰 3 请求 + expires_at 反证无后续推理 + out.txt mtime 唯一）｜标准未放宽 ✓（判据原文执行，无 `||` 兜底、无降格断言）。

### 4.2 与既有 M1 验收结论的一致性（qa-M1.md）

- qa-M1.md 遗留 #2"M1-2 前置条件：用户 key 配置确认"——本次以**本地 Ollama + 占位 key**方式闭环。LLMClient 的 key 仅做非空校验（llm.py:29-31 注释明示），非空即通过，Ollama 端点不校验 key——**不与 M1-2 判据冲突**（判据未指定供应商；ADR-002 base_url 切换即为此设计），且避免了真实云 key 的使用与落盘风险 ✓
- M1-1/1b/3/4/5 与门禁结论均针对 src/ 产品代码与测试，本次零改动（§3.4 git 实证），**全部既有结论继续有效**，无矛盾 ✓
- M1-1 集成测试断言的六元组事件序列在真实 LLM 下原样复现（§1.2），FakeLLM 契约与真实链路行为一致 ✓

### 4.3 受限入口偏差的 QA 意见 —— **接受**（附 1 项登记建议）

**偏差**：ACCEPTANCE_CRITERIA v1.2 M1-2 命令块入口为 `python examples/run_agent.py`，实际入口为新建的 `examples/run_agent_m12.py`（仅注册 calc + file_write）。

**正当性评估**：

| 评估维度 | 事实 | 判定 |
|----------|------|------|
| 双约束不可调和 | run_agent.py:18 经 build_registry **固定注册三工具**（含 http_request），无配置开关；改其行为必须修改 M1 产品代码，违反冻结约束。用户授权"工具集限 calc+file_write 且禁用 http_request"在现有 run_agent.py 上**结构性不可满足** | 冲突属实 |
| 最小侵入 | 新增独立文件（77 行），复用 src/ 全部真实组件（LLMClient / AgentLoop / ToolRegistry / calc / file_write 的 ToolSpec 均来自 src/ 现有实现，零复制零改动）；与 run_agent.py 的行为差异**仅注册表内容一处**（另有 steps 输出行，见下）；M1 产品代码零修改经 git status 实证 | ✓ 是最小侵入方案 |
| 禁用 http_request | 结构性缺席 schema（§3.2），比"注册但提示禁用"更严格——模型层面无法调用 | ✓ 满足 |
| 判据等价性 | 判据 ①②③ 的断言对象（exit code、事件日志、out.txt、calc/file_write 调用）在 m12 入口下语义完全等价；被测核心（AgentLoop + LLMClient + 工具）与 run_agent.py 共享同一实现 | ✓ 等价 |
| 可替代方案比较 | 备选①：临时改 .env 隐藏 http_request——不可行，注册表无条件注册三工具；备选②：修改 run_agent.py 加开关——违反 M1 冻结；备选③：环境变量注入 ALLOWED_TOOLS——需要改 src/config.py 与 build_registry，侵入更大。均劣于新入口方案 | ✓ 无更优解 |
| 溯源与留档 | 文件头 docstring 完整声明存在原因、复用关系、行为差异、退出码约定（与 run_agent.py 一致 0/1/2）；保留作审计记录 | ✓ |

**QA 意见：接受该偏差。** 其性质是"验收命令入口替换"，非"验收标准放宽"——判据 ①②③ 与用户附加要求全部按原文执行。

> **登记建议（非阻断）**：① run_agent_m12.py 较 run_agent.py 多输出一行 `steps:`——对 M1-2 判据无影响（判据不约束 stdout 格式），但属于 docstring 中"行为差异仅此一处"之外的微小不符，建议 Lead 在文件头补记（一行文字，不动逻辑）；② 正式判据命令与实际入口不一致一事，建议随 M2 契约回写时由 Architect 在 ACCEPTANCE_CRITERIA 或 ADR 中登记（E2E-1 使用 run_agent.py 全三工具，不受此影响）。

---

## 核查五：模型兼容性限制评估

### 5.1 qwen2.5:7b tool-calling 表现（基于本次运行证据）

| 维度 | 实测 | 评价 |
|------|------|------|
| 单轮成功率 | 3/3 轮全部符合预期（第 1 轮发 calc 调用、第 2 轮发 file_write 调用、第 3 轮给最终文本终止） | 本次运行 100%，但 **n=1 单样本**，不构成统计置信 |
| 参数精度 | calc 参数 `{"expression": "123 * 456 / 7"}` 语义正确；file_write 参数 `{"content": "8012.571428571428", "path": "out.txt"}`——**content 与 calc 返回值逐字符一致**（模型忠实转写工具结果，未自算或截断） | 精确 |
| 轮次效率 | steps=3 = 理论最小值（2 次工具调用 + 1 次总结），无冗余轮次、无重复调用、无提前终止 | 最优 |
| 协议合规 | 无 LLMProtocolError、无 error 事件；tool_call id/arguments 解析正常（事件链完整即为证明）；第一、二轮 assistant 消息 content 与 tool_calls 并存回传（loop.py:112-114）未引发 Ollama 端异常（后续轮次均 200） | 无异常 |
| 延迟 | 8.7-11.3s/轮（GIN 实测 8.68-11.14s） | 在 readiness R2 预估带宽（5-25s）内；M1 timeout=60s 余量充足 |

### 5.2 已知限制确认（docs/handoff/ollama-m1.2-readiness.md）

| 限制 | 本次运行验证情况 |
|------|------------------|
| R1 ctx 默认偏小 | **已缓解并实证**：llama-server 启动参数 `-c 8192`，/api/ps `context_length: 8192`；本任务 3 轮消息量小（最后轮 n_tokens=461），8192 余量充足 |
| R2 单轮延迟 5-25s | 印证（8.7-11.3s）；对 M1-2 无碍，但对 M2 SSE 长任务的用户体验需有预期 |
| R3 7B 级可靠性弱于 GPT-4 级 | 未在本单次运行中暴露（可能因 goal 措辞明确 + 任务简单）；**单次成功不推翻该限制**，E2E-1（三工具长链）仍需按此风险预案 |
| R4 旧版 Ollama 空 tool_call id | 未发生（事件链 id 解析正常） |

### 5.3 新发现的兼容性问题 —— **无阻断级新问题**

- 未发现消息格式异常、content/tool_calls 并存引发的拒绝、参数 JSON 解析失败。
- **NOTE-3（运营级观察，非缺陷）**：Ollama 空闲 5 分钟后模型卸载（expires_at 机制实测），下次调用需重新加载（本次模型拉取后首次加载耗时约 14s，见 GIN 18:56:18 首请求 14.13s 含冷启动）——后续演示若间隔超 5 分钟，首轮延迟会显著高于稳态。E2E-1 执行时建议预热一次。

---

## 遗留风险与模型兼容性限制清单

| # | 事项 | 等级 | 归属 |
|---|------|------|------|
| 1 | qwen2.5:7b 可靠性为单样本观察（n=1），R3 风险（参数错/漏调/提前总结）在更复杂的 E2E-1（三工具链）仍可能暴露 | 中 | E2E-1 执行时监控 |
| 2 | 单轮延迟 8-11s（冷启动首轮约 14s；空闲 5min 卸载重载）——M2 SSE 长任务体验与 E2E-1 时长预期 | 低 | Lead 运营预案 |
| 3 | 受限入口与正式判据命令的不一致需契约层登记（§4.3 登记建议②）；run_agent_m12.py docstring 漏记 steps 输出行差异（建议①） | 低 | Lead / Architect（随 M2 契约回写） |
| 4 | .env 占位 key 方案仅适用于本地 Ollama；未来若接真实云供应商，占位 key 将失效——run_agent 非空校验会正确报错（exit 2），无静默风险 | 低 | 无需动作（记录在案） |
| 5 | qa-M1.md 遗留 #3/#4（超时口径勘误、手写 HTTP 客户端真实外网兼容性）仍未闭环——本次 M1-2 未使用 http_request，不新增证据，维持原状态 | 低 | Architect / E2E-1 |

---

## 总体结论

# **M1-2：通过（放行）**

**理由**：

1. **判据 ①②③ 全部 PASS**（§4.1 判定表），且用户附加要求（calc ≥1 / file_write ≥1 / http_request 0 次 / data/ 沙箱 / 单次运行 / 不放宽标准）逐项满足——其中 ②③ 由 QA 独立命令取证，非采信自报。
2. **真实性四路证据闭环**：事件日志结构（与 src/agent 源码逐项一致）× 时间线（每轮 8.7-11.3s，符合本地 7B 推理延迟，排除 FakeLLM）× Ollama 服务端 GIN 日志（19:00 时段恰 3 次 chat 请求，完成时刻与事件 ts 逐轮对应；expires_at 反证无后续推理）× 产物物证（out.txt mtime/字节数/内容三方一致，float repr 格式无法硬编码伪造）。
3. **合规性无越界**：运行窗口内产品代码零变更（git status 实证）、http_request 结构性缺席、产出严格落沙箱、单次运行无重试痕迹。
4. **受限入口偏差经评估为正当**（最小侵入 + 双约束满足 + 判据等价 + 无更优替代方案），属"入口替换"而非"标准放宽"，QA 接受，附 2 项低危登记建议。
5. **与既有 M1 验收（qa-M1.md 最终放行结论）零矛盾**，M1 里程碑（含 M1-2）至此全部闭环。

> 后续：Lead 可凭本报告向用户汇报 M1 全量完成；E2E-1（真实 LLM 三工具全链路）使用 examples/run_agent.py 原入口，届时按遗留清单 #1/#5 监控 qwen2.5:7b 复杂任务表现与手写 HTTP 客户端真实外网兼容性。
