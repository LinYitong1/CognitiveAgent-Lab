# 架构评审报告 — CognitiveAgent Lab v1.1（QA 独立复审）

> 评审人：QA Agent（独立复审，未参与 v1.1 修订，避免自审偏差）
> 评审日期：2026-10-20
> 评审对象：docs/ARCHITECTURE.md v1.1、docs/ACCEPTANCE_CRITERIA.md v1.1、docs/ROADMAP.md v1.1、docs/AGENT_ROLES.md v1.1、README.md（引用 v1.1）、docs/ENVIRONMENT_AUDIT.md v1.0（背景参考）
> 评审依据：`.workbuddy/skills/architecture-review/SKILL.md` 六项硬约束 + 执行流程 + 交付标准；用户对 v1.0 提出的 4 项关键问题修复要求
> 评审范围声明：本评审为纯文档复审（尚无代码实现），评审对象是设计文档的完整性、一致性与可实现性。

---

## 一、六项硬约束逐条核对

| # | 硬约束 | 结论 | 证据 |
|---|--------|------|------|
| 1 | 技术栈限定：Python 3.13 + FastAPI + Pydantic v2 + pytest | **通过** | ARCHITECTURE §2 技术栈表与 §2.1 依赖白名单一致；README 技术栈节一致；pyright 仅为开发期类型检查门禁（G-5a），不违背限定 |
| 2 | 必须真实 LLM Agent runtime，禁止静态规则模拟 | **通过** | ARCHITECTURE §4"真实 LLM：工具选择由模型 tool-calling 决定"+ ADR-001 自研单主循环；M1-2 / E2E-1 强制真实 LLM 且断言实际工具调用；FakeLLM 仅作测试替身（M1-1/M1-1b），非生产实现 |
| 3 | 不引入多 Agent 框架 | **通过** | §2.1 依赖红线白名单中无 LangGraph/CrewAI/AutoGen；ADR-001 论证自研单循环；ROADMAP"明确不做"节列多 Agent 协作于 Scope 外 |
| 4 | 密钥只经环境变量，禁止硬编码 | **通过** | ARCHITECTURE §7：`.env`（gitignore）+ pydantic-settings，红线声明"密钥出现在代码/测试/日志即 Blocker"；G-3 扫描失败即阻断（退出码 0/2 均阻断）；M1-1b/E2E-3 覆盖无 key 环境 |
| 5 | Agent 状态可持久化、可中断、可恢复 | **通过** | §5 Task/Step/ToolCall/TaskEvent 四表 + §5.1 恢复语义（checkpoint、状态机含 uncertain、幂等性矩阵、confirm/cancel、并发恢复锁）；ROADMAP M2 与 ACCEPTANCE M2-1~M2-8 对应 |
| 6 | 每个功能有可执行验收方式 | **通过**（有瑕疵，见问题清单 M-1/M-2/m-1） | ACCEPTANCE v1.1 全部功能有验收条目且反假阳性原则明确；但 G-2 覆盖率命令所需 pytest-cov 不在依赖白名单（M-1）、check.sh 与 G-4 矛盾（M-2）、M2-5/6/8 命令非可直接执行形式（m-1）——功能覆盖完整，命令层有缺陷，不改变"有验收方式"的总体满足 |

**小结**：六项硬约束全部通过，无违规。瑕疵集中在验收命令与依赖白名单的衔接处，列于问题清单。

---

## 二、用户评审四项关键问题逐项验证

### 关键问题 1：断点恢复安全语义 — **已解决**

