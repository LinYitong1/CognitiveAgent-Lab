# 提案：实验工具扩展设计 — generate_trials / validate_experiment / export_experiment

> 状态：**提案（proposal）——未获用户批准前不实施，不写入任何代码**
> 作者：Architect Agent ｜ 日期：2026-10-20
> 产品方向：CognitiveAgent Lab — AI Agent for Game-Based Cognitive Experiment Design and Evaluation（游戏化认知实验设计与评估）
> 现实基础（已读真实代码，本文所有签名/路径均据此）：
> - `src/models/tool_spec.py` — `ToolSpec(BaseModel)`：`name / description / input_model: type[BaseModel] / idempotency: Literal["idempotent","non-idempotent"] / risk_level: Literal["low","medium","high"] / executor: Callable[[BaseModel], Awaitable[ToolResult]]`，含 `effective_idempotency(args)` 方法
> - `src/agent/registry.py` — `ToolRegistry.register(spec) -> None`（校验失败抛 `ToolRegistryError`）、`execute(name, args) -> ToolResult`（未知工具/参数校验失败/executor 异常一律返回 `ToolResult(ok=False)`，不外抛）
> - `src/agent/loop.py` — `AgentLoop.run_task(goal)`：工具失败以 `ERROR:` 前缀 tool message 回传 LLM 自纠；`settings.calc_agent_max_steps` 为硬上限；终态必发 `final`
> - `src/tools/calc.py` / `src/tools/file_write.py` — 工具实现风格参照：`XxxInput(BaseModel)` + 内部 `_XxxBlocked` 异常 + `BLOCKED:` 前缀 + `build_tool_spec(settings: Settings) -> ToolSpec` 工厂
> - `src/agent/__init__.py` — `build_registry(settings) -> ToolRegistry`（注册 M1 三工具）
> - 本提案**独立于里程碑**（不推进 M2 SQLite 持久化设计），是未来"实验工具扩展"阶段的设计输入。

---

## ① 产品定位与范围

**定位**：Agent 扮演"认知实验设计者"——与用户对话理解研究意图，产出结构化实验配置（`ExperimentConfig`），经确定性引擎验证、展开为试次序列，导出为未来网页游戏可直接呈现的 JSON。

**范围（本提案覆盖）**：
- 三个新工具：`generate_trials`（试次生成）、`validate_experiment`（配置验证）、`export_experiment`（导出游戏格式）；
- `ExperimentConfig` Pydantic schema 草案（以 Stroop 与 N-back 两范式验证表达力）；
- 确定性生成/验证引擎设计；
- 验证-迭代循环（Agent 依据验证错误修改设计）；
- 导出 JSON 格式契约；
- 测试与验收策略草案。

**明确不在本提案范围**：网页游戏本体（M3+ 或更后）、被试数据回收/评估分析、M2 持久化、多实验管理。

## ② 总体思路：职责边界（提案核心）

```
LLM（设计决策）                确定性 Python 代码（生成与验证）
┌──────────────────┐          ┌──────────────────────────────┐
│ 理解研究意图       │          │ validate_experiment: 校验 config │
│ 撰写/修改 config  │ ──工具──► │ generate_trials: 展开试次序列    │
│ 根据验证错误迭代   │ ◄─回传──  │ export_experiment: 物化导出 JSON │
│ 汇报设计结果       │          │ 概率/随机化/算术：全部在此         │
└──────────────────┘          └──────────────────────────────┘
```

**分工铁律**：
1. **LLM 不做算术**——概率、频数、平衡、随机化全部由确定性代码执行（LLM 输出的数字仅作为设计意图声明，一律经引擎验证/计算）。这延续 M1 的既有事实：`calc` 工具存在的意义即是"算术不信任 LLM"。
2. **引擎不做决策**——因素怎么选、比例定多少、范式用什么，是 LLM 与用户的对话产物；引擎只负责忠实、可重复地物化。
3. **同 config + 同 seed → 逐字节相同输出**——可重复性是科研底线，由纯函数引擎保证（§⑤）。

由此，三个工具在 M1 `ToolRegistry` 看来只是**三个新的注册项**，AgentLoop、事件模型、错误回传机制全部原样复用。

## ③ 三工具 ToolSpec 设计

