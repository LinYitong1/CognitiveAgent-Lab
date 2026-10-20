# CognitiveAgent Lab — 环境能力审计报告

> 审计时间：2026-10-20 ｜ 审计人：Lead Engineering Orchestrator ｜ 版本：v1.0

## 1. 工作区状态

| 项目 | 结论 |
|------|------|
| 当前工作区 | `~/WorkBuddy/2026-10-20-15-47-28/`，**全新空目录**，无任何现有代码 |
| 原有游戏项目 | 位于同级兄弟目录（如 `2026-10-17-13-55-38/` 含 GDD、godot-mystery、mystery-dinner、GBA 原型；`2026-10-17-16-16-18/` 含经济模拟脚本），**全部只读确认、未做任何修改** |
| 覆盖风险 | 无。CognitiveAgent Lab 所有产出 confined 在当前工作区内；其他 WorkBuddy 目录一律不写入 |

## 2. 运行时与依赖

| 能力 | 状态 |
|------|------|
| Python | ✅ 3.13.12（managed，推荐）+ 3.9.6（system fallback） |
| 项目 venv | ⚠️ `~/.workbuddy/binaries/python/envs/default/` 已存在，但仅 16 个包（pdfplumber/pymupdf/numpy 等文档处理类）。**FastAPI / Pydantic / pytest / openai SDK 均未安装**，M0 阶段需 pip 安装 |
| Node.js | ✅ v22.22.2（managed）+ v24.6.0（system） |
| 包安装隔离 | ✅ 所有 pip 安装进 venv，npm 进 managed workspace，不污染系统环境 |

## 3. 协作能力（实际可调用 vs 仅文档存在）

| 能力 | 实际状态 | 说明 |
|------|----------|------|
| **Subagents** | ✅ 真实可用 | Agent tool 支持按类型（general-purpose / Explore / Plan 等）派生子代理，可并行派生、可命名（SendMessage 互联）、可设权限模式与轮数上限。**限制：子代理是会话内任务型实例，非常驻守护进程**——每次任务即时实例化，任务结束即回收 |
| **共享任务列表** | ✅ 真实可用 | TaskCreate/TaskUpdate/TaskList，含依赖阻塞关系（blockedBy/blocks），是团队协作的真实调度面板 |
| **并行任务** | ✅ 真实可用 | 单条消息内并行工具调用 + 后台 Bash + 并行子代理派生 |
| **项目级 Skills** | ✅ 已落地 | `.workbuddy/skills/` 下已创建 4 个（architecture-review / agent-development / testing / code-review），经官方 skill-creator 脚本初始化，格式已验证 |
| **用户级 Skills** | ✅ 存在 14 个 | 均为游戏设计 / 学术研究类，与本工程无冲突 |
| **自定义 MCP** | ❌ 未配置 | `~/.workbuddy/mcp.json` 不存在，无用户自建 MCP server |
| **内置 MCP 工具** | ✅ 会话内可用 | sheetagent（表格）、genie-baas（云 DB/免密 LLM）、weixinpay、agent-mail。**与本项目无直接依赖**；项目 LLM 调用走标准 SDK + 环境变量密钥，保证可移植 |
| **Skill 触发方式** | ✅ 真实 | Skill tool 按名称加载，项目级 skills 随项目生效 |

**区分结论**：本报告只声明上述验证过的能力；不存在的能力（常驻 Agent 守护进程、跨会话存活的子代理）明确标注为不支持，团队协作以"任务型子代理 + 共享任务列表 + 交接文档"模式实现。

## 4. 对本项目的影响与决策

1. **可行**：四角色协作（以任务型子代理实例化）、并行开发、Skill 化工程规范、pytest 自动验收——全部有真实支撑。
2. **需补充**：项目 venv 需安装 `fastapi uvicorn pydantic pydantic-settings pytest openai`（M0 第一步）。
3. **不采用**：genie-baas 免密 LLM（会话绑定，不可移植）；多 Agent 框架（违背约束 3）；任何对兄弟目录的写入。
4. **密钥策略**：`.env`（gitignore）+ `pydantic-settings`，`OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` 四个环境变量。
