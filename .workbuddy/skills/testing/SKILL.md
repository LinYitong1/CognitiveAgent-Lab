---
name: testing
description: CognitiveAgent Lab 的测试工程技能。当需要为新功能编写 pytest 用例、搭建/更新测试夹具（fake LLM、临时数据库）、运行回归测试、排查失败用例，或对 Agent 行为做端到端验证时触发。适用于"写测试 / 跑测试 / 测试挂了 / 验收某个功能"类请求。
agent_created: true
---

# Testing

## Overview

为 CognitiveAgent Lab 建立并维护分层测试体系（单元 / 集成 / 端到端），保证 Agent runtime 行为可验证、可回归。

## 触发条件

- 任何新模块/新工具合入前（配套用例必须同步交付）。
- 用户要求运行测试或验证某个里程碑的验收标准。
- 测试失败需要定位，或需要更新过时用例。

## 测试分层

| 层级 | 位置 | 覆盖对象 | 依赖 LLM？ |
|------|------|----------|-----------|
| 单元测试 | `tests/unit/` | 工具 executor、Pydantic 模型、状态机流转、存储层 | 否 |
| 集成测试 | `tests/integration/` | Agent 主循环（用 FakeLLM 注入预设 tool-call 序列）、FastAPI 端点、持久化恢复 | 否（FakeLLM） |
| 端到端 | `tests/e2e/` | 真实 LLM 跑通完整任务 | 是（无 key 时自动 skip） |

## 执行流程

1. **选择层级**：按被测对象查上表；先单元后集成，能用 FakeLLM 就不打真实 API。
2. **使用标准夹具**（`tests/conftest.py` 提供）：
   - `fake_llm`：按脚本返回预设 tool-call / 文本响应，用于确定性验证循环逻辑。
   - `tmp_db`：临时 SQLite，隔离状态测试。
   - `api_client`：FastAPI TestClient。
3. **编写用例**遵守：
   - 一个用例只验证一个行为；命名 `test_<行为>_<预期>`。
   - 每个工具至少 1 个成功用例 + 1 个失败用例（错误输入、异常抛出）。
   - Agent 循环用例必须断言：步数上限生效、状态被持久化、事件日志完整。
   - 端到端用例开头检查 `OPENAI_API_KEY`/`ANTHROPIC_API_KEY`，缺失则 `pytest.skip`。
4. **运行**：`pytest -v --tb=short`；定位失败时先读 traceback 与相关日志事件，再最小化复现。
5. **报告**：输出通过/失败数、失败原因归类（代码缺陷 / 用例过时 / 环境问题）与修复建议。

## 验收标准（本 Skill 的交付标准）

- 全量 `pytest` 通过，或失败项均有明确归因与修复建议。
- 覆盖率不回退：`pytest --cov=src --cov-report=term`，核心模块（agent/、tools/、storage/）行覆盖 ≥ 80%。
- 新增用例符合分层表定位，不引入对真实 LLM 的非必要依赖。
- 端到端用例在无 key 环境下优雅 skip 而非报错。