新模块：`src/tools/experiment_tools.py`（单文件三工具，风格对齐 `calc.py`/`file_write.py`：Input 模型 + `BLOCKED:` 前缀 + `build_tool_spec(settings)` 工厂）。共享引擎代码位于新包 `src/experiment/`（§⑤），`src/tools/` 依赖它（分层方向 `agent → tools → experiment → models/config`，见 §⑨）。

### 3.1 validate_experiment — 配置验证（幂等、只读）

```python
class ValidateExperimentInput(BaseModel):
    config: dict[str, object]      # ExperimentConfig 的 JSON 对象（LLM 直接内联生成，无需先落盘）

# build_tool_spec 返回：
ToolSpec(
    name="validate_experiment",
    description="校验实验配置的 schema 合法性与语义约束（比例和、试次数、约束可满足性）。"
                "返回机器可读的验证报告（错误含 error_code/path/suggestion），供修改 config 后重验。",
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
  "fingerprint": "9f3ab2c1",       // sha256(canonical_json(config))[:8]，迭代对齐锚点
  "warnings": [{"code": "RATIO_ROUNDED", "path": "constraints.ratios", "message": "..."}],
  "stats": {"trial_count": 96, "factor_count": 2, "blocks": 3}
}
```

**错误返回契约（两级，冻结）**：
- **领域级（验证不通过）**：`ToolResult(ok=True)` + `result` 含 `"valid": false` 与 `errors` 数组（§⑥ 的机器可读错误结构）。理由：验证发现 config 问题是**有效结果**而非工具失败，回传 LLM 时不带 `ERROR:` 前缀，与"工具坏了"明确区分。
- **工具级失败**：仅限输入非 dict、JSON 序列化失败等基础设施错误——沿用 `registry.execute` 的 `ok=False` 路径（`invalid arguments: ...`），不外抛。安全拒绝（如 config 体积超限 256KB）→ `BLOCKED: config too large`。

### 3.2 generate_trials — 试次生成（幂等、纯函数、不落盘）

```python
class GenerateTrialsInput(BaseModel):
    config: dict[str, object]
    max_preview_trials: int = Field(default=8, ge=0, le=50)   # 回传 LLM 的试次预览条数

ToolSpec(
    name="generate_trials",
    description="按实验配置确定性生成完整试次序列（同 config+seed 结果逐字节相同）。"
                "返回序列指纹、各因素水平频数统计与试次预览；不写任何文件，"
                "完整序列由 export_experiment 用同一 config+seed 物化。",
    input_model=GenerateTrialsInput,
    idempotency="idempotent",      # 纯函数：同输入同输出，无副作用（可安全重试，M2 恢复矩阵友好）
    risk_level="low",
    executor=...,
)
```

**输出结构**：

```json
{
  "fingerprint": "5d21e0f7",            // sha256(导出 trials 数组的 canonical JSON)[:8]
  "trial_count": 96,
  "frequency": {                         // 统计性质摘要（LLM 核对设计意图的依据）
    "congruency": {"congruent": 48, "incongruent": 48},
    "ink_color": {"red": 32, "green": 32, "blue": 32}
  },
  "preview": [ {"index": 0, "block": "block-1", "factors": {...}, "derived": {...}}, ... ],
  "note": "full sequence reproducible via export_experiment with identical config"
}
```

**设计要点**：完整试次序列**不进 ToolResult.result**（可能数百 KB，超出 512 字符摘要契约且污染 LLM 上下文）——result 只含指纹与统计。完整序列的交付通道是 `export_experiment`（同 config+seed 由纯函数性质保证两工具产出一致，§⑤ 验证方法）。**一致性是可断言的**：`generate_trials.fingerprint == export_experiment` 导出文件中记录的 `trials_fingerprint`，测试与验收均以此断言。

**错误返回契约**：config 无效（schema/语义/约束不可满足）→ `ok=True` + `"valid": false` + errors（与 validate_experiment 同构，实现上直接复用同一验证函数）；工具级失败走 registry 路径。

### 3.3 export_experiment — 导出游戏格式（非幂等、落盘）

```python
class ExportExperimentInput(BaseModel):
    config: dict[str, object]
    path: str = Field(min_length=1)   # 相对 data/ 沙箱根的输出路径（建议 .json 后缀）

ToolSpec(
    name="export_experiment",
    description="把实验配置物化为游戏可读的完整 JSON（试次全量展开、correct_response 预计算、"
                "游戏端零计算逻辑），写入 data/ 沙箱内指定路径。",
    input_model=ExportExperimentInput,
    idempotency="non-idempotent",    # 写文件（覆盖语义），与 file_write 同级
    risk_level="medium",             # 与 file_write 同级（沙箱写）
    executor=...,
)
```

