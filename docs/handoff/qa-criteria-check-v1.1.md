# QA 静态检查报告 — ACCEPTANCE_CRITERIA v1.1 可执行性审查

> 检查人：QA Agent（角色定义见 docs/AGENT_ROLES.md §4）
> 日期：2026-10-20 ｜ 项目状态：M0 未启动，无代码可运行
> 检查对象：`docs/ACCEPTANCE_CRITERIA.md`（v1.1）
> 交叉核对：`docs/ARCHITECTURE.md`（v1.1）、`docs/ROADMAP.md`（v1.1）、`.workbuddy/skills/testing/SKILL.md`
> 检查方式：**可执行性静态检查**——不运行验收命令，逐条审查命令的逻辑正确性、假阳性风险、判据可判定性与跨文档一致性。

---

## 总体结论：**需修正**

v1.1 的修订方向正确：反兜底原则（G-3/G-5a/G-5b）、M0 真实测试（M0-2）、无 key 集成测试（M1-1b）、恢复语义五项（M2-3b/5/6/7/8）均已落实，**用户评审要求的 6 项新验收项全部在册（覆盖完整性 6/6，见 §六）**。

但静态检查发现 **3 项 P0 阻断问题**（跨文档依赖/交付物缺失、判据与命令错位）与若干命令级缺陷：31 条验收 ID 中 **14 条通过（含 4 条附注意事项）、17 条需修正（其中 6 条为轻度）**。建议修正后发布 v1.2 再进入 M0。

### 问题分级统计

| 级别 | 定义 | 数量 | 涉及 ID |
|------|------|------|---------|
| P0 | 阻断验收执行（依赖缺失 / 交付物缺失 / 判据不可判定） | 3 | G-2、G-4、G-1（见 §四） |
| P1 | 命令级假阳性风险或可执行性缺陷 | 8 | G-3、M0-1、M0-3、M1-1b、M1-2、M2-3b、M2-7、E2E-1（见 §五） |
| P2 | 判据/命令欠明确但方向正确，建议补充 | 6 | M2-2、M2-5、M2-6、M2-8、E2E-3、E2E-4（见 §五） |

---

## 一、逐条检查结果

### 1. 通用门禁（6 条）

| ID | 结论 | 主要问题 |
|----|------|----------|
| G-1 | ❌ 需修正（P0） | 命令 `bash scripts/check.sh` 与判据"pytest 退出码 0"错位：check.sh 聚合 pytest+覆盖率+G-3+G-5a+G-5b 五项，其退出码无法单独归因 pytest——pyright 失败时 G-1"测试全绿"不可判定 |
| G-2 | ❌ 需修正（P0） | ① `pytest --cov=...` 需要 **pytest-cov**，但 ARCHITECTURE §2.1 依赖清单（"除此之外不加依赖"）与 ROADMAP M0 安装清单均未列——命令无法运行，且补装即触发依赖红线流程；② agent/tools/storage 在 M0 不存在，"每个里程碑"生效但未注明适用期 |
| G-3 | ❌ 需修正（P1） | ① `; echo "exit=$?"` 使整条 shell 命令退出码恒为 0（echo 的），人工判读可行但**不可机器判定**、无法直接入 check.sh；② 正则 `sk-[a-z0-9]{8,}` 不含连字符，漏检现代 key 前缀 `sk-proj-…`、`sk-ant-…`（假阴性盲区）。判据语义本身（1=通过 / 0=阻断 / 2=阻断）**正确且明确** |
| G-4 | ❌ 需修正（P0） | ① `scripts/check_layers.py` **未列入 ROADMAP M0 交付物**——标注"M0 提供"但 M0 交付清单没有它；② ROADMAP M0 的 check.sh 内容清单（pytest+覆盖率+G-3+G-5a+G-5b）**不含 G-4**，与 E2E-4"G-1~G-5 全量门禁"矛盾；③ 判据"无反向 import 报告"应量化为退出码 |
| G-5a | ✅ 通过 | pyright 在 §2.1 与 M0 安装清单；`python -m pyright` 可用；判据明确（退出码 0）；独立判定已声明。附注意：pyright pip 包依赖本机 Node.js 运行时，M0-4 正好暴露此问题，建议判据补一句"node 缺失视为依赖未就位" |
| G-5b | ✅ 通过 | compileall 为标准库，`-q` 下语法错误退出非 0；空 src/ 退出 0；独立判定已声明，无 `||` 兜底路径 |

