# M1-2 真实 LLM 全链路测试报告

> 运行时间：2026-10-20 18:00 UTC（本地 19:00 GMT+1）｜ 执行：Lead Orchestrator ｜ 独立核查：QA Agent（`qa-M1-2.md`）
> 结论速览：**M1-2 通过**——判据 ①②③ 全部满足，单次运行零重试，M1 产品代码零改动。

## 1. 运行配置

| 项 | 值 |
|----|----|
| 模型 | qwen2.5:7b（本地 Ollama，`/api/ps` 确认 ctx=8192 实际生效） |
| 端点 | `http://127.0.0.1:11434/v1`（OpenAI 兼容，非流式） |
| 认证 | 占位 key `ollama`（`.env`，已确认被 gitignore） |
| 任务 | 计算 (123 * 456) / 7，并将结果写入 out.txt |
| 任务 ID | `task-3a3879b0db2b` |
| 运行约束 | 单次运行、不重试；http_request 禁用；步数/超时/安全规则不放宽 |

### 入口偏差声明（透明记录）

`examples/run_agent.py` 经 `build_registry` 固定注册全部三工具，无法满足本轮授权的"禁用 http_request"，且 M1 产品代码冻结不可修改。故创建 **M1-2 专用测试入口 `examples/run_agent_m12.py`**（新增文件，零产品代码改动）：复用真实 `LLMClient`/`AgentLoop`/`ToolRegistry`/`ToolSpec`，仅将注册表限定为 calc + file_write——http_request **结构性不进入 tools schema**，模型无法调用。

QA 审计意见：**接受**（最小侵入方案、满足"产品代码冻结"+"禁用 http_request"双约束、与正式判据命令的执行路径等价）。建议后续（M2 契约回写时）为 run_agent.py 增加工具集配置能力——已列入遗留项。

## 2. 运行结果

```
$ .venv/bin/python examples/run_agent_m12.py "计算 (123 * 456) / 7，并将结果写入 out.txt。"
task_id: task-3a3879b0db2b
status: completed
steps: 3
result: 计算结果 (123 * 456) / 7 = 8012.571428571428 已写入 out.txt。
EXIT_CODE=0
```

模型轮次：3 轮（Round1 发起 calc → Round2 发起 file_write → Round3 给出最终答案），为该任务的理论最小轮次。
时间线：18:00:24 启动 → 18:00:35 calc → 18:00:44 file_write → 18:00:53 final（每轮 8.7–11.3s，符合本地 7B 推理延迟）。

## 3. 实际 Tool Call Trace（事件日志原文）

来源：`logs/agent-task-3a3879b0db2b.jsonl`（logs/ 被 gitignore，原文在此保全）

| seq | 时间 (UTC) | 事件 | 关键内容 |
|-----|-----------|------|----------|
| 1 | 18:00:24.583 | status | running / task started |
| 2 | 18:00:35.851 | tool_call | `call_0002` · **calc** · `{"expression": "123 * 456 / 7"}` |
| 3 | 18:00:35.867 | tool_result | `call_0002` · ok=true · `8012.571428571428` |
| 4 | 18:00:44.783 | tool_call | `call_0004` · **file_write** · `{"content": "8012.571428571428", "path": "out.txt"}` |
| 5 | 18:00:44.848 | tool_result | `call_0004` · ok=true · `wrote out.txt (17 bytes)` |
| 6 | 18:00:53.555 | final | status=completed · 计算结果 (123 * 456) / 7 = 8012.571428571428 已写入 out.txt |

事件流合规：仅 `status/tool_call/tool_result/final` 四类（无 thought）；seq 单调 1–6；tool_call_id 为稳定 `call_{seq:04d}` 格式；final 必发；事件先落盘再继续。**http_request 调用次数 = 0**（schema 结构性缺席 + 事件日志零记录双确认）。

## 4. out.txt 内容与数值校验

- 文件：`data/out.txt`（17 字节，mtime 19:00:44 本地，落在 seq4/5 执行窗口内；file_write 沙箱将相对路径 `out.txt` 解析至 `data/` 内）
- 内容：`8012.571428571428`
- QA 独立复算：`123 × 456 = 56088`；`repr(56088 / 7) = '8012.571428571428'`——与 tool_result 事件、out.txt 内容**三方逐字符一致**，且为 calc 真实输出格式（Python float repr），排除硬编码冒充。

## 5. M1 验收项目最终汇总

| ID | 标准 | 结果 | 证据 |
|----|------|------|------|
| M1-1 | FakeLLM 循环集成 | ✅ 通过 | `qa-M1.md`：4 passed（步数上限/事件序列/call_XXXX/final 必发/无 thought） |
| M1-1b | 无 key 集成（双通道清理） | ✅ 通过 | `qa-M1.md`：`env -u … CALC_AGENT_ENV_FILE=/dev/null` 全绿 |
| **M1-2** | **真实 LLM 多步任务** | ✅ **通过（本报告）** | ① exit 0；② tool_call 事件数 2 ≥ 2、工具种类 2（calc+file_write）；③ out.txt 与复算逐字符一致 |
| M1-3 | 工具失败不致命 | ✅ 通过 | `qa-M1.md`：异常捕获、ERROR 前缀回传 LLM |
| M1-4 | 步数上限 | ✅ 通过 | `qa-M1.md`：超限终止语义正确 |
| M1-5 | 工具安全边界 | ✅ 通过 | `qa-M1.md`：44 个攻击用例全绿（注入/私有 IP/云元数据/重定向/DNS rebinding/路径穿越/符号链接） |
| G-1~G-5b | 通用门禁 | ✅ 通过 | 用户本地验收：check.sh 六项全 PASS；pytest 55 passed；coverage tools/ 91.45%、agent/ 83.54%；pyright 0 errors |

**M1 全部验收项（含真实 LLM）至此全部通过。**

## 6. 模型兼容性限制（QA 评估）

- 无阻断级问题；本次 steps=3 为理论最小值，参数精确、content 忠实转写 calc 结果
- 已知限制（`ollama-m1.2-readiness.md` + 本次实证）：ctx 8192 生效；单轮 9–11s；模型空闲 5 分钟后卸载，冷启动首轮约 +14s（E2E-1 前建议预热）
- qwen2.5:7b 可靠性系**单样本观察**；未来 E2E-1（三工具链）仍需监控 function-calling 稳定性

## 7. 遗留项（不阻断 M1）

1. run_agent.py 工具集配置能力（本轮受限入口的长期解）——建议 M2 契约回写时处理
2. 受限入口与正式判据命令的偏差需在 ACCEPTANCE_CRITERIA 变更记录中登记
3. check.sh node 路径硬编码（既有小改进项）
4. 旧 `~/.ollama` 遗留目录（qwen2:7b/llama3.2，用户历史数据，保持不动）
