# M1-2 前置能力核查：WorkBuddy 内置模型 API 可用性评估

> 核查人：Lead Orchestrator ｜ 日期：2026-10-20 ｜ 性质：**只读核查，未执行任何真实 LLM 调用、未提取任何凭据、未修改任何代码**
> 依据：cloud-service 官方技能文档（SKILL.md + references/llm/code-generation.md）、genie-baas 工具 schema、M1 源码（src/agent/llm.py、src/config.py）、本机只读探测

## 1. WorkBuddy 内置模型 API（genie-baas / 云服务 LLM 模块）现状

| 维度 | 事实 |
|------|------|
| 是否存在 | 存在。WorkBuddy 云服务四模块之一（免密钥 LLM 调用），面向 WorkBuddy 构建的 **web 应用/微信小程序** |
| Endpoint | 应用发布域名下 `/.cloud/llm/chat/completions` 数据面路径（来自 activate 时 publicConfig.endpoint） |
| 认证方式 | 应用级 `publishableKey` + 服务器**强制 Origin 精确匹配**（web）/ 请求域名白名单（小程序）；平台密钥全部留在服务端不下发 |
| 官方客户端 | **仅 JS SDK**（`@tencent-ai/workbuddy-cloud-sdk`，npm / CDN / 小程序三种形态），无官方 Python SDK |
| 前置条件 | 必须先为本工作区激活一个云服务应用（wbapp_ 前缀 applicationId，UI 确认对话框授权，有配额/计费属性）。**当前工作区无 applications.yaml，未注册任何应用** |
| tool calling | 协议层支持 OpenAI 风格 tool_calls delta（模型目录含 `supportsToolCall` 能力标识，是否可用取决于具体模型） |
| 流式约束 | **仅支持流式**（`stream: true` 强制；非流式请求在发出前即被 SDK 拒绝：`request_stream_required`）；首条消息必须是应用侧 system 消息 |
| 额度 | 平台侧管理（quota_ 错误族、rate limit、credits 展示信息），无公开的绝对额度数字 |

## 2. 与 CognitiveAgent Lab 独立 Agent Runtime 的兼容性判定：**不兼容，不推荐**

1. **无 Python 通道**：官方仅 JS SDK；文档明令禁止手工拼接 `/.cloud/llm/*` 路径、禁止 BFF/服务端代理模式、禁止浏览器外使用平台 token。本地 Python 进程绕过 SDK 直连属于未支持接口。
2. **Origin 强制匹配**：认证为浏览器 Origin（或小程序域名白名单）设计，本地 Python CLI 无 Origin 概念，直连会被 `auth_` 类错误拒绝。
3. **流式强制 vs M1 非流式**：M1 `LLMClient` 使用 `AsyncOpenAI.chat.completions.create()` 非流式调用；genie-baas 流式强制 → 接入需改 M1 代码（已冻结，禁止）。
4. **不可移植**：应用专属通道（绑定 wbapp_ 应用与会话），与"独立、开源、可公开部署"的产品定位冲突——不能作为开源项目的模型接入方案推荐给第三方用户。
5. **激活副作用**：需要新建云服务应用并经 UI 授权，带配额/计费属性，与"不产生付费调用"的约束存在冲突风险。

**结论：会话内部模型调用（本 Agent 自身、MCP 云服务工具）与可移植外部 API 是两个世界——前者绑定 WorkBuddy 会话/应用，无法作为本地 Python 项目的模型后端。**

## 3. M1 LLMClient 的接入兼容面（零改动验证）

`src/agent/llm.py` 的 `LLMClient` 经 `Settings` 读取 `openai_api_key` / `llm_base_url` / `llm_model`，`base_url` 非空即切换端点（ADR-002 兼容端点设计）。**任何"非流式可用的 OpenAI 兼容端点"均可经 `.env` 零改动接入**，无需重写 Agent Loop。

## 4. 可行方案对比

| 方案 | 成本 | 是否需 key | M1 零改动 | 可移植/开源复现 | 评级 |
|------|------|-----------|-----------|---------------|------|
| **A. 本地 Ollama**（OpenAI 兼容端点 `http://localhost:11434/v1`） | 免费（需装 Ollama ~1GB + 模型 4~7GB 下载） | 否（key 填占位值即可） | ✅ | ✅ 开源用户可完整复刻 | **推荐** |
| B. 免费额度 OpenAI 兼容云服务（如智谱 GLM-4-Flash 等免费档模型） | 免费（需注册外部账号领取 free key） | 是（free key 入 .env） | ✅ | ✅（用户各自注册） | 备选 |
| C. WorkBuddy genie-baas | 平台配额内 | 应用级（不可外用） | ❌ 需改 M1（流式） | ❌ 不可移植 | 不推荐 |

本机探测（2026-10-20 18:30）：Ollama 未安装（`which ollama` 未命中、11434 端口无监听、/Applications 无相关 App）；LM Studio 同样未安装。

**方案 A 落地路径（待批准后执行）**：安装 Ollama → `ollama pull` 一个 tool calling 能力可靠的模型（建议 qwen2.5:7b 或 qwen3:8b 级别，M1-2 要求 tool_call ≥2 次且 ≥2 种工具，小模型成功率低）→ `.env` 配 `LLM_BASE_URL=http://localhost:11434/v1`、`LLM_MODEL=<模型名>`、`OPENAI_API_KEY=ollama`（占位）→ 用户单独授权后执行 M1-2 受限测试（范围不变：1 次运行、3-8 轮往返、calc+file_write 各 ≥1 次、零云端费用）。

**方案 A 风险提示**：本地 7B 级模型的 function-calling 可靠性弱于 GPT-4 级，单次运行可能失败需重跑（每次成本为零，可接受）；M1-2 判据（工具调用次数/种类断言 + 产出内容交叉校验）不因模型而放松。

## 5. 红线遵守声明

本次核查未提取 WorkBuddy 内部 Token/Cookie/会话凭据；未使用未公开接口或逆向工程；未修改 M1 代码；未产生任何付费调用；未执行真实 LLM 测试。
