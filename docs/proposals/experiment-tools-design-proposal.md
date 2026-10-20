# 提案：实验工具扩展设计 — generate_trials / validate_experiment / export_experiment

> 状态：**提案（proposal）v2.1 —— 未获用户批准前不实施，不写入任何代码**（v2 按用户 6 点意见修订；v2.1 按 QA 审查报告修复 3 项 Major + 7 项 Minor + 采纳 4 项 Suggestion）
> 作者：Architect Agent ｜ v1 日期：2026-10-20 ｜ v2 修订日期：2026-10-20 ｜ v2.1 修订日期：2026-10-20（QA 审查修复轮，依据 docs/handoff/qa-proposal-v2-review.md）
> 产品方向：CognitiveAgent Lab — **独立、开源、通用的** Game-Based Cognitive Experiment Agent（游戏化认知实验设计与评估）
> 产品边界（用户已明确，本提案全部设计受其约束）：**不兼容**用户既有认知模型/实验项目；**不为**特定认知理论硬编码；**不扩展为**完整游戏引擎；**不开发**特定实验范式（范式仅作为可选插件示例出现）。
> 现实基础（已读真实代码，本文所有签名/路径均据此）：
> - `src/models/tool_spec.py` — `ToolSpec(BaseModel)`：`name / description / input_model: type[BaseModel] / idempotency: Literal["idempotent","non-idempotent"] / risk_level: Literal["low","medium","high"] / executor: Callable[[BaseModel], Awaitable[ToolResult]]`，含 `effective_idempotency(args)` 方法
> - `src/agent/registry.py` — `ToolRegistry.register(spec) -> None`（校验失败抛 `ToolRegistryError`）、`execute(name, args) -> ToolResult`（未知工具/参数校验失败/executor 异常一律返回 `ToolResult(ok=False)`，不外抛）
> - `src/agent/loop.py` — `AgentLoop.run_task(goal)`：工具失败以 `ERROR:` 前缀 tool message 回传 LLM 自纠；`settings.calc_agent_max_steps` 为硬上限；终态必发 `final`
> - `src/tools/calc.py` / `src/tools/file_write.py` — 工具实现风格参照：`XxxInput(BaseModel)` + 内部 `_XxxBlocked` 异常 + `BLOCKED:` 前缀 + `build_tool_spec(settings: Settings) -> ToolSpec` 工厂
> - `src/agent/__init__.py` — `build_registry(settings) -> ToolRegistry`（注册 M1 三工具）
> - 本提案**独立于里程碑**（不推进 M2 SQLite 持久化设计），是未来"实验工具扩展"阶段的设计输入。
> 变更记录见文末（v1→v2、v2→v2.1）。文中 fingerprint 值均为**示意占位值**（真实值由 canonical JSON 计算，§5.4）。

---

## ① 产品定位与范围

**定位**：Agent 扮演"认知实验设计者"——与用户对话理解研究意图，产出结构化实验规格（`ExperimentSpec`，v1 名为 ExperimentConfig，v2 统一命名），经**通用确定性引擎**验证、展开为试次序列，导出为可独立复现与校验的实验包；游戏表现层（`GameSpec`）与实验逻辑层解耦（§④）。

**范围（本提案覆盖）**：
- 三个新工具：`generate_trials`（试次生成）、`validate_experiment`（规格验证）、`export_experiment`（导出实验包）；
- `ExperimentSpec` 与 `GameSpec` 两份 schema 草案及职责边界；
- 通用因素组合生成器（系统核心）与可选 paradigm 插件（扩展）；
- 确定性生成/验证引擎与可重复性契约；
- 验证-迭代循环、测试与验收策略草案。

**明确不在本提案范围**：网页游戏本体（M3+ 或更后）、GameSpec 的具体游戏机制 DSL、被试数据回收/评估分析、M2 持久化、多实验管理、任何特定范式的正式开发（Stroop/N-back 仅作插件示例，§⑤）。

## ② 总体思路：职责边界与通用性红线（提案核心）

```
LLM（设计决策）                确定性 Python 代码（生成与验证）
┌──────────────────┐          ┌──────────────────────────────────┐
│ 理解研究意图       │          │ validate_experiment: 校验 spec      │
│ 撰写/修改 spec    │ ──工具──► │ generate_trials: 通用组合生成器(核心)│
│ 根据验证错误迭代   │ ◄─回传──  │                  + 可选范式插件     │
│ 汇报设计结果       │          │ export_experiment: 物化实验包       │
└──────────────────┘          │ 概率/随机化/算术：全部在此            │
                              └──────────────────────────────────┘
```

**分工铁律**：
1. **LLM 不做算术**——概率、频数、平衡、随机化全部由确定性代码执行（LLM 输出的数字仅作为设计意图声明，一律经引擎验证/计算）。这延续 M1 的既有事实：`calc` 工具存在的意义即是"算术不信任 LLM"。
2. **引擎不做决策**——因素怎么选、比例定多少，是 LLM 与用户的对话产物；引擎只负责忠实、可重复地物化。
3. **同 spec + 同 seed → 逐字节相同输出**——可重复性是科研底线，由纯函数引擎保证（§⑤）。
4. **实验逻辑与游戏表现解耦**——条件分配、正确性判定归 ExperimentSpec；呈现与交互归 GameSpec（§④）。

**通用性红线（产品边界的落实，v2 新增）**：
- **核心 schema（ExperimentSpec）、验证器、通用组合生成器中零范式/零理论名词**——只有通用结构（因素/水平/组合/约束/计时/响应变量）；
- **范式知识只存在于可选插件层**（§5.3）与 spec 的 `paradigm`/`paradigm_params` 两个自由字段——插件是 enhancement 不是 dependency：`paradigm` 缺省时纯通用路径完整可用（§4.1 示例）；
- **引擎不内嵌任何认知理论假设**（Bayesian updating、evidence sampling、sequential decision 或任何其他理论的计算模型）——理论假设属于用户的研究设计，经通用结构表达；引擎对其一无所知；
- 插件示例（Stroop、N-back）仅为验证表达力的**样例代码**，不是系统组成部分，不限制系统通用性。

由此，三个工具在 M1 `ToolRegistry` 看来只是**三个新的注册项**，AgentLoop、事件模型、错误回传机制全部原样复用。

## ③ 三工具 ToolSpec 设计

新模块：`src/tools/experiment_tools.py`（单文件三工具，风格对齐 `calc.py`/`file_write.py`：Input 模型 + `BLOCKED:` 前缀 + `build_tool_spec(settings)` 工厂）。共享引擎代码位于新包 `src/experiment/`（§⑤），`src/tools/` 依赖它（分层方向 `agent → tools → experiment → models/config`，见 §⑨）。

### 3.1 validate_experiment — 规格验证（幂等、只读）

```python
class ValidateExperimentInput(BaseModel):
    config: dict[str, object]      # ExperimentSpec 的 JSON 对象（LLM 直接内联生成，无需先落盘）
    previous_errors: list[str] = Field(default_factory=list)  # 可选：此前轮次的 error_code:path 指纹（§6.3 防死循环）

# build_tool_spec 返回：
ToolSpec(
    name="validate_experiment",
    description="校验实验规格的 schema 合法性与语义约束（比例和、约束冲突、试次数、可满足性）。"
                "返回机器可读的验证报告（错误含 error_code/path/suggestion），供修改 spec 后重验。",
    input_model=ValidateExperimentInput,
    idempotency="idempotent",      # 纯函数、无副作用
    risk_level="low",
    executor=...,
)
```

**输出结构**（`ToolResult.result`，JSON 字符串，截断 512 之前优先保留 errors 数组）：

```json
{
  "valid": true,
  "fingerprint": "1a2b3c4d",       // sha256(canonical_json(spec))[:8]（示意值；本示例即 §4.2 spec，与 §7.1 同值）
  "engine_spec_version": "1.0",    // 引擎算法规范语义版本（§5.4 可重复性契约）
  "warnings": [{"code": "RATIO_ROUNDED", "path": "constraints.ratios", "message": "..."}],
  "stats": {"trial_count": 88, "factor_count": 2, "blocks": 2, "plugin": null}
}
```

**错误返回契约（两级，冻结）**：
- **领域级（验证不通过）**：`ToolResult(ok=True)` + `result` 含 `"valid": false` 与 `errors` 数组（§⑥ 的机器可读错误结构）。理由：验证发现 spec 问题是**有效结果**而非工具失败，回传 LLM 时不带 `ERROR:` 前缀，与"工具坏了"明确区分。
- **工具级失败**：仅限输入非 dict、JSON 序列化失败等基础设施错误——沿用 `registry.execute` 的 `ok=False` 路径（`invalid arguments: ...`），不外抛。安全拒绝（如 config 体积超限 256KB）→ `BLOCKED: config too large`。

