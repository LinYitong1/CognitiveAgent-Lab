# CognitiveAgent Lab

一个纯工程导向的 AI Agent 系统：理解用户目标，自主拆解任务，选择并调用工具（计算、HTTP 请求、文件写入），执行多步骤工作流，持久化任务状态，并通过 SSE 实时输出可观测的执行轨迹。

> 架构文档：[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（v1.2）｜ 路线图：[docs/ROADMAP.md](docs/ROADMAP.md) ｜ 验收标准：[docs/ACCEPTANCE_CRITERIA.md](docs/ACCEPTANCE_CRITERIA.md)

## 范围声明（重要）

**首版 Demo 展示的是多步骤工具执行能力（plan → tool → observe 循环），不是完整的论文研究助手。**

具体而言，首版包含：

- 真实 LLM 驱动的单 Agent 主循环（自研，约 300 行核心代码，非多 Agent 框架）
- 3 个安全边界内的工具：`calc`（AST 白名单表达式计算）、`http_request`（SSRF 防护）、`file_write`（沙箱目录写入）
- 任务状态持久化与断点恢复（含幂等性分级、uncertain 调用人工确认、恢复锁 fencing）
- SSE 公开事件流（`status | tool_call | tool_result | error | final`）与 Web 时间线可视化

**不包含**（Scope 外）：多 Agent 协作、RAG、接入 R 代码/认知模型/实验数据、用户认证体系。请以 Demo 实际展示的能力为准评估项目，勿预期论文级研究助手功能。

## 技术栈

Python 3.13 ｜ FastAPI ｜ Pydantic v2 + pydantic-settings ｜ SQLite ｜ SSE（原生 HTML/JS 前端）｜ 官方 `openai` SDK（真实 tool-calling，支持自定义 `base_url`）｜ pytest + pytest-asyncio + httpx ｜ pyright

运行时依赖完整清单与必要性见 [docs/ARCHITECTURE.md §2.1](docs/ARCHITECTURE.md)；除此之外不加依赖。

## 快速开始（占位）

> 本节为占位内容，将在 M0 脚手架落地后由 Backend Agent 补充实际命令。

```bash
# 1. 创建虚拟环境并安装依赖（待 M0 后补充具体命令）
# 2. 配置 .env（复制 .env.example，填入 OPENAI_API_KEY 或兼容端点）
# 3. 启动服务：uvicorn src.api.app:app --port 8000
# 4. 打开 http://localhost:8000 创建任务并查看执行轨迹
```

## 文档索引

| 文档 | 说明 |
|------|------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 技术架构 v1.2（含恢复/幂等性语义、工具安全规范、ADR-001~006） |
| [docs/ROADMAP.md](docs/ROADMAP.md) | 开发路线图 M0~M4 |
| [docs/ACCEPTANCE_CRITERIA.md](docs/ACCEPTANCE_CRITERIA.md) | 可执行验收标准（反假阳性） |
| [docs/AGENT_ROLES.md](docs/AGENT_ROLES.md) | 多角色协作（Architect/Backend/Frontend/QA）定义 |
