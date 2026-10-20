# Ollama 本地模型接入 M1-2：环境就绪与兼容性评估报告

> 评估人：Lead Orchestrator ｜ 日期：2026-10-20 ｜ 性质：**只读评估，未安装任何软件、未下载模型、未发起任何调用、未修改任何代码**
> 依据：本机硬件探测（只读命令）+ M1 源码逐行核对（src/agent/llm.py / loop.py / registry.py / src/config.py / examples/run_agent.py）+ Ollama OpenAI-compatibility API 公开规格

## 1. 硬件检查结果（只读探测）

| 项目 | 结果 | 判定 |
|------|------|------|
| macOS | 26.2（Build 25C56） | ✅ 支持 |
| 芯片 | Apple M3（arm64） | ✅ 原生支持 Ollama Apple Silicon 版 |
| 内存 | 16 GB（探测时系统空闲约 38% ≈ 6 GB） | ⚠️ 可跑 7B 级（q4 量化），14B 不建议 |
| 磁盘 | 根分区可用 152 GB | ✅ 充裕（7B 模型约 4.7 GB） |

## 2. 推荐模型（tool calling 可靠性 × 资源占用）

| 优先级 | 模型 | 磁盘/内存占用 | 理由 |
|--------|------|--------------|------|
| **首选** | `qwen2.5:7b` | ~4.7 GB / 运行 ~5-6 GB | Qwen2.5 官方 tool calling 支持、Ollama 生态实测最稳的 7B 级之一；16GB 内存余量合理 |
| 备选 | `qwen3:8b` | ~5.2 GB | 更新、能力更强，但带 thinking 模式，content 可能混入思考文本，对 M1-2 断言干扰略高 |
| 兜底 | `qwen2.5:3b` | ~1.9 GB | 内存吃紧时用，但 3B 级 function-calling 可靠性明显下降，M1-2 一次通过率低 |

不建议 14B（q4 约 9GB，加 KV cache 在 16GB 机器上与 WorkBuddy/浏览器并存会触发内存压力换页，反而拖慢推理）。

## 3. M1 LLMClient × Ollama OpenAI 兼容 API 兼容性核对（逐项）

M1 请求面（`LLMClient.chat` → `AsyncOpenAI.chat.completions.create`）：

| 检查项 | M1 现状 | Ollama `/v1/chat/completions` 支持 | 结论 |
|--------|---------|-----------------------------------|------|
| 调用模式 | 非流式（一次 create，等完整响应） | 支持非流式（genie-baas 的流式强制问题不存在于 Ollama） | ✅ |
| `tools` 参数 | 标准 OpenAI 格式 `{type:"function", function:{name, description, parameters}}`（registry.get_schemas） | 支持；qwen2.5 系列为 tools-capable 模型 | ✅ |
| `parameters` JSON Schema | Pydantic `model_json_schema()` 导出；M1 三工具输入均为扁平字段（str/Literal），无嵌套 `$defs` | 简单 schema 完全支持（`title` 等附加键被忽略） | ✅ |
| tool_call 返回解析 | 读 `choice.message.tool_calls[].id / function.name / function.arguments`（JSON 字符串） | 近期 Ollama 版本返回标准结构与 `call_xxx` 形式 id；arguments 为 JSON 字符串 | ✅（要求 Ollama ≥ 0.3，装最新版即满足） |
| tool_call_id 回传 | assistant 消息带 `tool_calls[].id` + tool 消息带同值 `tool_call_id`（loop.py:103/143 均用 `call.remote_id`，两侧一致） | 支持该消息序列；id 两侧一致即可通过校验 | ✅ |
| 工具结果回传 | `{"role":"tool", "tool_call_id":..., "content":"结果或 ERROR: 前缀"}` | 支持 role=tool 消息 | ✅ |
| `finish_reason` | 读 `tool_calls` / `stop` | 一致 | ✅ |
| 额外参数扫描 | **仅发 model / messages / tools 三个参数**——无 temperature、无 tool_choice、无 parallel_tool_calls、无 response_format、无 strict | 请求面为 Ollama 兼容子集 | ✅ 无不支持参数 |
| 认证 | `AsyncOpenAI(api_key=..., base_url=...)`；`run_agent.py:30` 要求 key 非空 | Ollama 不校验 key 但 openai SDK 要求非空 → 填占位值 `ollama` 同时满足两边的非空要求 | ✅ |
| base_url 切换 | `settings.llm_base_url` 非空即生效（ADR-002），`.env` 配置即可 | `http://localhost:11434/v1` 为官方推荐用法 | ✅ M1 零改动 |

