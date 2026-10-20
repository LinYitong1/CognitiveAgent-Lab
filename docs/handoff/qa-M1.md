# QA 验收报告 — M1（Agent 核心循环 + 工具安全）非真实 LLM 部分

> 验收人：QA Agent（docs/AGENT_ROLES.md §4）｜ 日期：2026-10-20
> 判据唯一依据：docs/ACCEPTANCE_CRITERIA.md **v1.2** M1 节 + 通用门禁
> 契约依据：docs/handoff/architect-m1-contract.md（冻结版）
> Backend 交接：docs/handoff/backend-m1.md
> 范围：M1-1 / M1-1b / M1-3 / M1-4 / M1-5 + 通用门禁 + 静态审查。**M1-2（真实 LLM）不在本轮**——待用户 key 配置确认后由 Lead 另行安排。
> 约束遵守情况：未修改任何产品代码与测试；未执行 git 操作；未联网调用真实 API。
> **版本说明**：初版结论"退回（局部）"（见下）；Backend 按 §三退回要求完成修复后，QA 按 §九口径复验通过，**最终结论见 §十：M1 非真实 LLM 部分通过（放行）**。原退回记录保留为审计轨迹。

---

## 最终结论（复验后更新）：**M1 非真实 LLM 部分：通过（放行）**

初版唯一阻断项 G-2 已消除：Backend 按退回要求**只补测试、零改动产品代码**（核实方式见 §十.1），QA 按 §九口径复验三项全绿，覆盖率 tools/ 78.35% → **91.45%**、agent/ 81.71% → **83.54%**（均 ≥ 80%）。新增 25 个用例（http 19 + registry 6）断言质量抽查合格，退回清单全覆盖且多处超出。以下初版结论与退回记录保留不删。

---

## 初版结论（2026-10-20，复验前）：退回（局部）——仅 G-2 覆盖率一项，功能与安全实现全部通过

| 维度 | 结果 |
|------|------|
| 验收命令（M1-1/1b/3/4/5） | **5/5 PASS** |
| 通用门禁（G-1/2/3/4/5a/5b） | 5 PASS + **1 FAIL（G-2：tools/ 78.35% < 80%）** |
| 安全实现源码审计 | **通过**（calc/http_request/file_write 与契约 §2 及 ADR-005 一致，无发现可利用缺陷） |
| 安全测试覆盖度审计 | **齐备**（契约 §3.2 清单全落地，多处超出）；附 1 个非阻断补测建议 |
| 7 项实现决策 | **7/7 接受**（其中 4 项建议 Architect 出契约勘误同步），另附 1 项超时语义观察提请确认 |
| 契约一致性抽查 | 通过（模型字段/事件五类/payload 字段名/Message 形态/run_agent 行为逐项一致） |
| M2 越界检查 | 无越界（无 SQLite/SSE/resume/cancel/confirm/checkpoint；src/api 保持 M0 /health 原样） |

**退回范围**：仅要求 Backend 补充 `tests/unit/test_http_request.py` 用例（chunked 响应体、EOF 读取、畸形响应/URL 错误分支），使 tools/ 行覆盖 ≥ 80%。补齐后**免全量重验**，QA 仅复跑 G-2 + 全量回归即可放行 M1 非真实 LLM 部分。

---

## 一、环境说明（先于逐项结果，影响判读）

| 项 | 实测情况 |
|----|----------|
| 沙箱 unlink/rename 拦截（预设） | **本会话未复现**：裸 `pytest`（含 FDCapture）、`--cov`、`compileall` 均实际可运行。对照命令：裸 `pytest tests/integration -k loop` → 4 passed, exit 0 |
| 等效口径 | 仍按指示以 `--capture=no -p no:cacheprovider` 执行全部 pytest 验收命令（与裸命令结果一致，已对照） |
| G-2 / G-5b 预设 ENV-BLOCKED | 因环境未拦截，**改为实际执行并记录真实结果**——其中 G-2 实跑暴露了 Backend 自验时无法发现的问题（见 FAIL 项） |
| 宿主 mkdir PermissionError 怪癖 | 本会话未复现（`_ensure_dir` 容错代码未触发，保留无害） |

---

## 二、逐项验收结果（命令 → 退出码 → 输出摘要 → 结论）

### M1 验收项