### 3.2 generate_trials — 试次生成（幂等、纯函数、不落盘）

```python
class GenerateTrialsInput(BaseModel):
    config: dict[str, object]
    max_preview_trials: int = Field(default=8, ge=0, le=50)   # 回传 LLM 的试次预览条数

ToolSpec(
    name="generate_trials",
    description="按实验规格确定性生成完整试次序列（通用因素组合路径；若声明 paradigm 且插件可用，"
                "附加范式派生逻辑。同 spec+seed 结果逐字节相同）。返回序列指纹、各因素水平频数统计"
                "与试次预览；不写任何文件，完整序列由 export_experiment 用同一 spec+seed 物化。",
    input_model=GenerateTrialsInput,
    idempotency="idempotent",      # 纯函数：同输入同输出，无副作用（可安全重试，M2 恢复矩阵友好）
    risk_level="low",
    executor=...,
)
```

**输出结构**：

```json
{
  "fingerprint": "5d21e0f7",            // sha256(canonical_json(trials))[:8]
  "trial_count": 88,
  "frequency": {                         // 统计性质摘要（LLM 核对设计意图的依据）
    "cue_type": {"valid": 44, "invalid": 44},
    "target_side": {"left": 44, "right": 44}
  },
  "preview": [ {"index": 0, "block": "practice", "factors": {...}, "derived": {...}}, ... ],
  "plugin_used": null,                   // 或 "stroop@1.0"（插件名@版本，§5.3）
  "note": "full sequence reproducible via export_experiment with identical spec"
}
```

**设计要点**：完整试次序列**不进 ToolResult.result**（可能数百 KB，超出 512 字符摘要契约且污染 LLM 上下文）——result 只含指纹与统计。完整序列的交付通道是 `export_experiment`（同 spec+seed 由纯函数性质保证两工具产出一致）。**一致性是可断言的**：`generate_trials.fingerprint == export_experiment` 实验包内 `trials_fingerprint`，测试与验收均以此断言。

**错误返回契约**：spec 无效（schema/语义/约束不可满足）→ `ok=True` + `"valid": false` + errors（与 validate_experiment 同构，实现上直接复用同一验证函数）；工具级失败走 registry 路径。

### 3.3 export_experiment — 导出实验包（非幂等、落盘）

```python
class ExportExperimentInput(BaseModel):
    config: dict[str, object]
    path: str = Field(min_length=1)   # 相对 data/ 沙箱根的输出路径（建议 .json 后缀）

ToolSpec(
    name="export_experiment",
    description="把实验规格物化为自包含的实验导出包（ExperimentBundle：原始 spec + 全量试次 + "
                "可重复性元数据），写入 data/ 沙箱内指定路径。游戏端零实验逻辑，只按序列呈现。",
    input_model=ExportExperimentInput,
    idempotency="non-idempotent",    # 写文件（覆盖语义），与 file_write 同级
    risk_level="medium",             # 与 file_write 同级（沙箱写）
    executor=...,
)
```

**输出**：`ToolResult(ok=True, result=f"wrote {path} ({bytes} bytes, trials_fingerprint={fp})")`。

**落盘安全规则**：完全沿用 `file_write` 的五步沙箱规则（`..` 拒绝 → realpath + `is_relative_to` 组件边界 → lstat 各级目录无符号链接 → 大小上限 → 沙箱内自动建目录）。导出内容须过 1MB 上限（超大实验导出失败 → `BLOCKED: export too large`，提示分块导出——开放问题 §⑩）。实现路径见 §⑨（共享 helper，**不改 file_write.py 本体**）。

**错误返回契约**：spec 无效 → 先验证，`ok=True` + valid:false（不导出无效实验）；沙箱违规 → `BLOCKED:` 前缀（对齐 M1 惯例）；其余工具级失败走 registry 路径。

### 3.4 与现有 ToolRegistry 的注册方式（接入点，真实签名）

```python
# 新增文件 src/agent/experiment_registry.py（不动 src/agent/__init__.py，见 §⑨）：
from src.agent import build_registry          # 复用 M1 组装（agent → agent 同包 import 合法）
from src.tools import experiment_tools

def build_experiment_registry(settings: Settings) -> ToolRegistry:
    """M1 三工具 + 实验三工具（组合注册：既有 build_registry 零改动）。"""
    registry = build_registry(settings)
    registry.register(experiment_tools.build_validate_spec(settings))
    registry.register(experiment_tools.build_generate_spec(settings))
    registry.register(experiment_tools.build_export_spec(settings, sandbox=Path(settings.data_sandbox_dir)))
    return registry
```

`ToolRegistry.register` 的既有校验（`src/agent/registry.py:24-33`：name 非空/不重复、`input_model` 为 BaseModel 子类、executor 为 async callable）对新工具同样生效——三工具天然满足，无需改注册器。

## ④ 两份 schema：ExperimentSpec 与 GameSpec

**核心解耦铁律：实验逻辑归 ExperimentSpec，游戏表现归 GameSpec。** 两层经双 fingerprint 引用对齐（§⑦）。

### 4.0 职责边界表（字段归属划分，冻结）

| 关注点 | ExperimentSpec（实验层） | GameSpec（表现层） |
|--------|--------------------------|---------------------|
| 因素/水平/条件分配 | ✅ `factors`/`constraints` | ❌（不可见） |
| 试次序列与顺序 | ✅ 物化于导出包 `trials` | 引用（`experiment_ref` 对齐） |
| 正确性判定规则 | ✅ `correct_from` | ❌（不定义对错，只呈现反馈样式） |
| 实验计时（fixation/stimulus/ISI） | ✅ `timing`（逐试次物化） | ❌ |
| 响应变量类型与取值域 | ✅ `responses`（kind/options/scale） | ❌ |
| 输入方式与键位映射 | ❌ | ✅ `input.bindings`（按响应变量名绑定） |
| 反馈有无/时机/样式 | ❌ | ✅ `feedback` |
| 场景呈现/布局/素材 | ❌ | ✅ `scene` |
| 交互流程（ready/block 间歇/结束页） | ❌ | ✅ `flow` |
| 游戏化包装（积分/进度/连击） | ❌ | ✅ `gamification` |

**导出关系**：ExperimentSpec →（`export_experiment` 物化）→ **ExperimentBundle**（原始 spec + 全量 trials + 可重复性元数据）；GameSpec 为**独立文档**，经 `experiment_ref`（name/version/seed + 双 fingerprint）引用 Bundle 的试次序列并叠加交互描述（§⑦）。两层可独立演化——改呈现不动实验，改实验（需重导出）呈现层经 fingerprint 感知变更。

### 4.1 ExperimentSpec schema 草案（`src/experiment/schemas.py`，Pydantic v2）

```python
class Level(BaseModel):
    name: str
    weight: float = Field(default=1.0, gt=0)          # 水平采样权重（意图声明，引擎整数化；balance=true 时被忽略→警告）

class Factor(BaseModel):
    name: str = Field(min_length=1)
    levels: list[Level] = Field(min_length=1)          # 水平（有序——展开顺序的确定性来源）

class RatioRule(BaseModel):
    factor: str
    ratios: dict[str, float]                            # level name -> 比例；和须 ≈1.0（容差 1e-6）

class Constraints(BaseModel):
    balance: bool = False                               # 所有因素所有水平等权（与 ratios 互斥，见 §6.1 规则 C1）
    ratios: list[RatioRule] = Field(default_factory=list)
    max_repeat: int | None = None                       # 同一水平连续出现上限（防 streak，如 3）
    mutually_exclusive: list[list[str]] = Field(default_factory=list)  # 禁止同现的水平名对（跨因素）

class ResponseVar(BaseModel):
    name: str
    kind: Literal["choice", "text", "rating"]
    options: list[str] = Field(default_factory=list)    # choice 用
    scale: tuple[int, int] | None = None                # rating 用 (min, max)
    correct_from: str | None = None                     # 正确答案来源：因素名（通用路径）或插件派生字段名（§5.3）

class BlockSpec(BaseModel):
    name: str                                           # 全 spec 内唯一（重名 → SCHEMA_INVALID；§5.1 子流派生键依赖其唯一）
    trial_count: int = Field(gt=0)
    factor_filter: dict[str, list[str]] = Field(default_factory=dict)  # 该 block 只含指定水平
    shuffle_within: bool = True

class TimingSpec(BaseModel):
    fixation_ms: int = 500
    stimulus_ms: int | None = None                      # None = 直至响应
    isi_ms: int = 1000

class ExperimentSpec(BaseModel):                        # v1 名为 ExperimentConfig，v2 统一命名
    schema_version: Literal[1] = 1
    name: str = Field(min_length=1)
    version: str = "0.1.0"
    seed: int                                           # 必填——确定性源头（§5.1）
    paradigm: str | None = None                         # 可选插件键（§5.3）；None = 纯通用路径（核心，无需任何插件）
    paradigm_params: dict[str, object] = Field(default_factory=dict)  # 插件自由参数（n、字母表等）
    factors: list[Factor] = Field(min_length=1)
    blocks: list[BlockSpec] = Field(min_length=1)
    constraints: Constraints = Constraints()
    responses: list[ResponseVar] = Field(min_length=1)
    timing: TimingSpec = TimingSpec()
```