| 用户要求 | v1.1 证据 | 判定 |
|----------|-----------|------|
| 工具执行状态机（含 uncertain） | ARCHITECTURE §5.1：`pending → running → (succeeded \| failed \| uncertain)`，uncertain 定义为"调用已发出但结果未知" | ✅ |
| 稳定 tool_call_id | §5.1"稳定调用 ID"：派发前分配全局唯一 ID，是恢复、幂等判定、SSE 对齐与人工确认的唯一锚点；ToolCall 表含 tool_call_id 字段 | ✅ |
| checkpoint 语义 | §5.1：checkpoint = 调用进入 running **之前**持久化的完整上下文（任务状态+已完成步骤+待执行调用及 ID） | ✅ |
| 幂等性分级 | §6.4 注册表强制声明 `idempotency`（缺失即注册失败）+ §5.1 恢复策略"状态 × 幂等性"矩阵 | ✅ |
| uncertain 非幂等禁止自动重试、置 paused 等确认 | §5.1 矩阵明确"禁止自动重试：任务置 paused"；confirm API `POST /tasks/{id}/tool-calls/{tool_call_id}/confirm`（retry 新调用 ID / skip 标记 failed 回传 LLM）；ADR-004"宁可暂停等人，不可静默重复副作用" | ✅ |
| 任务取消 | §5.1 cancel 语义：停止派发；pending 标记 failed(cancelled)；running 标记 uncertain；终态 cancelled + 必发 final；API 列表含 cancel 端点 | ✅ |
| 并发恢复控制 | §5.1：同一任务同时只允许一个活跃执行；Task.version 乐观并发控制，双 resume 返回 409；心跳机制 | ✅（存在 fencing 缺口，见 M-4） |
| 对应测试要求 | ACCEPTANCE M2-5（uncertain 非幂等置 paused）、M2-6（uncertain 幂等自动重试一次）、M2-7（并发 resume 409）、M2-8（cancel）；M2-2 以 tool_call_id 断言 succeeded 复用不重执行；ROADMAP M2 同步 | ✅ |

**结论**：用户要求的全部语义要素均已具备且四份文档（ARCHITECTURE/ACCEPTANCE/ROADMAP/README）表述一致。残余缺口为并发抢占 fencing（M-4）与状态机迁移缺失（M-5），属深化项，不构成对该关键问题"未解决"的判定。

### 关键问题 2：工具安全边界 — **已解决**

| 用户要求 | v1.1 证据 | 判定 |
|----------|-----------|------|
| calc 禁 eval，改 AST 白名单 | ARCHITECTURE §6.1：基于 `ast` 的白名单节点解析（数字常量、白名单二元/一元运算、白名单函数 Call）；禁 eval/exec/名称解析（Name 节点一律拒绝）；限长度 ≤256 与 AST 深度 ≤32 | ✅ |
| http_request SSRF：协议白名单 | §6.2：仅 http/https | ✅ |
| 域名白名单 | §6.2 + §7 `HTTP_ALLOWED_HOSTS` 配置项 | ✅ |
| 实际 IP 校验阻断内网与云元数据 | §6.2：DNS 解析后对实际 IP 校验，IPv4 阻断 127/8、10/8、172.16/12、192.168/16、169.254/16（含 169.254.169.254 云元数据），IPv6 阻断 ::1、fc00::/7、fe80::/10 | ✅ |
| 重定向逐跳校验 | §6.2：禁止自动跟随未校验重定向，每跳重新走"域名白名单+IP 校验"全流程，最大跳数 3 | ✅ |
| file_write 沙箱边界/realpath/符号链接/穿越 | §6.3：限定 `data/` 沙箱；先 realpath 规范化再前缀校验；显式拒绝 `..`；lstat 检查目标路径**各级目录**不含符号链接；大小上限 1MB | ✅ |
| 对应验收 | M1-5 工具安全边界（攻击用例：表达式注入、SSRF 私有 IP/云元数据/重定向绕过、路径穿越/符号链接）；ROADMAP M1 单元测试任务 | ✅ |

**结论**：用户要求的全部安全机制均已定义。残余缺口为 DNS rebinding TOCTOU（校验后未规定绑定该 IP 连接，见 M-3），属攻击面深化项，不构成"未解决"。

### 关键问题 3：事件模型 — **已解决**

| 用户要求 | v1.1 证据 | 判定 |
|----------|-----------|------|
| 公开事件收敛为 status/tool_call/tool_result/error/final，不含 thought | ARCHITECTURE §3.1 完整枚举并声明"不再存在 thought 事件"；§5 Step 表"无 thought 字段"；§8"thought 不落任何观测通道"；ADR-006；AGENT_ROLES Frontend 职责、ROADMAP M2/M3、README、ACCEPTANCE M2-3/E2E-2 五处表述全部一致；全仓 grep 验证无残留矛盾 | ✅ |
| seq 单调递增 | §3.1/§5：每任务独立、单调递增、从 1 开始，storage 层写入时原子分配 | ✅ |
| SSE Last-Event-ID 断线重连 | §3.1：`id:` 携带 seq；重连从 seq+1 续传；事件先落库再推送（不依赖内存缓冲）；终态任务重连重放全部事件以 final 结束；验收 M2-3b | ✅ |
| final 事件保证 | §3.1/§4/§8 三处一致"任务终止必发 final"；cancel 场景同样保证（§5.1） | ✅ |

