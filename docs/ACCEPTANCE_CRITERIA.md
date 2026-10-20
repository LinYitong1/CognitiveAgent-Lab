# CognitiveAgent Lab — 验收标准（可执行）

> 版本：v1.2（按架构复审 + QA 验收标准检查两轮报告修订） ｜ 原则：每条标准都附带**可直接执行的验收命令**，QA 逐条运行并附实际输出。
> 反假阳性原则：验收命令**独立执行、独立判定**，禁止用 `||` 兜底把失败兜成通过；多行命令以表格下方代码块为准（整块退出码即判定结果）。

## 通用门禁（每个里程碑、每次合入）

| ID | 标准 | 验收命令 | 通过判据 |
|----|------|----------|----------|
| G-1 | 测试全绿 | `bash scripts/check.sh` | check.sh 内部**逐项独立执行并输出分项结果**（聚合退出码 + 分项报告）；判据为**分项全部通过**——失败可从分项报告归因到具体子门禁，不以聚合退出码单独判定 |
| G-2 | 覆盖率 | `pytest --cov=src --cov-report=term-missing` | agent/ tools/ storage/ 行覆盖 ≥ 80%（**自 M1 起生效**——M0 尚无此三模块不适用，仅要求命令可运行不报错；term-missing 便于逐文件核对） |
| G-3 | 无硬编码密钥 | 见下方 G-3 命令块 | **失败即阻断**：grep 退出码 1（无匹配）→ 整块退出 0 = 通过；退出码 0（有匹配）或 2（扫描出错）→ 整块退出 1 = 阻断。禁止 `|| echo CLEAN` 式兜底 |
| G-4 | 分层依赖正确 | `python -m scripts.check_layers`（M0 提供，见 ROADMAP M0 交付物） | **退出码 0 且无反向 import 输出**（从项目根执行） |
| G-5a | 静态类型检查 | `python -m pyright src/` | 退出码必须为 0（pyright 已列入 M0 依赖；本机 Node.js 运行时缺失导致 pyright 不可用时，视为依赖未就位、门禁不通过） |
| G-5b | 语法编译检查 | `python -m compileall -q src/` | 退出码必须为 0 |

**G-5a 与 G-5b 为两条独立检查，必须分别执行、分别判定；禁止合并为 `pyright ... || compileall ...` 之类的兜底形式——任一失败即门禁失败。** M4 可选增强：引入 `gitleaks` 或 `detect-secrets` 做依赖化密钥扫描（引入前须 Architect 更新 §2.1 依赖清单）。

### G-3 命令块（整块退出码即判定结果）

```bash
grep -rniE "(sk-[a-z0-9_-]{8,}|api[_-]?key[[:space:]]*=[[:space:]]*[\"'][^\"']+)" src/ tests/ web/
rc=$?
[ "$rc" -eq 1 ]
```

> 正则含 `sk-[a-z0-9_-]{8,}`（覆盖 `sk-proj-…` / `sk-ant-…` 前缀形态）。语义：grep rc=1（无匹配）→ 通过；rc=0（有匹配）或 rc=2（扫描出错）→ 阻断。check.sh 集成时须用显式 `if` 判定退出码，不可依赖 `set -e` 链（grep rc=1 是通过态，会中断 `set -e` 脚本）。测试 fixture 中的占位 key 须用明显非真实形态（如 `test-key-not-real`），避免被本扫描误报。

## M0 — 脚手架

| ID | 标准 | 验收命令 | 通过判据 |
|----|------|----------|----------|
| M0-1 | 服务可起 | 见下方 M0-1 命令块 | 30 次就绪探测内 `/health` 返回 `{"status":"ok"}`（body 精确匹配），且服务进程被清理 |
| M0-2 | 测试骨架（含真实测试） | `pytest` | 0 failed，且 **collected ≥ 1**——必须至少收集并通过 1 个真实测试（`/health` 端点测试），不再允许 0 collected |
| M0-3 | 配置从环境读取（无 key 可起） | 见下方 M0-3 命令块 | 双通道清理（unset 环境变量 + `CALC_AGENT_ENV_FILE=/dev/null` 绕开 .env，见 ARCHITECTURE §7）后服务就绪且 `/health` 返回 `{"status":"ok"}` |
| M0-4 | pyright 依赖就位 | `python -m pyright --version` | 输出版本号，退出码 0；Node.js 运行时缺失视为依赖未就位 |