**通用性声明（§② 红线的 schema 落实）**：上述结构只有通用概念；`paradigm`/`paradigm_params` 是**自由字段**——核心引擎不解释其内容，只有对应插件（若存在且被声明）消费它。`correct_from` 允许指向因素名（纯通用路径的正确性判据，见 §4.2 示例）或插件派生字段名（§4.3/4.4 示例）。

### 4.2 示例一：纯通用路径（无插件，系统核心能力的最小示例）

```json
{
  "schema_version": 1,
  "name": "cueing-generic",
  "version": "0.1.0",
  "seed": 11,
  "paradigm": null,
  "factors": [
    {"name": "cue_type",    "levels": [{"name": "valid"}, {"name": "invalid"}]},
    {"name": "target_side", "levels": [{"name": "left"}, {"name": "right"}]}
  ],
  "blocks": [
    {"name": "practice", "trial_count": 8,  "factor_filter": {}, "shuffle_within": true},
    {"name": "main",     "trial_count": 80, "factor_filter": {}, "shuffle_within": true}
  ],
  "constraints": {"balance": true},
  "responses": [
    {"name": "locate_target", "kind": "choice", "options": ["left", "right"], "correct_from": "target_side"}
  ],
  "timing": {"fixation_ms": 400, "stimulus_ms": null, "isi_ms": 800}
}
```

**自洽性**：2 因素各 2 水平 → 4 个组合；`balance: true` 且无 `ratios`、无显式 weight → 无约束冲突（规则 C1，§6.1）。practice 8 试次 = 4 组合 × 2；main 80 = 4 × 20；总计 88 试次，每组合 22（2+20）。`correct_from: "target_side"` 指向**因素名**——纯通用路径无须任何派生逻辑即可定义正确答案；`stimulus` 为空对象（通用 combinator 不产出刺激物化，游戏端按 GameSpec 的 `scene` 规则从 `factors` 渲染）。此例证明：**核心路径不依赖任何范式代码**。

### 4.3 示例二：Stroop（可选插件示例）

```json
{
  "schema_version": 1,
  "name": "stroop-plugin-demo",
  "version": "1.0.0",
  "seed": 42,
  "paradigm": "stroop",
  "factors": [
    {"name": "congruency", "levels": [{"name": "congruent"}, {"name": "incongruent"}]},
    {"name": "ink_color",  "levels": [{"name": "red"}, {"name": "green"}, {"name": "blue"}]}
  ],
  "blocks": [
    {"name": "practice", "trial_count": 12, "factor_filter": {}, "shuffle_within": true},
    {"name": "test",     "trial_count": 96, "factor_filter": {}, "shuffle_within": true}
  ],
  "constraints": {"balance": true},
  "responses": [
    {"name": "classify_ink", "kind": "choice", "options": ["red", "green", "blue"], "correct_from": "correct_ink"}
  ],
  "timing": {"fixation_ms": 500, "stimulus_ms": null, "isi_ms": 1000}
}
```

**自洽性**：congruency(2) × ink_color(3) → 6 组合；`balance: true`、无 ratios、无显式 weight → 无冲突（C1）。practice 12 = 6 × 2；test 96 = 6 × 16；总计 108。test block 内：congruency 48/48、ink_color 32/32/32（§8.2 统计断言即用此数）。插件职责（§5.3）：由 (congruency, ink_color) 派生 `word_color`（congruent → 同色；incongruent → 另两色中按 rng 选一）、物化 `stimulus`（{word, color}）与派生字段 `correct_ink`；`correct_from` 指向插件派生字段。**设计注**：congruency 被建为**显式因素**而非隐式派生量——这是通用 schema 表达派生量平衡的标准做法（隐式派生量的分布只是组合分布的投影，不受约束控制）。

### 4.4 示例三：N-back（可选插件示例，序列型）

```json
{
  "schema_version": 1,
  "name": "nback-plugin-demo",
  "version": "1.0.0",
  "seed": 7,
  "paradigm": "nback",
  "paradigm_params": {"n": 2, "alphabet": ["B", "F", "H", "K", "M", "Q", "R"]},
  "factors": [
    {"name": "match_type", "levels": [{"name": "match", "weight": 0.3}, {"name": "nonmatch", "weight": 0.7}]}
  ],
  "blocks": [
    {"name": "main", "trial_count": 120, "shuffle_within": false}
  ],
  "constraints": {"balance": false, "max_repeat": 3},
  "responses": [
    {"name": "nback_judge", "kind": "choice", "options": ["yes", "no"], "correct_from": "correct_match"}
  ],
  "timing": {"fixation_ms": 0, "stimulus_ms": 500, "isi_ms": 2000}
}
```

**自洽性**：`balance: false` 且无 `ratios` → 有效权重 = Level.weight（0.3/0.7，和为 1.0，无需 ratios 声明）→ 无冲突（C1）。N-back 是**序列型插件**（§5.3 `kind: "sequence"`）：match 位点与频数由**插件按有效权重 0.3/0.7 安排**（120 × 0.3 = 36 match / 84 nonmatch，精确整数）——核心 combinator 的 largest remainder 分配路径**不参与**，核心的职责是**生成后频数校验**（实测频数与有效权重期望的偏差超容差 → `PLUGIN_FREQUENCY_DEVIATION`，§5.3）。`shuffle_within: false` 表示序列型：插件按 match 位点安排 + n-back 序列约束（前 n 个试次必然 nonmatch——序列生成的结构性事实）生成字母流并派生 `correct_match`（"yes"/"no"）；`trial_count ≥ n+1` 的校验由**示例插件的 validate 钩子**执行（§5.3——规则内容归插件层，核心无 `n` 概念，红线闭合）。**语义映射声明（SG 边界）**：本插件把通用约束 `max_repeat: 3`（通用语义："同一水平连续出现上限"）映射为"同一**字母**连续呈现上限"——插件对通用约束字段的范式级语义映射必须在其文档中显式声明（§5.3）。此例展示序列型插件的**序列构造覆写**能力（核心是"组合展开+洗牌"语义，序列依赖逻辑与频数实现归插件，核心事后校验兜底）。

### 4.5 GameSpec schema 草案（表现层，`src/experiment/game_schemas.py`）

```python
class ExperimentRef(BaseModel):                  # 对 ExperimentBundle 的引用（双指纹对齐）
    name: str
    version: str
    seed: int
    config_fingerprint: str                      # §5.4 canonical JSON 指纹
    trials_fingerprint: str

class SceneSpec(BaseModel):
    layout: str = "canvas-fullscreen"            # 呈现布局类型（自由字符串，游戏端解释）
    assets: dict[str, str] = Field(default_factory=dict)   # 素材名 → 路径/内联描述

class InputBinding(BaseModel):
    response_name: str                           # 绑定到 ExperimentSpec.responses 中的哪个响应变量
    keys: dict[str, str]                         # 键 → 选项值（choice 型），如 {"r": "red", ...}

class InputSpec(BaseModel):
    modalities: list[Literal["keyboard", "pointer", "touch"]] = ["keyboard"]
    bindings: list[InputBinding] = Field(default_factory=list)

class FeedbackSpec(BaseModel):
    on_response: Literal["none", "correctness-flash", "outcome-text"] = "none"   # 反馈有无与形式
    duration_ms: int = 200

class FlowSpec(BaseModel):
    ready_screen: bool = True
    block_breaks: bool = True                    # block 间休息
    end_screen: Literal["none", "summary"] = "summary"

class GamificationSpec(BaseModel):               # 游戏化包装（全部可选、可全关）
    score: bool = False
    progress_bar: bool = True
    streak_bonus: bool = False

class GameMeta(BaseModel):                       # 强类型（v2.1：弃用弱类型 dict，获得 Pydantic 校验）
    name: str = Field(min_length=1)
    version: str = "0.1.0"

class GameSpec(BaseModel):
    schema_version: Literal[1] = 1
    game: GameMeta = Field(...)                  # 游戏名/版本（表现层自标识）
    experiment_ref: ExperimentRef
    scene: SceneSpec = SceneSpec()
    input: InputSpec = InputSpec()
    feedback: FeedbackSpec = FeedbackSpec()
    flow: FlowSpec = FlowSpec()
    gamification: GamificationSpec = GamificationSpec()
```