**结论**：完全解决，且为本次修订中四份文档间一致性最高的部分。

### 关键问题 4：验收命令假阳性 — **已解决**

| 用户要求 | v1.1 证据 | 判定 |
|----------|-----------|------|
| G-5 拆分独立、禁 \|\| 兜底 | ACCEPTANCE：G-5a（pyright 退出码必须 0）与 G-5b（compileall 退出码必须 0）独立两条，加粗声明"禁止合并为 `pyright ... \|\| compileall ...` 兜底形式，任一失败即门禁失败"；ROADMAP M0 check.sh 与 E2E-4 同步 | ✅ |
| G-3 密钥扫描失败即阻断 | G-3：grep 退出码 1（无匹配）=通过、0（有匹配）=阻断、2（扫描出错）=阻断，明确"禁止 `\|\| echo CLEAN` 式兜底" | ✅ |
| M0 至少 1 个真实测试 | M0-2：collected ≥ 1，必须收集并通过 /health 端点真实测试，"不再允许 0 collected"；ROADMAP M0 补 /health 测试任务 | ✅ |
| FakeLLM 测试无 key 运行 | 新增 M1-1b：`env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY pytest tests/integration` 全绿；ROADMAP M1 同步"必须覆盖无 key 环境" | ✅ |
| 真实 LLM 测试断言实际工具调用 | M1-2：tool_call 事件数 ≥ 2 且工具种类 ≥ 2，out.txt 内容与 calc 实际计算结果 QA 复算一致，"禁止以硬编码输出冒充（预置期望文件内容即退回）"；E2E-1 进一步要求三工具齐备 + QA 交叉校验 | ✅ |

**结论**：五项反假阳性要求全部落实。残余问题：G-2 命令依赖 pytest-cov 不在白名单（M-1）、check.sh 与 G-4 的矛盾（M-2）——属新引入的衔接缺陷，非原问题复发。

---

## 三、一致性检查

### 3.1 路径表述（src/ 前缀）

ARCHITECTURE §3（src/api、src/services、src/agent、src/tools、src/storage、src/models）、ROADMAP（src/agent/llm.py 等）、AGENT_ROLES（Architect/Backend 工作边界）、ACCEPTANCE（`--cov=src`、`pyright src/`、`uvicorn src.api.app:app`）、README——**全部一致，通过**。ROADMAP v1.1 变更记录第 4 条明确完成此项修订。

### 3.2 新增依赖必要性说明

§2.1 依赖清单 10 项均有必要性一句话说明；pyright 已注明"G-5a 门禁"且"仅用于开发期检查，可置于 dev 分组"。README 技术栈同步。**通过**。缺口：G-2 实际需要 pytest-cov 但未列入（见 M-1）——这是"遗漏依赖"而非"依赖缺说明"。

### 3.3 版本号、变更记录、ADR

| 文档 | 版本 | 变更记录 | 判定 |
|------|------|----------|------|
| ARCHITECTURE.md | v1.1（头部） | 7 条，逐条对应 4 关键 + 3 次要 | ✅ |
| ACCEPTANCE_CRITERIA.md | v1.1 | 7 条 | ✅ |
| ROADMAP.md | v1.1 | 4 条 | ✅ |
| AGENT_ROLES.md | v1.1 | 无独立变更记录节，修订说明仅置于头部版本行 | ⚠️ 可接受（信息未丢失），建议补独立节（S-6） |
| README.md | 引用 v1.1 | 无版本要求 | ✅ |
| ENVIRONMENT_AUDIT.md | v1.0 历史快照 | 未修改 | ✅ 合理（背景参考） |

ADR-004（断点恢复与幂等性语义）、ADR-005（工具安全边界）、ADR-006（公开事件模型）**齐全**，且内容分别与 §5.1、§6、§3.1 正文核对一致。✅

### 3.4 修订是否引入新矛盾