| ID | 实际命令 | 退出码 | 输出摘要 | 结论 |
|----|----------|--------|----------|------|
| M1-1 | `.venv/bin/python -m pytest tests/integration -k loop --capture=no -p no:cacheprovider` | 0 | `4 passed in 1.67s`（multistep / step_limit / tool_failure_not_fatal / llm_error_fails_task；step_limit 与 tool_failure 由 marker 命中） | **PASS** |
| M1-1b | `env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY CALC_AGENT_ENV_FILE=/dev/null .venv/bin/python -m pytest tests/integration --capture=no -p no:cacheprovider` | 0 | `4 passed in 1.64s`（双通道清理：进程环境无 key + /dev/null 绕开 .env） | **PASS** |
| M1-3 | `… pytest tests/integration -k tool_failure …` | 0 | `1 passed, 3 deselected` | **PASS** |
| M1-4 | `… pytest tests/integration -k max_steps …` | 0 | `1 passed, 3 deselected` | **PASS** |
| M1-5 | `… pytest tests/unit -k tool_security …` | 0 | `25 passed, 1 deselected in 1.65s`（calc 5 + file_write 5 + http_request 15，含参数化） | **PASS** |

### 通用门禁

| ID | 实际命令 | 退出码 | 输出摘要 | 结论 |
|----|----------|--------|----------|------|
| G-1 等效 | `.venv/bin/python -m pytest --capture=no -p no:cacheprovider`（全量） | 0 | `30 passed in 2.44s`（1 health + 4 loop + 21 unit） | **PASS(等效)** |
| G-2 | `.venv/bin/python -m pytest --cov=src --cov-report=term-missing` | 0（命令成功；**判据不达标**） | 30 passed；TOTAL 82%，但分目录：**agent/ 81.71%**（164 stmt / 30 miss）、**tools/ 78.35%**（351 stmt / 76 miss）、storage/ 0 stmt（M1 无代码，不适用）。tools/ 未达 ≥80% 门禁，整体 79.4% 亦不达标 | **FAIL** |
| G-3 | 命令块原样执行（grep + `rc=$?; [ "$rc" -eq 1 ]`） | 0 | `grep_rc=1`（src/ tests/ web/ 无硬编码密钥匹配） | **PASS** |
| G-4 | `.venv/bin/python -m scripts.check_layers` | 0 | `[PASS] 分层依赖检查通过：无反向 import` | **PASS** |
| G-5a | `.venv/bin/python -m pyright src/` | 0 | `0 errors, 0 warnings, 0 informations` | **PASS** |
| G-5b | `.venv/bin/python -m compileall -q src/` | 0 | 无输出（无语法错误）——本会话可实跑，未标 ENV-BLOCKED | **PASS** |

### 冒烟

| 项 | 实际命令 | 退出码 | 输出摘要 | 结论 |
|----|----------|--------|----------|------|
| run_agent 缺 key | `env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY CALC_AGENT_ENV_FILE=/dev/null .venv/bin/python examples/run_agent.py "test"` | **2** | stderr：`ERROR: no LLM API key configured — … (CALC_AGENT_ENV_FILE='/dev/null', default path: .env).`（契约 §1.5：明确报错、含 env 文件路径提示、不静默） | **PASS** |
| FakeLLM 端到端 | 由 M1-1 集成测试承载（真实 AgentLoop + 真实三工具 + FakeLLM，含真实文件产出与 JSONL 落盘断言）；交接文档未另提供独立冒烟入口 | 0 | 同 M1-1 | **PASS** |

---

## 三、G-2 FAIL 详述（退回项）

**判据**（ACCEPTANCE v1.2）：agent/ tools/ storage/ 行覆盖 ≥ 80%（自 M1 起生效）。

**实测**（`--cov-report=term-missing`，目录级精确计算）：