### 2. M0 — 脚手架（4 条）

| ID | 结论 | 主要问题 |
|----|------|----------|
| M0-1 | ❌ 需修正（P1） | ① `uvicorn … &` 后立即 curl 存在**竞态**（服务未就绪时 curl 失败，假阴性/抖动）；② 判据"返回 {\"status\":\"ok\"}"未给出 body 比对方式，`curl -sf` 只保证 HTTP 200；③ 无服务清理步骤 |
| M0-2 | ✅ 通过 | 判据机器可判定：pytest 在 0 collected 时退出码为 5（非 0），"≥ 1 collected"与退出码 0 联合后无假阳性路径；与 ROADMAP M0"/health 端点 + 对应 pytest 测试"交付物一致 |
| M0-3 | ❌ 需修正（P1） | ① 无具体命令（"删掉 .env 中 key 后启动"是步骤描述）；② **双通道漏洞**：pydantic-settings 中环境变量优先级高于 .env——只删 .env 不 unset 环境变量（shell 已 export 的 key 仍生效）、只 unset 不删 .env（.env 仍供 key），两种做法单独使用都不构成"无 key"的有效判据；③ 判据"服务仍可起"未量化 |
| M0-4 | ✅ 通过 | `python -m pyright --version` 可执行，判据（输出版本号+退出码 0）明确 |

### 3. M1 — Agent 核心循环（6 条）

| ID | 结论 | 主要问题 |
|----|------|----------|
| M1-1 | ✅ 通过 | `-k loop` 无匹配时 pytest 退出码 5（失败），无假阳性路径；判据（全绿+断言内容）可由测试承载 |
| M1-1b | ❌ 需修正（P1，轻） | `env -u` 只清进程环境变量，**不清 .env 文件**——若 .env 含真实 key，集成测试仍可能经 pydantic-settings 拿到 key，"不依赖真实 API"的证明力打折 |
| M1-2 | ❌ 需修正（P1） | ① `export $(grep -v '^#' .env \| xargs)` 脆弱：.env 缺失/全注释时 `export` 无参数仍退出 0，掩盖配置装载失败；值含空格时被静默截断（`export A=1 B` 合法不报错）；② 判据要求"tool_call 事件数 ≥ 2 且工具种类 ≥ 2"，但**命令未指定事件观测渠道**（stdout/logs JSONL/DB）；③ out.txt 实际落在 file_write 沙箱 `data/` 内（ARCHITECTURE §6.3），路径应写明 `data/out.txt`；④ `examples/run_agent.py` 未列入 ROADMAP M1 交付物 |
| M1-3 | ✅ 通过 | `-k tool_failure` 选择器安全（无匹配→退出 5）；判据由测试断言承载 |
| M1-4 | ✅ 通过 | 同上；判据（status=failed+原因记录）明确 |
| M1-5 | ✅ 通过 | 判据与 ARCHITECTURE §6 三工具安全规范逐项对齐（名称/函数注入、私有 IP/云元数据/重定向、`..` 穿越与符号链接），无遗漏 |

### 4. M2 — 持久化 + API（9 条）