**边界约束**：GameSpec **不含**任何条件分配、试次生成、正确性判定字段（§4.0 表的"❌"侧）；`input.bindings` 只能引用 ExperimentSpec 已声明的 `responses` 名（跨 schema 校验规则）；`feedback.on_response: "none"` 是认知实验默认（无反馈不影响实验本身）。本提案只定义 schema 与引用关系——**GameSpec 的产出通道**（LLM 直接生成？未来独立工具？）见开放问题 §⑩。

## ⑤ 确定性引擎设计

新包 `src/experiment/`：`schemas.py`（§4.1）、`game_schemas.py`（§4.5）、`validation.py`（§⑥）、`generation.py`、`export.py`、`plugins/`（可选插件：`stroop.py`、`nback.py`——**示例性质**）。

### 5.1 seed 全链路传递

```
ExperimentSpec.seed (int, 必填)
  └─ 每实验一个根 rng: random.Random(spec.seed)                    # 引擎入口创建，绝不触全局 random
       └─ 每 block 派生子流: random.Random(f"{seed}:block:{block.name}")
            └─（若使用插件）插件内随机决策一律消费传入的 rng 实例
```

- **唯一随机源**：引擎与插件代码**禁止** `import random` 的模块级函数（`random.random()` 等），只允许 `random.Random` 实例；code-review 门禁项（正则可查）。
- **派生子流跨进程稳定**：CPython `random.Random(str)` 对字符串种子走 sha512 派生（与 `PYTHONHASHSEED` 无关的 documented 行为），且根 seed 为 int 完全无歧义——跨进程/跨 `PYTHONHASHSEED` 可重复（验证方法 §8.1）。
- 子流而非单流贯穿的理由：block 独立派生使得"增删一个 block 不扰动其他 block 的序列"（科研迭代友好），且派生式可写进文档供第三方复现。

### 5.2 核心：通用因素组合生成器（factorial combinator，系统核心）

**纯函数，零范式知识，直接由 factors/levels/blocks/constraints 驱动**：

```python
# src/experiment/generation.py（签名冻结）
def generate_trials(spec: ExperimentSpec) -> GeneratedExperiment:
    """纯函数：无 IO、无时间依赖、无隐藏状态。
    同 spec（含同 seed）→ 返回值逐字节相同（canonical JSON 比较，§5.4）。
    spec.paradigm 为 None 或插件未注册时走纯通用路径；声明插件时插件只增补派生逻辑。"""

class GeneratedExperiment(BaseModel):
    config_fingerprint: str       # sha256(canonical_json(spec))[:8]
    trials_fingerprint: str       # sha256(canonical_json(trials))[:8]
    engine_spec_version: str      # 引擎算法规范语义版本（§5.4）
    plugin_used: str | None       # 如 "stroop@1.0"；None = 纯通用路径
    trials: list[Trial]           # 全量物化

class Trial(BaseModel):
    index: int                    # 全局序（0 起）
    block: str
    factors: dict[str, str]       # 因素 → 水平名
    stimulus: dict[str, object]   # 通用路径为 {}；插件可物化（如 stroop: {"word": "red", "color": "blue"}）
    derived: dict[str, object]    # 通用路径为 {}；插件派生字段（correct_ink、correct_match...）
    timing: TimingSpec            # 物化的计时参数
```

**通用路径算法（确定性实现规范，逐条冻结）**：
1. 组合展开：按 `factors` 声明顺序的笛卡尔积（`itertools.product`），水平按 `levels` 声明序——声明序即确定性来源；
2. **有效权重**（每水平）：`constraints.ratios` 声明的因素用 ratios；未声明因素用 `Level.weight`（默认 1.0）按因素内归一化。组合权重 = 各因素水平有效权重之积；
3. 组合次数分配：block 内按组合权重对 `trial_count` 做 **largest remainder 整数分配**（确定性；余数并列时按组合声明序分配前 k 个——冻结的并列打破规则）；
4. block 切分：`factor_filter` 过滤可用组合（过滤后为空 → `BLOCK_FILTER_EMPTY` 验证错误）；每 block 独立完成分配；
5. 排序：`shuffle_within: true` → 用该 block 的派生 rng 洗牌；`false` → 按声明序输出（组合展开序）；
6. 约束执行：`max_repeat` / `mutually_exclusive` 用拒绝采样（每轮重洗限次 `max_attempts=100`，超限 → `CONSTRAINT_INFEASIBLE` 验证错误——确定性失败，非随机挂死）；
7. **禁止迭代 `set`**（迭代序不稳定）——任何集合先 `sorted()` 再用；dict 依赖 Python 保序语义（合法，文档化）；
8. 概率计算（频数、比例校验）全部在引擎内用确定性代码完成——**LLM 输出的 weight/ratios 只是意图声明，引擎是唯一计算权威**；
9. 全程 `datetime.now()` / `uuid` / 全局状态零接触（时间戳只出现在导出包 `generated_at` 元字段，**不参与任何 fingerprint**）。

### 5.3 可选：paradigm 插件（enhancement，非 dependency）

```python
# src/experiment/plugins/base.py
class ParadigmPlugin(Protocol):
    name: str                                          # 如 "stroop"
    version: str                                       # 插件语义版本（§5.4 导出记录）
    kind: Literal["derive", "sequence"]                # 能力声明（v2.1 新增，区分两类插件语义，见下）
    def derived_fields(self) -> list[str]: ...         # 本插件产出的派生字段名（correct_from 校验依据）
    def validate(self, spec: ExperimentSpec) -> list[ValidationIssue] | None: ...
    # 范式级校验钩子（v2.1 新增）：核心验证器在通用校验后调用被声明插件的此钩子并合并结果——
    # 范式知识（如 n-back 的 trial_count ≥ n+1）留在插件层，核心 validation.py 零范式知识（§② 红线闭合）
    def derive(self, spec: ExperimentSpec, trials: list[Trial],
               rng: random.Random) -> list[Trial]: ... # 对核心生成的 trials 增补 stimulus/derived（不改动因素分配）
    def generate_sequence(self, spec: ExperimentSpec,
                          rng: random.Random) -> list[Trial] | None: ...
    # 仅 kind="sequence" 实现并返回 list（覆写整个试次构造）；kind="derive" 返回 None（走核心组合路径）

PLUGINS: dict[str, ParadigmPlugin] = {}
# 注册表代码初始为空 dict；示例插件模块（plugins/stroop.py、plugins/nback.py）在 import 时自注册；
# 运行时是否默认装载示例插件，由 §⑩ 治理决策定（两种部署形态：空注册表的纯核心 / 含示例插件的完整发行）
```

**核心与插件的关系（冻结）**：
- `spec.paradigm is None` → 纯通用路径（§4.2 示例），**不触碰任何插件代码**；
- `spec.paradigm` 有值且插件已注册 → 按 `kind` 分流（见下）；
- `spec.paradigm` 有值但插件**未注册** → 验证错误 `UNKNOWN_PARADIGM`（含已注册插件清单）——**系统的可用性不依赖任何插件**：核心路径对全部用户始终可用；
- 新插件 = 新文件 + 注册表一行；schema、三工具、核心生成器零改动。Stroop/N-back 是随提案分发的**示例插件**，证明插件协议的表达力，不是系统部件。

**两类插件的能力边界与统计性质保证通道（v2.1 修正，消除 v2 的矛盾表述）**：

| | `kind="derive"`（增补型，如 stroop） | `kind="sequence"`（序列型，如 nback） |
|---|---|---|
| 试次构造 | **核心 combinator**（组合展开 + largest remainder 分配 + 洗牌/保序 + 约束执行） | **插件 `generate_sequence` 接管** |
| 因素分配与频数 | **核心强制**——插件只增补 stimulus/derived，不可能改动频数 | **插件按有效权重实现**——核心不参与分配 |
| 统计性质保证 | 核心算法事前保证（largest remainder + 拒绝采样） | **核心生成后校验**：实测频数与有效权重推出的期望数偏差超容差 → 验证错误 `PLUGIN_FREQUENCY_DEVIATION`（生成失败而非静默接受） |
| 范式级约束校验 | 插件 `validate` 钩子（可选） | 插件 `validate` 钩子（如示例插件的 trial_count ≥ n+1） |

