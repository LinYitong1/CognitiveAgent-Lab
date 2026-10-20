# CognitiveAgent Lab — 验收标准（可执行）

> 版本：v1.0 ｜ 原则：每条标准都附带**可直接执行的验收命令**，QA 逐条运行并附实际输出。

## 通用门禁（每个里程碑、每次合入）

| ID | 标准 | 验收命令 | 通过判据 |
|----|------|----------|----------|
| G-1 | 测试全绿 | `bash scripts/check.sh` | pytest 退出码 0 |
| G-2 | 覆盖率 | `pytest --cov=src --cov-report=term` | agent/ tools/ storage/ 行覆盖 ≥ 80% |
| G-3 | 无硬编码密钥 | `grep -rniE "(sk-[a-z0-9]{8,}|api[_-]?key\s*=\s*[\"'][^\"']+)" src/ tests/ web/ \|\| echo CLEAN` | 输出 CLEAN |
| G-4 | 分层依赖正确 | `python -m scripts.check_layers`（M0 提供） | 无反向 import 报告 |
| G-5 | 类型检查 | `python -m pyright src/ 2>/dev/null \|\| python -m compileall -q src/` | 退出码 0 |

## M0 — 脚手架

| ID | 标准 | 验收命令 | 通过判据 |
|----|------|----------|----------|
| M0-1 | 服务可起 | `uvicorn src.api.app:app --port 8000 &` 后 `curl -sf localhost:8000/health` | 返回 `{"status":"ok"}` |
| M0-2 | 测试骨架 | `pytest` | 0 failed（可 0 collected） |
| M0-3 | 配置从环境读取 | 删掉 `.env` 中 key 后启动 | 服务仍可起（key 仅调 LLM 时需要） |

## M1 — Agent 核心循环

| ID | 标准 | 验收命令 | 通过判据 |
|----|------|----------|----------|
| M1-1 | FakeLLM 循环集成测试 | `pytest tests/integration -k loop` | 全绿，断言步数上限、事件序列 |
| M1-2 | 真实 LLM 多步任务 | `export $(grep -v '^#' .env \| xargs) && python examples/run_agent.py "计算 (123*456)/7 并把结果写入 out.txt"` | exit 0；out.txt 内容正确；终端打印 ≥ 2 次工具调用轨迹 |
| M1-3 | 工具失败不致命 | `pytest tests/unit -k tool_failure` | 工具异常被捕获并回传 LLM，任务不悬挂 |
| M1-4 | 步数上限 | `pytest tests/integration -k max_steps` | 超限时 Task.status=failed，原因记录在案 |

## M2 — 持久化 + API

| ID | 标准 | 验收命令 | 通过判据 |
|----|------|----------|----------|
| M2-1 | 状态即写库 | `pytest tests/unit -k storage` | 每次状态变更有对应记录 |
| M2-2 | 断点恢复 | 启动任务→中途 `kill -9` 服务→重启→`curl -sf -X POST localhost:8000/tasks/<id>/resume` | 任务从 checkpoint 续跑并完成 |
| M2-3 | SSE 事件流 | `curl -sfN localhost:8000/tasks/<id>/events`（任务运行时） | 依序收到 thought/tool_call/tool_result 事件 |
| M2-4 | API 契约 | `curl -sf localhost:8000/openapi.json` | schema 与 ARCHITECTURE.md §3 一致 |

## M3 — 前端

| ID | 标准 | 验收命令 | 通过判据 |
|----|------|----------|----------|
| M3-1 | 端到端可视化 | 浏览器（或 Playwright 脚本）创建任务 | 时间线实时渲染 ≥ 2 个工具调用事件与最终结果 |
| M3-2 | 无前端报错 | 浏览器 console | 0 error |

## M4 — 端到端验收（项目级）

| ID | 标准 | 验收命令 | 通过判据 |
|----|------|----------|----------|
| E2E-1 | 真实 LLM 全链路 | `python examples/run_agent.py "用 http_request 获取 example.com 标题，calc 统计字符数，结果写入 report.txt"` | 三类工具均被真实调用；report.txt 内容合理 |
| E2E-2 | 轨迹可回放 | `python -m cli.replay <task_id>` | 完整事件序列与 DB 记录一致 |
| E2E-3 | 无 key 环境健壮 | `env -i PATH=$PATH pytest tests/e2e` | e2e skip 而非 error，其余全绿 |
| E2E-4 | G-1~G-5 全量门禁 | `bash scripts/check.sh` | 全部通过 |

## 验收报告模板

QA 在 `docs/handoff/qa-<里程碑>.md` 输出：每条 ID → 实际命令输出摘要 → 通过/失败 → 失败归因与退回对象。
