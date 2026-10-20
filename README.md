# CognitiveAgent Lab

一个纯工程导向的 AI Agent 系统：单一 Agent 主循环驱动**确定性实验生成管线**——从
ExperimentSpec 出发，生成可复现的试次序列（ExperimentBundle），再经 GameSpec 渲染为
`file://` 直开即玩的**单文件 HTML 游戏**，实验逻辑不可被表现层篡改。

```
自然语言任务（Researcher Prompt）
  → ExperimentSpec ──validate_experiment──┐
  → 试次序列 generate_trials（同 spec+seed 逐字节可复现）
  → ExperimentBundle export_experiment（含 SHA-256 完整性指纹）
  → GameSpec ──validate_game（引用六项指纹，只描述呈现、不可改实验）──┘
  → render_game → 单文件可玩 HTML（内嵌双指纹启动校验 + 事件日志）
```

> **首版 Demo 展示的是多步骤工具执行 + 确定性实验→游戏管线能力，不是论文级研究助手。**
> 范围外：多 Agent 协作、RAG、认证体系、正式数据收集（计时为 Demo 级）。

## 快速开始（无需 LLM 密钥）

```bash
# 1. Python >= 3.13，创建虚拟环境并安装
python3.13 -m venv .venv
.venv/bin/pip install -e .

# 2. 端到端 Demo：FakeLLM 驱动完整 Agent 工作流（无网络、无密钥）
#    单一 AgentLoop 依次调用 validate_experiment → generate_trials
#    → export_experiment → validate_game → render_game，产出可玩 HTML
.venv/bin/python examples/run_game_agent.py

# 3. 用浏览器打开（file:// 直开）
open data/games/demo-agent-game.html        # macOS
# 浏览器试玩检查清单：docs/checklists/browser-playtest-checklist.md

# 4. 独立校验实验包完整性（免生成器，重算双指纹）
.venv/bin/python -m src.experiment.verify data/experiments/demo-agent-game.json
```

其他示例：

```bash
.venv/bin/python examples/run_game_render.py     # 不经 Agent，纯函数生成可玩游戏
.venv/bin/python examples/run_experiment_agent.py # Phase A：实验三工具工作流
.venv/bin/python examples/run_agent.py           # M1：基础三工具（需真实 LLM）
```

连接真实 LLM（可选，`examples/run_agent*.py` 需要）：复制 `.env.example` 为 `.env`
填入 `OPENAI_API_KEY` 或任意 OpenAI-compatible 端点（`LLM_BASE_URL` + `LLM_MODEL`）。
上面的 B3 Demo 不读取任何密钥。

## 安装

| 项 | 说明 |
|---|---|
| Python | >= 3.13 |
| 安装 | `.venv/bin/pip install -e .` |
| 依赖 | FastAPI、Pydantic v2、pydantic-settings、httpx、openai SDK（详见 pyproject.toml） |
| 密钥 | 仅为 `examples/run_agent*.py` 可选；管线与测试零密钥 |

## 架构

```
src/
├── agent/        AgentLoop（plan→act→observe 单循环）、ToolRegistry、注册组合器
├── tools/        工具层：calc / http_request / file_write（M1 三工具）
│                 + validate_experiment / generate_trials / export_experiment（Phase A）
│                 + validate_game / render_game（Phase B）
├── experiment/   确定性实验引擎：schemas / validation / generation / export /
│                 verify（免生成器独立校验 CLI）/ game_schemas / game_render
├── models/       Pydantic 模型（LLM、工具规格、事件、结果）
└── api/          FastAPI + SSE 事件流（M1）
```

**防篡改四道防线**（游戏层无法改动实验条件/试次/正确性）：

1. GameSpec schema `extra="forbid"`——实验语义字段（如 trials）直接拒收；
2. 渲染器是 trials 唯一消费者，trials/correct 只从 ExperimentBundle 复制；
3. HTML 内嵌纯 JS SHA-256，启动时校验 bundle_sha256 + trials_fingerprint，
   失配拒绝启动；
4. pytest 逻辑核对账（黄金文件逐字节比对 + 试次/正确性 100% 一致）。

**两级错误契约**：工具级失败 → `BLOCKED:` 前缀；领域级失败 → `ok=true, valid:false`
结构化报告（error_code / path / suggestion），供 LLM 迭代修正，重复提交触发
`ITERATION_STALLED`。

详细设计：[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) ｜
Phase A/B 冻结契约：[docs/handoff/](docs/handoff/) ｜
路线图：[docs/ROADMAP.md](docs/ROADMAP.md)

## 测试

```bash
.venv/bin/python -m pytest            # 全量测试（213 项，无需密钥）
.venv/bin/python -m pyright src/      # 静态类型（0 errors）
.venv/bin/python -m scripts.check_layers  # 分层依赖检查
scripts/check.sh                      # CI 门禁（上述 + 密钥扫描 + 编译检查）
```

确定性验收要点：同 spec+seed 重跑 → bundle 指纹一致、HTML 逐字节一致
（PYTHONHASHSEED 无关，外部 shasum 交叉验证）；黄金文件见 `tests/golden/`。

## 浏览器试玩检查清单

人工验收生成的 HTML 游戏（键盘响应、反馈、区块切换、结束总结、事件日志下载、
防篡改）：[docs/checklists/browser-playtest-checklist.md](docs/checklists/browser-playtest-checklist.md)

## 已知限制

1. **真实 LLM 端到端未通过（PA-14 已知问题）**：qwen2.5:7b + Ollama 0.40.6 组合
   下工具调用被静默丢弃（详见 `docs/handoff/ollama-toolcall-diagnosis-report.md`）；
   当前验收门槛为 FakeLLM + pytest，真实 LLM 集成推迟到集成阶段，
   LLM 接口（`LLMClientProtocol`）保持可替换。
2. **计时未经验证**：浏览器 `setTimeout` 调度为近似值，**不用于正式实验数据收集**。
3. **游戏交互类型有限**：MVP 仅支持键盘（choice 按键 / text / rating 输入），
   无指针/触摸/音频；反馈样式三种枚举；多响应试次不重绘刺激。
4. **事件日志不强制持久化**：仅存页面内存，结束屏手动下载。
5. 浏览器自动化可玩性测试（Playwright 类）推迟（D2 决策：人工检查清单替代）。

## 文档索引

| 文档 | 说明 |
|------|------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 技术架构（恢复/幂等性、工具安全规范、ADR-001~006） |
| [docs/ROADMAP.md](docs/ROADMAP.md) | 开发路线图 |
| [docs/ACCEPTANCE_CRITERIA.md](docs/ACCEPTANCE_CRITERIA.md) | 可执行验收标准（反假阳性） |
| [docs/plans/phaseB-plan.md](docs/plans/phaseB-plan.md) | Phase B 规划（GameSpec → 可玩 HTML） |
| [docs/handoff/](docs/handoff/) | 各里程碑冻结契约与 QA 报告 |
| [docs/checklists/browser-playtest-checklist.md](docs/checklists/browser-playtest-checklist.md) | 浏览器人工试玩检查清单 |

## 许可证

待定——推荐 MIT 或 Apache-2.0（现有依赖 FastAPI/Pydantic/httpx/openai SDK 均为
MIT/Apache 系宽松许可，无传染性约束）。许可证文件将在确认后添加。