| ID | 结论 | 主要问题 |
|----|------|----------|
| M2-1 | ✅ 通过 | `-k storage` 选择器安全；判据由测试断言承载 |
| M2-2 | ❌ 需修正（P2） | 手工 kill -9 演练流程合理，但判据"succeeded 调用复用不重执行（**以 tool_call_id 断言**）"超出 curl 可判定范围——需配套集成测试或 DB 查询命令 |
| M2-3 | ✅ 通过（附建议） | `-sfN` 用于 SSE 正确（200 后流式、服务端关闭后退出 0）；判据明确。建议落盘后机检（`tee` + 检查 seq 单调递增、无 thought、有 final），替代纯人工观屏 |
| M2-3b | ❌ 需修正（P1） | **无可执行命令**（纯 prose）；判据"无丢失、无重复"需比对两次捕获，未给方法 |
| M2-4 | ✅ 通过（附建议） | "schema 与 §3 一致"为人工比对；建议补 jq 机检核心端点存在性（见 §五）。注意 FastAPI 实际路径参数命名（{task_id} vs {id}）与 ARCHITECTURE 记法可能不同，比对时按语义 |
| M2-5 | ❌ 需修正（P2） | ① **缺可执行命令**（同组 M2-1 用 pytest，本条只有 prose）；② 措辞"重启→**自动** resume"与 M2-2 的显式 POST resume 矛盾——ARCHITECTURE §5.1 未定义启动时自动恢复，易生歧义。判据本身与 §5.1 完全一致（paused 非 auto-retry；confirm retry 新 ID / skip 标 failed） |
| M2-6 | ❌ 需修正（P2） | **缺可执行命令**；判据本身明确且与 §5.1 恢复矩阵一致 |
| M2-7 | ❌ 需修正（P1） | **无可执行命令**；且注意 `curl -sf` 在 409 时退出 22，不能直接用于"恰一个 200 一个 409"的判定（需 `-w '%{http_code}'` 抓码且不能带 `-f`，或走 pytest）。判据本身明确（409 语义与 §5.1 一致） |
| M2-8 | ❌ 需修正（P2） | happy path 的 curl 可行，但"pending 标 failed(cancelled)、进行中标 uncertain、终态 cancelled 且收到 final"是内部状态+事件断言，超出单条 curl 可判定范围，需配套 pytest |

### 5. M3 — 前端（2 条）

| ID | 结论 | 主要问题 |
|----|------|----------|
| M3-1 | ✅ 通过（附注意） | 人工浏览器验收可接受，判据明确（≥2 个工具调用事件 + final 判定结束）。注意：**Playwright 选项与 §2.1 依赖红线冲突**——若要用 Playwright 脚本须先经 Architect 批准入清单，建议括注删除或注明"引入前须 Architect 更新依赖清单" |
| M3-2 | ✅ 通过 | 判据（console 0 error）明确；人工/DevTools 可判 |

### 6. M4 — 端到端（4 条）

| ID | 结论 | 主要问题 |
|----|------|----------|
| E2E-1 | ❌ 需修正（P1） | ① **判据自相矛盾**："tool_call 事件数 ≥ 2 且工具种类 ≥ 2"与"三类工具均被真实调用（…齐备）"并存——齐备蕴含种类=3；② 同 M1-2：事件观测渠道未指定；③ report.txt 应写明 `data/report.txt`（沙箱）；④ 前置条件未声明：example.com 必须在 HTTP_ALLOWED_HOSTS 默认白名单（§6.2"默认含示例域名"需在 M1 落实，否则本项必失败）；⑤ key 加载方式与 M1-2 不一致（M1-2 显式 export，本条未加载——须明确 run_agent 是否自读 .env） |
| E2E-2 | ✅ 通过（附注意） | `python -m cli.replay` 与 ARCHITECTURE §8 一致。注意：cli.replay 未列入 ROADMAP 任何里程碑的交付物清单，建议明确归属（M2 可观测性或 M4）；"与 DB 记录一致"建议注明比对方式（replay 输出 vs TaskEvent 表查询） |
| E2E-3 | ❌ 需修正（P2，轻） | `env -i PATH=$PATH` 只清进程环境，**不清 .env 文件**——若 .env 含真实 key，e2e 不会 skip 而是真跑，"skip 而非 error"判据失真。判据本身机器可判定（pytest 输出 SKIPPED + 退出码 0） |
| E2E-4 | ❌ 需修正（P2） | "G-1~G-5 全量门禁"与 check.sh 实际内容（缺 G-4）矛盾——依赖 G-4 项修正联动；"无 `\|\|` 兜底"需 QA 阅读 check.sh 源码确认，属代码评审动作，可接受 |

---

## 二、P0 阻断问题详述与修改建议

### P0-1：G-2 需要 pytest-cov，但依赖清单未列（违反 §2.1 红线）

`pytest --cov=src --cov-report=term` 依赖 pytest-cov 插件；ARCHITECTURE §2.1（"完整清单，除此之外不加依赖"）与 ROADMAP M0 安装命令均无 pytest-cov。同时 ROADMAP M0 的 check.sh 明确含"覆盖率"段——两处都无法执行。

**修改建议**（两步，需 Architect 执行）：
1. ARCHITECTURE §2.1 增补 `pytest-cov`（dev 分组，一句话必要性：G-2 覆盖率门禁的 pytest 集成插件），递增版本号。
2. G-2 验收命令与判据修订为：