**输出**：`ToolResult(ok=True, result=f"wrote {path} ({bytes} bytes, trials_fingerprint={fp})")`。

**落盘安全规则**：完全沿用 `file_write` 的五步沙箱规则（`..` 拒绝 → realpath + `is_relative_to` 组件边界 → lstat 各级目录无符号链接 → 大小上限 → 沙箱内自动建目录）。实现上，导出内容仍须过 1MB 上限（超大实验导出失败 → `BLOCKED: export too large`，提示分块导出——开放问题 §⑩）。实现路径见 §⑨（共享 helper vs 规则复制的取舍，**不改 file_write.py 本体**）。

**错误返回契约**：config 无效 → 先验证，`ok=True` + valid:false（不导出无效实验）；沙箱违规 → `BLOCKED:` 前缀（对齐 M1 惯例）；其余工具级失败走 registry 路径。

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

## ④ ExperimentConfig schema 草案

新模块 `src/experiment/schemas.py`。核心结构（Pydantic v2）：

```python
class Level(BaseModel):
    name: str
    weight: float = Field(default=1.0, gt=0)          # 组合采样权重（比例意图，引擎整数化）

class Factor(BaseModel):
    name: str = Field(min_length=1)
    levels: list[Level] = Field(min_length=1)          # 水平（有序——展开顺序的确定性来源）

class RatioRule(BaseModel):
    factor: str
    ratios: dict[str, float]                            # level name -> 比例；和须 ≈1.0（容差 1e-6）

class Constraints(BaseModel):
    balance: bool = False                               # 各因素水平等比例（与 ratios 互斥声明）
    ratios: list[RatioRule] = Field(default_factory=list)
    max_repeat: int | None = None                       # 同一水平连续出现上限（防 streak，如 3）
    mutually_exclusive: list[list[str]] = Field(default_factory=list)  # 禁止同现的水平名对（跨因素）

class ResponseVar(BaseModel):
    name: str                                           # 如 "classify_ink"
    kind: Literal["choice", "text", "rating"]
    options: list[str] = Field(default_factory=list)    # choice 用
    scale: tuple[int, int] | None = None                # rating 用 (min, max)
    correct_from: str | None = None                     # 试次派生字段名（准确率判据），如 "correct_ink"

class BlockSpec(BaseModel):
    name: str
    trial_count: int = Field(gt=0)
    factor_filter: dict[str, list[str]] = Field(default_factory=dict)  # 该 block 只含指定水平
    shuffle_within: bool = True

class TimingSpec(BaseModel):
    fixation_ms: int = 500
    stimulus_ms: int | None = None                      # None = 直至响应
    isi_ms: int = 1000

class ExperimentConfig(BaseModel):
    schema_version: Literal[1] = 1                      # 导出兼容锚点（§⑦）
    name: str = Field(min_length=1)
    version: str = "0.1.0"
    seed: int                                           # 必填——确定性源头（§⑤）
    paradigm: str                                       # "stroop" | "nback" | ...（生成器注册表键，§⑤）
    paradigm_params: dict[str, object] = Field(default_factory=dict)  # 范式私有参数（n、字母表等）
    factors: list[Factor] = Field(min_length=1)
    blocks: list[BlockSpec] = Field(min_length=1)
    constraints: Constraints = Constraints()
    responses: list[ResponseVar] = Field(min_length=1)
    timing: TimingSpec = TimingSpec()
```

**范式私有逻辑的边界**：`paradigm + paradigm_params` 表达范式特定输入（如 N-back 的 n、字母表），而**派生字段与 correct_response 的计算规则**由范式生成器插件（§⑤ 的 generator 注册表）实现——schema 保持范式无关的通用骨架，范式细节不进 schema 结构（否则每加一个范式都要改 schema 结构本身）。

### 4.1 范例一：Stroop 任务（最小配置）

