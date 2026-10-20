# Phase B 规划 — GameSpec 与可玩 HTML 游戏生成（精简版 v1.0）

> 作者：Lead（依据 Architect 调研报告 + 用户策略调整指令）｜ 状态：**待用户批准**
> 依据：`docs/research/game-prototype-survey.md`（推荐路线已获用户原则批准）、用户 D1~D5 决策、2026-10-20 晚策略调整指令（8 条）
> 基线：commit `c6ede05`（Phase A + R2，128/128 测试绿）

## 0. 策略调整记录（用户指令，2026-10-20）

1. PA-14（qwen2.5:7b + Ollama 真实 LLM 端到端）停止反复修复，登记为已知问题（见 `pa14-r1-reevaluation-report.md` 追加节：R2 已恢复工具调用发射与正确 spec 结构，剩余单一措辞歧义，留待集成阶段）。
2. Phase B 起以 **FakeLLM + pytest + 确定性测试**为验收门槛；非必要不调真实 LLM。
3. LLM 接口保持可替换（现有 `LLMClientProtocol` 已具备：FakeLLM 与真实客户端同接口，未来本地 Ollama 与任何 OpenAI-compatible API 均可接入）。
4. 不把实验范式、游戏主题、模型名写死进产品。
5. 真实 LLM 端到端测试推迟到核心功能完成后的**集成阶段**。

## 1. 目标与最小可玩原型范围

**一句话目标**：从 ExperimentSpec 出发，经 GameSpec 与确定性渲染器，产出 `file://` 直开即玩、实验逻辑不可篡改的单文件 HTML 游戏原型。

**最小原型链路**（单 AgentLoop 内）：

```
Researcher Prompt
  → design_game / validate_game（LLM 产出浅层 GameSpec，结构化校验）
  → render_game（确定性渲染器：GameSpec + ExperimentBundle → 单文件 HTML）
  → 双轨验证（pytest 逻辑核 + 浏览器自检页）
```

**范围内**：
- GameSpec：**浅层枚举型**呈现层描述（沿用 v2.1 §4.5 草案）——刺激呈现方式、响应采集方式（键盘按键映射）、视觉主题枚举、反馈显示开关、文案模板。**只有引用，没有重算**：trials、正确性判定、约束全部来自 ExperimentBundle。
- 新工具 2 个：`validate_game`、`render_game`（复制 Phase A 组合器模式，新增 `build_game_registry`，不动 M1）。
- 渲染器：**仓库内 Python 代码**（非 LLM 产物），输出零依赖单文件 HTML（内嵌 trials 数据、确定性判定逻辑、事件日志、双指纹启动校验）。
- 浏览器自检页：HTML 内置（数据装载校验、指纹校验、判定逻辑抽样自测、事件日志导出按钮）。D2 口径：自检页≠完整可玩性验证，Playwright 类自动化交互测试列为后续可选项。

**范围外（硬边界）**：
- 不做 GameSpec 之外的复杂游戏逻辑；不做多 Agent Runtime；不做 M2（数据库）/M3（前端服务）/MCP/公共 Skill；
- 不写死 Stroop/N-back 或任何范式——渲染器只认识 GameSpec 枚举，不认识具体实验；
- 计时精度为 Demo 级（D3：不用于正式采数）；
- M1 与 Phase A 已验收代码零修改（GameSpec 工具为纯新增）。

**防篡改四道防线**（沿用调研报告结论）：
1. GameSpec schema 拒收实验语义字段（越界键 → SCHEMA_INVALID）；
2. 渲染器是 trials 唯一消费者，判定走确定性代码（HTML 内嵌，非 LLM 产物）；
3. HTML 启动时校验 bundle_sha256 + trials_fingerprint；
4. 事件日志与 trials 机器对账（pytest 回放核）。

## 2. 里程碑与验收标准（全部 FakeLLM/确定性验收）

### B0 — GameSpec Schema 与契约冻结（Architect）
- 交付：GameSpec Pydantic schema、职责边界表（§4.0 延伸）、Phase B 契约文档（含防篡改边界机器可查条款）。
- 验收（pytest）：① GameSpec 单测全绿（枚举校验、越界字段拒绝）；② 边界表可执行——渲染器对含实验语义字段的 GameSpec 拒绝并返回结构化错误；③ 与 ExperimentSpec 零字段耦合泄漏（交叉引用检查）。

### B1 — validate_game 工具与 FakeLLM 设计循环（Backend）
- 交付：`validate_game` 工具（校验 GameSpec + 引用 Bundle 指纹一致性）、`build_game_registry` 组合器、FakeLLM 集成测试（产出→校验失败→修正→通过，复制 PA-8 模式）。
- 验收：① FakeLLM 集成测试全绿；② 错误报告结构化（error_code/path/suggestion）；③ 全量回归 128+ 项全绿；④ pyright 0 errors。

### B2 — 确定性渲染器与可玩 HTML（Backend）
- 交付：`render_game` 工具（GameSpec + Bundle → data/ 沙箱内单文件 HTML）；HTML 含自检页与事件日志。
- 验收：① **渲染黄金文件**：同输入逐字节可复现（外部 shasum 交叉验证，复制 PA-2 模式）；② **逻辑核（无浏览器）**：pytest 解析 HTML 内嵌数据与判定逻辑，回放对账全部 trials 的正确性判定 100% 与 Bundle 一致；③ 自检页数据装载/指纹/抽样自测通过（人工开一次 file:// 确认 + 截图记录）；④ 渲染器 grep 无范式名硬编码（复制 PA-12）。

### B3 — 端到端 Demo（FakeLLM）与开源整理
- 交付：`examples/run_game_agent.py`（默认 FakeLLM 模式）；README（定位/安装/快速开始/示例/测试/已知问题含 PA-14）；pyproject 安装配置；LICENSE 核查（现有依赖均为宽松许可）。
- 验收：① 一条命令跑通 ExperimentSpec→GameSpec→HTML→双指纹 verify；② README 步骤可在干净 venv 照抄执行成功；③ 全量测试绿；④ GitHub 开源清单（无密钥、无内部路径）审查通过。

### 集成阶段（推迟，核心完成后单独申请）
- 真实 LLM 端到端（重试 PA-14：措辞消歧一行修复已在案 / OpenAI-compatible API 切换验证）；可选 Playwright 自动化可玩性测试。

## 3. 流程约定

- 沿用 Architect 冻结契约 → Backend 实现 → QA 独立验证 → 用户批准推进，每里程碑一次提交+简报，**避免重复长报告**（QA 结论并入里程碑简报）。
- 每里程碑结束停下等用户批准，不自动推进。
- LLM 调用策略：开发期零真实 LLM 调用（FakeLLM 覆盖）；集成阶段一次性预算申请。

## 4. 主要风险

| 风险 | 影响 | 缓解 |
|------|------|------|
| R-1 GameSpec 表达力 vs 范式无关性张力 | 枚举不够用→偷偷加逻辑 | B0 冻结枚举集；不够用时走契约修订，不加通用逃生门 |
| R-2 HTML 计时精度 | 科学效度 | D3 已裁定 Demo 级，README 明示不用于采数 |
| R-3 可玩性验证自动化程度 | 自检页≠真验证 | 双轨中逻辑核为硬门槛；Playwright 列后续可选 |
| R-4 PA-14 遗留 | 集成阶段阻塞 | 已收窄至单一措辞歧义；FakeLLM 门槛不受影响 |
| R-5 HTML 体积膨胀 | 单文件失控 | 复用 1MB 导出护栏量级上限 |

—— 规划即止，不执行任何代码修改。等待用户批准 B0 启动。