```bash
pytest --cov=src --cov-report=term-missing
```

> 通过判据：agent/ tools/ storage/ 行覆盖 ≥ 80%（**自 M1 起生效**——M0 尚无此三模块，不适用；M0 仅要求命令可运行不报错）。term-missing 便于逐文件核对。

### P0-2：G-4 的 check_layers 工具无交付方，check.sh 清单缺 G-4

ACCEPTANCE 标注"（M0 提供）"，但 ROADMAP M0 交付物清单没有 `scripts/check_layers.py`；且 ROADMAP M0 描述的 check.sh 内容（pytest+覆盖率+G-3+G-5a+G-5b）不含 G-4，与 E2E-4"G-1~G-5 全量门禁"直接矛盾。

**修改建议**（需 Lead Orchestrator 安排 ROADMAP 修订）：
1. ROADMAP M0 交付物补一行：`scripts/check_layers.py`（分层依赖检查：校验 api→services→agent→tools/storage 单向、models 仅被引用，禁止反向 import）。
2. ROADMAP M0 的 check.sh 描述补 G-4。
3. G-4 判据量化：`python -m scripts.check_layers` **退出码 0 且无反向 import 输出**（从项目根执行，scripts/ 需可作包导入）。

### P0-3：G-1 命令与判据错位

命令 `bash scripts/check.sh` 的退出码聚合五个子门禁；判据只定义"pytest 退出码 0"。当 pyright 或 G-3 失败导致 check.sh 退出非 0 时，G-1（测试全绿）无法从退出码归因判定。

**修改建议**（二选一，推荐前者）：
- 方案 A：G-1 验收命令改为 `python -m pytest -q`，判据"退出码 0"；`bash scripts/check.sh` 仅作为 E2E-4 全量门禁的命令。
- 方案 B：保留命令，判据改为"check.sh 退出码 0（脚本内各子门禁独立判定、任一失败则整体失败，且输出中 pytest 段无失败）"——要求 check.sh 实现分段输出。

---

## 三、P1/P2 问题与修改后的命令文本

### G-3（P1）：退出码被 echo 覆盖 + 正则盲区

`; echo "exit=$?"` 使 shell 层退出码恒为 0。人工判读"exit=N"可行（v1.1 判据语义本身正确），但不可机器判定、不能直接入 check.sh。另：`sk-[a-z0-9]{8,}` 不匹配含连字符的 `sk-proj-…`/`sk-ant-…` 前缀。

**修改建议**（验收命令，整条退出码即判定结果——0 仅当无匹配）：

```bash
grep -rniE "(sk-[a-z0-9_-]{8,}|api[_-]?key[[:space:]]*=[[:space:]]*[\"'][^\"']+)" src/ tests/ web/
rc=$?
[ "$rc" -eq 1 ]
```

> 正则变更：`sk-[a-z0-9]{8,}` → `sk-[a-z0-9_-]{8,}`。语义不变：grep rc=1（无匹配）→ 整条退出 0 = 通过；rc=0（有匹配）或 rc=2（扫描出错）→ 退出 1 = 阻断。

### M0-1（P1）：竞态 + body 未机判

**修改建议**：

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

> 要点：① 就绪等待消除竞态；② **必须用标志位收尾判定**——若写成 `for …; do curl … && break; sleep 0.5; done`，全部失败时循环最后执行的是 sleep（退出码 0），构成假阳性；③ body 用 grep 精确匹配实现机器判定（FastAPI 默认 JSON 序列化无空格）；④ 结束清理服务进程。

### M0-3（P1）：无具体命令 + 双通道漏洞

**修改建议**：

```bash
mv .env .env.bak
env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY uvicorn src.api.app:app --port 8000 >/tmp/m0-nokey.log 2>&1 &
APP_PID=$!
# …同 M0-1 的就绪等待 + '"status":"ok"' 判定…
kill "$APP_PID" 2>/dev/null
mv .env.bak .env
```

> 理由：pydantic-settings 中环境变量优先级高于 .env。只删 .env 不 unset 环境变量、或只 unset 不删 .env，都不能证明"无 key 可起"。判据量化为：服务就绪且 /health 返回 `{"status":"ok"}`。

### M1-1b（P1 轻）：env -u 不清 .env

**修改建议**：

