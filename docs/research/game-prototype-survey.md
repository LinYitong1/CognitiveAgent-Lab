# 技术调研报告：交互式认知实验游戏原型生成（下一阶段预研）

- **文档性质**：只读调研与架构比较。**不构成开发授权，不修改 Phase A 契约与 M1 代码，不引入任何新依赖。**
- **作者**：Architect（调研）／QA（简要审查）
- **日期**：2026-10-20
- **基线**：Phase A commit `45c42c1`（ExperimentSpec 引擎，QA PA-1~13 已过，PA-14 待用户决策）；M1 基线 `ae8dd68`；提案 v2.1（`docs/proposals/experiment-tools-design-proposal.md`）
- **调研对象**（均于 2026-10-20 在线核查，未克隆、未复制任何代码）：
  1. `silentlamp/opengame`（`leigest519/OpenGame` 的 fork）
  2. `miharbi/game-studio-ai`
  3. `ludenio/WebGameTemplateForAgents`
  4. `rsasaki0109/gamedev-agent`

---

## 1. 四个参考项目架构对比与许可证核查

### 1.1 逐项摘要

| | OpenGame | game-studio-ai | WebGameTemplateForAgents | gamedev-agent |
|---|---|---|---|---|
| **许可证（已核查）** | **Apache-2.0**（GitHub API license 字段；fork 与源仓库一致） | **Apache-2.0**（GitHub API license 字段） | **MIT**（README 明示） | **MIT**（LICENSE 文件） |
| **定位** | 端到端"自然语言 → 可玩 Web 游戏"Agentic 框架（CUHK MMLab） | 28 个多智能体"游戏工作室"编排器，产出设计文档/关卡 JSON/资产规格 | 给编码 Agent 用的**项目模板 + 规则文档**（非框架） | 受限域"自然语言 → Phaser 2D 游戏"CLI，含验证/修复/部署闭环 |
| **NL→Spec 流程** | 无独立 Spec；Agent 直接写代码（Template Skill 脚手架） | NL → plan 模板 → 多 Agent 产出设计文档与关卡 JSON（schema 驱动） | NL prompt → Agent 写 `DESIGN.md`（受规则约束） | **Planner：LLM + Zod 校验 → 结构化 GameSpec**（支持离线 fixture） |
| **Agent 机制** | 单 Agent（qwen-code/Gemini CLI 底座）+ Template/Debug 两个 Skill；headless 审批模式 | 28 Agent 三层 + YAML plan（`depends_on`/gate：auto/conditional/**human_review**）；SQLite 持久化 + resume | 4 阶段固定工作流（Design→Planning→Implementation→Testing）；**guard 行为**：违反规则先警告并提替代方案 | 单管线：Planner→Codegen→Verifier→Repair Loop（确定性修复优先，LLM 修复限白名单路径，≤3 轮，错误哈希去重，回滚最佳版本） |
| **Spec→游戏方法** | LLM 自由生成 Phaser/canvas/three.js 代码 + 多模态资产生成 | **不产出可玩游戏**——引擎就绪规格，落地在用户的 Godot/Unity/UE 项目 | Agent 在受控架构（store + seeded PRNG）内写代码 | **确定性模板代码生成**（Codegen 消费 GameSpec），Phaser 3.90 + Vite |
| **测试/评估** | OpenGame-Bench：Build Health / Visual Usability / Intent Alignment 三维（headless 浏览器 + VLM 评审，管线未发布） | pytest 全离线（fixtures，无真实 LLM 调用）+ spec validators/mergers | 浏览器内测试页（`file://` 直开，28 个 store 测试，Node 亦可跑） | 五层 Verifier：format/typecheck/unit/build/browser(Playwright)；全绿才允许 commit/deploy |
| **人工审批** | headless 默认 `auto-edit`，shell 需 `--yolo` | **human_review gate**（暂停等待人工批准后合并） | guard 警告 + 人工在编辑器中主导每轮 | 全绿自动 commit/deploy（人工介入仅在修复循环放弃后） |
| **模型要求** | 专用 GameCoder-27B（CPT+SFT+RL）或同级强模型 | litellm 多路由（云端强模型） | 任意（由用户 Agent 决定，规则文档兜底） | OpenAI Responses API（gpt 级） |

### 1.2 许可证合规结论

四项均可合法借鉴。**本项目立场是零代码复制、仅借鉴架构思想与设计约束**，因此义务最小化；但为可追溯性，实现文档中应注明思想来源：

- **Apache-2.0**（OpenGame、game-studio-ai）：借鉴思想无义务；若未来直接复制代码，需保留版权/许可证/NOTICE 声明（Apache-2.0 §4）。
- **MIT**（WebGameTemplateForAgents、gamedev-agent）：最宽松；若复制代码需保留版权与许可声明。
- 特别注意：OpenGame 底座是 qwen-code（Gemini CLI 系），**不要**借鉴其 CLI 集成方式；我们只取 Template/Debug Skill 的**机制思想**。

### 1.3 与本项目相关的关键启示

1. **gamedev-agent 是与我们目标形态最接近的项目**：Planner（LLM 只产出经 Zod 校验的 GameSpec）+ Codegen（**确定性模板**生成代码）+ 分层 Verifier + 量化控制的 Repair Loop。它证明了"LLM 出 Spec、代码由模板确定性生成"路线在工程上成立，且其"刻意收窄为单一原型"的 MVP 纪律与本项目的分阶段策略一致。
2. **WebGameTemplateForAgents 的运行时约束与 Phase A 的确定性哲学完全同构**，可直接作为游戏模板 runtime 的设计规则：禁 `Math.random`（全部走 seeded PRNG）、纯可序列化 state、事件日志（dispatch history）支持确定性回放、无构建链无 ES modules（`file://` 直开）。其"离散事件（有日志）与连续模拟（无日志）分离"的模型恰好对应"实验试次流程（对账必需）与游戏化动效（不影响数据）分离"。
3. **OpenGame 是我们要明确避开的路线**：LLM 自由生成整个游戏代码 + 依赖 27B 专用模型 + VLM 评审。qwen2.5:7b 无法支撑，且自由生成无法保证实验条件不被篡改。仅借鉴两点：Debug Skill 的"已验证修复活协议"（远期）与"沙箱运行游戏→捕获控制台错误"的验证思想。
4. **game-studio-ai 的多 Agent 复杂度是反面教材**（对 7B 模型而言），但其三点可借鉴：① `human_review` gate 的审批语义；② **schema 驱动的 validator/merger**（输出经 schema 验证、批准后才合并）——与我们的工具校验前置思路一致；③ pytest 全离线（fixtures 无 LLM）的测试纪律——正是 FakeLLM 模式。

---

## 2. 推荐的最小游戏生成技术路线

### 2.1 端到端工作流（Phase B 候选，全部在现有单 AgentLoop 内）

```
Researcher Prompt（自然语言）
  │  AgentLoop（M1，不动）+ LLM（Ollama qwen2.5:7b 或 FakeLLM）
  ▼
ExperimentSpec ──validate_experiment──► generate_experiment ──► export_experiment
  │                                                            │
  │                                              ExperimentBundle（trials + 双 fingerprint，Phase A 已交付）
  ▼
GameSpec（v2.1 §4.5 冻结草案：experiment_ref/scene/input/feedback/flow/gamification）
  │  新工具 validate_game：跨 schema 校验（双指纹对齐 / bindings⊆responses / 边界表"❌"侧字段拒收）
  ▼
render_game（新工具：确定性渲染器，仓库内 Python 代码，非 LLM 产物）
  │  输入 = GameSpec + ExperimentBundle；输出 = 单文件 HTML（内嵌 trials JSON + 固定 JS runtime 模板）
  ▼
Playable Prototype（file:// 直开，零构建、零网络、零外部依赖）
  │
  ├─ 实验正确性测试：渲染器逻辑核单测（回放对账，无需浏览器）+ 事件日志审计
  ├─ 可玩性测试：浏览器内自检页 / headless smoke（决策点见 §5.2）
  ▼
Evaluation（原型阶段：人工试玩 checklist + 自动化报告；正式被试数据回收属 M2+，不在本阶段）
```

### 2.2 六个焦点问题的回答

**Q1 如何保证游戏化包装不擅自改变实验条件、刺激与正确性判定？——四道防线**
1. **结构隔离**：v2.1 §4.0 边界表已冻结——GameSpec 无任何条件分配/判定字段；`validate_game` 拒收越界字段。
2. **渲染器是唯一消费者**：渲染器只读 Bundle 的 `trials/responses/timing`，trial 按序呈现，正确性判定由渲染器内**确定性代码**按 `correct_from` 物化结果执行——**LLM 生成的任何内容都不参与判定路径**。
3. **双 fingerprint 启动校验**：游戏端加载时校验 `experiment_ref` 的 config/trials 双指纹与内嵌 Bundle 一致，不一致拒绝启动（v2.1 §7.2 已规定）。
4. **事件日志对账**：运行时记录实际呈现的 trial 序列与响应事件（借鉴 WebGameTemplate 的 dispatch history），与 Bundle.trials 逐条对账即可机器验证"呈现即所生成"。游戏化元素（分数/进度条）只消费对账日志，不写回实验状态。

**Q2 如何通过受控模板生成可玩原型，而不是让 LLM 自由生成游戏引擎？**
采用 gamedev-agent 的 Planner/Codegen 分离：LLM 的全部产出是**一份小而浅的 GameSpec JSON**（枚举 + 布尔 + 少量字符串，v2.1 §4.5 草案本来就是"自由度受限"的设计）；可玩性来自仓库内**确定性渲染器**——固定 JS runtime 模板 + 数据驱动（trials JSON 注入）。LLM 永远不写游戏代码。这同时是安全边界（无任意代码执行）与 7B 模型可行性边界。

**Q3 如何分别测试实验正确性与游戏可玩性？——双轨**
- **实验正确性（逻辑层，无需浏览器）**：渲染器输出前的纯逻辑核心（trial 调度、计时物化、判定、日志格式）做成可独立导入的模块，pytest 直接测：固定 Bundle → 断言呈现序列 == trials、判定正确、fingerprint 校验路径。外加 golden 测试（GameSpec+Bundle → 渲染产物哈希稳定）。
- **游戏可玩性（表现层，浏览器）**：两级——① 零依赖级：自检页模式（WebGameTemplate 式，页面内跑断言：canvas 有渲染、按键事件流通、结束页出现）；② headless 级（决策点）：Playwright/Chromium smoke。原型阶段建议 ① 优先。

**Q4 如何复用 AgentLoop 与 ToolRegistry，不引入多 Agent？**
照抄 Phase A 的 `build_experiment_registry(settings)` 组合器模式：新增 `build_game_registry(...)` 只注册三个新工具（`validate_game` / `render_game`，以及可选的 `design_game`——见 §5.4）。`AgentLoop`、`LLMClient`、`ToolRegistry`、M1 三工具、Phase A 三工具**零修改**；工具落盘复用 `file_write` 的沙箱五步规则（Phase A 已共享化的 `_sandbox_io`）。

**Q5 如何适配 qwen2.5:7b 的能力限制？——PA-14 的教训**
PA-14 失败根因是 7B 构造**大而深**的 ExperimentSpec（嵌套列表 + 交叉引用）。GameSpec 天然更友好：字段少、枚举/布尔为主、默认值即可运行。缓解组合：① 工具 description 内嵌**完整合法样例**（few-shot）；② 分步生成（先 `experiment_ref` + `input`，再全量）；③ **FakeLLM 全链路作为验收门槛，真 LLM Demo 作为尽力而为的增强目标**（沿用 PA-8/PA-14 分离原则）；④ 若仍不可行，升级 qwen2.5:14b 属用户决策（§5.1）。

**Q6 如何设计可扩展接口，不局限于固定范式？**
- 渲染器按 `scene.layout` 字符串分派到**注册表中的 layout 渲染器**（`registry: dict[str, LayoutRenderer]`，与 ToolRegistry 同哲学）——新增游戏呈现类型 = 新增一个 layout 模板 + 单测，核心不感知任何范式；
- `input.bindings` 按响应变量名绑定（v2.1 已冻结），输入方式天然通用；
- 没有任何 Stroop/N-back 专属字段进入 GameSpec 或渲染器核心（红线沿用）。
- 插件（`paradigm`）在 Phase B **完全不需要**——渲染器只消费物化后的 Bundle，不关心范式。

---

## 3. 与 Phase A 的接口和依赖关系

| 依赖项 | 性质 | 状态 |
|---|---|---|
| `ExperimentBundle`（trials + config/trials 双 fingerprint + canonical JSON） | 只读消费，`experiment_ref` 对齐源 | Phase A 已交付（`src/experiment/bundle.py`） |
| v2.1 §4.5 GameSpec schema 草案 | 冻结的契约起点，落地为 `src/experiment/game_schemas.py`（提案预留路径） | 已冻结（提案 v2.1） |
| `build_experiment_registry` 组合器模式 | 复制模式，非代码依赖 | Phase A 已交付 |
| `_sandbox_io` 沙箱（file_write 五步规则） | 共享复用（`render_game` 落盘） | Phase A 已共享化 |
| `AgentLoop`/`LLMClient`/`ToolRegistry` | 零修改复用 | M1 冻结 |

**明确的非依赖**：Phase B 不需要 GameSpec 插件机制、不需要修改 `generation.py`/`validate.py`（实验层校验）、不触碰 `spec.py`。唯一的前置决策是 PA-14 的处理（不影响本调研结论：FakeLLM 路线对两者一致）。

---

## 4. 建议的最小里程碑与可执行验收标准（Phase B 候选，均需独立 QA + 用户逐项审批）

| 里程碑 | 范围 | 可执行验收标准 |
|---|---|---|
| **B0：GameSpec 契约** | `game_schemas.py` + `validate_game` 工具（跨 schema 校验：双指纹、bindings⊆responses、边界表"❌"字段拒收、`feedback`/`flow` 枚举） | ① FakeLLM 全链路通过；② 错误码体系（UNSAT 风格）：指纹不匹配/bindings 越界/未知字段各有独立错误码且有测试；③ 字段级边界测试：每一条 §4.0 边界表"❌"行构造一个违规 GameSpec，必须被拒 |
| **B1：确定性渲染器 v1** | 单一 layout（`canvas-fullscreen` 默认）→ 单文件 HTML（内嵌 trials + 固定 JS runtime：seeded PRNG、纯 state、事件日志）；`render_game` 工具 | ① Bundle+GameSpec → `index.html`，`file://` 直开可玩，零网络零构建；② 渲染器逻辑核单测：呈现序列==trials、判定与 `correct_from` 一致、计时物化正确、fingerprint 启动校验（不匹配拒启动）；③ golden 测试：同输入 → 产物逐字节稳定；④ 事件日志对账工具/测试 |
| **B2：Agent 集成 Demo** | `build_game_registry` + `design_game`（或对话直出，§5.4）+ `examples/run_game_agent.py` | ① FakeLLM 全链路 Demo（NL → ExperimentBundle → GameSpec → HTML）作为**验收门槛**；② qwen2.5:7b 真 LLM Demo 尽力而为（≥1 次成功或完整失败模式记录），**不作硬门槛**；③ M1/Phase A 全部既有测试不回归 |
| **B3：可玩性验证** | 浏览器内自检页（推荐）或 headless smoke（§5.2 决策） | ① 自检页断言全绿（渲染/输入/结束流程）；② 人工试玩 checklist（研究者视角：呈现符合设计、键位可用、无反馈默认）；③ QA 独立复核 |

排障纪律沿用现状：每个里程碑独立 QA 报告 → Lead 抽查 → 用户审批，不自动推进。

---

## 5. 主要技术风险与需要用户决定的问题

### 5.1 技术风险

| # | 风险 | 等级 | 缓解 |
|---|---|---|---|
| R1 | qwen2.5:7b 无法可靠产出 GameSpec（PA-14 同型风险） | 高 | FakeLLM 门槛 + 样例嵌入 + 分步生成；必要时升 14b（决策 D1） |
| R2 | 浏览器计时精度不满足认知实验毫秒级 RT 记录（`setTimeout` 抖动） | 高（科学效度） | 原型定位为**设计验证/预演**而非采数工具；运行时用 `performance.now()` 打时间戳并写入事件日志；正式采数精度要求留给 M2+ 决策（D3） |
| R3 | 单文件 HTML 体积膨胀（trials + runtime + 内嵌素材） | 低 | 千级试次 JSON 约 100~300KB，可接受；素材用纯色/几何图形起步 |
| R4 | 游戏 runtime（JS）本身引入缺陷（渲染器是新的确定性代码面） | 中 | 逻辑核与渲染分离，逻辑核（调度/判定/日志）纯 JS 可在 Node 下测试；golden + 对账测试兜底 |
| R5 | 范围蔓延（被 OpenGame 式"自由生成整游戏"诱惑） | 中 | 本报告已将自由生成路线明确排除；B 系列里程碑硬边界 |

### 5.2 需要用户决定的问题

- **D1（模型）**：接受"FakeLLM 为验收门槛、7B 真 LLM 尽力而为"，还是批准本地升级 qwen2.5:14b（约 +9GB 磁盘）以提高 GameSpec 产出成功率？
- **D2（可玩性测试形态）**：B3 采用零依赖浏览器自检页（推荐，无新依赖），还是引入 Playwright + Chromium（约数百 MB 下载，自动化更强）？
- **D3（计时精度定位）**：确认 Phase B 原型"演示级"计时精度（偏差数十毫秒级）可接受，正式采数精度问题推迟到 M2+？
- **D4（GameSpec 产出通道）**：采纳 `design_game` 工具化产出（推荐——校验前置、与三工具同模式），还是 v2.1 §⑩ 开放问题维持的"对话直出"？本报告推荐前者并在 B2 落地。
- **D5（时机）**：本调研已确认可与 Phase A 并行且零影响；Phase B 的 B0 何时启动（Phase A 正式验收后，还是 PA-14 决策落地后即启动）由您指定。

---

## 6. QA 简要审查意见

1. **许可证核查方式**：OpenGame 与 game-studio-ai 的许可证经 GitHub API license 字段（spdx_id）核实，WebGameTemplateForAgents（README）与 gamedev-agent（LICENSE 文件）经仓库页面核实；结论（Apache-2.0 ×2、MIT ×2）证据充分。注意 silentlamp/opengame 是 fork，许可随上游。
2. **边界合规**：本报告未修改任何产品代码；报告文件位于 `docs/research/`，属文档增量；未克隆/复制外部代码，符合本轮全部红线。
3. **一致性**：§2.2 Q1 的四道防线与 v2.1 §4.0/§7.2 已冻结契约一致，无越权新增字段；§4 里程碑沿用"独立 QA + 用户审批"流程，未预设自动推进。
4. **提醒**：R2（计时精度）属于科学效度级风险，建议用户在 D3 上明确表态后再进入 B1。

—— 以上调研完成即止，不自动进入任何下一阶段开发。