```json
{
  "schema_version": 1,
  "name": "stroop-standard",
  "version": "1.0.0",
  "seed": 42,
  "paradigm": "stroop",
  "factors": [
    {"name": "word_color", "levels": [{"name": "red"}, {"name": "green"}, {"name": "blue"}]},
    {"name": "ink_color",  "levels": [{"name": "red"}, {"name": "green"}, {"name": "blue"}]}
  ],
  "blocks": [
    {"name": "practice", "trial_count": 12, "factor_filter": {}, "shuffle_within": true},
    {"name": "test",     "trial_count": 96, "factor_filter": {}, "shuffle_within": true}
  ],
  "constraints": {
    "balance": true,
    "ratios": [{"factor": "word_color", "ratios": {"red": 0.34, "green": 0.33, "blue": 0.33}}]
  },
  "responses": [
    {"name": "classify_ink", "kind": "choice", "options": ["red", "green", "blue"], "correct_from": "correct_ink"}
  ],
  "timing": {"fixation_ms": 500, "stimulus_ms": null, "isi_ms": 1000}
}
```

表达力检查：✅ 2 因素×3 水平、练习/测试分块、`word_color` 比例微调（34/33/33）、congruency 由生成器派生（`word_color==ink_color`）无须显式建模、按键反应与正确答案（`correct_ink`）齐备。

### 4.2 范例二：N-back 任务（最小配置）

```json
{
  "schema_version": 1,
  "name": "nback-2letter",
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

表达力检查：✅ 2-back（paradigm_params.n）、字母表约束、match/nonmatch 0.3/0.7 权重、**序列型范式**（`shuffle_within: false`——N-back 的试次序列有先后依赖，生成器按序列约束构造而非洗牌；match 位点由生成器安排且 `correct_match` 物化为 "yes"/"no"）、防同一字母连续 streak（max_repeat）。

## ⑤ 确定性引擎设计

新包 `src/experiment/`：`schemas.py`（§④）、`validation.py`（§⑥）、`generation.py`、`export.py`、`generators/`（范式插件：`stroop.py`、`nback.py`）。

### 5.1 seed 全链路传递

```
ExperimentConfig.seed (int, 必填)
  └─ 每实验一个根 rng: random.Random(config.seed)              # 引擎入口创建，绝不触全局 random
       └─ 每 block 派生子流: random.Random(f"{seed}:block:{block.name}")
```

- **唯一随机源**：引擎代码**禁止** `import random` 的模块级函数（`random.random()` 等），只允许 `random.Random` 实例；code-review 门禁项（正则可查）。
- **派生子流跨进程稳定**：CPython `random.Random(str)` 对字符串种子走 sha512 派生（与 `PYTHONHASHSEED` 无关的 documented 行为），且根 seed 为 int 完全无歧义——跨进程/跨 `PYTHONHASHSEED` 可重复（验证方法 §⑧）。
- 子流而非单流贯穿的理由：block 独立派生使得"增删一个 block 不扰动其他 block 的序列"（科研迭代友好），且派生式可写进文档供第三方复现。

### 5.2 试次生成 = 纯函数

```python
# src/experiment/generation.py（签名冻结）
def generate_trials(config: ExperimentConfig) -> GeneratedExperiment:
    """纯函数：无 IO、无时间依赖、无隐藏状态。
    同 config（含同 seed）→ 返回值逐字节相同（model_dump_json 比较）。"""

class GeneratedExperiment(BaseModel):
    config_fingerprint: str       # sha256(canonical_json(config))[:8]
    trials_fingerprint: str       # sha256(canonical_json(trials))[:8]
    trials: list[Trial]           # 全量物化（含派生字段与 correct_response，§⑦）

class Trial(BaseModel):
    index: int                    # 全局序（0 起）
    block: str
    factors: dict[str, str]       # 因素 → 水平名
    stimulus: dict[str, object]   # 范式生成器产出（如 stroop: {"word": "red", "color": "blue"}）
    derived: dict[str, object]    # 派生字段（congruency、correct_ink、correct_match...）
    timing: TimingSpec            # 物化的计时参数