```bash
mv .env .env.bak
env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY python -m pytest tests/integration
rc=$?
mv .env.bak .env
exit $rc
```

> 理由：.env 仍在磁盘时，"无真实 key 环境"前提不成立（pydantic-settings 仍可从 .env 取 key）。移走 .env 后才能证明集成测试不依赖真实 API。

### M1-2（P1）：export 模式脆弱 + 观测渠道缺失

**修改建议**：

```bash
set -a; . ./.env; set +a
python examples/run_agent.py "计算 (123*456)/7 并把结果写入 out.txt"
echo "exit=$?"
# 事件断言（约定 run_agent 打印 task_id；事件落 logs/agent-<task_id>.jsonl，见 ARCHITECTURE §8）
TASK_ID=<run_agent 输出的任务 ID>
jq -r 'select(.type=="tool_call") | .payload.tool_name' "logs/agent-${TASK_ID}.jsonl" | sort | uniq -c
cat "data/out.txt"
```

> 判据：① run_agent exit 0；② uniq -c 统计 tool_call 总数 ≥ 2 且工具种类 ≥ 2；③ `data/out.txt` 内容与 QA 复算一致（123×456=56088；56088÷7=8012.571428…，以 calc 实际输出格式为准比对）。
>
> 配套修订：a) 弃用 `export $(grep -v '^#' .env | xargs)`——.env 缺失/全注释时 export 无参数退出 0 掩盖装载失败，值含空格被静默截断；`set -a; . ./.env; set +a` 是标准等价物。b) ROADMAP M1 交付物补 `examples/run_agent.py`。c) 文档中产出文件路径写明 `data/out.txt`（file_write 沙箱为 `data/`，ARCHITECTURE §6.3）。

### M2-3b（P1）：缺可执行命令

**修改建议**：

```bash
# 第一次连接，收到若干事件后 Ctrl-C 断开
curl -sfN localhost:8000/tasks/<id>/events | tee /tmp/sse1.log
MAX_SEQ=$(grep '^id:' /tmp/sse1.log | tail -1 | awk '{print $2}')
# 携带 Last-Event-ID 重连
curl -sfN -H "Last-Event-ID: ${MAX_SEQ}" localhost:8000/tasks/<id>/events | tee /tmp/sse2.log
```

> 判据：sse2.log 首个事件 `id:` == MAX_SEQ+1；两段拼接后 seq 连续、无丢失无重复。建议同步自动化为 `pytest tests/integration -k sse_reconnect`（ROADMAP M2 已含"SSE 重连"测试项，验收命令应指向它）。

### M2-7（P1）：缺可执行命令，curl -sf 不能判 409

**修改建议**：

```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST localhost:8000/tasks/<id>/resume &
curl -s -o /dev/null -w '%{http_code}\n' -X POST localhost:8000/tasks/<id>/resume
wait
```

> 判据：两行输出恰为 {200, 409} 各一。注意**不能带 `-f`**（409 时 curl 退出 22，无法以输出判定）。建议同步 `pytest tests/integration -k concurrent_resume`（httpx 并发请求，断言 200/409 各一）。

### E2E-1（P1）：判据矛盾 + 观测渠道/沙箱路径/前置条件

**修改建议**：
1. 判据改为："**tool_call 事件数 ≥ 3 且工具种类 = 3（http_request/calc/file_write 齐备）**"（消除"≥ 2"与"三类齐备"的自相矛盾）。
2. 事件观测渠道与统计命令同 M1-2（logs/agent-\<task_id\>.jsonl + jq）。
3. 产出文件写明 `data/report.txt`。
4. 前置条件注明："example.com 须在 HTTP_ALLOWED_HOSTS 默认白名单（由 M1 交付落实）"。
5. 统一 key 加载方式：若 run_agent 经 pydantic-settings 自读 .env，则 M1-2 的 export 前缀冗余可删；若不自读，本条须补加载步骤。二选一并写入文档。

### M2-2 / M2-5 / M2-6 / M2-8（P2）：补自动化命令与措辞