**结论：M1 代码与 Ollama OpenAI 兼容端点完全兼容，接入仅需配置 `.env`，无需改任何代码。**

## 4. 兼容性风险（不改代码前提下的运营级风险）

| 风险 | 说明 | 缓解措施（零代码改动） |
|------|------|----------------------|
| **R1 默认上下文窗口偏小（主要风险）** | Ollama 默认 num_ctx 约 2k-4k token；M1-2 全程（system + goal + 三工具 schema 约 600+ token + 3-8 轮消息累积 + 工具结果）可能超出，导致早期消息被截断、多轮后工具调用质量下降 | 启动 Ollama 时设环境变量 `OLLAMA_CONTEXT_LENGTH=8192`（Ollama ≥0.5.13 支持，全局生效，无需改请求参数） |
| R2 单轮推理时长 | 7B q4 在 M3 上约 20-40 tok/s；单轮 5-25s，含长参数 JSON 或最终总结可能更久。M1 默认 timeout=60s + SDK 重试 2 次 | 测试期间关闭重负载应用（浏览器多标签等）释放内存；若个别轮次超时，SDK 自动重试兜底 |
| R3 7B 模型 function-calling 成功率 | 弱于 GPT-4 级：可能出现参数格式错、漏调工具、提前总结 | M1-2 判据不放宽（失败即重跑，本地零成本）；goal 措辞明确（"先计算…再写入文件…"）可显著提高一次通过率 |
| R4 tool_call id 为空（旧版 Ollama） | 极旧版本 id 返回空字符串 | 安装最新版 Ollama 即规避 |

## 5. 官方安装与配置指引（待批准后执行）

**安装（官方方式，二选一）：**
```bash
# 方式一：官网下载 macOS(Apple Silicon) 版 App（ollama.com/download/mac），拖入 Applications
# 方式二：Homebrew 官方 cask
brew install --cask ollama
```

**拉取模型（~4.7 GB 下载）：**
```bash
ollama pull qwen2.5:7b
```

**带 8k 上下文启动服务（R1 缓解）：**
```bash
OLLAMA_CONTEXT_LENGTH=8192 ollama serve    # 终端前台方式；或 App 方式启动后验证 env 生效
```

**项目 `.env` 配置（唯一需要的项目侧变更，M1 代码零改动）：**
```env
CALC_AGENT_ENV_FILE=.env
OPENAI_API_KEY=ollama
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=qwen2.5:7b
CALC_AGENT_MAX_STEPS=25
HTTP_ALLOWED_HOSTS=example.com
DATA_SANDBOX_DIR=data
```

**安装后验证顺序（我执行，均为零成本本地操作）：**
1. `curl -s http://localhost:11434/v1/models` → 确认模型在列
2. 一次最小 tool-calling 冒烟（单轮、单工具，确认 id/arguments 解析正常）
3. 等你单独授权 → 执行 M1-2 受限测试（范围不变：1 次运行、3-8 轮往返、calc+file_write 各 ≥1 次、断言不放宽）

## 6. 红线遵守声明

本次评估未安装软件、未下载模型、未调用任何 LLM（云端/本地均未）、未使用 WorkBuddy 内部凭据、未修改 M1 代码、未放宽 M1-2 验收标准、未启动 M2/Phase A。
