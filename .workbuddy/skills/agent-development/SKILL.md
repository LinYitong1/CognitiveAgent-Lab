---
name: agent-development
description: CognitiveAgent Lab 的 Agent 运行时开发技能。当需要实现或修改 Agent 核心循环（理解目标→拆解任务→选择工具→执行→保存状态→产出日志）、注册新工具（tool schema / executor）、实现任务持久化或 FastAPI 接口时触发。适用于所有 runtime/src 目录下的编码任务，以及"给 Agent 加一个工具 / 修改执行循环 / 增加一个 API 端点"类请求。
agent_created: true
---

# Agent Development

## Overview

按项目架构规范实现 CognitiveAgent Lab 的 Agent runtime 代码：主循环、工具注册、状态持久化、API 层，确保实现为真实 LLM 驱动而非静态模拟。

## 触发条件

- 实现/修改 Agent 主循环（planner、executor、工具选择逻辑）。
- 注册新工具（定义 tool schema + executor + 单元测试）。
- 实现/修改任务状态持久化（SQLite/JSON 存储、恢复逻辑）。
- 实现/修改 FastAPI 端点或 Pydantic 模型。

## 执行流程

1. **前置检查**：
   - 确认 `docs/ARCHITECTURE.md` 已获用户批准（未批准前只做脚手架，不做大规模编码）。
   - 确认在项目 venv 中工作：`/Users/linyitong/.workbuddy/binaries/python/envs/default/bin/python`（或项目自建 venv）。
2. **遵循分层结构**（严格依赖方向）：
   ```
   api/        FastAPI 路由，只做参数校验与调度
   services/   业务编排，不直接调 LLM
   agent/      Agent 核心：主循环、planner、tool registry
   tools/      工具实现：每个工具 = Pydantic 输入模型 + executor 函数
   storage/    状态持久化（任务、步骤、日志）
   models/     共享 Pydantic schema
   ```
3. **实现 Agent 主循环**时必须满足：
   - LLM 调用走统一的 `LLMClient`（从环境变量读取 `OPENAI_API_KEY` 或 `ANTHROPIC_API_KEY` 及 base URL/model 名）。
   - 每步循环产出结构化事件（thought / tool_call / tool_result / observation）写入日志。
   - 循环有最大步数与超时保护，防止无限循环。
4. **注册新工具**时必须交付三件套：`tools/<name>.py`（实现）、tool schema（给 LLM 的 JSON 描述，从 Pydantic 模型自动生成）、`tests/test_<name>.py`（至少含一个成功用例 + 一个失败用例）。
5. **状态持久化**：任务与步骤状态变更即写库，保证进程重启后可恢复。
6. **收尾**：运行 `pytest` 全量回归，确认无失败后交付，并在回复中列出改动文件。

## 验收标准（本 Skill 的交付标准）

- 新增代码有对应 pytest 用例，`pytest` 全绿。
- 无硬编码密钥；所有外部配置经 `os.environ` / pydantic-settings 读取。
- Agent 行为由 LLM tool-calling 驱动，可用真实 API key 运行 `examples/run_agent.py` 端到端验证。
- 每个执行步骤可从日志文件/API 回放完整轨迹。
- 改动文件清单完整列在交付说明中。