### M0-1 命令块（就绪等待 + 标志位收尾，防 sleep 假阳性）

```bash
uvicorn src.api.app:app --port 8000 >/tmp/m0-uvicorn.log 2>&1 &
APP_PID=$!
ok=0
for i in $(seq 1 30); do
  curl -sf localhost:8000/health | grep -q '"status":"ok"' && { ok=1; break; }
  sleep 0.5
done
kill "$APP_PID" 2>/dev/null
[ "$ok" -eq 1 ]
```

> 要点：就绪等待消除竞态；**必须用标志位收尾判定**（若循环体以 `curl && break; sleep` 收尾，全失败时最后执行的是 sleep、退出 0，构成假阳性）；body 用 grep 精确匹配实现机器判定；结束清理服务进程。

### M0-3 命令块（无 key 环境，双通道清理）

```bash
env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY CALC_AGENT_ENV_FILE=/dev/null \
  uvicorn src.api.app:app --port 8000 >/tmp/m0-nokey.log 2>&1 &
APP_PID=$!
ok=0
for i in $(seq 1 30); do
  curl -sf localhost:8000/health | grep -q '"status":"ok"' && { ok=1; break; }
  sleep 0.5
done
kill "$APP_PID" 2>/dev/null
[ "$ok" -eq 1 ]
```

> 要点：pydantic-settings 中环境变量优先级高于 .env——只 unset 不绕开 .env（或只移 .env 不 unset）都不构成有效"无 key"判据；`CALC_AGENT_ENV_FILE=/dev/null`（ARCHITECTURE §7）显式绕开 .env 文件，无需移动真实 `.env`。

## M1 — Agent 核心循环

| ID | 标准 | 验收命令 | 通过判据 |
|----|------|----------|----------|
| M1-1 | FakeLLM 循环集成测试 | `pytest tests/integration -k loop` | 全绿，断言步数上限、事件序列 |
| M1-1b | FakeLLM 不依赖真实 key | `env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY CALC_AGENT_ENV_FILE=/dev/null python -m pytest tests/integration` | 全绿——进程环境无 key **且**绕开 .env（双通道清理），证明集成测试不依赖真实 API |
| M1-2 | 真实 LLM 多步任务 | 见下方 M1-2 命令块 | ① run_agent exit 0；② tool_call 事件数 ≥ 2 且工具种类 ≥ 2（以 `logs/agent-<task_id>.jsonl` 统计，见 ARCHITECTURE §8）；③ `data/out.txt` 内容与 calc 实际计算结果一致（QA 复算：123×456=56088，56088÷7≈8012.57，以 calc 实际输出格式比对）；**禁止以硬编码输出冒充** |
| M1-3 | 工具失败不致命 | `pytest tests/unit -k tool_failure` | 工具异常被捕获并回传 LLM，任务不悬挂 |
| M1-4 | 步数上限 | `pytest tests/integration -k max_steps` | 超限时 Task.status=failed，原因记录在案 |
| M1-5 | 工具安全边界 | `pytest tests/unit -k tool_security` | calc 拒绝非白名单表达式（名称/函数注入）；http_request 阻断私有 IP/云元数据/未校验重定向/DNS rebinding（注入 fake resolver 用例）；file_write 拒绝 `..` 穿越与沙箱外符号链接 |

### M1-2 命令块（事件观测渠道 + 沙箱产出路径）

```bash
python examples/run_agent.py "计算 (123*456)/7 并把结果写入 out.txt"
echo "exit=$?"
# run_agent 约定：启动时打印 task_id；事件落 logs/agent-<task_id>.jsonl（ARCHITECTURE §8）
TASK_ID=<run_agent 输出的任务 ID>
jq -r 'select(.type=="tool_call") | .payload.tool_name' "logs/agent-${TASK_ID}.jsonl" | sort | uniq -c
cat "data/out.txt"
```