| 目录 | stmt | miss | 覆盖率 | 判定 |
|------|------|------|--------|------|
| agent/ | 164 | 30 | 81.71% | 勉强达标（registry.py 74%、llm.py 46% 拖低，loop.py 97% 拉高） |
| **tools/** | **351** | **76** | **78.35%** | **不达标** |
| storage/ | 0 | 0 | —（仅 `__init__`，M1 无代码，M2 起适用） | 不适用 |

**缺口定位**：`src/tools/http_request.py` 68%（182 stmt / 58 miss），未覆盖行集中在：
- `_read_body` chunked 模式（162–178）——**transfer-encoding: chunked 的真实响应形态完全未测**
- `_read_body` EOF 模式（196–205）
- URL 解析错误分支（131–139、147、153）
- 畸形响应解析（231、234–235）、连接清理（251–252）
- 超时路径（297–300）
- 默认 resolver/connector（84–88、97–106）——需真实网络，可接受不覆盖

**退回要求（Backend，唯一阻断项）**：
1. `tests/unit/test_http_request.py` 补充用例（全部可用现有 FakeReader/RecordingConnector 注入，无需联网）：
   - chunked 响应读取（正常 + 超限截断）
   - 无 content-length 读至 EOF + 截断
   - 畸形 status line / 畸形 content-length / 空 URL scheme / 无 hostname / 带 userinfo 的 URL
   - 连接抛 OSError（http_request: 连接错误回传）
   - （可选）FakeConnector 挂起触发 10s 超时——建议用 `asyncio.wait_for` 语义以短超时 monkeypatch 或接受跳过
2. 目标：tools/ ≥ 80%（当前 275/351，再覆盖约 6 行即达 80.06%；覆盖 chunked 段约 17 行可达 ~83%，建议按上述清单全补）。
3. 建议（非强制）：agent/registry.py 三条注册校验失败路径（空名/重复/非 async executor）补注册期测试，缓解 agent/ 勉强过线的脆弱性。

**复验口径**：补测后 QA 复跑 `pytest --cov=src --cov-report=term-missing` + 全量回归即可，其余项不再重验。

---

## 四、M1-1 集成测试断言质量核验（人工读源码）

`tests/integration/test_loop.py` 4 测试对照契约 §3.2：

| 契约断言要点 | 实测断言 | 判定 |
|--------------|----------|------|
| 步数上限 | `test_loop_step_limit`：max_steps=3，`fake.calls == 3`（FakeLLM 脚本耗尽会 AssertionError——loop.py 对 AssertionError 穿透不吞，双重保证恰 3 次） | ✓ |
| 事件序列无 thought | multistep 精确断言六元组 `[status, tool_call, tool_result, tool_call, tool_result, final]` | ✓ |
| seq 从 1 连续递增 | `[event.seq for …] == [1,2,3,4,5,6]` | ✓ |
| tool_call_id 稳定格式 call_XXXX | 成对相等断言 + 精确值 `call_0002`/`call_0004` | ✓ |
| final 必发 | 三条失败路径（step_limit / llm_error）末两条均 `[error, final]`，multistep 以 final 收尾 | ✓ |
| JSONL 与内存事件一致 | `lines == [event.model_dump(mode="json") …]` 逐行比对 | ✓ |
| 真实产出文件 | `(sandbox/"out.txt").read_text() == "result: 7"` | ✓ |
| M1-3 错误回传 | 第一轮 `tool_result.ok is False` 且 summary 含 BLOCKED；第二轮 messages 的 tool message `content.startswith("ERROR:")`；任务 completed；沙箱外无文件 | ✓ |
| LLM 不可恢复异常 | ExplodingLLM → failed + error + final | ✓ |

**结论**：断言质量高，无"跑通即过"的弱断言；marker（loop/max_steps/tool_failure/tool_security）与冻结名双保险，`-k` 选择器命中已实测（4/1/1/25）。

---

## 五、M1-5 安全测试覆盖度审计 + 安全实现源码核实（重点）

**审计方法**：不只信测试——逐行读三工具实现源码核实安全机制本身，再对照测试清单。

### 5.1 calc（实现 src/tools/calc.py + tests/unit/test_calc.py 5 用例）

| 审计项 | 实现 | 测试 | 结论 |
|--------|------|------|------|
| 无 eval/exec/compile 字符串执行 | ✓ `ast.parse` + 自实现白名单递归求值器 | —（G-3/grep + 源码核实） | ✓ |
| 名称注入（`__import__`/`open`/裸名） | Name 节点 fall-through 拒绝（L128） | 5 种表达式全断言 BLOCKED | ✓ |
| bool/字符串/None 常量 | Constant 显式排除 bool（int 子类陷阱）、非 int/float 拒绝 | `"True"` 用例覆盖 | ✓ |
| Attribute/Lambda/下标/条件表达式 | 白名单外一律拒绝 | `"''.join([])"`、`"(lambda:1)()"`、`"[1,2][0]"`、`"a if b else c"` | ✓ |
| 函数白名单 + 元数 | 六函数 + min/max/round 元数校验 | 名称注入用例覆盖函数面 | ✓ |
| keywords/starargs | 显式拒绝（L115-118） | —（白名单规则内） | ✓（实现核实） |
| 深度（结构性） | AST 递归深度 ≤20 | `"1+"*21+"1"` 深度 22 拒绝（契约示例之外的增强用例） | ✓ |
| 深度（括号） | max(AST 深度, 括号嵌套) | `"("*25+…` 拒绝 | ✓ |
| 长度 >200 | Pydantic Field（经 registry 统一入口验证） | 221 字符 → `invalid arguments` | ✓ |
| Pow 越界 | `_power` 统一检查（abs 指数>1000 / 复数 / inf），BinOp 与 pow() 共用 | `pow(10,10000)` → out of range | ✓ |
| 除零/domain 非 BLOCKED | 语义区分正确 | `1/0`、`sqrt(-1)` 断言无 BLOCKED | ✓ |

### 5.2 http_request（实现 src/tools/http_request.py + tests/unit/test_http_request.py 15 用例）

**实现核实（逐项）**：
- **resolve-then-connect**：`_validate_and_resolve` 返回首个已校验 IP 字符串；`connector(ip, …)` 直连该 IP，**全程无二次解析**——rebinding TOCTOU 在连接路径上不成立 ✓
- **Host 头原域名**：请求行 `Host: {hostname}`（L220），连接地址为 IP ✓（测试断言 `b"Host: example.com\r\n" in written[0]`）
- **HTTPS SNI/证书校验原域名**：`asyncio.open_connection(ip, port, ssl=create_default_context(), server_hostname=原域名)`——SNI 与 check_hostname 均以原域名进行；**无 verify=False**（默认 context 为 CERT_REQUIRED + check_hostname=True）✓（测试断言 `sni == "example.com"`）
- **全量 IP 校验**：`getaddrinfo` 全部地址逐一过 `_ip_allowed`（private/loopback/link_local/reserved/multicast/unspecified——显式覆盖 IPv4 四段 + 169.254.169.254 与 IPv6 ::1 / fc00::/7 / fe80::/10），任一违规整条拒绝 ✓
- **白名单先于 DNS**（精确匹配，无通配）✓；**userinfo 拒绝** ✓；scheme 白名单 ✓
- **重定向手动逐跳**：`follow_redirects` 不存在——30x 提取 Location（urljoin RFC 3986 相对解析）→ 下一跳重走完整链路（白名单+DNS+IP 校验全量）；≤3 跳 ✓
- **超时/大小**：每跳 `asyncio.wait_for(10s)`；1MB 三种读取模式（chunked/content-length/EOF）累计截断 + `truncated: true` 标注 ✓

**测试覆盖**：

| 用例（含参数化） | 断言要点 | 结论 |
|------------------|----------|------|
| 白名单放行 + resolve-then-connect 证据 | resolver 恰一次、连接 IP==已校验 IP、SNI==原域名、Host 头原域名、port 443 | ✓ |
| 私有 IP（192.168.1.1 / 10.0.0.5 / 172.16.31.4） | BLOCKED + **未建连**（connections==[]） | ✓ |
| 云元数据 169.254.169.254（白名单内放行后由 IP 校验阻断） | BLOCKED | ✓ |
| IPv6（::1 / fe80::1 / fc00::1） | BLOCKED | ✓ |
| 非白名单主机 | BLOCKED + **resolver.calls==[]**（白名单先于 DNS 证据） | ✓ |
| 混合 DNS 记录 [93.184.216.34, 10.0.0.1] | 整条 BLOCKED（防多记录 rebinding） | ✓ |
| 重定向→私有 IP | 第二跳未建连（重新走全链路被拒） | ✓ |
| 重定向循环/超限 | 恰 4 次连接后 BLOCKED: redirect | ✓ |
| **DNS rebinding（FakeResolver 两次不同结果）** | 恰解析一次 + 连接 IP==首次校验值 | ✓ |
| 1MB 截断 | `truncated: true` + body 恰 1MB | ✓ |
| 幂等声明覆写 | GET→idempotent / 缺省 GET / POST→non-idempotent | ✓ |

**结论：任务要求的安全用例全部齐备**（私有 IP 全段、云元数据、IPv6 三类、重定向逐跳重校验、DNS rebinding fake resolver、userinfo 诱骗——由实现 L138 的 `username/password is not None` 拒绝覆盖并经源码核实；字面量 IP 直填由云元数据用例承载）。

**非阻断 gap**（并入 G-2 退回补测）：chunked 读取、EOF 读取、畸形响应/URL 分支无测试（安全上由白名单兜底，功能上有回归风险）。

### 5.3 file_write（实现 src/tools/file_write.py + tests/unit/test_file_write.py 5 用例）

| 审计项 | 实现 | 测试 | 结论 |
|--------|------|------|------|
| `..` 穿越（段级，非子串误判） | `Path.parts` 逐段比较 + isabs（L44） | `../evil.txt`、`a/../../evil`、绝对路径 `/tmp/x`；沙箱外文件不存在断言 | ✓ |
| realpath + 组件边界前缀 | 已存在最深路径 realpath 后 `is_relative_to(sandbox_real)`（防 `data-evil` 前缀歧义） | 前缀混淆用例（symlink 指向沙箱外同前缀目录）→ `outside sandbox` | ✓ |
| 符号链接各级目录 lstat | 沙箱根起逐级 lstat（目录与目标文件本身均查，S_ISLNK 即拒） | 目录 symlink + 文件 symlink 两用例 → `symlink` | ✓ |
| 1MB 上限 | Pydantic 字符层 + executor UTF-8 字节复核 | 字符超限（registry 层 `invalid arguments`）+ 60 万宽字符 ≈1.2MB 字节（`content too large`）双层用例 | ✓ |
| 沙箱根配置 | `settings.data_sandbox_dir` | 测试沙箱根指向 `data/.test-sandbox/…` | ✓ |

**结论**：任务要求的四类用例（穿越/绝对路径/symlink 各级/超大内容）全部齐备且断言到具体错误语义。

---

## 六、7 项实现决策 QA 意见（backend-m1.md"契约偏离记录"逐项）

| # | 决策 | QA 意见 | 理由 |
|---|------|---------|------|
| 1 | ToolSpec 落 `src/models/tool_spec.py`（契约 §1.2 写 registry.py） | **接受**；建议 Architect 出契约勘误 | 契约自身矛盾：§1.2 位置 vs §2 工具模块构造 ToolSpec vs §4 禁 tools import agent，三者不可同时满足。按 §4"共享类型一律走 src/models/"消解是唯一自洽方案；签名逐字段一致（已核对：Literal 幂等/风险 + effective_idempotency 默认实现） |
| 2 | AgentLoop 增可选参数 `task_id` | **接受**；建议契约勘误 | 契约矛盾：§1.5 要求 CLI 在任务开始前打印 task_id，而 §1.3 task_id 生成在 run_task 内。可选参数不动冻结签名 `run_task(goal)`；QA 已核实 run_agent 首行 `task_id: <id>` 且与 JSONL 文件名一致（M1-2 提取依据） |
| 3 | `build_tool_spec(settings)` 代替模块级 TOOL_SPEC 常量 | **接受**；建议契约勘误 | 契约 §2 的 TOOL_SPEC 模块级常量无法闭包 settings（白名单/沙箱根）——又一处契约内部张力；统一签名（calc 忽略 settings）合理 |
| 4 | 手写最小 HTTP/1.1 客户端代替 SafeTransport(httpx) | **接受**（契约 §2.2 链路 4 明示"等价物"允许） | 四项硬性要求全满足并经源码+测试双重核实（连接 IP=已校验 IP、Host 原域名、SNI/证书校验原域名、无 verify=False）；Reader/Writer Protocol 注入点设计使 resolve-then-connect 可被测试证明。**附观察 A**：超时为**每跳** 10s（3 跳最多 30s）vs 契约字面"总超时 10.0s"——提请 Architect 确认口径（非安全缺陷，建议按"每跳"更新契约或改为总预算）。**附观察 B**：手写客户端不支持 HTTP/2/gzip/真实 chunked 形态——真实外网兼容性留待 M1-2/E2E-1 实测（届时若 example.com 响应异常，归因点在此） |
| 5 | calc 深度 = max(AST 节点深度, 括号嵌套深度) | **接受** | 契约示例 `"("*25+…` 纯 AST 计数无法拒绝（括号不产生节点）——该消解忠实于契约示例意图，且实现为"取 max"而非"只查括号"，结构性深链同样拦截（已有测试用例证明） |
| 6 | `-k` 选择器经 pytest marker（冻结名不动） | **接受** | 测试函数名与 §3.2 冻结名逐一一致（已核对）；marker 为实现手段，pyproject 已注册，四个选择器命中经 QA 实测（4/1/1/25） |
| 7 | 测试文件名 `test_loop.py` | **接受** | 契约 §3.2 原文即此名，任务描述中的 test_agent_loop.py 为口误 |

**小结**：7 项均属契约内部矛盾/明示等价物的合理消解，无一项改变冻结的接口签名、事件格式或安全语义；其中 #1/#2/#3 建议 Architect 以勘误形式回写契约（避免 M2 阅读时再起歧义），#4 附带的超时口径请 Architect 一并确认。

---

## 七、其他静态审查结果

### 7.1 契约一致性抽查（逐项核对通过）

- 共享模型五件套字段与契约 §1.0 **逐字段一致**：ToolCallRequest(remote_id/tool_name/arguments)、LLMResponse(content/tool_calls/finish_reason)、AgentEvent(type/seq/ts/payload)、ToolResult(ok/result/error)、AgentResult(task_id/status/result/steps/events)
- 事件五类型枚举无 thought（ADR-006）✓；payload 字段名与契约表一致（status{status,reason} / tool_call{tool_call_id,tool_name,args_summary} / tool_result{tool_call_id,ok,result_summary} / error{message} / final{status,result_summary}）✓；摘要统一截断 512（`_SUMMARY_LIMIT` 应用于 args_summary/result_summary/error/final）✓
- `tool_call_id = call_{seq:04d}`（取该 tool_call 事件 seq）✓；seq 任务级从 1 单调递增 ✓；事件**先落 JSONL 再入内存/回调**（loop.py emit 顺序）✓
- Message 三形态 + tool message `ERROR:` 前缀回传契约 ✓
- LLMClient：key 空不抛错（调用方校验）、base_url or None、timeout/max_retries 透传、arguments JSON 解析失败 → LLMProtocolError、异常原样上抛 ✓
- run_agent：缺 key stderr + exit 2（实测）、首行 task_id、结束 status/result（截断 512）、退出码 0/1/2、sys.path 注入 ✓
- `build_registry(settings)` 于 src/agent/__init__.py 注册三工具 ✓
- `HTTP_ALLOWED_HOSTS` 默认 `example.com`（config.py）——**E2E-1 前置条件已由 M1 落实** ✓

### 7.2 分层合规与 M2 越界

- G-4 门禁实跑通过（无反向 import）；源码复核：tools/ 无 import src.agent（ToolSpec 经 models 传递）、loop 无 api/services/storage import ✓
- M2 越界 grep（sqlite3/CREATE TABLE/text/event-stream/EventSource/resume/cancel/confirm/checkpoint/fencing，扫 src/ + examples/）：**无匹配** ✓
- `src/api/app.py` 保持 M0 /health 原样 ✓；事件仅 JSONL 无 DB ✓；`tests/unit/test_health.py` M0 原样 ✓
- 依赖白名单：pyproject 与 venv 实际安装核对——顶层依赖恰为 §2.1 白名单（fastapi/uvicorn/pydantic/pydantic-settings/httpx/openai + dev: pytest/pytest-asyncio/pytest-cov/pyright），其余均为传递依赖；**未新增白名单外依赖** ✓

---

## 八、遗留与风险

| # | 事项 | 归属 | 状态 |
|---|------|------|------|
| 1 | **G-2 退回**：补 http_request 单元测试（chunked/EOF/畸形分支），tools/ ≥ 80% | Backend | **阻断 M1 放行**；补齐后 QA 复跑 G-2 + 全量回归即可 |
| 2 | M1-2 前置条件：用户 key 配置确认（OPENAI_API_KEY 或 ANTHROPIC_API_KEY + 可选 LLM_BASE_URL/LLM_MODEL），QA 在用户环境执行 M1-2 命令块 | Lead → 用户 | 待安排 |
| 3 | 超时语义口径（每跳 10s vs 契约"总超时 10s"）与 3 处契约勘误（ToolSpec 位置/task_id 参数/build_tool_spec） | Architect | 建议随 M2 契约制定时一并回写 |
| 4 | 手写 HTTP 客户端真实外网兼容性（gzip/HTTP-2/真实 chunked 形态）——M1 测试全部不联网，未暴露 | M1-2/E2E-1 实测 | 风险登记：若真实请求异常，归因点在 src/tools/http_request.py 手写协议层 |
| 5 | http_request 默认 resolver/connector（15 行）依赖真网，M1 无法覆盖（可接受） | M1-2 实测覆盖 | 登记 |
| 6 | 测试产物残留（data/.test-sandbox/、logs/agent-*.jsonl）已被 .gitignore 覆盖 | 无害 | 已确认 |
| 7 | 环境怪癖（unlink 拦截、mkdir PermissionError）本会话未复现；等效口径命令保留在 backend-m1.md 备查 | 环境 | 登记 |

---

## 九、复核清单（Backend 修复后 QA 复验口径）

1. `pytest tests/unit -k tool_security --capture=no -p no:cacheprovider` —— 新增用例随 marker 命中
2. `pytest --cov=src --cov-report=term-missing` —— tools/ ≥ 80%（agent/ 不回退）
3. `pytest --capture=no -p no:cacheprovider`（全量回归）—— 0 failed
4. （如 Backend 改动了 src/）加跑 `python -m scripts.check_layers` + `python -m pyright src/`

> 复验通过即出具 M1 非真实 LLM 部分最终放行意见；M1-2 待用户 key 环境另行执行。

---

## 十、复验记录（G-2 退回修复后，2026-10-20）

> 依据：Backend 修复交接（backend-m1.md"覆盖率退回修复"节：+19 http 用例、+6 registry 用例，声明产品代码零改动）+ 本报告 §九复验口径。

### 10.1 产品代码零改动核实

git index 异常不可用，改用三路源码核对：

| 核对路径 | 结果 |
|----------|------|
| 修复节改动文件清单 | 仅 `tests/unit/test_http_request.py`（追加）、`tests/unit/test_registry.py`（新建）、`test_loop.py`/`test_file_write.py`（fixture 类型标注 `Path → Iterator[Path]`，generator fixture 标注修正，非行为变更）+ 交接文档本身——**无 src/ 文件** ✓ |
| 源码内容抽查（对比 QA 初版审计记录） | `src/tools/http_request.py` 前 60 行（模块结构、常量、Protocol 定义）与初版逐行审计记录**完全一致**；`calc.py`/`file_write.py`/`loop.py`/`registry.py`/`tool_spec.py` 均与初版审计内容一致（含关键安全实现点：`_validate_and_resolve` 返回已校验 IP、`_ip_allowed` 六属性拒绝、`is_relative_to` 组件边界、`lstat` 逐级、`call_{seq:04d}`、final 必发）✓ |
| mtime 抽查 | src/ 全部 .py 的 mtime（16:24–17:26）均落在 Backend M1 交付时段内，晚于该时段无修改痕迹；tests/ 新文件时间符合修复批次 ✓ |

**结论：产品代码零改动成立**，符合退回要求"只补测试不改产品代码"，未触发全量重验条件。

### 10.2 复验三项（§九口径，真实命令、退出码、输出）

| # | 实际命令 | 退出码 | 输出摘要 | 结论 |
|---|----------|--------|----------|------|
| 1 | `.venv/bin/python -m pytest -k tool_security --capture=no -p no:cacheprovider` | 0 | **44 passed, 11 deselected in 2.11s**（原 25 + 新增 http 19 全部命中 tool_security marker） | **PASS** |
| 2 | `.venv/bin/python -m pytest --cov=src --cov-report=term-missing --capture=no -p no:cacheprovider` | 0 | **55 passed**；TOTAL 90%（598 stmt / 58 miss）——`.coverage` 落盘本会话未被拦截，无需 COVERAGE_FILE 变通。目录级精确计算见下表 | **PASS** |
| 3 | `.venv/bin/python -m pytest --capture=no -p no:cacheprovider`（全量回归） | 0 | **55 passed in 2.54s**（原 30 + http 19 + registry 6；0 failed / 0 error） | **PASS** |

**G-2 判据复核（§九第 2 项，目录级）**：

| 目录 | 修复前（初版实测） | 复验实测 | 判据 ≥ 80% | 判定 |
|------|--------------------|----------|------------|------|
| **tools/** | 78.35%（351/76） | **91.45%**（351 stmt / 30 miss） | ✓ | **达标**（http_request.py 68% → 93%，未覆盖行仅剩 84–88/97–106 默认 resolver/connector——初版 §三明示需真实网络、可接受，留待 M1-2） |
| **agent/** | 81.71%（164/30） | **83.54%**（164/27） | ✓ | 达标且**不降反升**（registry.py 74% → 82%，由新增 registry 用例贡献） |
| storage/ | 0 stmt（仅 `__init__`） | 0 stmt | — | 不适用（M1 无代码，M2 起生效） |

复验数字与 Backend 自验记录（91.45% / 83.54% / 55 passed）**逐项一致**。

### 10.3 新增用例质量抽查

**test_http_request.py 新增 19 用例**（文件累计 34，文件级实跑 34 dots 吻合）对照初版 §三退回清单：

| 退回清单要求 | 对应用例 | 断言质量核验 |
|--------------|----------|--------------|
| chunked 正常读取 | `test_http_reads_chunked_body` | 3-chunk 拼接内容断言 + 无 truncated ✓ |
| chunked 超限截断 | `test_http_chunked_truncation` | `truncated: true` + body 精确 1MB 长度断言 ✓ |
| 无长度头读至 EOF | `test_http_reads_body_to_eof` | body 内容断言 + **额外**：请求行 `GET /path?q=1` 精确断言（覆盖 L153 path?query 拼接）✓ |
| EOF 超限截断 | `test_http_eof_truncation` | 精确 1MB 长度断言 ✓ |
| 畸形 status line | `test_http_rejects_malformed_status_line`（参数化 3：空响应/缺码/非数字） | 断言 `http_request: ` 前缀且**非 BLOCKED**——功能错误与安全拒绝语义区分正确 ✓ |
| 畸形 content-length | `test_http_rejects_malformed_content_length` | 具体错误消息断言 ✓ |
| URL 错误分支 | `test_http_rejects_bad_urls`（参数化 5：scheme×2/无 hostname/**userinfo**/端口超范围） | 每例断言 BLOCKED + 具体 reason + **未建连**（connections==[]）✓ |
| 连接 OSError | `test_http_connection_oserror` | 结构化错误 `http_request: OSError: connection refused` + 非 BLOCKED ✓ |
| 超时路径 | `test_http_timeout` | **采纳初版建议的 monkeypatch 短超时方案**（TIMEOUT_SECONDS=0.05），HangingConnector 内置 `AssertionError("should be cancelled")` 反向断言——超时若不生效测试必失败，非空转用例 ✓ |
| （清单外补充） | writer 清理失败忽略 / 空 DNS 结果 BLOCKED / 畸形 chunk size / content-length short read 提前 EOF | 4 例均具体断言（含"已读部分仍返回"的短读语义）✓ |