```

**确定性实现规范（逐条冻结，实施与评审依据）**：
1. 因素组合展开按 `factors` 声明顺序的笛卡尔积（`itertools.product`），水平按 `levels` 声明序——声明序即确定性来源；
2. 权重/比例 → 每组合次数的整数分配用 **largest remainder 法**（确定性的经典整除分配；禁止浮点取整导致的平台/顺序抖动）；
3. **禁止迭代 `set`**（迭代序不稳定）——任何集合先 `sorted()` 再用；dict 依赖 Python 保序语义（合法，文档化）；
4. 拒绝采样（max_repeat / mutually_exclusive / N-back 序列约束）每轮重洗限次（`max_attempts=100`），超限返回约束不可满足的验证错误（确定性失败，非随机挂死）；
5. 概率计算（频数、比例校验）全部在引擎内用确定性代码完成——**LLM 输出的 weight/ratios 只是意图声明，引擎是唯一计算权威**；
6. 全程 `datetime.now()` / `uuid` / 全局状态零接触（时间戳只允许出现在导出文件的 `generated_at` 元字段，且**不参与 trials_fingerprint**——指纹只覆盖 trials 数组）。

### 5.3 范式生成器插件（generator 注册表）

```python
# src/experiment/generators/base.py
class ParadigmGenerator(Protocol):
    def expand(self, config: ExperimentConfig, rng: random.Random) -> list[Trial]: ...
    def derived_fields(self) -> list[str]: ...   # 本范式产出的派生字段名（correct_from 校验依据）

GENERATORS: dict[str, ParadigmGenerator] = {"stroop": StroopGenerator(), "nback": NBackGenerator()}
```

- `stroop`：组合展开 + 派生 `congruency`（`word_color==ink_color`）与 `correct_ink`（= ink_color 水平名）；
- `nback`：按 match 位点安排 + 序列约束生成字母流，派生 `correct_match`（"yes"/"no"）；
- 未知 paradigm → 验证错误 `UNKNOWN_PARADIGM`（含已支持清单）——新范式扩展 = 新增插件文件 + 注册表加一行，schema 与三工具零改动。

### 5.4 可重复性验证方法（设计）

- **同进程**：`generate_trials(config)` 两次，`model_dump_json()` 逐字符串比较相等；
- **跨进程**：`PYTHONHASHSEED` 设两个不同值各跑一次生成，输出文件 `diff` 为空；
- **跨工具**：`generate_trials` 的 `trials_fingerprint` == `export_experiment` 导出文件内 `trials_fingerprint`；
- **黄金文件**：固定范例 config（§4.1/4.2）+ 固定 seed，生成结果落 `tests/golden/`，CI diff（§⑧）。

## ⑥ 验证-迭代循环设计

### 6.1 机器可读验证错误结构（冻结）

```python
# src/experiment/validation.py
class ValidationIssue(BaseModel):        # warnings 与 errors 共用
    error_code: str                      # 稳定枚举（下表）
    path: str                            # JSON 路径，如 "constraints.ratios[0].ratios" / "factors[1].levels"
    message: str                         # 人类可读描述（含实际值）
    suggestion: str                      # 修复建议（LLM 行动指令，如 "将比例和调整为 1.0（当前 0.9）"）
```

**error_code 稳定枚举（初版）**：`SCHEMA_INVALID`（Pydantic 层错误的包装，逐字段转 issue）｜`RATIO_SUM`｜`TRIAL_COUNT_MISMATCH`（blocks 总数与约束推出数不符）｜`CONSTRAINT_INFEASIBLE`（max_repeat 等无法满足）｜`UNKNOWN_PARADIGM`｜`CORRECT_FROM_UNKNOWN`（correct_from 不在该范式 derived_fields）｜`MUTEX_VIOLATION`｜`BLOCK_FILTER_EMPTY`（factor_filter 过滤后无可用组合）。

`validate_experiment` 的 `ToolResult.result`（LLM 实际收到的 tool message content）：

```json
{"valid": false, "fingerprint": "9f3ab2c1",
 "errors": [
   {"error_code": "RATIO_SUM", "path": "constraints.ratios[0].ratios",
    "message": "sum=0.9 (red=0.34, green=0.33, blue=0.23)", "suggestion": "调整 ratios 使和为 1.0"}
 ]}