> 要点：① `examples/run_agent.py` 经 pydantic-settings **自读 .env**（受 `CALC_AGENT_ENV_FILE` 路径覆盖约束）——.env 缺失且环境无 key 时**必须显式报错退出非 0，不得静默通过**（弃用 `export $(grep … | xargs)` 模式：其空参数退出 0 会掩盖装载失败、值含空格被截断）；② 事件观测渠道明确为 JSONL 事件日志（`logs/agent-<task_id>.jsonl`）；③ 产出文件在 file_write 沙箱内，路径为 `data/out.txt`（ARCHITECTURE §6.3）；④ jq 为系统工具（macOS `brew install jq`），不属 Python 依赖白名单管辖，可用 `python -c` 等价实现替代。

## M2 — 持久化 + API（含恢复语义）

| ID | 标准 | 验收命令 | 通过判据 |
|----|------|----------|----------|
| M2-1 | 状态即写库 | `pytest tests/unit -k storage` | 每次状态变更有对应记录 |
| M2-2 | 断点恢复 | 手工演练：启动任务→中途 `kill -9` 服务→重启→`curl -sf -X POST localhost:8000/tasks/<id>/resume`；自动化承载：`pytest tests/integration -k resume` | 任务从 checkpoint 续跑并完成；succeeded 调用复用结果不重执行（测试断言 ToolCall 表中 succeeded 调用无新 tool_call_id、updated_at 不变） |
| M2-3 | SSE 事件流 | `curl -sfN localhost:8000/tasks/<id>/events \| tee /tmp/sse.log`（任务运行时） | 依序收到 `status/tool_call/tool_result` 事件（无 thought）；事件 `id:` 携带单调递增 seq；任务终止收到 `final`；落盘后可机检 seq 单调与 final 存在 |
| M2-3b | SSE 断线重连 | 见下方 M2-3b 命令块；自动化承载：`pytest tests/integration -k sse_reconnect` | 重连后首个事件 `id:` == MAX_SEQ+1；两段拼接 seq 连续，无丢失、无重复 |
| M2-4 | API 契约 | `curl -sf localhost:8000/openapi.json` | schema 与 ARCHITECTURE.md §3 一致（含 cancel/confirm 端点；可比对路径参数按语义，如 `{id}` vs `{task_id}`）。建议机检：`curl -sf localhost:8000/openapi.json \| jq -r '.paths \| keys[]'` 核对端点存在性 |
| M2-5 | uncertain 非幂等恢复置 paused | 自动化承载：`pytest tests/integration -k uncertain_nonidempotent`；辅助手工演练：模拟 `file_write` 调用执行中 `kill -9`→重启→执行 `POST /tasks/<id>/resume`（**恢复为手动触发**，重启不自动扫描，见 ARCHITECTURE §5.1） | 恢复流程发现 uncertain 非幂等调用即任务置 `paused`（**非自动重试**）；`POST /tasks/<id>/tool-calls/<tool_call_id>/confirm` 确认后才继续（retry 生成新调用 ID / skip 标记 failed 回传 LLM） |
| M2-6 | uncertain 幂等工具自动重试 | `pytest tests/integration -k uncertain_idempotent` | GET 型 http_request（调用级有效幂等性为 idempotent，见 ARCHITECTURE §6.4）uncertain→resume 自动重试一次并完成；重试仍 uncertain 则置 paused |
| M2-7 | 并发 resume 拒绝 | 见下方 M2-7 命令块；自动化承载：`pytest tests/integration -k concurrent_resume` | 并发两个 resume 请求，**恰一个 200、一个 409**——同一任务同时只允许一个活跃执行 |
| M2-8 | 任务取消 | happy path：任务运行中 `curl -sf -X POST localhost:8000/tasks/<id>/cancel`；内部状态与事件断言：`pytest tests/integration -k cancel` | 停止派发新调用；pending 调用标记 failed(cancelled)；进行中调用标记 uncertain；任务终态 cancelled 且收到 final 事件；paused/pending 任务取消同样合法（ARCHITECTURE §5.1） |

### M2-3b 命令块（Last-Event-ID 重连）