| ID | 修改建议 |
|----|----------|
| M2-2 | 保留手工 kill -9 演练；判据中"succeeded 复用不重执行（以 tool_call_id 断言）"补自动化承载：`pytest tests/integration -k resume`（断言 ToolCall 表中 succeeded 调用无新 tool_call_id、updated_at 不变） |
| M2-5 | 补命令：`pytest tests/integration -k uncertain_nonidempotent`（+ 手工 kill -9 演练）；措辞"重启→自动 resume"改为"重启→执行 resume（POST /tasks/<id>/resume），恢复流程发现 uncertain 非幂等调用即置 paused" |
| M2-6 | 补命令：`pytest tests/integration -k uncertain_idempotent`；判据不变 |
| M2-8 | 保留 curl 判定 happy path；pending→failed(cancelled)、running→uncertain、final 事件断言补 `pytest tests/integration -k cancel` |

### E2E-3（P2 轻）：env -i 不清 .env

**修改建议**：

```bash
mv .env .env.bak
env -i PATH="$PATH" HOME="$HOME" python -m pytest tests/e2e
rc=$?
mv .env.bak .env
exit $rc
```

> 理由：.env 含真实 key 时 e2e 不会 skip 而是真跑，"skip 而非 error"判据失真；保留 HOME 避免无关的环境错误干扰判定。

### E2E-4（P2）：与 G-4 联动

check.sh 内容清单补 G-4（随 P0-2 修正），或将 E2E-4 标准列改为"G-1~G-3 + G-5（G-4 单独执行）"——二选一，保持口径一致。

---

## 四、假阳性路径专项核查（对应检查项 1）

| 检查点 | 结论 |
|--------|------|
| G-3 grep 退出码 0/1/2 语义 | **判据语义正确**（1=通过、0=阻断、2=阻断），且已明令禁止 `\|\| echo CLEAN` 兜底；但 `; echo "exit=$?"` 在 shell 层掩盖退出码，机器判定需包装（见 §三 G-3 修正） |
| G-5a/G-5b 独立判定 | **通过**：两条独立命令、各自退出码判据，并显式禁止合并为 `pyright … \|\| compileall …`；不存在兜底路径 |
| `&&` 链中断 | M1-2 的 `export … && python …`：export 失败则 python 不执行→验收失败（假阴性方向，不构成假阳性）；但 export 空参数退出 0 的边缘场景会掩盖配置装载失败（见 M1-2 修正） |
| 等待循环陷阱 | M0-1 若采用朴素 `for … do curl && break; sleep …; done`，全失败时以 sleep 收尾退出 0——**假阳性**，修正方案已用标志位规避（见 §三） |
| `-k` 选择器空匹配 | 所有 `pytest -k …` 条目（M1-1/3/4/5、M2-1）在无匹配测试时 pytest 退出码 5=失败，无假阳性 |
| `curl -sf` 与非 200 | M2-7 用 `-sf` 判 409 会得退出 22，无法区分"预期 409"与"意外错误"——修正为 `-w '%{http_code}'` 抓码判定（见 §三） |

---

## 五、可执行性专项核查（对应检查项 2）

| 核查点 | 结论 |
|--------|------|
| shell 语法 | 所有命令语法完整（表格内 `\|` 为 Markdown 转义，还原后可执行）；M0-3/M2-2/M2-3b/M2-5/M2-6/M2-7 为 prose 步骤而非命令，需补可执行形式 |
| 模块/路径 | `src.api.app:app`、`python -m pyright`、`python -m compileall`、`python -m cli.replay` 均语法可行；`examples/run_agent.py`、`scripts/check_layers.py`、`cli/replay` 存在**交付方缺位**（ROADMAP 未列，见 P0-2 与 E2E-2 注意项） |
| 里程碑交付物对齐 | M0 条目引用的 `scripts/check.sh`、/health 端点、pyright 均在 ROADMAP M0 交付清单 ✓；**例外**：check_layers（G-4）与 examples/run_agent.py（M1-2）未列入对应里程碑交付物 ✗ |
| 外部依赖 | pytest-cov 缺失（P0-1）；pyright 需 Node 运行时（M0-4 可暴露）；Playwright 与依赖红线冲突（M3-1 注意项）；jq 仅出现在本报告建议中，若采纳需确认环境可用（macOS 可 `brew install jq`，或改用 `python -c` 等价实现） |

---

## 六、覆盖完整性核对（对应检查项 4：用户评审要求的 6 项）