即：**两条路径下统计性质都有强制通道**（derive 型事前强制、sequence 型事后校验）——插件无法在任一路径下静默破坏平衡性，但 sequence 型的频数精确性是"插件实现 + 核心校验"的合约结果，而非核心分配算法的直接产物（v2 把 §4.4 的 36/84 归因于 largest remainder 是错误的，v2.1 已改述）。

**通用约束的语义映射边界（v2.1 新增）**：插件可对通用约束字段作**范式级语义映射**（如 n-back 示例把 `max_repeat`——通用语义"同一水平连续出现上限"——映射为"同一字母连续呈现上限"），但映射必须在插件自身文档中显式声明，且不得改变约束的**强度语义**（上限仍是上限，不得放松为建议）。

### 5.4 可重复性契约（v2 完善核心）

**导出产物必须支持独立验证与重新生成**。契约四要素：

| 要素 | 内容 | 位置 |
|------|------|------|
| 原始 ExperimentSpec | 完整 spec 原文（**含 seed**）——重生成的唯一输入 | 导出包 `spec` 节（§⑦） |
| 引擎规范版本 | `engine_spec_version`（如 `"1.0"`）——**算法规范的语义版本，非代码哈希**：开源项目须跨实现可复现，任何兼容实现（遵循同一规范文档的 Python/C/JS 实现）产出相同 fingerprint | 导出包 + validate/generate 输出 |
| 插件版本 | `plugin_used`（如 `"stroop@1.0"`）；纯通用路径为 null | 导出包 + generate 输出 |
| 试次指纹 | `trials_fingerprint` = sha256(canonical JSON of trials)[:8] | 导出包 + 所有工具输出 |

**canonical JSON 规范（冻结，跨实现可复现的根基）**：`json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))`；float 用最短往返十进制表示（`repr` 语义）；trials 中**禁止** NaN/Inf。该规范随 `engine_spec_version` 版本化——规范变更 = 版本号递增 = 显式破坏性事件。

**conformance 测试向量集（v2.1：从开放问题升格为 `engine_spec_version` 1.0 的发布必选条件）**：引擎规范发布时必须附带一组**权威向量**——`(spec, canonical_json(trials), trials_fingerprint)` 三元组清单（覆盖：纯通用路径、derive 型插件路径、sequence 型插件路径、余数分配、拒绝采样边界）。任何宣称兼容的第三方实现须对全量向量复算出相同 canonical JSON 与 fingerprint 才可自称兼容。理由：跨语言实现复现隐含要求复刻 `random.Random` 的 MT19937 初始化、字符串种子 sha512 派生与 shuffle 消费序，以及 float 最短往返在不同语言间的边界差异——没有权威向量集，"独立、开源、跨实现可复现"不可证伪。向量集由本引擎的黄金文件（§8.4）直接导出，随 `engine_spec_version` 版本化。

**独立验证的两条路径（含义明确）**：
1. **重生成验证**：第三方用相同 spec（含 seed）+ 兼容版本（`engine_spec_version` 相同、插件版本相同）的实现重新生成，比对 `trials_fingerprint` 相等 → 证明序列可独立复现；
2. **仅验证（不重生成）**：对导出包的 `trials` 数组按 canonical JSON 规范做 sha256 → 与包内 `trials_fingerprint` 比对 → 证明导出文件未被篡改/损坏（完整性校验，不需要任何生成器实现）。

**验证方法（测试设计，§8.1 落实）**：同进程两次生成 canonical JSON 全等；跨 `PYTHONHASHSEED` 子进程 diff 为空；generate 与 export 的 fingerprint 相等；黄金文件 diff。

## ⑥ 验证-迭代循环设计

### 6.1 机器可读验证错误结构与约束规则（冻结）

```python
# src/experiment/validation.py
class ValidationIssue(BaseModel):        # warnings 与 errors 共用
    error_code: str                      # 稳定枚举（下表）
    path: str                            # JSON 路径，如 "constraints.ratios[0].ratios" / "factors[1].levels"
    message: str                         # 人类可读描述（含实际值）
    suggestion: str                      # 修复建议（LLM 行动指令）
```

**约束语义规则（C1~C3，v2 修正、v2.1 完善生效范围——消除 balance/ratios 冲突的未定义行为）**：
- **C1（互斥）**：`constraints.balance == true` 且 `ratios` 非空 → **验证错误** `CONSTRAINT_CONFLICT`（path: `constraints`，message 指明两者互斥，suggestion 二选一）；
- **C2（覆盖警告，v2.1 扩展生效范围）**：以下两种"显式权重被覆盖"情形均发警告 `WEIGHT_IGNORED`（不影响 valid 判定，保证"能通过验证"与"设计意图被覆盖"同时成立）：① `balance == true` 且任何 `Level.weight ≠ 1.0`（被全等权覆盖）；② `balance == false` 且某因素被 `ratios` 声明、该因素上存在显式 `Level.weight ≠ 1.0`（被 ratios 覆盖——有效权重按 C3 取 ratios）；
- **C3（有效权重）**：`balance == false` 时，因素水平有效权重 = `ratios`（若该因素被声明）> `Level.weight`（默认 1.0，因素内归一化）；ratios 值允许 0.0（显式排除该水平），和须 ≈1.0（容差 1e-6）否则 `RATIO_SUM`。

**error_code 稳定枚举（初版，v2.1 修订）**：`SCHEMA_INVALID`（Pydantic 层错误包装 + **block 名重复**——`BlockSpec.name` 须全 spec 唯一，重名会碰撞 §5.1 子流派生键）｜`RATIO_SUM`｜`CONSTRAINT_CONFLICT`（C1）｜`TRIAL_COUNT_MISMATCH`（**v2.1 澄清触发语义**：某 block 经 `factor_filter` 与有效权重（含 ratios 置 0 的水平）过滤后，可用正权重组合数为 0——请求 trial_count > 0 但组合空间已空）｜`CONSTRAINT_INFEASIBLE`（max_repeat / mutually_exclusive 等通用约束无法满足）｜`PLUGIN_FREQUENCY_DEVIATION`（**v2.1 新增**：sequence 型插件产出频数偏离有效权重容差——核心生成后校验，§5.3）｜`UNKNOWN_PARADIGM`（声明的插件未注册——核心路径无须插件，此错误只表示"声明了但环境没有"）｜`CORRECT_FROM_UNKNOWN`（correct_from 既非因素名、也非所声明插件的 derived_fields；纯通用路径只允许因素名）｜`MUTEX_VIOLATION`（mutually_exclusive 声明与因素结构使过滤后可用组合为空，或声明对同一因素内的两个水平——无意义声明）｜`BLOCK_FILTER_EMPTY`（factor_filter 圈定的水平在该 block 无对应组合）｜`ITERATION_STALLED`（§6.3）。**插件级校验**：范式特有规则（如示例插件的 trial_count ≥ n+1）经 `ParadigmPlugin.validate` 钩子产生 issue，与上述通用错误同构合并——**规则内容归插件层，核心 validation.py 零范式知识（§② 红线）**。警告码：`WEIGHT_IGNORED`（C2 两种情形）、`RATIO_ROUNDED`（分配存在余数舍入）。

`validate_experiment` 的 `ToolResult.result`（LLM 实际收到的 tool message content）：

```json
{"valid": false, "fingerprint": "9f3ab2c1", "engine_spec_version": "1.0",
 "errors": [
   {"error_code": "CONSTRAINT_CONFLICT", "path": "constraints",
    "message": "balance=true 与 ratios 非空互斥（当前 ratios 声明了 1 个因素）",
    "suggestion": "删除 ratios（全等权）或将 balance 置 false（用自定义比例）"}
 ]}
```

> 注：本示例是含约束冲突的另一份 spec，故 fingerprint 与 §4.2/§7.1（`1a2b3c4d`）不同——均为示意占位值（见头部声明）。

LLM 依据 `path` 定位字段、依据 `suggestion` 修改 spec、依据 `error_code` 判断修改类别——三者共同构成"定位-修改-复验"闭环。**§4.2/4.3/4.4 三个示例均通过上述规则自检**（自洽性数字见各节"自洽性"段）。

### 6.2 复用现有 AgentLoop（零改动论证）

- 工具结果回传链路（`src/agent/loop.py:129-144`）：`registry.execute` → `ToolResult` → tool message（`ok=True` 时 content=result 原文，即上节 JSON）→ 下一轮 LLM 输入。**验证报告作为正常 tool 结果进入对话，LLM 天然可读可改**——无需任何 loop 改动。
- 迭代 bounded：`settings.calc_agent_max_steps`（M1 默认 25）是硬上限。典型循环：`validate(失败) → LLM 改 spec → validate(通过) → generate → export → final`，5~8 步内完成；最坏情况被 max_steps 截断 → `failed` + final 必发——**死循环在 M1 机制下不可能无限运行**。
- 验证失败不带 `ERROR:` 前缀（§3.1 领域级/工具级两级契约），LLM 不会把"设计尚不合法"误判为"工具坏了"而绕开验证直接导出。

