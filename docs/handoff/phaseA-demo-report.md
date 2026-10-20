# Phase A — PA-14 真实 LLM Demo 运行报告

> 运行窗口：2026-10-20 19:10–19:45 GMT+1 ｜ 执行：Lead Orchestrator ｜ 依据：`architect-phaseA-contract.md` §9 / PA-14
> **结论：PA-14 未达成（0/5 次运行完成导出）。PA-1~PA-13 全部通过且不受影响。失败根因已定位并归因为模型侧能力边界 + 工具自描述设计代价，修复路径已列出待用户决策。**

## 1. 运行环境

| 项 | 值 |
|----|----|
| 模型 | qwen2.5:7b（本地 Ollama 0.40.6，ctx 8192） |
| 端点 | `http://127.0.0.1:11434/v1`（占位 key） |
| 入口 | `examples/run_experiment_agent.py`（契约 §9 冻结 goal，一字未改） |
| 工具集 | validate_experiment / generate_trials / export_experiment（契约 §9.1 裁定，无 calc） |
| 运行策略 | AgentLoop 内部自然迭代；无外部自动重试循环（多次运行为透明记录，见 §3） |

## 2. PA-14 判据核对

| 判据 | 要求 | 结果 |
|------|------|------|
| ① | exit 0 且 status: completed | ⚠️ run 2/4/5 满足形式（见 §3 失败模式 B/C） |
| ② | stdout 含 `bundle:` 行 + 双指纹（64 hex） | ❌ 5 次运行均无 |
| ③ | `python -m src.experiment.verify <bundle>` exit 0 | ❌ 无 Bundle 可验 |
| ④ | 事件序列 validate ≥1、generate ≥1、export ==1、final=completed | ❌ validate 达标（每有效运行 ≥1）；**generate=0、export=0** |

**PA-14：未通过。**

## 3. 五次运行完整记录（全部如实保留）

| Run | task_id | 结果 | 失败模式 |
|-----|---------|------|----------|
| 1 | task-096fc733a517 | failed（APITimeoutError） | **环境 A**：模型空闲卸载后冷加载，超过 LLMClient 60s×3 重试窗口 |
| 2 | task-53393ecf55c7 | completed（形式） | **模型 B**：2 轮 validate 均 SCHEMA_INVALID（spec 被包在 `"inputs"` 包装层内，顶层缺 name/seed/factors）；错误消息已列出全部缺失字段，模型第二轮未采纳修正，输出反思文本终止——export=0 |
| 3 | task-96f2efbcbec5 | failed（APITimeoutError） | **环境 A**：同 Run 1（Run 2 审计期间模型再次空闲卸载） |
| 4 | task-9f01913cd076 | completed（形式） | **模型 C**：首轮即返回空 content 且无 tool_calls（AgentLoop 按设计判定 completed，空答案也是"最终答案"） |
| 5 | task-d869e575f8c5 | completed（形式） | **模型 B+C 复合**：1 轮 validate SCHEMA_INVALID（`"experimentSpec"` 错误包装）+ 空响应终止 |

事件日志保全：`logs/agent-task-<id>.jsonl`（5 份，gitignore 内，关键内容已摘录于本报告）。

环境 A 的缓解已验证有效：显式预热（小请求触发加载）+ 确认 `/api/ps` 后立即运行——Run 4/5 均无超时。**环境问题可完全工程化解决，不是本报告的核心问题。**

## 4. 根因分析（模型侧为核心瓶颈）

### 4.1 工具 schema 暴露不足（设计代价，已知取舍）

`validate_experiment` 的 input_model 为宽松 `config: object`（契约 §5 两级错误契约的必然选择——强类型输入会在 registry 层被 Pydantic 拦截，无法返回结构化 `SCHEMA_INVALID` 报告）。代价：**模型在 tools schema 中完全看不到 ExperimentSpec 的内部结构**，只能凭 goal 自然语言描述猜测，然后靠错误消息试错。

工具 description（契约 §5.2 冻结文本）不含结构示例。模型三次猜测三种错误结构（`inputs` 包装 / `experimentSpec` 包装 / 直接散字段），全部失败。

### 4.2 错误消息质量良好但 7B 利用能力不足

Run 2 第一轮 tool_result 实际返回了**全部缺失字段列表**（name/seed/factors/…，每条含 path 与 suggestion），并非只报第一个错。但 qwen2.5:7b 第二轮未将内容从包装层提升到顶层——对结构性反馈的利用能力是硬瓶颈。对照：M1-2 中同一模型对简单扁平参数（calc 的 expression）的工具调用一次成功——**差距在嵌套深、字段多的 schema 构建**。

### 4.3 系统能力与模型能力的边界（重要结论）

- **系统侧全链路正确**：PA-8 FakeLLM 集成测试证明了完整的"验证失败 → 修正 → 通过 → 生成 → 导出 → 指纹验证"循环在 AgentLoop 上真实可运行；本轮 Run 2/5 中 validate_experiment 对错误 spec 的结构化拒绝（多字段错误、path、suggestion、engine_spec_version）也全部按契约工作
- **失败全部发生在"模型构造正确 spec"这一环**——这是模型能力边界，不是引擎缺陷
- AgentLoop 的 `completed` 语义（模型不再调用工具即终止）按 M1 设计工作；空响应/反思文本被判定为最终答案是已知语义（M1 契约），非缺陷

## 5. 修复路径选项（待用户决策，未擅自实施）

| 选项 | 内容 | 代价/影响 | 预期效果 |
|------|------|-----------|----------|
| **A. 契约微调：工具自描述补全** | validate_experiment 的 description 增加 ExperimentSpec 顶层结构摘要（字段名+类型+最小示例），属 Phase A 契约修订（非 M1 接口） | 需修订契约 §5.2 并同步 QA 复核；PA-14 判据不变（不放宽） | 预计显著提高 7B 成功率——模型不再猜结构 |
| B. 换更强模型 | qwen3:8b（风险：thinking 文本干扰）或 14B（16GB 内存不建议）或未来更强本地模型 | 需重新拉模型 + 重跑冒烟 | GPT-4 级模型可凭错误迭代自行修复（两级错误契约的设计初衷） |
| C. 接受现状 | PA-14 记为"qwen2.5:7b 能力受限未达成"；系统正确性由 PA-8 背书；Demo 留待更强模型接入时补验 | Phase A 验收留缺口 | 无 |

**Lead 建议：选项 A**（工程正当性：工具 description 的职责就是让调用方知道输入格式，当前 description 对复杂结构确实自描述不足；这不是放宽验收——所有 PA-14 判据保持原样，模型仍需真实完成 validate→generate→export→指纹验证全链路）。

## 6. 遗留风险登记

1. Ollama 冷启动（空闲 5 分钟卸载）：所有未来真实 LLM 测试前需预热（已写入实践；LLMClient 超时 60s 不可配——M1 冻结，预热是零改动缓解）
2. 模型空响应（Run 4/5 模式 C）：AgentLoop 判定 completed 的语义对空答案不设防——M2 恢复/重试语义设计时可考虑（不改 M1）
3. Run 2/5 显示 `previous_errors` 防死循环协议未被模型主动使用（契约 §6 的无状态协议依赖模型传参）——7B 不会主动带，框架层不计后果但也没兜底消费它；Phase B 可评估框架侧指纹记忆