```

LLM 依据 `path` 定位字段、依据 `suggestion` 修改 config、依据 `error_code` 判断修改类别——三者共同构成"定位-修改-复验"闭环。

### 6.2 复用现有 AgentLoop（零改动论证）

- 工具结果回传链路（`src/agent/loop.py:129-144`）：`registry.execute` → `ToolResult` → tool message（`ok=True` 时 content=result 原文，即上节 JSON）→ 下一轮 LLM 输入。**验证报告作为正常 tool 结果进入对话，LLM 天然可读可改**——无需任何 loop 改动。
- 迭代 bounded：`settings.calc_agent_max_steps`（M1 默认 25）是硬上限。典型循环：`validate(失败) → LLM 改 config → validate(通过) → generate → export → final`，5~8 步内完成；最坏情况被 max_steps 截断 → `failed` + final 必发——**死循环在 M1 机制下不可能无限运行**。
- 验证失败不带 `ERROR:` 前缀（§3.1 领域级/工具级两级契约），LLM 不会把"设计尚不合法"误判为"工具坏了"而绕开验证直接导出。

### 6.3 防死循环：重复错误终止策略

AgentLoop 无跨轮记忆、工具为纯函数（幂等性要求，§3.2），**服务端不引入会话状态**。防死循环采用三层组合：

1. **硬上限（已有）**：max_steps 截断——兜底保证终止；
2. **软引导（提示层）**：面向实验设计任务的 goal/系统提示模板建议"同一验证错误出现 2 次即应大幅修改或向用户澄清，而非重复提交"；
3. **协议层去重（本提案新增的可选输入字段）**：`ValidateExperimentInput` 增加可选 `previous_errors: list[str]`（LLM 传入此前轮次的 `error_code:path` 指纹列表）。工具保持无状态——若当前验证的 errors 与 `previous_errors` 的交集 ≥ 3 个指纹，返回 `"stalled": true` + 错误 `ITERATION_STALLED`（suggestion："停止重复提交，总结未解决冲突并请用户裁决"）。状态由 LLM 侧维护，工具仍是纯函数。

FakeLLM 集成测试须覆盖两条路径：正常迭代（失败→修改→通过）与停滞（重复错误→`ITERATION_STALLED` 或 max_steps → 终止非挂死）（§⑧）。

## ⑦ 导出 JSON 格式设计（GameSpec）

`export_experiment` 的落盘产物——**给未来网页游戏（M3+ 或更后）读的唯一接口**。核心原则：**游戏端零计算逻辑，只按序列呈现**。

```json
{
  "schema_version": 1,
  "generated_at": "2026-10-20T12:00:00Z",
  "experiment": {
    "name": "stroop-standard", "version": "1.0.0", "seed": 42,
    "paradigm": "stroop", "paradigm_params": {},
    "config_fingerprint": "9f3ab2c1", "trials_fingerprint": "5d21e0f7"
  },
  "responses": [
    {"name": "classify_ink", "kind": "choice", "options": ["red", "green", "blue"],
     "correct_from": "correct_ink"}
  ],
  "trials": [
    {
      "index": 0, "block": "practice",
      "factors": {"word_color": "red", "ink_color": "red"},
      "stimulus": {"word": "red", "color": "red"},
      "derived": {"congruency": "congruent", "correct_ink": "red"},
      "timing": {"fixation_ms": 500, "stimulus_ms": null, "isi_ms": 1000}
    }
  ],
  "summary": {"trial_count": 108, "blocks": ["practice", "test"],
              "frequency": {"congruency": {"congruent": 54, "incongruent": 54}}}
}
```

**格式契约要点**：
- **schema_version**：与 `ExperimentConfig.schema_version` 同源；游戏端按版本做兼容分支，版本升级是显式破坏性变更事件；
- **试次全量物化**：`trials` 为完整列表（与 §⑤ `GeneratedExperiment.trials` 逐字节一致——`trials_fingerprint` 双向可断言）；派生量（congruency、correct_response、计时）全部预算好——游戏端读取 `stimulus`/`derived`/`timing` 直接呈现与判分；
- **与 ExperimentConfig 的映射**：`experiment` 节为 config 的元信息投影（含两个指纹），完整 config 不重复内嵌（导出文件自包含即可复现实验：任何人拿到 `seed + paradigm + factors/constraints` 即可由引擎再生成——`config_fingerprint` 是对齐凭据）；
- **落点**：`data/` 沙箱内（沿用 `file_write` 五步规则，§3.3）；建议命名 `experiments/<name>-v<version>-seed<seed>.json`；
- 本提案**只定义格式不实现游戏**；游戏端开发时若需 JSON Schema 校验导出文件，可直接用 `GeneratedExperiment` 的 `model_json_schema()` 生成（开放问题 §⑩）。

## ⑧ 测试与验收策略

**测试布局**（对齐现有 `tests/unit|integration`）：`tests/unit/experiment/`（schema/引擎/统计/工具）+ `tests/integration/`（FakeLLM 设计迭代循环）+ `tests/golden/`（黄金文件）。

### 8.1 确定性/可重复性测试

| 测试名 | 断言 |
|--------|------|
| `test_generation_same_seed_byte_identical` | 同 config 两次 `generate_trials`，`model_dump_json()` 全等（同进程） |
| `test_generation_cross_process_stable` | 子进程以 `PYTHONHASHSEED=1` / `=2` 各跑一次生成脚本，输出 JSON `diff` 为空 |
| `test_generate_export_fingerprint_match` | `generate_trials.trials_fingerprint == 导出文件.experiment.trials_fingerprint` |
| `test_block_isolation` | 增删一个 block 后，其余 block 的试次子序列逐字节不变（§5.1 子流设计证据） |

### 8.2 统计性质测试（固定 seed）

| 测试名 | 断言 |
|--------|------|
| `test_frequency_balance_stroop` | seed=42、96 试次：congruency 两水平各 48（整数分配精确断言）；ink_color 各 32 |
| `test_frequency_ratio_nback` | seed=7、120 试次：match 占比 ∈ 0.30±0.05（大样本比例容差） |
| `test_max_repeat_respected` | 任一水平连续出现长度 ≤ max_repeat（全序列扫描） |
| `test_deterministic_rejection_sampling` | 约束紧的 config（max_repeat=1）在 100 次重洗内收敛或确定性报 `CONSTRAINT_INFEASIBLE` |

统计断言用比例容差而非检验统计量（不引入 scipy；卡方临界值硬编码表为可选增强，开放问题 §⑩）。

### 8.3 schema 验证测试

`test_config_rejects_*` 系列（非法 config 拒绝用例）：缺 seed、ratios 和=0.9（`RATIO_SUM`）、blocks 总数≠约束推出数（`TRIAL_COUNT_MISMATCH`）、未知 paradigm（`UNKNOWN_PARADIGM`）、`correct_from` 指向不存在派生字段（`CORRECT_FROM_UNKNOWN`）、factor_filter 过滤后为空（`BLOCK_FILTER_EMPTY`）。断言 `valid==false` 且 errors 含对应 `error_code`/`path`/`suggestion`。

### 8.4 黄金文件（golden file）策略

- `tests/golden/stroop-standard-seed42.json`、`tests/golden/nback-2letter-seed7.json`（§4.1/4.2 配置的完整导出产物）；
- 测试 `test_golden_export_unchanged`：生成导出 → 与 golden 比对（语义 diff：解析 JSON 后比较，忽略 `generated_at`）；
- **更新流程**：`UPDATE_GOLDEN=1 pytest tests/golden` 重写文件 → 人工 review diff（seed/算法变更影响面）→ 提交。黄金文件变更必须在 PR 描述说明原因（引擎算法变更/范式逻辑修正）。

### 8.5 FakeLLM 集成测试（设计迭代全循环）

复用 M1 FakeLLM 注入模式（`AgentLoop(client=FakeLLM(script), registry=build_experiment_registry(settings), ...)`）：

| 测试名 | 脚本与断言 |
|--------|-----------|
| `test_design_iteration_success` | 脚本：[validate(比例和错的 config) → valid:false+RATIO_SUM, validate(修正后) → valid:true, generate, export, final]；断言：最终 completed、`data/` 下导出文件存在且 fingerprint 一致、第二轮 FakeLLM 收到的 messages 含第一轮验证 JSON（迭代证据） |
| `test_design_iteration_stalled` | 脚本：三次提交含同一错误的 config（带递增 previous_errors）→ 第三次收到 `ITERATION_STALLED` → final；断言终止且未导出 |
| `test_design_iteration_max_steps` | 脚本恒返回 validate(同一坏 config) → max_steps 截断 → failed + final 必发（防挂死兜底证据） |

### 8.6 验收条目草案（未来实施时并入正式验收标准，本提案仅记录）

| ID | 条目 | 命令（示意） | 判据 |
|----|------|--------------|------|
| EX-1 | 确定性 | `pytest tests/unit/experiment -k determinism`（或 cross_process） | 同 seed 两次生成 diff 为空 |
| EX-2 | 统计性质 | `pytest tests/unit/experiment -k frequency` | 固定 seed 频数精确/容差断言全绿 |
| EX-3 | 非法配置拒绝 | `pytest tests/unit/experiment -k rejects` | 全部返回机器可读 errors（error_code/path/suggestion） |
| EX-4 | 黄金文件 | `pytest tests/golden` | 语义 diff 为空；更新须走 UPDATE_GOLDEN 流程 |
| EX-5 | 迭代全循环 | `pytest tests/integration -k design_iteration` | 失败→修改→通过→导出全链路 FakeLLM 断言 |
| EX-6 | 导出物化完整性 | `pytest tests/unit/experiment -k export` | 导出 JSON 含全量 trials、correct_response 派生字段、双 fingerprint；游戏端字段自包含（无引用缺失） |
| EX-7 | 分层与幂等声明 | `python -m scripts.check_layers` + registry 自检 | 三工具 idempotency/risk_level 声明正确；无反向 import |

## ⑨ 对现有 M1 代码的影响评估

**结论：M1 既有文件零修改，仅新增文件。**

| 动作 | 文件 | 性质 |
|------|------|------|
| 新增 | `src/experiment/`（schemas/validation/generation/export/generators/） | 新包，依赖 `src/models`、`src/config` |
| 新增 | `src/tools/experiment_tools.py` | 三工具（依赖 `src/experiment` + `src/models`） |
| 新增 | `src/agent/experiment_registry.py` | 组合注册（import 既有 `build_registry`，不改它） |
| 新增 | `tests/unit/experiment/`、`tests/golden/`、集成测试 | 测试 |
| **不改** | `src/agent/loop.py`、`src/agent/registry.py`、`src/agent/llm.py`、`src/models/*`、`src/tools/calc.py`、`src/tools/http_request.py`、`src/tools/file_write.py`、`src/agent/__init__.py`、`src/config.py` | AgentLoop/Registry/三工具/事件模型原样复用（§⑥ 已论证零改动） |

两个实施期注意点（如实声明）：
1. **G-4 分层规则**：新层 `experiment` 位于 tools 之下（`agent → tools → experiment → models/config`）。`scripts/check_layers.py` 若按显式图层白名单实现，需**一行规则扩展**（这是 M0 交付的脚本，属门禁配置而非 M1 产品代码；若按目录约定推断则零改动）——实施时确认。
2. **沙箱写规则复用**：`export_experiment` 落盘须与 `file_write` 同规则。默认方案：新增 `src/tools/_sandbox_io.py` 共享 helper（新文件，从 `file_write.py` 的五步规则提取为可复用函数，export 使用之）；`file_write.py` **不迁移不改**（helper 与其逻辑并行存在，注明同步义务）。备选方案是 export 闭包内直接调 `file_write` 的私有函数（零新文件但引入私有耦合，不推荐）。

## ⑩ 开放问题与风险（留给用户决策）

1. **numpy 是否引入**：本提案设计为**不引入**（`random.Random` + 标准库覆盖当前需求，且受 ARCHITECTURE §2.1 依赖红线约束）。若未来需要复杂抽样（分层抽样/精确拉丁方），须先走依赖变更流程。风险：整数分配的 largest remainder 在极端比例下与"完美平衡"有 ±1 偏差——对认知实验通常可接受，黄金文件会显式暴露。
2. **`ITERATION_STALLED` 的 previous_errors 协议**：状态放 LLM 侧保持工具纯函数（§6.3 方案 3），依赖 LLM 如实回传——是"软协议"。是否接受，或宁可只靠 max_steps + 提示（去掉协议层）？请用户裁决。
3. **schema JSON Schema 导出给前端**：`ExperimentConfig`/`GeneratedExperiment` 均可经 `model_json_schema()` 导出。若未来前端要做表单驱动设计或导出文件校验，需要固化导出物与版本策略——暂缓决定。
4. **导出大小上限**：1MB（沿用 file_write）约容纳 ~5k 试次。超大实验是否需要分块导出或多文件格式？
5. **范式插件治理**：新范式的 generator 属于"新代码 = 新验证责任"（黄金文件+统计测试随范式增加）。是否要求每个新范式必须附带黄金文件才准合入？
6. **与 M2 的交汇**：实验工具的 `generate_trials` 幂等性声明使其天然适配 M2 恢复矩阵（uncertain 自动重试安全）；`export_experiment` 非幂等、`file_write` 同级。本提案刻意不设计 M2 交互细节，待 M2 契约冻结时对齐。

---

> **再次声明：本文件为提案（proposal）。未获用户批准前不实施——不写代码、不改正式文档（ARCHITECTURE/ROADMAP/ACCEPTANCE_CRITERIA）、不推进 M2。批准后由 Architect 将本提案要点升格为正式契约（届时版本递增、变更记录落 ARCHITECTURE.md），Backend 按契约实施。**