### 6.3 防死循环：重复错误终止策略

AgentLoop 无跨轮记忆、工具为纯函数（幂等性要求，§3.2），**服务端不引入会话状态**。防死循环采用三层组合：

1. **硬上限（已有）**：max_steps 截断——兜底保证终止；
2. **软引导（提示层）**：面向实验设计任务的 goal/系统提示模板建议"同一验证错误出现 2 次即应大幅修改或向用户澄清，而非重复提交"；
3. **协议层去重（可选输入字段，v2.1 修正触发语义）**：`ValidateExperimentInput.previous_errors`（§3.1 已含）——LLM 传入此前轮次的 `error_code:path` 指纹**列表**（每轮把当次验证 errors 的指纹追加进去）。工具保持无状态，判定规则：**任一指纹在 `previous_errors` 中已出现 ≥ 2 次 → `"stalled": true` + 错误 `ITERATION_STALLED`**（suggestion："停止重复提交，总结未解决冲突并请用户裁决"）。推演（与 §8.5 测试脚本逐轮对齐）：同一错误 f1 重复提交——第 1 次 prev=[]（f1 出现 0 次，通过并回传错误）；第 2 次 prev=[f1]（出现 1 次 < 2，仍回传）；第 3 次 prev=[f1, f1]（出现 2 次 ≥ 2 → stalled）。该语义与层 2 软引导（"同一验证错误出现 2 次即应大幅修改"）一致；状态由 LLM 侧维护，工具仍是纯函数。

FakeLLM 集成测试须覆盖两条路径：正常迭代（失败→修改→通过）与停滞（重复错误→`ITERATION_STALLED` 或 max_steps → 终止非挂死）（§8.5）。

## ⑦ 导出格式设计：ExperimentBundle 与 GameSpec 的关系

`export_experiment` 的落盘产物为 **ExperimentBundle（实验导出包）**——自包含、可独立验证（§5.4）。GameSpec 为独立文档，经双 fingerprint 引用 Bundle。

### 7.1 ExperimentBundle 结构（§4.2 纯通用示例的导出形态）

```json
{
  "schema_version": 1,
  "generated_at": "2026-10-20T12:00:00Z",
  "spec": {
    "schema_version": 1, "name": "cueing-generic", "version": "0.1.0", "seed": 11,
    "paradigm": null,
    "factors": [ {"name": "cue_type", "levels": [{"name": "valid"}, {"name": "invalid"}]},
                 {"name": "target_side", "levels": [{"name": "left"}, {"name": "right"}]} ],
    "blocks": [ {"name": "practice", "trial_count": 8}, {"name": "main", "trial_count": 80} ],
    "constraints": {"balance": true},
    "responses": [ {"name": "locate_target", "kind": "choice",
                    "options": ["left", "right"], "correct_from": "target_side"} ],
    "timing": {"fixation_ms": 400, "stimulus_ms": null, "isi_ms": 800}
  },
  "reproducibility": {
    "config_fingerprint": "1a2b3c4d",
    "trials_fingerprint": "5d21e0f7",
    "engine_spec_version": "1.0",
    "plugin_used": null,
    "effective_weights": {"cue_type": {"valid": 0.5, "invalid": 0.5},
                           "target_side": {"left": 0.5, "right": 0.5}},
    "allocation": {"practice": {"valid|left": 2, "valid|right": 2, "invalid|left": 2, "invalid|right": 2},
                    "main": {"valid|left": 20, "valid|right": 20, "invalid|left": 20, "invalid|right": 20}}
  },
  "trials": [
    {"index": 0, "block": "practice", "factors": {"cue_type": "valid", "target_side": "left"},
     "stimulus": {}, "derived": {},
     "timing": {"fixation_ms": 400, "stimulus_ms": null, "isi_ms": 800}}
  ],
  "summary": {"trial_count": 88, "blocks": ["practice", "main"],
              "frequency": {"cue_type": {"valid": 44, "invalid": 44},
                             "target_side": {"left": 44, "right": 44}}}
}
```

**格式契约要点**：
- **`spec` 节 = 规范化后的完整 ExperimentSpec**（v2.1 措辞精确化）：Pydantic 默认值字段可省略（示例中 paradigm_params/factor_filter/shuffle_within 省略即取默认），**fingerprint 对解析后的规范化对象计算**——因此"省略默认字段"与"补全默认字段"两种写法的 config_fingerprint 一致，重生成不依赖字面"原文"；
- **`reproducibility` 节**：双 fingerprint、`engine_spec_version`（算法规范语义版本）、`plugin_used`（含版本）、**参数摘要**（`effective_weights` 归一化后的实际有效权重 + `allocation` **按 block 为键**的每组合实际分配数——v2.1 补 practice 块，口径明示 per-block）——参数摘要让"意图 → 实际分配"的转换透明可审计；
- **`trials` 全量物化**：与 `GeneratedExperiment.trials` 逐字节一致（canonical JSON + sha256 == `trials_fingerprint`，§5.4 路径 2 的仅验证依据）；派生量（插件 stimulus/derived、计时）全部预算好——游戏端零实验逻辑；
- **落点**：`data/` 沙箱内（沿用 `file_write` 五步规则，§3.3）；建议命名 `experiments/<name>-v<version>-seed<seed>.json`；
- 通用路径的 `stimulus/derived` 为空对象——呈现素材由 GameSpec 的 `scene` 规则基于 `factors` 渲染（实验与表现解耦的体现）。

### 7.2 GameSpec 对 Bundle 的引用（导出关系）

```
ExperimentSpec ──(export_experiment: 物化)──► ExperimentBundle ──(trials_fingerprint 引用)──► GameSpec
```

- GameSpec（§4.5 schema）的 `experiment_ref` 携带 name/version/seed + **双 fingerprint**——游戏端加载时校验 ref 与 Bundle 一致才启动（防止呈现层与实验版本错配）；
- 游戏端运行时读 Bundle 的 `trials`（按序呈现）+ `responses`/`timing`（判定与计时），按 GameSpec 的 `scene/input/feedback/flow/gamification` 呈现与交互——**两层职责即 §4.0 边界表的运行时落实**；
- 本提案只定义格式与引用关系，**不实现游戏、不设计游戏机制 DSL 的深层细节**；GameSpec 的产出通道见开放问题 §⑩。

## ⑧ 测试与验收策略

**测试布局**（对齐现有 `tests/unit|integration`）：`tests/unit/experiment/`（schema/引擎/统计/工具/纯通用路径）+ `tests/integration/`（FakeLLM 设计迭代循环）+ `tests/golden/`（黄金文件）。

### 8.1 确定性/可重复性测试

| 测试名 | 断言 |
|--------|------|
| `test_generation_same_seed_byte_identical` | 同 spec 两次 `generate_trials`，canonical JSON 全等（同进程） |
| `test_generation_cross_process_stable` | 子进程以 `PYTHONHASHSEED=1` / `=2` 各跑一次生成脚本，输出 JSON `diff` 为空 |
| `test_generate_export_fingerprint_match` | `generate_trials.fingerprint == 导出包.reproducibility.trials_fingerprint` |
| `test_bundle_integrity_no_regen` | 仅验证路径：对导出包 trials 做 canonical JSON sha256 == 包内 fingerprint（§5.4 路径 2） |
| `test_block_isolation` | 增删一个 block 后，其余 block 的试次子序列逐字节不变（§5.1 子流设计证据） |

### 8.2 统计性质测试（固定 seed，断言数字与 §4 示例自洽）

| 测试名 | 断言 |
|--------|------|
| `test_frequency_balance_generic` | §4.2 通用示例 seed=11、88 试次：4 组合各 22；两因素各水平 44/44 |
| `test_frequency_balance_stroop` | §4.3 示例 seed=42、test block 96 试次：congruency 48/48；ink_color 32/32/32（整数分配精确断言，largest remainder 零余数） |
| `test_frequency_weight_nback` | §4.4 示例 seed=7、120 试次：match 恰 36 / nonmatch 84（**序列型插件**按有效权重 0.3/0.7 安排位点——归因是插件行为；核心 largest remainder 不参与，其职责是生成后频数校验，§5.3） |
| `test_sequence_plugin_frequency_guard` | 用测试桩插件（故意偏离权重的 sequence 输出）→ 核心生成后校验报 `PLUGIN_FREQUENCY_DEVIATION`（事后校验通道证据） |
| `test_max_repeat_respected` | 任一水平连续出现长度 ≤ max_repeat（全序列扫描） |
| `test_deterministic_rejection_sampling` | 约束紧的 spec（max_repeat=1）在 100 次重洗内收敛或确定性报 `CONSTRAINT_INFEASIBLE` |