- 事件类型枚举：ARCHITECTURE §3.1/§8、ADR-006、AGENT_ROLES Frontend、ROADMAP M2/M3、README、ACCEPTANCE M2-3/E2E-2——**六处一致，无矛盾**。
- 幂等性声明：存在工具级单值（§6.4）与 http_request 方法级（§6.2 GET 视为幂等）、M2-6 调用级判定之间的表述张力，需一句澄清（m-2）。
- check.sh 内容：ROADMAP M0 定义（不含 G-4）与 E2E-4"G-1~G-5 全量"判据**矛盾**（M-2）。
- 其余交叉核对（状态机、恢复矩阵、cancel/confirm 语义、SSE 机制、依赖清单、端点清单）在 ARCHITECTURE 与 ROADMAP/ACCEPTANCE 间一致。

---

## 四、问题清单

### Blocker（0 条）

无。

### Major（5 条）

**M-1 G-2 覆盖率命令依赖 pytest-cov，与 §2.1 依赖红线矛盾**
- 位置：ACCEPTANCE_CRITERIA.md G-2（`pytest --cov=src --cov-report=term`）vs ARCHITECTURE.md §2.1（白名单仅 fastapi/uvicorn/pydantic/pydantic-settings/pytest/pytest-asyncio/httpx/openai/pyright）；AGENT_ROLES.md QA 权限"运行 pytest/coverage"亦隐含该工具存在。
- 理由：`--cov` 参数由 pytest-cov 插件提供，白名单未含则 G-2 在 M0 合入时即不可执行，或执行时违反"除此之外不加依赖"红线。
- 修复建议：§2.1 增加 `pytest-cov`（dev 分组，必要性："G-2 覆盖率门禁采集"）并递增版本号；或改用标准库外置命令（`coverage run -m pytest`）并同样补依赖说明。二选一，须同步 ROADMAP M0 依赖安装行。

**M-2 check.sh 未含 G-4，且 check_layers 脚本无开发归属，与 E2E-4 矛盾**
- 位置：ROADMAP.md M0（check.sh = pytest + 覆盖率 + G-3 + G-5a + G-5b，无 G-4；任务清单亦无 check_layers 开发条目）vs ACCEPTANCE_CRITERIA.md G-4（"M0 提供"）与 E2E-4（"G-1~G-5 全量门禁 bash scripts/check.sh"）。
- 理由：E2E-4 要求 check.sh 覆盖 G-1~G-5 全量，但 ROADMAP 定义的 check.sh 缺 G-4；且 `scripts/check_layers` 在 ROADMAP M0 任务清单中无人负责实现，M0-1~M0-4 验收也不覆盖它——首次合入门禁即出现不可执行项。
- 修复建议：① ROADMAP M0 任务补"scripts/check_layers（AST/import 检查分层依赖）"；② M0 的 check.sh 定义加"分层检查（G-4）"；③ 可选：M0 验收补 G-4 或在 G-4 注明启用时点。

**M-3 http_request 未规定"校验通过的 IP 直接用于连接"，存在 DNS rebinding TOCTOU 缺口**
- 位置：ARCHITECTURE.md §6.2"IP 校验"条。
- 理由：若流程为"解析域名→校验 IP→httpx 按域名再次解析并连接"，攻击者可在两次解析间切换 DNS 应答（rebinding），绕过内网/云元数据阻断。评审意见要求的"实际 IP 校验"应闭环到实际连接。
- 修复建议：§6.2 补一句"校验通过后必须绑定该已校验 IP 建连（HTTP Host 头保留原域名），禁止连接时二次解析"，并在 M1-5 攻击用例中补 rebinding 用例（测试可注入 fake resolver）。

**M-4 并发恢复控制缺 fencing：被抢占的旧持有方无察觉与自杀机制**
- 位置：ARCHITECTURE.md §5.1"并发恢复控制"。
- 理由：version 乐观锁只保证 resume 请求恰有一个赢家；心跳过期被抢占后，若旧持有方实际仍存活（心跳延迟而非死亡），会继续派发调用——"同一任务同时只允许一个活跃执行"在抢占场景下可能被破坏为双活跃执行。
- 修复建议：§5.1 补"活跃执行在每次派发工具调用与状态写库时携带持有 version 做条件更新（CAS）；写失败即检测到被抢占，立即自行终止派发"，并将"抢占后旧执行方退出"纳入 M2-7 或新增用例。