```bash
# 第一次连接，收到若干事件后 Ctrl-C 断开
curl -sfN localhost:8000/tasks/<id>/events | tee /tmp/sse1.log
MAX_SEQ=$(grep '^id:' /tmp/sse1.log | tail -1 | awk '{print $2}')
# 携带 Last-Event-ID 重连
curl -sfN -H "Last-Event-ID: ${MAX_SEQ}" localhost:8000/tasks/<id>/events | tee /tmp/sse2.log
```

> 判据：sse2.log 首个事件 `id:` == MAX_SEQ+1；两段拼接后 seq 连续、无丢失无重复。

### M2-7 命令块（409 判定——注意不能带 `-f`）

```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST localhost:8000/tasks/<id>/resume &
curl -s -o /dev/null -w '%{http_code}\n' -X POST localhost:8000/tasks/<id>/resume
wait
```

> 判据：两行输出恰为 {200, 409} 各一。**不能带 `-f`**：409 时 curl 退出码 22，无法以退出码区分"预期 409"与"意外错误"，须以 `-w '%{http_code}'` 抓状态码判定。

## M3 — 前端

| ID | 标准 | 验收命令 | 通过判据 |
|----|------|----------|----------|
| M3-1 | 端到端可视化 | 浏览器（或 Playwright 脚本——**Playwright 不在 §2.1 依赖白名单，引入前须 Architect 更新依赖清单；手动浏览器验收即满足**）创建任务 | 时间线实时渲染 ≥ 2 个工具调用事件与最终结果（以 `final` 事件判定流结束） |
| M3-2 | 无前端报错 | 浏览器 console | 0 error |

## M4 — 端到端验收（项目级）

| ID | 标准 | 验收命令 | 通过判据 |
|----|------|----------|----------|
| E2E-1 | 真实 LLM 全链路 | `python examples/run_agent.py "用 http_request 获取 example.com 标题，calc 统计字符数，结果写入 report.txt"`（run_agent 自读 .env，见 M1-2 要点；事件统计同 M1-2 命令块的 jq 方式） | **tool_call 事件数 ≥ 3 且工具种类 = 3（http_request/calc/file_write 齐备）**；`data/report.txt` 内容与 http 响应实际内容及 calc 实际计算结果一致（QA 交叉校验）；**禁止以硬编码输出冒充**。前置条件：example.com 须在 `HTTP_ALLOWED_HOSTS` 默认白名单（M1 交付落实） |
| E2E-2 | 轨迹可回放 | `python -m cli.replay <task_id>`（cli.replay 为 M2 可观测性交付物，见 ROADMAP） | 完整事件序列与 DB 记录一致（无 thought 事件；比对方式：replay 输出 vs TaskEvent 表查询） |
| E2E-3 | 无 key 环境健壮 | 见下方 E2E-3 命令块 | e2e skip 而非 error（进程环境无 key 且绕开 .env，判据不失真），其余全绿 |
| E2E-4 | G-1~G-5 全量门禁 | `bash scripts/check.sh` | check.sh 覆盖 **G-1 + G-2 + G-3 + G-4 + G-5a + G-5b 全部分项**，逐项独立执行、输出分项结果，分项全部通过；无 `\|\|` 兜底（QA 阅读 check.sh 源码确认） |

### E2E-3 命令块（无 key 环境，绕开 .env）

```bash
env -i PATH="$PATH" HOME="$HOME" CALC_AGENT_ENV_FILE=/dev/null python -m pytest tests/e2e
```

> 要点：`env -i` 只清进程环境、不清 .env 文件——若 .env 含真实 key，e2e 不会 skip 而是真跑，判据失真；故须 `CALC_AGENT_ENV_FILE=/dev/null` 绕开 .env。保留 `HOME` 避免缓存/临时目录报错产生假阴性。

## 验收报告模板

QA 在 `docs/handoff/qa-<里程碑>.md` 输出：每条 ID → 实际命令输出摘要 → 通过/失败 → 失败归因与退回对象。

## 变更记录

### v1.0 → v1.1