统计断言用精确整数或比例容差（不引入 scipy；卡方临界值硬编码表为可选增强，开放问题 §⑩）。

### 8.3 schema 验证测试

`test_spec_rejects_*` 系列（非法 spec 拒绝用例）：缺 seed；ratios 和=0.9（`RATIO_SUM`）；**balance=true 且 ratios 非空（`CONSTRAINT_CONFLICT`，规则 C1）**；**block 名重复（`SCHEMA_INVALID`，§5.1 子流键依赖唯一性）**；**ratios 把某 block 的 factor_filter 圈定水平全部置 0 → 该 block 可用正权重组合为空（`TRIAL_COUNT_MISMATCH`，§6.1 澄清后的可构造触发）**；未知 paradigm（`UNKNOWN_PARADIGM`——注意纯通用路径 paradigm=null 合法，不触发）；`correct_from` 既非因素名也非插件派生字段（`CORRECT_FROM_UNKNOWN`）；factor_filter 过滤后无组合（`BLOCK_FILTER_EMPTY`）；**mutually_exclusive 声明使可用组合为空（`MUTEX_VIOLATION`）或声明同因素内两水平（`MUTEX_VIOLATION` 无意义声明）**；**示例插件路径 trial_count < n+1（`CONSTRAINT_INFEASIBLE`——经示例插件的 validate 钩子触发，核心无 n 概念，§5.3）**；**测试桩 sequence 插件频数偏离权重（`PLUGIN_FREQUENCY_DEVIATION`）**。另加警告用例：balance=true + 显式 weight（`WEIGHT_IGNORED` 情形①，C2）；balance=false + ratios 声明因素上的显式 weight（`WEIGHT_IGNORED` 情形②，v2.1 扩展）。断言 `valid==false`（或警告在场）且 errors 含对应 `error_code`/`path`/`suggestion`。

### 8.4 黄金文件（golden file）策略

- `tests/golden/cueing-generic-seed11.json`、`tests/golden/stroop-plugin-demo-seed42.json`、`tests/golden/nback-plugin-demo-seed7.json`（§4.2/4.3/4.4 三示例的完整导出包）——**通用路径与插件路径各至少一份黄金文件**；
- 测试 `test_golden_export_unchanged`：生成导出 → 与 golden 比对（语义 diff：解析 JSON 后比较，忽略 `generated_at`）；
- **更新流程**：`UPDATE_GOLDEN=1 pytest tests/golden` 重写文件 → 人工 review diff（seed/算法变更影响面）→ 提交。黄金文件变更必须在 PR 描述说明原因（引擎算法变更/插件逻辑修正——`engine_spec_version`/插件版本须同步递增）。

### 8.5 FakeLLM 集成测试（设计迭代全循环）

复用 M1 FakeLLM 注入模式（`AgentLoop(client=FakeLLM(script), registry=build_experiment_registry(settings), ...)`）：

| 测试名 | 脚本与断言 |
|--------|-----------|
| `test_design_iteration_success` | 脚本：[validate(balance+ratios 冲突的 spec) → valid:false+CONSTRAINT_CONFLICT, validate(修正后) → valid:true, generate, export, final]；断言：最终 completed、`data/` 下导出包存在且 fingerprint 一致、第二轮 FakeLLM 收到的 messages 含第一轮验证 JSON（迭代证据） |
| `test_design_iteration_stalled` | 脚本：三次提交含同一错误的 spec，previous_errors 逐轮累积（[] → [f1] → [f1,f1]）→ 第 3 次触发（f1 出现 2 次 ≥ 2，§6.3 新阈值数学可触发）收到 `ITERATION_STALLED` → final；断言终止且未导出 |
| `test_design_iteration_max_steps` | 脚本恒返回 validate(同一坏 spec) → max_steps 截断 → failed + final 必发（防挂死兜底证据） |
| `test_generic_path_no_plugin_end_to_end` | 脚本全程用 §4.2 纯通用 spec（validate→generate→export→final）；断言 plugin_used==null、导出包 stimulus/derived 为空对象、正确性判据来自因素名——**核心路径不依赖插件端到端证据** |

### 8.6 验收条目草案（未来实施时并入正式验收标准，本提案仅记录）

| ID | 条目 | 命令（示意） | 判据 |
|----|------|--------------|------|
| EX-1 | 确定性 | `pytest tests/unit/experiment -k determinism or cross_process` | 同 seed 两次生成 diff 为空 |
| EX-2 | 统计性质 | `pytest tests/unit/experiment -k frequency` | 固定 seed 频数精确/容差断言全绿 |
| EX-3 | 非法规格拒绝 | `pytest tests/unit/experiment -k rejects` | 全部返回机器可读 errors（含 CONSTRAINT_CONFLICT）；警告码独立断言 |
| EX-4 | 黄金文件 | `pytest tests/golden` | 语义 diff 为空；更新须走 UPDATE_GOLDEN 流程 |
| EX-5 | 迭代全循环 | `pytest tests/integration -k design_iteration` | 失败→修改→通过→导出全链路 FakeLLM 断言 |
| EX-6 | 导出物化完整性 | `pytest tests/unit/experiment -k export` | 导出包含原始 spec、可重复性元数据（双 fingerprint/engine_spec_version/plugin_used/参数摘要）、全量 trials；仅验证路径 sha256 校验通过 |
| EX-7 | 分层与幂等声明 | `python -m scripts.check_layers` + registry 自检 | 三工具 idempotency/risk_level 声明正确；无反向 import |
| EX-8 | 纯通用路径 | `pytest tests/unit/experiment tests/integration -k generic` | paradigm=null 全链路可用（核心不依赖插件） |

## ⑨ 对现有 M1 代码的影响评估

**结论：M1 既有文件零修改，仅新增文件（v2 重申，全文无任何要求改动 M1 的表述）。**

| 动作 | 文件 | 性质 |
|------|------|------|
| 新增 | `src/experiment/`（schemas/game_schemas/validation/generation/export/plugins/） | 新包，依赖 `src/models`、`src/config` |
| 新增 | `src/tools/experiment_tools.py` | 三工具（依赖 `src/experiment` + `src/models`） |
| 新增 | `src/agent/experiment_registry.py` | 组合注册（import 既有 `build_registry`，不改它） |
| 新增 | `tests/unit/experiment/`、`tests/golden/`、集成测试 | 测试 |
| **不改** | `src/agent/loop.py`、`src/agent/registry.py`、`src/agent/llm.py`、`src/models/*`、`src/tools/calc.py`、`src/tools/http_request.py`、`src/tools/file_write.py`、`src/agent/__init__.py`、`src/config.py` | AgentLoop/Registry/三工具/事件模型原样复用（§6.2 已论证零改动） |

两个实施期注意点（如实声明，均**不触碰 M1 代码**）：
1. **G-4 分层规则**：新层 `experiment` 位于 tools 之下（`agent → tools → experiment → models/config`）。`scripts/check_layers.py`（M0 交付的门禁脚本）若按显式图层白名单实现，需要一行规则扩展——**这是门禁配置变更而非 M1 产品代码修改**，实施时作为独立小变更提请 Lead 批准；若脚本按目录约定推断则零改动。
2. **沙箱写规则复用**：`export_experiment` 落盘须与 `file_write` 同规则。默认方案：新增 `src/tools/_sandbox_io.py` 共享 helper（新文件，按 `file_write.py` 的五步规则实现为可复用函数，export 使用之）；`file_write.py` **不迁移不改**（helper 与其逻辑并行存在，注明同步义务）。

## ⑩ 开放问题与风险（留给用户决策）

> v2.1：原第 5 条"canonical JSON 跨实现规范维护 / conformance 向量集"已按 QA 建议（SG-1）**升格为 `engine_spec_version` 1.0 的发布必选条件**（§5.4），不再是开放问题。