**M-5 任务状态机缺 `paused → cancelled` 迁移**
- 位置：ARCHITECTURE.md §5 状态机图（`pending → running → (completed|failed|paused|cancelled)`、`paused → running`、`running → cancelled`）。
- 理由：任务因 uncertain 非幂等调用置 paused 等待确认期间，用户无法取消（只能 confirm 或 resume 后再取消）；`pending → cancelled` 亦未定义（刚创建未启动的任务无取消/删除路径）。SKILL 执行流程"状态机完整性"检查项不通过部分。
- 修复建议：v1.2 补 `paused → cancelled`（cancel 语义对 paused 任务同样适用，进行中无 running 调用则直接终态）；`pending → cancelled` 明确支持或声明"pending 任务以删除代替取消"。同步 §3 cancel 端点说明与 M2-8 判据。

### Minor（6 条）

**m-1 M2-5/M2-6/M2-8 验收命令非可直接执行形式；M2-5"自动 resume"语义含糊**
- 位置：ACCEPTANCE_CRITERIA.md M2-5/6/8（命令列为"集成测试：模拟…"描述性文字，无 pytest -k 选择器，违背文档头部"每条标准都附带可直接执行的验收命令"原则）；M2-5"重启→自动 resume"与 §3 手动 `POST /tasks/{id}/resume` 的触发关系未澄清（服务重启后是否自动扫描中断任务并发起 resume）。
- 修复建议：给出可执行选择器（如 `pytest tests/integration -k resume_uncertain`）；明确恢复触发方式（手动 resume 或启动时自动扫描，二选一写入 §5.1）。

**m-2 幂等性声明粒度三处表述张力**
- 位置：ARCHITECTURE.md §6.4（工具级单值 `idempotency`）vs §6.2（http_request"non-idempotent，其中 GET 视为幂等，注册表以方法参数区分"）vs §5.1 恢复矩阵 + M2-6（按调用级幂等性判定）。
- 理由：若注册表只能工具级声明单一值，GET 型 http_request 的 uncertain 自动重试判定依据（M2-6 用"GET 型 http_request"模拟幂等工具）无明确定义的"有效幂等性"计算规则。
- 修复建议：§6.4 补一句"恢复判定采用调用级有效幂等性 = 工具默认声明，可按参数规则覆写（如 http_request GET 覆写为 idempotent）；ToolCall 表的 idempotency 字段即该调用生效值的快照"。

**m-3 uncertain 幂等自动重试复用原调用 ID，与事件对齐语义存在渲染歧义**
- 位置：ARCHITECTURE.md §5.1（"原调用 ID 重新入 running"）vs §3.1/ADR-006（tool_call/tool_result 以 tool_call_id 对齐）。
- 理由：同一 tool_call_id 会产生第二轮 tool_call/tool_result 事件，前端时间线与 M2-3 断言"无重复"的语义需明确（m-3 与 M2-3b"无事件丢失、无重复"表述并列时尤甚）。
- 修复建议：§5.1 或 §3.1 注明"重试事件携带同一 tool_call_id + attempt 序号（或声明事件流允许同 ID 多轮事件），前端按最新一轮渲染"。

**m-4 cancel 后 uncertain 调用的"人工处置"无系统路径**
- 位置：ARCHITECTURE.md §5.1 cancel 节（"便于用户后续人工处置"）vs confirm API 仅服务 paused 任务、cancelled 为终态不可 resume。
- 理由：被取消任务中标记 uncertain 的非幂等调用，用户"处置"只能去系统外检查副作用，文档表述暗示系统支持但未定义路径。
- 修复建议：二选一——① 明确声明"cancelled 任务的 uncertain 调用不提供继续执行路径，仅结果摘要提示副作用未知"；② 补 `cancelled → paused`（受限迁移，仅存在 uncertain 调用时允许 confirm 续跑）。

**m-5 ROADMAP M2 未指明恢复语义实现归属 src/services/ 层**
- 位置：ROADMAP.md M2（恢复语义实现条目未指明模块）vs ARCHITECTURE.md §3（services 层注明"事务边界、checkpoint、恢复锁"职责）。
- 理由：Backend 照 ROADMAP 施工可能将 checkpoint/恢复锁写进 api 或 agent 层，触发 G-4 分层违规返工。
- 修复建议：ROADMAP M2 条目补"实现于 `src/services/`（编排层）"。

**m-6 ToolCall.seq 与 Step.seq 字段语义未定义；ToolCall.idempotency 用途未注明**
- 位置：ARCHITECTURE.md §5 数据模型。
- 理由：TaskEvent.seq 已定义清楚（每任务单调递增、storage 原子分配），但 Step.seq、ToolCall.seq 是否同一序号空间、由谁分配未说明；ToolCall 表携带 idempotency 的用途（建议注明为"调用时生效值快照"，与 m-2 联动）未注明，实现易产生歧义。
- 修复建议：§5 补两个字段的一句语义说明。

