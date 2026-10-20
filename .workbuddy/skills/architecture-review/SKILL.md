---
name: architecture-review
description: CognitiveAgent Lab 项目的架构评审技能。当用户或团队需要评审 docs/ARCHITECTURE.md、评价新模块的架构设计、审查接口规范（Pydantic schema / FastAPI route 契约）、评估技术选型（LLM runtime、状态存储、工具注册机制）是否符合项目约束时触发。适用于任何"这个设计合理吗 / 这个改动会不会破坏架构 / 更新架构文档"类请求。
agent_created: true
---

# Architecture Review

## Overview

对 CognitiveAgent Lab 的架构决策、模块边界、接口契约进行结构化评审，输出问题清单与改进建议，保持 docs/ARCHITECTURE.md 与代码实现一致。

## 项目硬约束（评审时逐条核对）

1. 技术栈限定：Python 3.13 + FastAPI + Pydantic v2 + pytest。
2. 必须使用真实 LLM Agent runtime（真实 tool-calling 循环），禁止用静态规则/if-else 模拟 Agent。
3. 不引入多 Agent runtime（不用 LangGraph/CrewAI/AutoGen 等重框架，单一主循环 + 自研轻量编排）。
4. 外部 API 密钥只经环境变量（`.env` + `os.environ`）读取，禁止硬编码或写进仓库。
5. Agent 状态必须可持久化（任务可中断、可恢复）。
6. 每个功能必须有可执行的验收方式（pytest 用例或脚本）。

## 触发条件

- 新增/修改模块、数据模型或 API 端点前。
- 用户要求"评审架构 / 检查设计 / 这个方案行不行"。
- 里程碑完成时（对照 docs/ARCHITECTURE.md 做一致性检查）。
- 任何引入新依赖的提议。

## 执行流程

1. **读取基线**：读 `docs/ARCHITECTURE.md` 与 `docs/ACCEPTANCE_CRITERIA.md`，建立评审基准。
2. **收集变更**：读待评审的设计文档/diff/代码，列出变更点。
3. **分层评审**，按顺序检查：
   - 分层违规（route → service → agent core → tools 的依赖方向是否正确，禁止跨层 import）。
   - 数据模型（Pydantic schema 是否覆盖输入校验、状态序列化、错误响应）。
   - 状态机完整性（任务状态流转是否有非法迁移路径）。
   - 可观测性（每个执行步骤是否产出结构化日志事件）。
   - 密钥与配置（是否有硬编码密钥、配置是否走 `settings.py`）。
   - 依赖最小化（新依赖是否必要，是否可用标准库/已有依赖替代）。
4. **输出评审报告**：按 `Blocker / Major / Minor / Suggestion` 分级，每条含位置、理由、修复建议。
5. **更新文档**：若评审通过且设计有变，同步更新 `docs/ARCHITECTURE.md` 并在变更记录节注明日期。

## 验收标准（本 Skill 的交付标准）

- 评审报告覆盖上述 6 项硬约束，每项给出"通过/不通过/不适用"结论。
- 所有 Blocker 问题有具体修复建议和涉及文件路径。
- 若架构文档被修改，版本号（文档头部）递增且变更记录有对应条目。
- 评审结论明确：`批准 / 有条件批准（列出条件）/ 驳回（列出理由）`。
