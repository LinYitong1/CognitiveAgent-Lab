# PA-14 复验报告 — R1 修复（工具自描述补全）后的真实 LLM Demo

- **执行窗口**：2026-10-20 19:40–20:05 GMT+1 ｜ 执行：Lead Orchestrator
- **依据**：用户批准的 PA-14 修复选项 A + 本轮五条执行要求
- **结论：PA-14 复验未通过（0/3 次完成工具调用，更无 Bundle 导出）。按指令停止重试，不更换模型、不修改 AgentLoop，保留全部真实记录。**
- **重要新发现**：A/B 对照诊断表明 R1 修订在本机栈（qwen2.5:7b + Ollama 0.40.6）上**使工具调用发射断裂**——旧 description 2/2 次正常发起工具调用，新 description 0/4 次（详见 §4）。这是超出预期的负面结果，如实报告。

---

## 1. R1 修复实施与 QA 结论（修复本身合格）

| 环节 | 内容 | 结果 |
|------|------|------|
| Architect | 契约 §5.1 修订记录 R1：validate_experiment description 追加结构摘要 + 反包装指令 + 最小完整示例（619 字符）；示例经实际 `ExperimentSpec.model_validate` + `validate_spec` 预验证（valid=true，0 错误 0 警告）；冻结 4 条修订约束（常量单一来源/一致性测试/示例与 Demo 任务刻意不同/token 预算） | 完成 |
| Backend | `_SPEC_EXAMPLE_JSON` 模块级常量 + description 重写（1385 字符，软预算 ≤1600 内）；新增 `tests/unit/experiment/test_tool_description_example.py` 4 项测试 | 完成 |
| QA | ① 独立探针确认示例确实进入发送给 LLM 的 tools schema（registry.get_schemas() 反向提取并校验）；② 示例与 Pydantic schema 一致（valid=true）；③ 确定性不变（黄金 Bundle 重生成逐字节一致 + verify CLI exit 0）；④ git diff 仅 3 文件（契约修订 + experiment_tools.py + 新测试），无越界 | **全部通过** |
| 回归 | 126/126（122 原有 + 4 新增）、pyright 0 errors、check_layers PASS | 全绿 |

**修复 commit**：`79a7cac`。R1 在其自身验收范围内完全合格——问题出在修复假设被真实模型行为证伪（§4）。

## 2. 三次官方 Demo 运行记录（判据未降低，全部独立记录）

环境：Ollama 0.40.6 @ `127.0.0.1:11434/v1`，qwen2.5:7b；**每次运行前显式预热**（curl 小请求触发加载），`/api/ps` 确认 **context_length: 8192 生效**、模型驻留 VRAM 后立即运行。无外部自动修正、无人工补写工具调用、入口 `examples/run_experiment_agent.py` 冻结 goal 未动。

| Run | task_id | 结果 | 事件轨迹 |
|-----|---------|------|----------|
| 1 | task-0cf9ca68db4b | completed（形式）| 2 事件：status(running) → final(completed, result="")。**零 tool_call、零 tool_result** |
| 2 | task-80775532d18d | completed（形式）| 同上，零工具调用 |
| 3 | task-79df7c3a0fec | completed（形式）| 同上，零工具调用 |

**PA-14 判据核对**：① exit 0 + completed 形式满足；② stdout 无 bundle/指纹行 ❌；③ 无 Bundle 可验 ❌；④ validate≥1/generate≥1/export==1 全部 =0 ❌。**未通过，标准未放宽。**

事件日志保全：`logs/agent-task-{0cf9ca68db4b,80775532d18d,79df7c3a0fec}.jsonl`。

## 3. 与修复前（R0）失败模式的对比

| | R0（修复前 5 次） | R1（修复后 3 次） |
|---|---|---|
| 失败模式 | B 为主：模型**主动发起** validate_experiment 调用（小体积、错误包装 `inputs`/`experimentSpec`）×2；A 超时 ×2；C 空响应 ×2 | **C 全面化：3/3 首轮零工具调用、空 content** |
| 工具调用发射 | 存在（结构错误） | **完全消失** |
| 模型是否生成内容 | 是（带错误包装的调用） | **是**——原始 API 显示 completion_tokens≈237，但 content=""、tool_calls=null（生成了约 237 token 的产物被解析层丢弃） |