1. **GameSpec 的产出通道**：LLM 在对话中直接生成 GameSpec JSON（与 ExperimentSpec 同模式），还是未来提供 `design_game`/`export_game` 工具？本提案只冻结 schema 与引用关系（§4.5/§7.2）。
2. **插件治理与分发**：示例插件（stroop/nback）随仓库分发还是移到独立 examples 目录以免被误认为"官方范式支持"？运行时是否默认装载示例插件（§5.3 两种部署形态）？新插件是否强制附带黄金文件与统计测试才准合入？
3. **numpy 是否引入**：设计为**不引入**（`random.Random` + 标准库覆盖当前需求，受 ARCHITECTURE §2.1 依赖红线约束）。未来需要复杂抽样（分层/精确拉丁方）须先走依赖变更流程。风险：largest remainder 在极端比例下与"完美平衡"有 ±1 偏差——黄金文件显式暴露。
4. **`ITERATION_STALLED` 的 previous_errors 协议**：状态放 LLM 侧保持工具纯函数（§6.3 方案 3），依赖 LLM 如实回传——是"软协议"。是否接受，或只靠 max_steps + 提示？
5. **导出大小上限**：1MB（沿用 file_write）约容纳 ~5k 试次。超大实验是否需要分块导出或多文件包（bundle 目录）？
6. **与 M2 的交汇**：`generate_trials`/`validate_experiment` 幂等声明天然适配 M2 恢复矩阵（uncertain 自动重试安全）；`export_experiment` 非幂等、与 file_write 同级。本提案刻意不设计 M2 交互细节，待 M2 契约冻结时对齐。

## 变更记录

### v2 → v2.1（QA 审查修复轮，依据 docs/handoff/qa-proposal-v2-review.md）

**Major 修复（3/3）**：
1. **MA-1**：§6.3 ITERATION_STALLED 触发阈值由"当前 errors 与 previous_errors 交集 ≥3 个指纹"（单指纹重复提交在数学上不可触发）改为"**任一指纹在 previous_errors 中出现 ≥2 次**"，附逐轮推演（[]→[f1]→[f1,f1]，第 3 次触发）与 §8.5 测试脚本逐轮对齐；语义与层 2 软引导一致。
2. **MA-2**：§5.3 重写插件能力边界——新增 `kind: Literal["derive","sequence"]` 能力声明字段与两类插件边界表（derive 型：因素分配与频数由核心 combinator 事前强制；sequence 型：频数由插件按有效权重实现、核心**生成后校验**，偏差超容差 → 新增错误码 `PLUGIN_FREQUENCY_DEVIATION`）；"插件无法破坏平衡性"改为"两条路径下统计性质都有强制通道（事前强制 / 事后校验）"；§4.4 N-back 的 36/84 归因由"largest remainder 零余数"（错误：序列型不走该路径）改述为"插件按 0.3/0.7 安排位点、核心事后校验"；§8.2 断言归因同步并新增 `test_sequence_plugin_frequency_guard`。
3. **MA-3**：`ParadigmPlugin` 协议新增 `validate(spec) -> list[ValidationIssue] | None` 钩子——核心验证器在通用校验后调用被声明插件的钩子并合并结果，范式知识（如 n-back 的 trial_count ≥ n+1）留在插件层，§② 通用性红线闭合；§4.4/§6.1/§8.3 的序列型校验表述改为"经示例插件 validate 钩子触发，核心无 n 概念"。

**Minor 修复（7/7，全部采纳）**：
- MI-1：指纹占位值统一——§3.1 示例改为与 §7.1 同值（`1a2b3c4d`，同 §4.2 spec）；头部声明全文 fingerprint 均为示意占位值。
- MI-2：§7.1"原始 spec 完整原文"改为"**规范化后的完整 spec**（默认值可省略，fingerprint 对解析后对象计算）"，消除与示例省略默认字段的矛盾。
- MI-3：§8.3 补 `MUTEX_VIOLATION` 用例（互斥声明使可用组合为空 / 同因素内两水平）。
- MI-4：`TRIAL_COUNT_MISMATCH` 触发语义澄清为"某 block 经 factor_filter 与有效权重（含 ratios 置 0）过滤后可用正权重组合为 0"；§8.3 给出可构造输入（ratios 置 0 + filter 圈定）；C3 补"ratios 值允许 0.0"。
- MI-5：`BlockSpec.name` 唯一性约束（重复 → `SCHEMA_INVALID`，§5.1 子流键依赖），§4.1/§6.1/§8.3 三处同步。
- MI-6：C2/`WEIGHT_IGNORED` 警告适用范围扩展至两种情形（balance 覆盖 weight / ratios 覆盖 weight），§8.3 补情形②警告用例。
- MI-7：§7.1 `allocation` 明示 **per-block 口径**并补 practice 块（每组合 2）。

**Suggestion 处理（4/4）**：
- SG-1 **采纳**（用户指示）：conformance 测试向量集从 §⑩.5 开放问题**升格为 `engine_spec_version` 1.0 发布必选条件**（§5.4 新增段落：权威 `(spec, canonical_json, fingerprint)` 三元组，由黄金文件导出，兼容实现须全量通过）；§⑩ 重编号并注明升格。
- SG-2 **采纳**：`GameSpec.game` 由弱类型 `dict[str, str]` 改为强类型嵌套模型 `GameMeta(name, version)`（§4.5）。
- SG-3 **采纳**：`PLUGINS` 注册表注释澄清为"代码初始为空 dict，示例插件模块 import 时自注册，运行时是否默认装载由 §⑩ 治理决策定"（§5.3）。
- SG-4 **采纳**：§5.3 新增"通用约束的语义映射边界"段 + §4.4 标注 max_repeat 的字母语义映射示例；约束强度语义不得放松。

**一致性同步**：§8.5 stalled 脚本、§8.2 归因与新增 guard 测试、§8.3 拒绝用例集、§⑩ 列表重编号；全文术语与数字复扫（示意指纹值、归因表述、错误码闭环均已对齐）。

### v1 → v2（按用户 6 点意见修订）

1. **通用组合生成器与范式插件分离**（修订点 1）：§⑤ 重构为 §5.2 核心 factorial combinator（零范式知识、纯 schema 驱动）+ §5.3 可选插件（`ParadigmPlugin` 协议、注册表初始为空、paradigm=None 走纯通用路径、插件不可用性不影响系统可用性）；新增 §4.2 纯通用路径示例；§② 新增"通用性红线"；Stroop/N-back 全文降格为"插件示例"（§4.3/4.4 标题与 §⑩ 治理问题）。
2. **ExperimentSpec 与 GameSpec 分层**（修订点 2）：ExperimentConfig 统一更名 ExperimentSpec；新增 §4.0 职责边界表（字段归属冻结）与 §4.5 GameSpec schema 草案；§⑦ 重构为 ExperimentBundle（实验导出包）+ GameSpec 经双 fingerprint 引用的导出关系，落实"实验逻辑与游戏表现解耦"铁律。
3. **修正 balance/ratios 冲突**（修订点 3）：§6.1 新增约束规则 C1（balance 与 ratios 互斥 → `CONSTRAINT_CONFLICT` 错误）/C2（balance 覆盖 weight → `WEIGHT_IGNORED` 警告）/C3（有效权重优先级）；§4 全部示例重写并逐示例自查数字自洽（§4.2：4 组合×22；§4.3：6 组合、congruency 48/48、ink 32/32/32；§4.4：0.3×120=36 精确整数）；§8.2/8.3 统计断言与拒绝用例同步更新。
4. **完善可重复性契约**（修订点 4）：§5.4 重写为契约四要素（原始 spec 含 seed、engine_spec_version 算法规范语义版本而非代码哈希、插件版本、trials fingerprint）+ canonical JSON 规范冻结 + 独立验证两路径（重生成比对 fingerprint / 仅验证 sha256 完整性校验）；§⑦ 导出包新增 `spec` 原文与 `reproducibility` 节（含 effective_weights/allocation 参数摘要）；§8.1/8.6 补对应测试与验收项。
5. **无理论硬编码声明**（修订点 5）：§② 通用性红线明确 core schema/验证器/核心生成器零范式零理论名词、引擎不内嵌任何认知理论假设；全文扫描确认范式知识仅存于插件层与 paradigm/paradigm_params 自由字段。
6. **M1 零修改重申**（修订点 6）：§⑨ 明确"全文无任何要求改动 M1 的表述"；check_layers 规则扩展明确为门禁配置变更、实施时提请批准（非 M1 代码修改）。
7. 命名统一：ExperimentConfig → ExperimentSpec；错误码枚举补 `CONSTRAINT_CONFLICT`/`ITERATION_STALLED`、警告码 `WEIGHT_IGNORED`；头部更新产品边界与 v2 状态行。

---

> **再次声明：本文件为提案（proposal）v2.1。未获用户批准前不实施——不写代码、不改正式文档（ARCHITECTURE/ROADMAP/ACCEPTANCE_CRITERIA）、不推进 M2。批准后由 Architect 将本提案要点升格为正式契约（届时版本递增、变更记录落 ARCHITECTURE.md），Backend 按契约实施。**