### Suggestion（7 条）

**S-1 IP 阻断段可进一步收紧**：§6.2 IPv4 未含 0.0.0.0/8、100.64.0.0/10（CGNAT）、224.0.0.0/4（多播）、255.255.255.255、198.18.0.0/15（基准测试段）；IPv6 未含 ::/128、2001:db8::/32 等。建议改为"仅允许公网单播地址"的白名单判定逻辑，或补充上述段。

**S-2 file_write 前缀校验与符号链接竞态**：§6.3 建议注明前缀匹配用路径组件边界（如 `Path.is_relative_to`），避免 "data/" 与 "data-evil/" 字符串前缀歧义；lstat 检查与 open 之间存在 TOCTOU，可注明"打开后对 fd 做校验（fstat）或使用 O_NOFOLLOW"作为实现提示。

**S-3 G-3 落入 check.sh 的实现注意**：check.sh 若启用 `set -e`，grep"退出码 1=通过"会中断脚本，需显式 if 判定退出码而非依赖链条；另正则会命中测试中占位符形态的假 key（如 `api_key = "sk-test-xxxx"`），测试 fixture 应使用明显非真实形态（如 `test-key-not-real`）并在 G-3 或 M1 备注豁免方式。

**S-4 M1-2 环境加载命令健壮性**：`export $(grep -v '^#' .env | xargs)` 对含空格/特殊字符的值不可靠，建议 `set -a; source .env; set +a`。

**S-5 M3-1 Playwright 依赖前置**：M3-1 允许"或 Playwright 脚本"，但 Playwright 不在 §2.1 白名单；若采用须先经 Architect 更新依赖清单，建议加括号注明此约束（或注明手动浏览器验收即满足）。

**S-6 AGENT_ROLES 变更记录**：v1.1 修订说明仅置于版本行，建议补独立"变更记录"节（与其余三份文档体例对齐）。

**S-7 E2E-3 命令健壮性**：`env -i PATH=$PATH` 会清空 HOME 等变量，pytest 缓存/临时目录可能因此报错产生假阴性；建议保留最小必要集（如 `env -i PATH=$PATH HOME=$HOME`）。

---

## 五、最终结论

# **有条件批准**

v1.1 对用户评审四项关键问题的修复**全部到位且证据充分**：断点恢复安全语义（含 uncertain 状态机、稳定 ID、checkpoint、幂等矩阵、paused+confirm、cancel、409 恢复锁，M2-5~M2-8 测试齐备）、工具安全边界（AST 白名单、SSRF 四层防护、沙箱三重防护、注册表强声明）、事件模型（五类收敛无 thought、seq/Last-Event-ID/final 三机制跨文档零矛盾）、验收反假阳性（G-5 拆分、G-3 阻断语义、M0 真测试、无 key 运行、真实调用断言）。六项硬约束全部通过，ADR-004/005/006 齐全，路径与版本表述一致。

**批准条件（须在 M0 启动前完成，均为文档级小修订，建议出 v1.2）：**

1. **[M-1]** 解决 G-2 与依赖白名单矛盾：§2.1 增补 pytest-cov（或改用 coverage 命令行并补依赖说明），同步 ROADMAP M0。
2. **[M-2]** 修复 check.sh 与 G-4/E2E-4 矛盾：check.sh 纳入分层检查，ROADMAP M0 补 check_layers 开发任务。
3. **[M-3]** §6.2 明确"校验通过的 IP 直接用于连接，禁止二次解析"，闭合 DNS rebinding 缺口。
4. **[M-4]** §5.1 补执行方 fencing 语义（派发/写库前 CAS 校验 version，被抢占即自行终止）。
5. **[M-5]** 任务状态机补 `paused → cancelled` 并明确 `pending → cancelled` 取舍。

**建议随 v1.2 一并处理（不作为批准条件）**：Minor m-1~m-6（其中 m-1/m-2/m-3 建议优先，直接影响 QA 执行与 M2 实现判定）；Suggestion 可延至对应里程碑。

条件满足并复核后即可进入 M0。本报告为唯一写入动作，未修改任何被评审文档。