## 4. A/B 对照诊断（只读探针，不计入官方 Demo；证据链）

用与 AgentLoop 完全相同的请求载荷（同 system prompt、同 goal、同 tools schema）直接请求 `/v1/chat/completions`，唯一变量是 validate_experiment 的 description：

| 组 | 采样 | 结果 |
|----|------|------|
| **旧 description**（R1 前冻结文本，探针内联构造） | 2 | **2/2 正常发起 `validate_experiment` 工具调用** |
| **新 description**（R1，含示例） | 2 | 0/2（1 次 ReadTimeout + 1 次 EMPTY，ct=236）|
| 新 description（官方 Demo 路径） | 3 | 0/3 EMPTY |

**根因判定（有证据支撑的机制推断）**：R1 的示例成功教会了模型正确的 spec 结构——模型从"发起小体积但结构错误的调用"转变为"尝试在工具参数中内联完整正确的 spec（~236 token 的大 JSON）"。但 **qwen2.5:7b 在 Ollama 0.40.6 的工具调用解析路径上，这种更长的参数 JSON 发射失败**：原始响应 finish_reason=stop、content=""、tool_calls=null，而 completion_tokens≈237 证明模型确实生成了内容——产物被解析层静默丢弃（服务端日志不可访问，无法进一步定位是模板渲染还是 JSON 解析失败）。

**结论：R1 修复方向（结构可发现性）本身被验证有效——模型确实不再猜错结构；但它暴露并放大了更深的一层瓶颈：本机栈对大参数工具调用的解析能力。失败模式从 B（结构错误）转移为 C（发射被丢弃）。**

## 5. 处置选项（待用户决策，本轮未实施）

| 选项 | 内容 | 预期 |
|------|------|------|
| **C-1. 接受现状**（原选项 C） | PA-14 记"qwen2.5:7b + 本机 Ollama 栈不可达成"；系统正确性由 PA-8 FakeLLM 背书（126/126 全绿）；Phase A 以此缺口申请关闭或留待更强模型 | 零改动 |
| **C-2. R1 保留 + 登记** | R1 保留不回退（QA 已证其自身合格且无回归；对更强模型反而有益——结构可发现性是通用改进），PA-14 处置同 C-1 | 零改动 |
| **C-3. 回退 R1** | git revert `79a7cac`，恢复旧 description | 恢复失败模式 B，无进展，不建议 |
| **R2. 缩小示例**（需新批准） | Architect 修订：示例 spec 缩到极小（如单因素 2 水平、1 block、2 试次），把内联 JSON 的 token 量降到旧模式成功案例的量级 | 可能避开解析瓶颈，但牺牲示例代表性，成功率未知 |
| **E. 环境路径**（需新批准） | 升级 Ollama / 换 OpenAI-compat 网关（如 llama.cpp server）/ 等更强本地模型 | 不改产品代码；验证成本一次性 |

**Lead 建议：C-2**（R1 保留 + PA-14 按"模型/栈能力边界"正式登记，Phase A 凭 PA-1~13 + FakeLLM 全链路申请有条件关闭；R2/E 列入 Phase B 前置可选项）。

## 6. 边界遵守声明

- 三次 Demo 均为冻结入口 + 冻结 goal + R1 提交后代码（`79a7cac`），无运行间改动；
- 诊断探针只读（直接 HTTP 请求，不改任何代码、不注入消息、不补写工具调用）；
- 未更换模型、未修改 AgentLoop/LLMClient/工具实现；
- 达到 3 次上限即停，未无限重试；
- 本轮未启动 Phase B / M2 / M3 / GameSpec / 网页游戏 / MCP。

—— 报告提交即止。等待用户对 PA-14 处置与 Phase A 关闭的裁定。