1. G-5 拆分为 G-5a（pyright，退出码必须 0）与 G-5b（compileall，退出码必须 0），独立执行、独立判定，禁止 `||` 兜底（修复假阳性）。
2. G-3 密钥扫描改为失败即阻断语义（grep 退出码 1=通过、0=阻断、2=阻断），移除 `|| echo CLEAN` 兜底；注明 M4 可选引入 gitleaks/detect-secrets。
3. M0-2 不再允许 0 collected，必须至少收集并通过 1 个真实测试（/health 端点测试）；新增 M0-4 pyright 依赖就位检查。
4. 新增 M1-1b：FakeLLM 集成测试必须在无真实 key 环境下运行通过。
5. 强化 M1-2 / E2E-1：必须断言实际发生的工具调用，校验产出文件内容与实际计算结果一致，禁止硬编码输出冒充。
6. 新增 M1-5 工具安全边界验收。
7. 新增恢复语义验收：M2-3b（SSE Last-Event-ID 断线重连）、M2-5（uncertain 非幂等恢复置 paused 等待确认）、M2-6（uncertain 幂等自动重试一次）、M2-7（并发 resume 409 拒绝）、M2-8（cancel 语义）；M2-2/M2-3 判据细化。

### v1.1 → v1.2（按架构复审 + QA 验收标准检查报告修订）

1. **[P0-1]** G-2 命令改 `--cov-report=term-missing`，判据注明自 M1 起生效（M0 仅要求可运行）；pytest-cov 已补入 ARCHITECTURE §2.1 依赖白名单与 ROADMAP M0 安装清单。
2. **[P0-2]** G-4 判据量化为"退出码 0 且无反向 import 输出"；`scripts/check_layers.py` 列入 ROADMAP M0 交付物（Backend 实现）；check.sh 内容清单补 G-4，与 E2E-4 口径一致。
3. **[P0-3]** G-1 判据改为"check.sh 内部逐项独立执行并输出分项结果（聚合退出码 + 分项报告），分项全部通过"——失败可归因，不再以聚合退出码单独判定 pytest。
4. **[P1] G-3**：命令改用 `rc=$?; [ "$rc" -eq 1 ]` 机器可判定形式（去掉 `; echo "exit=$?"`）；正则补 `sk-[a-z0-9_-]{8,}` 覆盖 `sk-proj-`/`sk-ant-` 前缀；补 check.sh 集成（set -e 注意）与 fixture 占位 key 豁免备注。
5. **[P1] M0-1**：就绪等待循环 + 标志位收尾判定（防全失败时以 sleep 退出 0 的假阳性）+ body 精确匹配 + 进程清理。
6. **[P1] M0-3 / M1-1b / E2E-3**：采用 `CALC_AGENT_ENV_FILE=/dev/null`（ARCHITECTURE §7 新定义）显式绕开 .env，与环境变量 unset 构成双通道清理；E2E-3 保留 `HOME` 防假阴性。
7. **[P1] M1-2**：弃用 `export $(grep … | xargs)`，改 run_agent 自读 .env 且缺 key 显式报错；事件观测渠道明确为 `logs/agent-<task_id>.jsonl`（jq 统计，注明系统工具属性）；产出路径改为沙箱 `data/out.txt`。
8. **[P1/P2] M2-3b / M2-5 / M2-6 / M2-7 / M2-8**：补可执行命令与 pytest 选择器（`-k sse_reconnect / uncertain_nonidempotent / uncertain_idempotent / concurrent_resume / cancel`）；M2-5 措辞去"自动 resume"（恢复为手动触发）；M2-7 用 `-w '%{http_code}'` 抓码判定（不带 `-f`，409 时 curl 退出 22 不可用）；M2-2/M2-4/M2-3 判据补自动化承载与机检建议。
9. **[P1] E2E-1**：判据修正为"tool_call 事件数 ≥ 3 且工具种类 = 3"（消除 ≥2 与三类齐备的自相矛盾）；补事件观测渠道、`data/report.txt` 沙箱路径、example.com 白名单前置条件、key 加载方式统一（run_agent 自读 .env）；E2E-2 注明 cli.replay 归属 M2。
10. M0-4 / G-5a 补 Node.js 运行时缺失判为依赖未就位；M3-1 Playwright 补依赖红线括注。