| # | 评审要求 | 对应验收 ID | 状态 |
|---|----------|-------------|------|
| 1 | M0 至少 1 个真实 /health 测试 | M0-2（collected ≥ 1 且须为 /health 端点测试） | ✅ 已覆盖，判据机器可判定（pytest 退出码 5 天然拦截 0 collected） |
| 2 | FakeLLM 集成测试在 `env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY` 下运行 | M1-1b | ✅ 已覆盖；⚠️ 需补 .env 移除（见 §三），否则证明力打折 |
| 3 | 真实 LLM 测试断言 tool_call 事件数 ≥ 2 且工具种类 ≥ 2 并交叉校验产出内容 | M1-2、E2E-1 | ✅ 已覆盖（含禁硬编码条款与 QA 复算）；⚠️ E2E-1 判据措辞矛盾需修 |
| 4 | uncertain 非幂等工具恢复置 paused | M2-5（confirm retry 新 ID / skip 标 failed 回传 LLM） | ✅ 已覆盖，与 ARCHITECTURE §5.1 逐条一致；⚠️ 缺可执行命令 |
| 5 | 并发 resume 拒绝（409） | M2-7（恰一个 200 一个 409） | ✅ 已覆盖；⚠️ 缺可执行命令 |
| 6 | SSE Last-Event-ID 重连 | M2-3b（seq+1 续传、无丢失无重复） | ✅ 已覆盖，与 §3.1 一致；⚠️ 缺可执行命令 |

**结论：6/6 齐全，无遗漏**；v1.1 变更记录与上述修订一一对应。

---

## 七、与 ARCHITECTURE / ROADMAP 交叉一致性发现汇总

| # | 发现 | 性质 |
|---|------|------|
| 1 | pytest-cov 被 G-2/check.sh 要求但不在 §2.1 依赖清单 | **P0，需 Architect 走依赖变更** |
| 2 | scripts/check_layers.py 未列入 ROADMAP M0 交付物；check.sh 清单缺 G-4 | **P0，需 ROADMAP 修订** |
| 3 | examples/run_agent.py 未列入 ROADMAP M1 交付物 | P1，需 ROADMAP 补记 |
| 4 | cli.replay 未指明交付里程碑（E2E-2 依赖它） | P2 |
| 5 | E2E-1 依赖 example.com 在默认域名白名单（§6.2"默认含示例域名"），需 M1 落实 | P2，前置条件应写入验收文档 |
| 6 | M2-4 判据引用 §3 端点清单（含 cancel/confirm）——两文档一致 ✓；M2-5/6/7/8 判据与 §5.1 恢复语义逐条一致 ✓；M1-5 与 §6 安全规范逐条一致 ✓；M2-3/E2E-2 事件模型（去 thought、seq、final）与 §3.1/ADR-006 一致 ✓ | 一致性确认 |

---

## 八、v1.2 修正后的复核清单（QA 下轮检查点）

1. G-1/G-2/G-4 命令与判据按 §二/§三 修订，pytest-cov 与 check_layers 的交付责任落位（ARCHITECTURE §2.1 + ROADMAP M0/M1 增补）。
2. M0-1/M0-3 采用带标志位收尾判定的就绪等待与双通道（.env + 环境变量）清理。
3. M1-1b/E2E-3 增加 .env 临时移除步骤。
4. M1-2/E2E-1 明确事件观测渠道（logs JSONL + 统计命令）与沙箱内产出路径；E2E-1 判据改为"事件数 ≥ 3 且工具种类 = 3"。
5. M2-3b/M2-5/M2-6/M2-7/M2-8 补 pytest 选择器命令（命名对齐 testing SKILL `test_<行为>_<预期>` 约定）；M2-5 措辞去"自动"。
6. G-3 正则补连字符并给出机器可判定的包装命令。

---

## 附：检查方法说明

- 本报告为**静态检查**：逐条推演每条验收命令的退出码路径（成功/失败/边缘场景），并与 ARCHITECTURE v1.1 的端点、事件模型、恢复语义（§3/§3.1/§5/§5.1/§6/§8）及 ROADMAP v1.1 各里程碑交付物交叉核对。
- 未运行任何验收命令（M0 未启动，无被检对象）；所有"修改后的命令文本"均已做 shell 语法与退出码语义推演，但尚待 M0 起有真实代码后实测。
- 本报告未改动 `docs/ACCEPTANCE_CRITERIA.md`（QA 职责边界：评审与修改分离，缺陷退回原角色）。