**test_registry.py 新增 6 用例**（对应初版 §三非强制建议项）：空名/重复名/非 async executor 拒绝（`pytest.raises` + match 具体消息）、非 BaseModel input_model（pydantic 构造期 ValidationError——用例注释正确说明 register 的 issubclass 为不可达第二道防线）、idempotency/risk_level Literal 构造期校验 ×2、get_schemas 导出格式（逐字段断言）——断言全部真实。

**抽查结论**：无空断言、无恒真断言；全部新增用例带 `@pytest.mark.tool_security`（复验 1 的 44 passed 命中证明）；退回清单 9 类要求全覆盖 + 4 类超出。**质量合格**。

### 10.4 复验最终判定

| 项 | 判定 |
|----|------|
| 复验 1（-k tool_security） | PASS（44 passed，exit 0） |
| 复验 2（G-2 --cov） | **PASS**（tools/ 91.45% ≥ 80%、agent/ 83.54% ≥ 80%、55 passed，exit 0） |
| 复验 3（全量回归） | PASS（55 passed，exit 0） |
| 产品代码零改动 | 核实成立 |
| 新增用例质量 | 合格（断言真实、清单对应、marker 命中） |

**M1 非真实 LLM 部分：最终结论为通过（放行）。**

- 初版全部 PASS 项（M1-1/1b/3/4/5、G-1/3/4/5a/5b、冒烟、静态审查）不受影响，继续有效；
- G-2 由 FAIL 转 PASS（数字见 10.2）；
- 遗留事项不变：M1-2 待用户 key 配置确认（Lead 安排）；3 处契约勘误 + 超时口径提请 Architect（随 M2 契约回写）；手写 HTTP 客户端真实外网兼容性留待 M1-2/E2E-1 实测归因。

> 后续：Lead Orchestrator 可凭本报告安排 M2（持久化 + API + 恢复语义）启动；M1-2 在用户 key 环境补验后闭环。
