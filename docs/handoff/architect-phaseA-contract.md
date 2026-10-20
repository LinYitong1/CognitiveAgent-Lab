# Phase A 契约 — Generic Experiment Engine（最小实现冻结版）

> 作者：Architect Agent ｜ 状态：**冻结**（用户已批准 Phase A 启动；本文档为 Backend 实现的唯一契约依据，QA 验收以此处 PA-1~PA-14 条目为准）
>
> **修订记录**：
> - **R1（2026-10-20，用户批准 PA-14 修复选项 A）**：修订 §5.1 `validate_experiment` 的 description 冻结文本——追加 ExperimentSpec 结构摘要与最小完整示例（PA-14 真实 LLM Demo 失败模式 B 的根因修复：宽松 `config: object` 输入导致模型在 tools schema 中不可见 spec 结构，只能盲猜错误包装）。修订范围**仅 description 文本**：不改 input_model、执行流程、输出结构、错误契约、算法与任何已验收行为。修订后实现须通过"示例经实际 ExperimentSpec 校验 valid=true"的一致性测试（见 §5.1 修订块）。基线 commit `45c42c1`（含本修订前的全部 Phase A 验收）。
> 上游依据：`docs/proposals/experiment-tools-design-proposal.md` v2.1（741 行，本契约从中裁剪出最小集）；`docs/handoff/architect-m1-contract.md`（M1 冻结契约，风格与错误回传模式沿用）
> 基线：commit ae8dd68（M1 全部验收通过，含真实 LLM 全链路）
> 产品边界（`.workbuddy/memory/MEMORY.md`，硬约束）：不兼容既有认知模型/实验项目；不为特定认知理论硬编码；不扩展为完整游戏引擎；不开发特定实验范式。**Phase A 纯通用路径（paradigm=null），不实现插件系统，不依赖 Stroop/N-back 或任何范式。**
> 冻结含义：schema 字段、算法步骤、错误码、指纹规则、测试清单按本文实现；实现内部细节（私有函数名、内部异常类型）Backend 可自定。**任何签名/语义变更必须回提 Architect 更新本文档。**
> 措辞约定：**必须**=强制；**禁止**=强制不做；"建议"=非约束。
>
> 真实代码核实声明：本文引用的全部 M1 签名均按基线代码核实（`src/models/tool_spec.py`、`src/agent/registry.py`、`src/agent/loop.py`、`src/tools/calc.py`、`src/tools/file_write.py`、`src/agent/__init__.py`、`src/config.py`、`tests/integration/fake_llm.py`），非凭记忆。注意一处与 M1 契约原文的落位差异：`ToolSpec` 实际位于 `src/models/tool_spec.py`（该文件 docstring 已说明原因），非 `src/agent/registry.py`。

---

## ① 范围裁剪决策表（提案 v2.1 → Phase A 最小集）

裁剪原则：**最小可用 + 不堵死未来扩展 + 通用性红线不破**。

### 1.1 进入 Phase A

| # | 提案条目（§节） | Phase A 形态 |
|---|----------------|--------------|
| IN-1 | ExperimentSpec schema（§4.1） | 全量进入（含 paradigm/paradigm_params 自由字段保留，见 §②）；新增少量精化约束（seed 范围、组合数上限、引用校验归属），逐项列于 §② 并标注"契约级精化" |
| IN-2 | 纯通用路径生成引擎（§5.1/§5.2） | 进入：确定性组合展开 + largest remainder 分配 + seeded shuffle；seed 派生算法落定为显式 SHA-256（见 §③，与提案 §5.1 的字符串种子方案不同，理由在 §③.1） |
| IN-3 | validate_experiment / generate_trials / export_experiment 三工具（§3.1~3.3） | 进入；错误两级契约（领域级 valid:false / 工具级 ok=False）沿用提案 |
| IN-4 | 约束模型 balance / ratios（§6.1 C1/C2/C3） | 进入（验证期可判定） |
| IN-5 | mutually_exclusive（§4.1 Constraints） | 进入，**语义精化**：Phase A 仅实现"组合空间静态过滤"（同一试次内两水平不同现 → 该组合剔除），验证期可判定；不涉及序列级重排（见 §④.3） |
| IN-6 | canonical JSON + 指纹（§5.4） | 进入；**指纹改为完整 SHA-256**（提案为 `[:8]` 截断，见 §⑥.1 契约级变更 CR-2）；**新增 bundle_sha256**（用户硬约束） |
| IN-7 | ExperimentBundle（§7.1） | 进入（仅实验层；reproducibility 节含参数摘要 effective_weights / allocation） |
| IN-8 | 防死循环三层（§6.3） | 进入：max_steps 硬上限（M1 既有）+ 提示层引导 + previous_errors 软协议（ITERATION_STALLED，v2.1 MA-1 触发语义） |
| IN-9 | 注册方式（§3.4） | 进入：`build_experiment_registry(settings)` 组合函数，M1 `build_registry` 零改动 |
| IN-10 | 独立验证两路径（§5.4） | 进入：路径①重生成比对（测试覆盖）+ 路径②仅验证（新增 `src/experiment/verify.py` CLI） |
| IN-11 | 黄金文件（§8.4） | 进入：纯通用路径 1 份（固定 spec+seed，注入固定时间戳后**逐字节**比对） |

### 1.2 推迟（附理由）

| # | 提案条目（§节） | 推迟理由 |
|---|----------------|----------|
| OUT-1 | ParadigmPlugin 协议与插件注册表（§5.3） | 用户硬约束 #6：Phase A 纯通用路径。schema 保留 paradigm/paradigm_params 字段（不堵死扩展）；Phase A 中 `paradigm != null` 一律报 `UNKNOWN_PARADIGM`（message 注明"Phase A 未实现插件系统"）——**不静默忽略**。插件相关错误码 `PLUGIN_FREQUENCY_DEVIATION` 一并推迟 |
| OUT-2 | GameSpec（§4.5/§7.2） | Phase A 只做实验层；Bundle 不含表现层。GameSpec/ExperimentRef 推迟到游戏表现层阶段 |
| OUT-3 | conformance 向量集跨实现复现（§5.4） | Phase A 验收标准 = **本实现内可重复**（同 Python 实现与版本）+ 本契约 §③ 冻结算法规范（`engine_spec_version="1.0"` 为 Phase A 算法版本号）。跨实现权威向量集（复刻 MT19937/shuffle 消费序/float 表示）是"规范对外发布"的前置条件，Phase A 不对外发布规范，推迟；开放问题 §⑩.1 记录 |
| OUT-4 | `max_repeat` 序列约束（§4.1/§5.2 第 6 条） | **唯一需要真搜索（拒绝采样/重排）的约束**。Phase A 约束集全部验证期可判定（用户硬约束 #5 的裁剪指示）；max_repeat 连同 SEARCH_EXHAUSTED 真实触发路径推迟到 Phase B。schema 保留字段，Phase A 非 null 声明报 `UNSUPPORTED_CONSTRAINT`（新错误码，见 §④.4）——不静默忽略 |
| OUT-5 | M2 持久化 / API / SSE / MCP / 公共 Skill / 网页游戏 | 里程碑边界（用户硬约束"Phase A 不做"） |
| OUT-6 | 卡方临界值表等统计增强（§8.2 尾注） | 非最小集；Phase A 频数断言用精确整数 |
| OUT-7 | 超大实验分块导出（§⑩.5） | 1MB 上限 ≈ 5k 试次，Phase A 接受；超限显式 BLOCKED（§⑤.3）；分块导出推迟 |
| OUT-8 | `ITERATION_STALLED` 之外的新增软协议硬化（§⑩.4） | 沿用 v2.1 裁定：软协议 + max_steps 兜底，Phase A 不硬化 |

### 1.3 契约级变更（与提案 v2.1 的显式差异，全部记录）

| # | 变更 | 提案原文 | Phase A 契约 | 理由 |
|----|------|----------|--------------|------|
| CR-1 | seed 子流派生 | `random.Random(f"{seed}:block:{block.name}")`（依赖 CPython 字符串种子 sha512 派生） | 显式 `SHA-256(f"{seed}:block:{block.name}")` 前 8 字节 → int64 → `random.Random(int)` | §③.1：把隐式实现细节变成显式规范，降低未来跨实现复现门槛（用户指令中的示例方案） |
| CR-2 | 指纹长度 | sha256 截断 `[:8]`（32 bit） | **完整 64 hex 字符** | 用户硬约束 #4"完整 SHA-256"；32 bit 对完整性校验碰撞空间不足 |
| CR-3 | 指纹构成 | 双指纹 = config_fingerprint + trials_fingerprint | 双指纹 = **trials_fingerprint + bundle_sha256**（用户硬约束）；config_fingerprint 保留为第三元数据（迭代对账用） | 用户重点 #6 |
| CR-4 | 互斥约束执行方式 | §5.2 第 6 条将 mutually_exclusive 归入拒绝采样 | **静态组合过滤**（验证期判定，无搜索） | "禁止同现的水平名对"本质是组合层约束；静态过滤语义更弱但更诚实，且满足"Phase A 零搜索路径"；序列级约束（含 max_repeat）推迟 |
| CR-5 | 新增错误码 | — | `UNSUPPORTED_CONSTRAINT`（max_repeat 声明）、`SEARCH_EXHAUSTED`（框架预留，Phase A 不可触发） | §④ |
| CR-6 | 输出字段命名 | validate/generate 输出 `fingerprint`（含义随上下文漂移） | 显式命名 `config_fingerprint` / `trials_fingerprint` | 消除歧义，QA 断言友好 |
| CR-7 | spec 约束精化 | seed: int（无范围）、组合数无上限 | seed ∈ [0, 2^63-1]；展开组合数 ≤ 100,000；单 block trial_count ≤ 100,000；blocks ≤ 32 | DoS 护栏 + 跨语言 int64 边界安全（§②） |

---

## ② ExperimentSpec Pydantic schema（精确字段定义）

新文件 `src/experiment/schemas.py`（Pydantic v2）。**必须**按以下字段表实现；**禁止**加入任何范式/理论名词字段（通用性红线）。

### 2.1 字段表

```python
# src/experiment/schemas.py
from typing import Literal
from pydantic import BaseModel, Field, model_validator

class Level(BaseModel):
    name: str = Field(min_length=1)              # 因素内唯一（model_validator 校验）
    weight: float = Field(default=1.0, gt=0)     # 采样权重（意图声明，引擎整数化；被覆盖时 C2 警告）

class Factor(BaseModel):
    name: str = Field(min_length=1)              # 全 spec 内唯一（model_validator 校验）
    levels: list[Level] = Field(min_length=1)    # 有序——组合展开确定性的来源之一

class RatioRule(BaseModel):
    factor: str = Field(min_length=1)            # 必须引用已声明因素名（→ SCHEMA_INVALID）
    ratios: dict[str, float]                     # level name -> 比例；键必须引用该因素的水平名；
                                                 # 值 ≥ 0.0（允许 0.0 = 显式排除）；和 ≈ 1.0（容差 1e-6，→ RATIO_SUM，验证层）

class Constraints(BaseModel):
    balance: bool = False                        # 所有因素所有水平等权；与 ratios 互斥（C1 → CONSTRAINT_CONFLICT）
    ratios: list[RatioRule] = Field(default_factory=list)   # 每因素至多一条（重复 → SCHEMA_INVALID）
    mutually_exclusive: list[list[str]] = Field(default_factory=list)
                                                 # 每项恰 2 个水平名，跨因素；引用必须存在（→ SCHEMA_INVALID）；
                                                 # 同因素内两水平 → MUTEX_VIOLATION（验证层）
    max_repeat: int | None = None                # Phase A 保留字段；非 None → UNSUPPORTED_CONSTRAINT（验证层）

class ResponseVar(BaseModel):
    name: str = Field(min_length=1)              # 全 spec 内唯一（model_validator 校验）
    kind: Literal["choice", "text", "rating"]
    options: list[str] = Field(default_factory=list)   # kind="choice" 时必须非空；否则必须为空（model_validator）
    scale: tuple[int, int] | None = None               # kind="rating" 时必须非 None 且 min < max；否则必须为 None
    correct_from: str | None = None              # 非 None 时必须为已声明因素名（→ CORRECT_FROM_UNKNOWN，验证层）

class BlockSpec(BaseModel):
    name: str = Field(min_length=1)              # 全 spec 内唯一（重名 → SCHEMA_INVALID；子流派生键依赖唯一）
    trial_count: int = Field(gt=0, le=100_000)   # 上限为 CR-7 护栏
    factor_filter: dict[str, list[str]] = Field(default_factory=dict)
                                                 # 键必须引用因素名、值必须引用该因素的水平名（→ SCHEMA_INVALID）
    shuffle_within: bool = True

class TimingSpec(BaseModel):
    fixation_ms: int = Field(default=500, ge=0)
    stimulus_ms: int | None = Field(default=None, ge=0)   # None = 直至响应
    isi_ms: int = Field(default=1000, ge=0)

class ExperimentSpec(BaseModel):
    schema_version: Literal[1] = 1
    name: str = Field(min_length=1)
    version: str = "0.1.0"
    seed: int = Field(ge=0, le=2**63 - 1)        # CR-7：非负 int64
    paradigm: str | None = None                  # Phase A 必须为 null（非 null → UNKNOWN_PARADIGM，验证层）
    paradigm_params: dict[str, object] = Field(default_factory=dict)
                                                 # paradigm 为 null 时必须为空 dict（非空 → SCHEMA_INVALID，model_validator）
    factors: list[Factor] = Field(min_length=1)
    blocks: list[BlockSpec] = Field(min_length=1, max_length=32)   # CR-7 护栏
    constraints: Constraints = Constraints()
    responses: list[ResponseVar] = Field(min_length=1)
    timing: TimingSpec = TimingSpec()
    # model_validator（ExperimentSpec 级，跨字段结构校验，全部产出 SCHEMA_INVALID 语义）：
    #   V1 factors 名唯一；V2 每 factor 内 levels 名唯一；
    #   V3 blocks 名唯一；V4 responses 名唯一；
    #   V5 factor_filter / ratios.factor / ratios 键 / mutually_exclusive 引用的因素名与水平名必须存在；
    #   V6 ratios 每因素至多一条；V7 mutually_exclusive 每项长度 == 2；
    #   V8 paradigm is None 且 paradigm_params 非空 → 拒绝；
    #   V9 展开组合数（∏ len(levels)）≤ 100_000（CR-7）
```

### 2.2 校验分界（冻结）

- **Pydantic 层**（schemas.py 的 Field 约束 + model_validator V1~V9）：结构与引用存在性——与 seed 无关、与约束语义无关。失败由验证层包装为 `SCHEMA_INVALID`（每条 Pydantic 错误一 个 issue，path 取 `loc` 拼接如 `factors[1].levels`）。
- **验证层**（src/experiment/validation.py）：约束语义与可满足性——C1/C2/C3、RATIO_SUM、CORRECT_FROM_UNKNOWN、UNKNOWN_PARADIGM、UNSUPPORTED_CONSTRAINT、BLOCK_FILTER_EMPTY、TRIAL_COUNT_MISMATCH、MUTEX_VIOLATION（§④）。
- **禁止**把语义校验放进 Pydantic（如 ratios 和检查——它属 C3 语义）；**禁止**把引用存在性放进验证层（结构性问题必须在解析期暴露）。

### 2.3 最小可表达边界（验收判据）

- Phase A schema **必须**能表达提案 §4.2 的通用示例（cueing-generic：2 因素 × 2 水平、2 blocks、balance、correct_from 指向因素名）——该示例进单元测试作为合法用例（仅作为 schema 表达力用例，不意味着任何范式支持）。
- **必须**能表达：多因素任意水平数、per-block trial_count、factor_filter、balance / ratios / mutually_exclusive 三类约束、choice/text/rating 三类响应、计时参数、seed。
- schema 中**禁止**出现任何指向特定实验范式的字段名、默认值或文档措辞（`paradigm`/`paradigm_params` 为不透明自由字段，核心不解释）。

### 2.4 Trial 与生成结果模型

```python
class Trial(BaseModel):
    index: int                    # 全局序（0 起，跨 block 连续）
    block: str                    # 所属 block 名
    factors: dict[str, str]       # 因素名 -> 水平名（键序为 factors 声明序；canonical 序列化时 sort_keys 消除影响）
    stimulus: dict[str, object]   # Phase A 恒为 {}（通用路径不物化刺激；GameSpec 层负责渲染）
    derived: dict[str, object]    # Phase A 恒为 {}（插件派生字段，Phase B+）
    timing: TimingSpec            # 物化的计时参数（spec.timing 的逐试次拷贝）

class GeneratedExperiment(BaseModel):
    config_fingerprint: str       # 完整 64 hex（CR-2）
    trials_fingerprint: str       # 完整 64 hex
    engine_spec_version: str      # 常量 "1.0"
    plugin_used: str | None       # Phase A 恒为 None
    trials: list[Trial]           # 全量物化
```

---

## ③ 确定性引擎设计

新文件 `src/experiment/generation.py`。**试次生成 = 纯函数**：无 IO、无时间依赖、无隐藏状态、不触全局 `random`。

### 3.1 seed 派生链（CR-1 落定）

```python
import hashlib, random

def derive_block_seed(seed: int, block_name: str) -> int:
    """每 block 独立子流种子（冻结算法）。"""
    digest = hashlib.sha256(f"{seed}:block:{block_name}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")   # 无符号 int64

# 每 block: rng = random.Random(derive_block_seed(spec.seed, block.name))
```

- **必须**用上述显式 SHA-256 派生（CR-1）；**禁止** `random.Random(str)` 直接字符串种子（隐式依赖 CPython 的 sha512 种子派生实现）。
- 用 `block.name`（非 index）作为派生键：block 名全局唯一（§② V3），增删/插入 block 不扰动其他 block 的序列（`test_block_isolation` 断言依据）。
- Phase A 通用路径中随机消费**只有一处**：block 内 shuffle。提案的"根 rng"仅服务于插件（Phase A 无插件），**不创建**——引擎内无闲置随机状态。

### 3.2 随机源唯一化（提案 §⑩.3 默认裁定，冻结）

- **唯一随机源 = stdlib `random.Random` 实例**。Phase A **不引入 numpy**（理由：`random.Random` + 标准库完全覆盖组合展开/整数分配/洗牌需求；引入 numpy 违反依赖白名单纪律（pyproject 仅 fastapi/uvicorn/pydantic/pydantic-settings/httpx/openai），且换随机源会改变全部指纹、破坏 engine_spec_version 语义。未来需要分层/精确拉丁方等复杂抽样须先走依赖变更流程并递增 engine_spec_version）。
- **禁止**在 `src/experiment/` 与 `src/tools/experiment_tools.py` 中调用 `random` 模块级函数（`random.random()` / `random.shuffle()` 等全局函数）——只允许 `random.Random` 实例方法。QA 以静态扫描断言（§⑦ PA-12）。
- **禁止** `datetime.now()` / `uuid` / 全局可变状态进入生成路径；时间戳只出现在 Bundle 的 `generated_at` 元字段且**不参与任何指纹**（§⑥）。

### 3.3 生成算法（逐步冻结，每步确定性保证）

```
generate_trials(spec) 算法（Phase A 通用路径）：
1. 组合展开：按 factors 声明序的笛卡尔积（itertools.product），水平按 levels 声明序。
   确定性来源：列表声明序（与 PYTHONHASHSEED 无关）。
2. 互斥过滤（IN-5/CR-4）：凡同现 mutually_exclusive 声明水平对的组合，从组合空间剔除。
   （组合序保持声明序，不做排序——序即确定性。）
3. 有效权重（C3，验证层已保证合法）：
   - balance=true → 每水平有效权重 = 1 / len(levels)（等权；显式 weight 被 C2 警告后忽略）；
   - 否则 → ratios 声明的因素用 ratios 值；未声明因素用 Level.weight 因素内归一化。
   组合权重 w_c = ∏ 各因素水平有效权重。
4. block 切分：每 block 独立执行 5~7（factor_filter 先过滤可用组合）：
5. largest remainder 整数分配（确定性，冻结）：
   exact_c = trial_count * w_c / Σw；floor_c = floor(exact_c)；
   余量 R = trial_count - Σfloor_c；按 fractional part（exact_c - floor_c）降序，
   并列时按组合声明序（第 1 步展开序）先者得 +1，共 R 个组合。
6. 试次物化：按组合声明序将各组合复制 n_c 次生成 block 内列表（此时为确定性"展开序"）。
7. 排序：shuffle_within=true → rng.shuffle(列表)，rng = 该 block 的派生子流（§3.1），
   每 block 恰一次 shuffle 调用（Phase A 无重洗——无序列约束）；
   shuffle_within=false → 保持展开序输出。
8. index 分配：按 blocks 声明序拼接各 block 结果，全局 index 从 0 连续递增。
9. 频数统计：遍历 trials 对每因素每水平计数（dict 构造序 = 声明序）。
```

### 3.4 PYTHONHASHSEED 无关性论证（冻结声明）

1. 种子派生：SHA-256 对 `(int, str) -> bytes` 的输入经 `str(int)` + utf-8 显式编码，无哈希随机化参与；
2. `random.Random(int)` 的 MT19937 初始化（init_by_array）为确定性 documented 算法，与 PYTHONHASHSEED 无关；
3. **禁止迭代 `set`**（`src/experiment/` 全部代码）：任何集合语义先 `sorted()` 再消费；实测：Phase A 引擎中**不存在任何 set 构造**（组合/因素/水平全部以 list 与 dict 表达）；
4. dict 依赖 Python ≥3.7 的插入序 documented 语义（合法，契约引用该保证）；
5. canonical JSON `sort_keys=True`（§⑥.1）消除键序差异；
6. 验证方法：子进程以 `PYTHONHASHSEED=1` / `PYTHONHASHSEED=2` 各生成一次，输出**逐字节 diff 为空**（§⑦ PA-2）。

### 3.5 引擎签名（冻结）

```python
# src/experiment/generation.py
ENGINE_SPEC_VERSION: str = "1.0"   # 模块常量；算法任何变更（分配/派生/洗牌/序列化）必须递增

def generate_trials(spec: ExperimentSpec, max_attempts: int = 100) -> GeneratedExperiment:
    """纯函数。同 spec（含同 seed）→ 返回值 canonical JSON 逐字节相同。
    前置条件：spec 已通过 validate_spec（工具层保证先验证后生成）。
    max_attempts：SEARCH_EXHAUSTED 框架能力参数（§④.2）——Phase A 约束集无搜索路径，
    本参数当前不被消费，签名保留以为 Phase B 序列约束预留。"""
```

**engine_spec_version 语义（Phase A 范围声明）**：`"1.0"` 标识本契约 §③/§⑥ 冻结的算法与序列化规范。Phase A 的可重复性范围 = **同一 Python 实现与版本**（项目锁定 ≥3.13）；跨实现/跨语言复现依赖 conformance 向量集（OUT-3），向量集发布前**禁止**对外宣称跨实现兼容。

---

## ④ 约束求解语义：UNSAT 与 SEARCH_EXHAUSTED 的区分（用户重点 #5）

### 4.1 ValidationIssue 结构（沿用提案 §6.1，冻结）

```python
# src/experiment/validation.py
class ValidationIssue(BaseModel):        # errors 与 warnings 共用
    error_code: str                      # 稳定枚举（§4.4 表）
    path: str                            # JSON 路径，如 "constraints.ratios[0].ratios" / "factors[1].levels"
    message: str                         # 人类可读描述（含实际值）
    suggestion: str                      # 修复建议（LLM 行动指令）
```

### 4.2 两类失败的语义定义（冻结）

| 维度 | UNSAT（约束不可满足） | SEARCH_EXHAUSTED（搜索耗尽） |
|------|----------------------|------------------------------|
| 语义 | 约束体系**数学上可证明无解**，验证期（生成前）即可判定，**不进入搜索** | 约束满足需搜索（序列重排类），在 `max_attempts` 次确定性尝试内未找到解——**不判定无解** |
| 判定时机 | validate_experiment 预检期 | 生成期（仅当存在搜索型约束） |
| 返回 | `valid: false` + 对应 UNSAT 类错误码（见 §4.4 映射） | `valid: false` + `error_code: "SEARCH_EXHAUSTED"` + message 明示"在 N 次尝试内未找到满足约束的排列，不排除存在解" |
| suggestion 要素 | 指出数学矛盾本身（如"ratios 和为 0.9，须 ≈1.0"） | 三个方向：放松约束 / 调整 trial_count / 更换 seed（换 seed 改变 shuffle 路径） |
| max_attempts 来源 | 不适用（无搜索） | `settings.experiment_max_search_attempts`（§⑧.2，默认 100，**定死**）；工具层读取后传入 `generate_trials(spec, max_attempts=...)` |

### 4.3 Phase A 约束集的可判定性（如实声明）

Phase A 约束集 = **balance（C1/C3 路径）+ ratios（C3）+ mutually_exclusive（静态组合过滤，CR-4）**，全部验证期可判定：

- **balance**：分配恒为 largest remainder 最优近似，**任何 trial_count 都有确定解**。trial_count 不被组合数整除时产生 ±1 偏差 → **警告 `RATIO_ROUNDED`（不是错误、更不是 UNSAT）**。裁定说明：提案 v2.1 冻结的 balance 语义即"近似等频 + 偏差显式警告"；严格等频（strict balance，不整除即 UNSAT）语义 Phase A **不引入**（避免新增失败路径；如未来需要，须新增 `strict_balance` 字段 + `BALANCE_NOT_DIVISIBLE` 错误码并递增 engine_spec_version，开放问题 §⑩.4 记录）。
- **ratios**：和 ≠ 1.0±1e-6 → `RATIO_SUM`（声明矛盾，验证期判定）；过滤后正权重组合为 0 → `TRIAL_COUNT_MISMATCH`（无解，验证期判定）。
- **mutually_exclusive**：静态剔除组合。剔除后（含与 factor_filter/权重为 0 的叠加）组合空 → `MUTEX_VIOLATION`；同因素内两水平的无意义声明 → `MUTEX_VIOLATION`。

**因此 Phase A 不存在任何搜索路径，`SEARCH_EXHAUSTED` 在 Phase A 不可触发。** 框架能力仍**必须**实现（用户要求，为 Phase B 的 max_repeat 序列约束准备）：

1. 错误码 `SEARCH_EXHAUSTED` 冻结于枚举与本文档（§4.4）；
2. `generate_trials` 的 `max_attempts` 参数签名冻结（§3.5）；
3. `Settings.experiment_max_search_attempts` 字段冻结（§⑧.2）；
4. QA 对应测试为**声明性弱断言**（枚举在场、Settings 字段存在、契约文档一致性），契约如实标注其局限（§⑦ PA-6）。

### 4.4 错误码稳定枚举与类别映射（Phase A 冻结）

| error_code | 类别 | 触发条件 |
|------------|------|----------|
| `SCHEMA_INVALID` | 结构 | Pydantic 解析失败（含 V1~V9：重名、引用不存在、options/scale 与 kind 不匹配、paradigm_params 矛盾、组合数超限等） |
| `UNKNOWN_PARADIGM` | 支持性 | `paradigm != null`（Phase A 无插件注册表；message 必须注明"Phase A 未实现插件系统，paradigm 必须为 null"并附已注册插件清单——当前为空） |
| `UNSUPPORTED_CONSTRAINT` | 支持性 | `max_repeat != null`（message 注明"Phase B 支持，当前请移除该字段"）——CR-5 |
| `CONSTRAINT_CONFLICT` | UNSAT | C1：`balance==true` 且 `ratios` 非空（声明矛盾，验证期判定） |
| `RATIO_SUM` | UNSAT | 某 RatioRule 的 ratios 和偏离 1.0 超容差 1e-6 |
| `BLOCK_FILTER_EMPTY` | UNSAT | 某 block 的 factor_filter 语义过滤后可用组合为空 |
| `TRIAL_COUNT_MISMATCH` | UNSAT | 某 block 经 factor_filter + 互斥剔除 + 有效权重（含 ratios 置 0）过滤后，正权重组合数为 0 而 trial_count > 0 |
| `MUTEX_VIOLATION` | UNSAT | 互斥声明使可用组合为空；或声明对同一因素内两个水平（无意义声明） |
| `CORRECT_FROM_UNKNOWN` | 语义 | `correct_from` 非 None 且不是已声明因素名（Phase A 无插件派生字段，只允许因素名） |
| `SEARCH_EXHAUSTED` | 搜索耗尽 | **Phase A 不可触发**（框架预留，§4.2/§4.3） |
| `ITERATION_STALLED` | 迭代协议 | previous_errors 中任一 `error_code:path` 指纹出现 ≥2 次（§⑤.1） |

警告码：`WEIGHT_IGNORED`（C2 两情形：① balance=true 且显式 weight≠1.0；② balance=false 且 ratios 声明因素上存在显式 weight≠1.0）、`RATIO_ROUNDED`（某 block 的 largest remainder 分配存在非整数 exact 值）。

**约束语义规则 C1~C3**（沿用提案 §6.1，冻结）：C1 互斥（balance ∧ ratios 非空 → 错误）；C2 覆盖警告（两种情形均不影响 valid 判定）；C3 有效权重优先级（ratios > Level.weight 因素内归一化；ratios 值允许 0.0）。

---

## ⑤ 三工具 ToolSpec 与注册方式

新文件 `src/tools/experiment_tools.py`（单文件三工具，风格对齐 `calc.py`/`file_write.py`：Input 模型 + 内部 `_ExperimentBlocked` 异常 + `BLOCKED:` 前缀 + `build_*(settings) -> ToolSpec` 工厂）。依赖方向：`src/tools/experiment_tools.py` → `src/experiment/*` → `src/models` / `src/config`（§⑧.4 分层）。

### 5.1 validate_experiment（幂等、只读、low）

```python
class ValidateExperimentInput(BaseModel):
    config: dict[str, object]                      # ExperimentSpec 的 JSON 对象（LLM 直接内联生成）
    previous_errors: list[str] = Field(default_factory=list)  # 此前轮次 error_code:path 指纹列表（防死循环，§5.4）

# ToolSpec 声明（冻结；R1 修订版——description 增补结构摘要与示例，其余字段不变）：
ToolSpec(
    name="validate_experiment",
    description=(
        "校验实验规格（ExperimentSpec JSON）的 schema 合法性与约束可满足性，"
        "返回机器可读验证报告（错误含 error_code/path/suggestion）。修改 spec 后可重复调用。"
        "config 的值必须就是 ExperimentSpec JSON 对象本身——顶层直接是 schema_version/name/seed 等字段，"
        "禁止再包一层（不要包在 inputs、experimentSpec、config 等任何外层键内）。"
        "必需顶层字段：schema_version(=1)、name、seed、paradigm(Phase A 必须为 null)、"
        "paradigm_params(必须为 {})、factors(每项 {name, levels:[{name, weight?}]}，水平名因素内唯一)、"
        "blocks(每项 {name, trial_count, factor_filter(默认 {}), shuffle_within(默认 true)}，块名唯一)、"
        "constraints({balance?, ratios?, mutually_exclusive?})、"
        "responses(每项 {name, kind(choice|text|rating), options(kind=choice 必填非空), "
        "scale(kind=rating 必填 [min,max]), correct_from?(已声明的因素名)}，名唯一)、"
        "timing({fixation_ms?, stimulus_ms?(null=直至响应), isi_ms?})。"
        "最小完整示例（把 factors/levels/blocks/responses/timing/seed 换成任务要求的内容即可）："
        '{"schema_version":1,"name":"example-cueing","version":"0.1.0","seed":7,"paradigm":null,'
        '"paradigm_params":{},"factors":[{"name":"cue_type","levels":[{"name":"valid"},{"name":"invalid"}]},'
        '{"name":"target_side","levels":[{"name":"left"},{"name":"right"}]}],'
        '"blocks":[{"name":"practice","trial_count":4,"factor_filter":{},"shuffle_within":true},'
        '{"name":"main","trial_count":40,"factor_filter":{},"shuffle_within":true}],'
        '"constraints":{"balance":true},'
        '"responses":[{"name":"locate_target","kind":"choice","options":["left","right"],'
        '"correct_from":"target_side"}],'
        '"timing":{"fixation_ms":400,"stimulus_ms":null,"isi_ms":800}}'
    ),
    input_model=ValidateExperimentInput,
    idempotency="idempotent",     # 纯函数、无副作用
    risk_level="low",
    executor=...,                 # async def executor(base) -> ToolResult（registry 统一签名，cast 到 Input）
)
```

**R1 修订约束（冻结）**：
1. 示例 JSON 必须作为模块级常量（建议 `_SPEC_EXAMPLE_JSON: str`）嵌入 description，禁止实现与测试各抄一份（防漂移）；
2. 一致性测试必须证明：`json.loads` 该示例 → `ExperimentSpec.model_validate` 通过 → `validate_spec` 返回 `valid=true` 且零错误零警告（示例与 Pydantic schema 及验证层逐字段一致的可执行证据）；
3. 示例刻意与 PA-14 Demo goal 的任务**不同**（不同因素名/水平名/试次数）——示例职责是结构可发现性，不是替模型代答任务；模型仍须按 goal 真实构造自己的 spec 并完成 validate→generate→export 全链路；
4. description 总长（含示例）软约束 ≤ 1600 字符，硬约束 ≤ 2400 字符（qwen2.5:7b ctx=8192 的 token 预算控制）。

**执行流程（冻结）**：
1. 输入体积护栏：`config` 序列化字节 > 256KB → `ToolResult(ok=False, error="BLOCKED: config too large")`；
2. `validate_spec(config)`（§②/§④ 验证层）→ `ValidationResult`；
3. stalled 判定：对当次 errors 计算 `error_code:path` 指纹，任一指纹在 `previous_errors` 中出现 ≥2 次 → `stalled: true` 且 errors 追加 `ITERATION_STALLED`（suggestion："停止重复提交，总结未解决冲突并请用户裁决"）。逐轮推演（v2.1 MA-1）：第 1 次 prev=[] 通过；第 2 次 prev=[f1] 仍回传；第 3 次 prev=[f1,f1] → stalled；
4. 输出（`ToolResult(ok=True, result=<JSON>)`，紧凑 JSON）：

```json
{"valid": false, "stalled": false,
 "config_fingerprint": "<64hex 或 null（schema 解析失败时）>",
 "engine_spec_version": "1.0",
 "errors": [{"error_code": "...", "path": "...", "message": "...", "suggestion": "..."}],
 "warnings": [...],
 "errors_truncated": false,
 "stats": {"trial_count": 104, "factor_count": 2, "blocks": 2, "combinations": 4, "plugin": null}}
```

- **errors 上限 20 条**：超出截断并置 `errors_truncated: true`（上下文膨胀护栏，风险报告 R-2，§⑧.5）；
- `valid` 与 `stalled` 独立：stalled 触发时 valid 照实返回。

### 5.2 generate_trials（幂等、纯函数、不落盘、low）

```python
class GenerateTrialsInput(BaseModel):
    config: dict[str, object]
    max_preview_trials: int = Field(default=8, ge=0, le=50)   # 回传 LLM 的试次预览条数

ToolSpec(
    name="generate_trials",
    description="按实验规格确定性生成完整试次序列（同 spec+seed 结果逐字节相同）。返回序列指纹与"
                "各因素水平频数统计，供核对设计意图；不写任何文件。完整序列由 export_experiment 用"
                "同一 spec+seed 确定性重新生成并落盘。",
    input_model=GenerateTrialsInput,
    idempotency="idempotent",     # 纯函数
    risk_level="low",
    executor=...,
)
```

**执行流程**：256KB 护栏 → `validate_spec`（失败 → `ok=True` + `valid:false` + errors，与 validate 同构，**不生成**）→ `generate_trials(spec, max_attempts=settings.experiment_max_search_attempts)` → 输出：

```json
{"valid": true,
 "config_fingerprint": "<64hex>", "trials_fingerprint": "<64hex>",
 "trial_count": 104, "engine_spec_version": "1.0", "plugin_used": null,
 "frequency": {"difficulty": {"easy": 52, "hard": 52}, "modality": {"audio": 52, "visual": 52}},
 "preview": [{"index": 0, "block": "practice", "factors": {"difficulty": "easy", "modality": "visual"}}, ...],
 "note": "full sequence reproducible via export_experiment with identical spec+seed"}
```

**设计要点（冻结）**：完整试次序列**禁止**进入 `ToolResult.result`（数百 KB 会污染 LLM 上下文）——result 只含指纹与统计；完整序列交付通道是 export_experiment（同 spec+seed 纯函数一致性，PA-8 断言 `generate_trials` 输出的 trials_fingerprint == Bundle 内 trials_fingerprint）。

### 5.3 export_experiment（非幂等、落盘、medium）

```python
class ExportExperimentInput(BaseModel):
    config: dict[str, object]
    path: str = Field(min_length=1)   # 相对 data/ 沙箱根的输出路径（建议 experiments/<name>-v<version>-seed<seed>.json）

ToolSpec(
    name="export_experiment",
    description="把实验规格物化为自包含实验导出包（ExperimentBundle：规范化 spec + 全量试次 + 可重复性"
                "元数据 + SHA-256 完整性指纹），写入 data/ 沙箱内指定路径（覆盖已存在文件）。",
    input_model=ExportExperimentInput,
    idempotency="non-idempotent",   # 写文件（覆盖语义），与 file_write 同级
    risk_level="medium",
    executor=...,
)
```

**关键裁定（用户重点 #5）——export 内部重新确定性生成，不接受 generate 的输出**。理由：①纯函数、幂等语义、无状态——同一 spec+seed 必然产出同一 Bundle，无"部分生成/引用失效"边界问题；②两工具一致性由同一纯函数保证（`generate_trials` 与 export 内部调用**同一个** `generation.generate_trials`），指纹相等是可断言的数学性质而非运行时传递；③无需定义试次引用协议（未来若需要增量导出再议，§⑩.5）。

**执行流程（冻结）**：
1. 256KB config 护栏（同 5.1）；
2. `validate_spec` → 失败 → `ok=True` + `valid:false` + errors（**不导出无效实验**）；
3. `build_bundle(spec)`（§⑥.2，`generated_at=now(UTC)`）→ canonical JSON → 字节 > 1MB → `BLOCKED: export too large`（OUT-7）；
4. **沙箱写盘：必须**复用 `file_write` 五步安全规则（新文件 `src/tools/_sandbox_io.py`，见下）；
5. 成功：`ToolResult(ok=True, result=f"wrote {path} ({bytes} bytes, trials_fingerprint={tf}, bundle_sha256={bh})")`——**必须**为短文本（<512 字符，保证事件流 result_summary 不被 `src/agent/loop.py:24` 的 `_SUMMARY_LIMIT=512` 截断；64+64 hex + 路径 + 固定文案 ≈ 200 字符，安全）。

**沙箱规则复用（冻结，沿用提案 §⑨.2 方案）**：新增 `src/tools/_sandbox_io.py`，按 `src/tools/file_write.py:39-79` 的五步规则（`..`/绝对路径拒绝 → realpath + `is_relative_to` 组件边界 → 各级目录 lstat 拒绝符号链接 → 大小上限 → 沙箱内自动建目录）实现为可复用函数（如 `validate_sandbox_path(path_str, sandbox_root) -> Path`）。**禁止修改 `src/tools/file_write.py`**——helper 与其并行存在，两处文件头**必须**注明同步义务注释（"与 file_write.py 的五步规则保持同步，任何规则变更须两处同改并回提 Architect"）。沙箱根 = `Path(settings.data_sandbox_dir)`（默认 `"data"`，零新配置）。

### 5.4 注册方式（M1 零修改落地，冻结）

```python
# 新文件 src/agent/experiment_registry.py（不改 src/agent/__init__.py）
from src.agent import build_registry          # 复用 M1 组装（agent 同包 import，合法）
from src.agent.registry import ToolRegistry
from src.config import Settings
from src.tools import experiment_tools

def build_experiment_registry(settings: Settings) -> ToolRegistry:
    """M1 三工具 + 实验三工具（组合注册：build_registry 零改动）。"""
    registry = build_registry(settings)
    registry.register(experiment_tools.build_validate_spec(settings))
    registry.register(experiment_tools.build_generate_spec(settings))
    registry.register(experiment_tools.build_export_spec(settings))
    return registry
```

- `ToolRegistry.register`（`src/agent/registry.py:24-33`）的既有校验（name 非空/不重复、input_model 为 BaseModel 子类、executor 为 async callable）对新工具同样生效——三工具天然满足，**禁止**改注册器。
- 工具级失败（输入非 dict、序列化失败等基础设施错误）走 `registry.execute` 既有 `ok=False` 路径（`invalid arguments: ...` / `tool execution failed: ...`，`src/agent/registry.py:50-64`）；领域级失败（spec 问题）永远 `ok=True` + `valid:false`——回传 LLM 时**不带** `ERROR:` 前缀（`src/agent/loop.py:139-141` 的前缀逻辑只作用于 `ok=False`），LLM 不会把"设计尚不合法"误判为"工具坏了"。

---

## ⑥ ExperimentBundle 与 SHA-256（用户重点 #3/#4）

### 6.1 canonical JSON 规范（冻结，随 engine_spec_version 版本化）

```python
# src/experiment/canonical.py
def canonical_json(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)
```

- 键排序、无空白、UTF-8、**禁止 NaN/Inf**（`allow_nan=False` 序列化即抛错——引擎数值路径不得产生）。
- **数字表示规则（裁定）**：int 十进制；float 用 Python 最短往返 repr（`json.dumps` 默认行为）。**trials 指纹计算路径中禁止 float**——Trial 全部字段为 int/str/空 dict（`stimulus`/`derived` 恒空），`trials_fingerprint` 跨平台无 float 表示歧义。float 仅出现在：spec 的 `weight`/`ratios`（意图声明）与 Bundle 的 `effective_weights`（审计摘要）——这些路径的指纹（config_fingerprint）在跨实现复现时须遵循同一 float 格式化规范（Python repr 语义），该边界由 conformance 向量集覆盖（OUT-3），契约如实记录为已知边界（风险 R-3，§⑧.5）。
- 指纹全部为**完整 SHA-256**（64 小写 hex，CR-2）：`sha256_hex(text) = hashlib.sha256(text.encode("utf-8")).hexdigest()`。

### 6.2 Bundle 结构（顶层 schema_version=1）

```json
{
  "schema_version": 1,
  "generated_at": "2026-10-20T12:00:00Z",
  "bundle_sha256": "<64hex —— 见下述计算规则>",
  "spec": { "…规范化后的完整 ExperimentSpec（Pydantic 解析后 model_dump，默认值补全）…" },
  "reproducibility": {
    "engine_spec_version": "1.0",
    "config_fingerprint": "<64hex>",
    "trials_fingerprint": "<64hex>",
    "plugin_used": null,
    "effective_weights": {"difficulty": {"easy": 0.5, "hard": 0.5}, "modality": {"audio": 0.5, "visual": 0.5}},
    "allocation": {"practice": {"easy|audio": 2, "easy|visual": 2, "hard|audio": 2, "hard|visual": 2},
                   "main":     {"easy|audio": 24, "easy|visual": 24, "hard|audio": 24, "hard|visual": 24}}
  },
  "trials": [ {"index": 0, "block": "practice", "factors": {"…": "…"}, "stimulus": {}, "derived": {},
               "timing": {"fixation_ms": 500, "stimulus_ms": null, "isi_ms": 1000}}, … ],
  "summary": {"trial_count": 104, "blocks": ["practice", "main"],
              "frequency": {"difficulty": {"easy": 52, "hard": 52}, "modality": {"audio": 52, "visual": 52}}}
}
```

格式契约（冻结）：
- **自包含**：`spec` 节 = 规范化后的完整 ExperimentSpec（**含 seed**）——重生成的唯一输入；`trials` 全量物化；`reproducibility` 含引擎版本与参数摘要（`effective_weights` = C3 归一化后的实际有效权重；`allocation` = **per-block 口径**的每组合实际分配数，组合键 = 按因素声明序以 `|` 连接水平名）；
- **`spec` 必须为规范化对象**：省略默认字段与补全默认字段两种写法的 `config_fingerprint` 一致（指纹对解析后对象计算，提案 MI-2 语义）；
- `allocation` 中被过滤组合（权重 0 / filter / 互斥剔除）**不出现**（只记录实际分配非 0 的组合）；
- 落盘文件本身 = canonical JSON 单行（UTF-8，无 BOM）。

### 6.3 SHA-256 双指纹与计算规则（CR-2/CR-3，冻结）

| 指纹 | 计算 |
|------|------|
| `config_fingerprint` | `sha256_hex(canonical_json(spec.model_dump()))`（第三元数据：迭代对账——同一 spec 反复验证/生成，指纹恒定） |
| `trials_fingerprint` | `sha256_hex(canonical_json([t.model_dump() for t in trials]))` |
| `bundle_sha256` | `sha256_hex(canonical_json(bundle 剥离 "bundle_sha256" 与 "generated_at" 两键后的 dict))` —— **generated_at 不参与任何指纹**（时间戳非确定性输入） |

**双指纹（用户口径）= `trials_fingerprint` + `bundle_sha256`**；`config_fingerprint` 为补充元数据（不改变"双"的口径）。

### 6.4 独立验证两路径（冻结）

1. **重生成比对**（需要兼容实现）：同 spec+seed 重新生成 → canonical JSON 逐字节相同 + 双指纹相同（测试 PA-2/PA-13 覆盖）；
2. **仅验证**（**不需要任何生成器实现**）：`src/experiment/verify.py` 提供：

```python
class VerifyReport(BaseModel):
    ok: bool                      # 两项检查全过才为 True
    bundle_sha256_match: bool     # 重算（§6.3 规则）== 记录值
    trials_fingerprint_match: bool  # trials canonical → sha256 == reproducibility.trials_fingerprint
    detail: str                   # 人类可读结果

def verify_bundle(path: str | Path) -> VerifyReport: ...
# CLI：python -m src.experiment.verify <bundle_path>   # ok → exit 0；失败 → exit 1 + stderr 详情
```

verify 是纯读操作（读指定路径、重算、比对），属验收/审计工具，不受 data/ 沙箱写规则约束。**禁止**在 verify 中调用生成器（路径②的语义就是"无生成器也可校验完整性"）。

---

## ⑦ 测试清单与 PA 验收条目（QA 执行依据）

测试布局：`tests/unit/experiment/`（单元）+ `tests/integration/test_experiment_agent.py`（FakeLLM 集成）+ `tests/golden/`（黄金文件）。不新增 pytest marker（用路径 + `-k` 选择器，零 pyproject 变更）。FakeLLM 复用 `tests/integration/fake_llm.py`（真实 loop + 真实工具 + 假 LLM，M1-1 模式）。

### PA 条目（每条含命令与判据，QA 照此执行）

| ID | 范围 | 测试名（冻结） | 命令 | 判据 |
|----|------|----------------|------|------|
| PA-1 | schema 单元 | `test_spec_accepts_*`（合法用例：提案 §4.2 通用示例、Demo spec、默认值省略形态）；`test_spec_rejects_*`（非法：缺 seed、seed 越界、factors/levels/blocks/responses 重名、factor_filter/ratios/mutually_exclusive 引用不存在、options 与 kind 不匹配、scale 缺失/多余、paradigm=null 且 params 非空、组合数 >100_000、trial_count 越界） | `python -m pytest tests/unit/experiment -k "spec_"` | 合法用例全过、非法用例逐条返回含对应 path 的 `SCHEMA_INVALID` |
| PA-2 | 确定性 | `test_generation_same_seed_byte_identical`（同进程两次 canonical 全等）；`test_generation_cross_pythonhashseed`（子进程 PYTHONHASHSEED=1/=2 输出 diff 为空）；`test_block_isolation`（增删一个 block，其余 block 子序列逐字节不变）；`test_regenerate_bundle_identical`（同 spec+seed 两次 build_bundle，剥离 generated_at 后逐字节相同） | `python -m pytest tests/unit/experiment -k "determin or cross_ or isolation or regenerate"` | diff 为空、子序列不变 |
| PA-3 | 约束与频数 | `test_c1_conflict`、`test_c2_weight_ignored_both_cases`（两情形警告且不影响 valid）、`test_c3_ratio_priority`（ratios 覆盖 weight）、`test_ratio_sum`、`test_ratio_rounded_warning`（10 试次 4 组合 → 3/3/2/2 + 警告在场）；`test_largest_remainder_math`（频数和 == trial_count；每组合 count ∈ {floor, floor+1}；余数按 fractional 降序/声明序分配——多组固定 seed 断言精确整数，含 Demo spec：104 试次每组合 26、每水平 52/52）；`test_trial_count_mismatch`（ratios 置 0 + filter 圈定构造触发）；`test_mutex_violation_empty`、`test_mutex_violation_same_factor`；`test_block_filter_empty`；`test_correct_from_unknown`；`test_unknown_paradigm`、`test_unsupported_constraint_max_repeat` | `python -m pytest tests/unit/experiment -k "c1 or c2 or c3 or ratio or remainder or mismatch or mutex or filter_empty or correct_from or paradigm or unsupported"` | 全绿；UNSAT 各形态返回对应错误码且 message/suggestion 非空；频数断言为精确整数 |
| PA-4 | canonical JSON | `test_canonical_sorted_compact`（键排序、无空白）；`test_canonical_utf8`（中文水平名往返）；`test_canonical_rejects_nan`；`test_default_omission_same_fingerprint`（省略/补全默认字段 config_fingerprint 一致） | `python -m pytest tests/unit/experiment -k canonical` | 全绿 |
| PA-5 | SHA-256 | `test_sha256_known_vectors`（固定输入 → 期望 64 hex 常量，期望值由独立 `python -c "import hashlib;..."` 计算后写死在测试中）；`test_fingerprint_full_length`（三指纹均 64 小写 hex）；`test_bundle_sha256_excludes_timestamp`（改 generated_at 不变 bundle_sha256）；`test_verify_bundle_ok`（verify 通过）；`test_verify_bundle_detects_tamper`（篡改 trials 任一字节 → 两项 check 失败、exit 1） | `python -m pytest tests/unit/experiment -k "sha256 or fingerprint or verify"` | 全绿 |
| PA-6 | UNSAT/SEARCH_EXHAUSTED 语义 | `test_unsat_error_code_mapping`（§4.4 表中 UNSAT 类逐码触发断言）；`test_search_exhausted_framework_capability`（**声明性弱断言**：错误码在实现枚举/常量中在场、`Settings.experiment_max_search_attempts` 存在且默认 100、`generate_trials` 签名含 max_attempts——契约如实声明：Phase A 无搜索路径，本条不测触发行为，真实触发测试随 Phase B max_repeat 进入） | `python -m pytest tests/unit/experiment -k "unsat or search_exhausted"` | 全绿（含弱断言的局限性说明注释） |
| PA-7 | 工具层单元 | `test_tool_specs_registered_flags`（三工具 idempotency/risk_level 声明：idempotent/low ×2、non-idempotent/medium ×1；`effective_idempotency` 默认返回声明值）；`test_validate_domain_vs_tool_error`（坏 spec → ok=True+valid:false 不带 ERROR:；非 dict config → registry 路径 ok=False）；`test_config_size_blocked`（>256KB → BLOCKED）；`test_generate_no_file_written`（generate 后 data/ 无新文件）；`test_errors_truncated_at_20` | `python -m pytest tests/unit/experiment -k "tool_"` | 全绿 |
| PA-8 | FakeLLM 全循环 | `test_design_iteration_success`：脚本 [validate(含 C1 冲突的 spec) → valid:false, validate(修正后) → valid:true, generate, export, final]；断言：completed；`data/experiments/` 下 Bundle 存在；`generate_trials` 输出 trials_fingerprint == Bundle 内值；`python -m src.experiment.verify <bundle>` 通过；FakeLLM 第二轮收到的 messages 含第一轮验证 JSON（迭代证据）；**事件断言 validate ≥1、generate ≥1、export ==1** | `python -m pytest tests/integration -k design_iteration_success` | 全绿 |
| PA-9 | 停滞终止 | `test_design_iteration_stalled`：三次提交同一错误 spec，previous_errors 逐轮累积（[] → [f1] → [f1,f1]）→ 第 3 次收到 `ITERATION_STALLED` → final；断言终止且未导出 | `python -m pytest tests/integration -k stalled` | 全绿 |
| PA-10 | max_steps 兜底 | `test_design_iteration_max_steps`：恒返回 validate(同一坏 spec) → failed + final 必发（M1 机制防挂死兜底） | `python -m pytest tests/integration -k "max_steps"` | 全绿 |
| PA-11 | export 沙箱安全 | `test_export_blocks_traversal`（`../evil.json`、绝对路径）；`test_export_blocks_symlink`（沙箱内符号链接目录/文件）；`test_export_blocks_prefix_confusion`（data-evil 前缀歧义）；`test_export_blocks_oversize`（构造 >1MB Bundle → BLOCKED: export too large）；沙箱根指到 tmp_path（与 M1 file_write 测试同构） | `python -m pytest tests/unit/experiment -k "export_blocks or export_sandbox"` | 全绿（五步规则全部生效证据） |
| PA-12 | 分层/依赖/安全静态 | `python -m scripts.check_layers`（experiment 层登记后退出码 0）；静态扫描：`src/experiment/` 无 `import src.agent`/`import src.tools`、无 `random.` 模块级函数调用（只允许 `random.Random`）、无 `datetime.now`/`uuid` 进入 generation.py；`src/tools/experiment_tools.py` 无 `import src.agent`；全仓无白名单外依赖（`pyproject.toml` dependencies 不变） | `python -m scripts.check_layers && python -m pytest tests/unit/experiment -k "layers or static_guard"` | 退出码 0、全绿 |
| PA-13 | 黄金文件 | `tests/golden/generic-2x2-seed7.json`（§7.1 冻结 spec）；`test_golden_export_unchanged`：`build_bundle(spec, generated_at=固定值)` → 落盘字节与 golden **逐字节一致**（含 bundle_sha256）；更新流程 `UPDATE_GOLDEN=1 python -m pytest tests/golden` → 人工 review → PR 说明（engine_spec_version 同步递增） | `python -m pytest tests/golden` | 逐字节 diff 为空 |
| PA-14 | Demo（真实 LLM） | `python examples/run_experiment_agent.py`（qwen2.5:7b @ Ollama，用户环境执行，M1-2 模式） | exit 0；stdout 含 `status: completed`、`bundle:` 行、双指纹行（64 hex）；`python -m src.experiment.verify <bundle 路径>` exit 0；事件序列（logs/agent-*.jsonl）validate ≥1、generate ≥1、export ==1、final=completed |

### 7.1 黄金文件 spec（冻结，任何范式无关）

```json
{"schema_version": 1, "name": "generic-2x2", "version": "0.1.0", "seed": 7, "paradigm": null,
 "factors": [{"name": "difficulty", "levels": [{"name": "easy"}, {"name": "hard"}]},
             {"name": "modality",   "levels": [{"name": "visual"}, {"name": "audio"}]}],
 "blocks": [{"name": "practice", "trial_count": 8},
            {"name": "main", "trial_count": 40}],
 "constraints": {"balance": true},
 "responses": [{"name": "judge_difficulty", "kind": "choice", "options": ["easy", "hard"],
                "correct_from": "difficulty"}],
 "timing": {"fixation_ms": 500, "stimulus_ms": null, "isi_ms": 1000}}
```

自洽性：4 组合；practice 8 = 4×2、main 40 = 4×10（整除，无 RATIO_ROUNDED）；总计 48 试次，每组合 12（2+10），每水平 24/24。黄金文件中 `generated_at` 固定为 `"2026-01-01T00:00:00Z"`（测试注入）。

**PA 验收标准位于本契约内；不动 `docs/ACCEPTANCE_CRITERIA.md`**——Phase A 全部验收通过并经用户批准后，PA-1~PA-14 再由 Lead 并入正式验收标准文档。

---

## ⑧ M1 接口影响评估（用户重点 #7）

### 8.1 零修改声明（冻结）

**M1 既有文件零修改**：`src/agent/loop.py`、`src/agent/registry.py`、`src/agent/llm.py`、`src/agent/events.py`、`src/agent/__init__.py`、`src/models/*`、`src/tools/calc.py`、`src/tools/http_request.py`、`src/tools/file_write.py`、`examples/run_agent.py`、`tests/`（M1 既有测试）。全部新能力经**新增文件**交付：

| 动作 | 文件 |
|------|------|
| 新增 | `src/experiment/`（`__init__.py`、`schemas.py`、`canonical.py`、`validation.py`、`generation.py`、`export.py`、`verify.py`） |
| 新增 | `src/tools/experiment_tools.py`、`src/tools/_sandbox_io.py` |
| 新增 | `src/agent/experiment_registry.py` |
| 新增 | `examples/run_experiment_agent.py` |
| 新增 | `tests/unit/experiment/`、`tests/golden/`、`tests/integration/test_experiment_agent.py` |
| **不改** | 上列全部 M1 文件 |

### 8.2 config.py 新增字段的裁定（用户指定的裁定点）

**裁定：属"扩展"，非"修改"，批准实施。** 新增一个字段：

```python
# src/config.py — Settings 追加（既有字段一律不动）：
experiment_max_search_attempts: int = 100   # SEARCH_EXHAUSTED 框架能力参数（§④.2；Phase A 无消费路径，Phase B 序列约束消费）
```

理由：①M1 契约 §4 的约束是"不改（既有）字段——新配置项须回提 Architect"——本次正是 Architect 经用户批准的正式回提，流程合规；②`BaseSettings` 新字段带默认值：既有构造路径（`get_settings()`、M1 全部测试、`extra="ignore"` 语义）行为不变，M1 代码对新增字段零感知；③无 key、无敏感信息，不触合规红线。**回归验证要求（QA 必跑）**：

```
python -m pytest tests/unit/test_calc.py tests/unit/test_http_request.py tests/unit/test_file_write.py \
  tests/unit/test_registry.py tests/unit/test_health.py tests/integration/test_loop.py
python -m pytest tests/e2e   # 若 M1 存在 e2e 套件，一并复跑
```

M1 测试套件必须全绿（config 扩展不破坏 M1 行为的证据）。

### 8.3 门禁脚本配置扩展（check_layers.py）

`scripts/check_layers.py:25-31` 的 `LAYER_ORDER` 为显式白名单——**未登记的 `src/experiment/` 层当前完全不受门禁保护**（脚本对未知层不检查任何方向）。**必须**登记：

```python
LAYER_ORDER: dict[str, int] = {
    "api": 0, "services": 1, "agent": 2, "tools": 3, "storage": 3,
    "experiment": 4,   # Phase A 新增：tools 之下的实验引擎层
}
```

裁定：这是**门禁配置变更**（往 dict 增加一行），不改任何既有层的检查规则、不改 M1 产品代码——沿用提案 §⑨.1 的定性，作为本契约的一部分提请用户批准（本次批准契约即批准此行）。生效后 `experiment` 层受完整保护：不得 import agent/tools/storage/api/services，只可依赖 `src/models`/`src/config` 与标准库/白名单三方。

### 8.4 分层与依赖方向（G-4，冻结）

```
api → services → agent → tools → experiment → models/config
```

- `src/experiment/` **禁止** import `src.agent` / `src.tools` / `src.api` / `src.services` / `src.storage`；只允许 `src.models`、`src.config` 与标准库；
- `src/tools/experiment_tools.py`（tools 层）→ `src.experiment` 合法（高层 → 低层）；
- `src/agent/experiment_registry.py`（agent 层）→ tools / experiment 合法；
- 共享类型（`ToolSpec`、`ToolResult`）一律经 `src/models/`（工具构造 ToolSpec import `src.models.tool_spec`，M1 既有模式）。

### 8.5 风险报告（不改 M1 默认行为，全部用适配层解决）

| # | 风险 | 影响与建议 | 处置 |
|----|------|-----------|------|
| R-1 | `src/agent/loop.py:24` `_SUMMARY_LIMIT=512`：`tool_result` 事件的 `result_summary` 截断至 512 字符（loop.py:136）——validate/generate 的完整 JSON 报告**进事件流时被截断**，可观测性受损 | 不影响 LLM：tool message 的 content 用 `tool_result.result` **全量**（loop.py:139-144），验证报告完整进入对话；仅事件流/JSONL 摘要截断。**不改 loop**。验收判据以 tool message（FakeLLM received_messages）与落盘文件为准（PA-8 已按此设计） | 接受 + 测试口径规避 |
| R-2 | 验证报告体积无上限 → LLM 上下文膨胀（错误极多的 spec） | 工具层适配：errors 最多 20 条 + `errors_truncated: true`（§5.1），不动 loop | 工具层护栏 |
| R-3 | `random.Random.shuffle`/MT19937 的跨 Python 版本稳定性是实现细节（非语言规范保证）；float 最短往返表示跨语言有边界差异 | Phase A 可重复性范围 = 同 Python 实现与版本（§3.5 声明）；Python 版本升级时黄金文件（PA-13）是回归网；跨实现复现依赖 conformance 向量集（OUT-3） | 契约声明边界 |
| R-4 | qwen2.5:7b 生成 spec JSON 的格式/语义错误率（Demo） | 缓解：validate_experiment 返回 error_code/path/suggestion 机器可读错误，AgentLoop 多步循环内部自然迭代修正（无需外部重试）；Demo 运行策略见 §⑨.4 | 设计内吸收 |
| R-5 | `check_layers.py` 若不登记 experiment 层则该层无门禁保护（§8.3） | 已裁定登记（一行配置扩展） | 本契约批准即生效 |
| R-6 | 1MB 导出上限 ≈ 5k 试次（每试次约 200B canonical） | Phase A 接受；超限显式 `BLOCKED: export too large`；分块导出/多文件包推迟（§⑩.5） | 显式失败 |

---

## ⑨ Demo 设计（用户重点 #9）

### 9.1 入口与工具集

新文件 `examples/run_experiment_agent.py`（结构对齐 `examples/run_agent.py`：sys.path 注入 → get_settings → key 显式校验（缺失 → stderr + exit 2，M1-2 模式）→ 组装 → 运行 → stdout 输出）。

**工具集裁定：只注册实验三工具（validate_experiment / generate_trials / export_experiment），不含 calc，也不含 http_request/file_write**。理由：①实验循环的全部算术权威是引擎——validate 返回 stats、generate 返回 frequency，"LLM 不做算术"由引擎直接承担，calc 无增量价值；②工具面越小，7b 模型误选工具的概率越低（Demo 稳健性，R-4 缓解）；③export 自含写盘，file_write 冗余且会引入"用 file_write 写伪 Bundle"的旁路风险；④Demo 聚焦展示"自然语言 → 验证 → 生成 → 导出"最小闭环。

```python
# Demo 组装（不经 build_experiment_registry——那是 6 工具组合，供测试与未来通用使用）
registry = ToolRegistry()
registry.register(experiment_tools.build_validate_spec(settings))
registry.register(experiment_tools.build_generate_spec(settings))
registry.register(experiment_tools.build_export_spec(settings))
loop = AgentLoop(client=LLMClient(settings), registry=registry, settings=settings, task_id=task_id)
```

集成测试（PA-8~10）**必须**统一经 `build_experiment_registry(settings)`（同时使组合注册函数获得覆盖）。

### 9.2 Demo 任务（goal 自然语言，冻结）

```
设计一个通用两因素实验并导出为实验包。要求：因素 difficulty 有 easy 和 hard 两个水平，
因素 modality 有 visual 和 audio 两个水平；两个 block：practice 8 试次、main 96 试次；
约束 balance=true（所有因素组合等频）；响应变量 respond 为 choice 类型，选项 easy/hard，
正确答案来自因素 difficulty；timing：fixation 500ms、stimulus 直至响应、ISI 1000ms；seed=42。
请先用 validate_experiment 验证规格，再用 generate_trials 确认频数分布，
最后用 export_experiment 导出到 experiments/ 目录下的 JSON 文件。
```

自洽性：4 组合；8 = 4×2、96 = 4×24（整除，无 RATIO_ROUNDED）；总计 104 试次，每组合 26，每水平 52/52——PA-3/PA-8 断言口径。无任何认知范式指向。

### 9.3 成功判据（PA-14）

1. exit 0；stdout 顺序：`task_id:` 行 → 运行结束 `status: completed` / `result:` 行 → 若导出成功，追加三行 `bundle: <相对路径>`、`trials_fingerprint: <64hex>`、`bundle_sha256: <64hex>`（Demo 入口在 run_task 后扫描 `AgentResult.events`：以 tool_call 事件的 `tool_call_id → tool_name` 映射定位 export_experiment 的成功 tool_result，从其 result_summary 提取路径与指纹——**禁止**为获取这些信息修改 AgentLoop）；
2. `data/experiments/` 下 Bundle 存在，`python -m src.experiment.verify <路径>` exit 0；
3. 事件序列（logs/agent-<task_id>.jsonl）：validate_experiment ≥1、generate_trials ≥1、export_experiment ==1、final=completed；
4. 典型步数 4~8 轮（M1 `calc_agent_max_steps=25` 硬上限兜底）。

### 9.4 运行策略（R-4 缓解，冻结）

- **AgentLoop 内部自然迭代**：多步循环本身就是迭代修正机制（validate 失败 → 错误 JSON 回传 → 模型改 spec → 复验），**无外部重试**、无 Demo 专属循环代码；
- 环境要求：`.env` 配置 `OPENAI_API_KEY`（Ollama 兼容端点任意非空值）+ `LLM_BASE_URL=http://localhost:11434/v1` + `LLM_MODEL=qwen2.5:7b`（M1-2 已验证该链路真实可用，`docs/handoff/m1-2-report.md`）；
- 若模型首轮 spec 含错误（预期常态），验证报告的 error_code/path/suggestion 引导修正——**这本身就是设计循环的展示目标**，不是 Demo 缺陷；
- 失败模式（max_steps 截断 / 模型放弃）→ exit 1，如实报告（Demo 不粉饰失败）。

---

## ⑩ 开放问题（不阻塞 Phase A，留待后续阶段决策）

1. **conformance 向量集**（OUT-3）：跨实现权威 `(spec, canonical_json(trials), trials_fingerprint)` 三元组，须复刻 MT19937 初始化、shuffle 消费序与 float 表示——`engine_spec_version` 对外发布（宣称跨实现兼容）的前置必选条件，Phase B+ 启动。
2. **max_repeat 序列约束 + SEARCH_EXHAUSTED 真实触发路径**（OUT-4）：拒绝采样/重排 + 验证期必要条件预判（UNSAT 快速失败 vs 搜索耗尽的完整语义闭环），Phase B。
3. **ParadigmPlugin 协议与插件治理**（OUT-1）：kind 声明、validate 钩子、分发形态——Phase B+，届时 UNKNOWN_PARADIGM 语义从"Phase A 无插件"升级为"注册表查找失败"。
4. **strict balance 语义**（§4.3）：`trial_count` 不整除组合数时是否提供严格等频模式（`BALANCE_NOT_DIVISIBLE` UNSAT 错误），需新增字段并递增 engine_spec_version。
5. **GameSpec 产出通道与游戏表现层**（OUT-2）：LLM 直接生成 or 独立工具，待游戏阶段。
6. **超大实验分块导出**（R-6/OUT-7）：bundle 目录/多文件包，待真实需求。
7. **previous_errors 软协议硬化**（OUT-8）：维持 v2.1 裁定（LLM 侧状态 + max_steps 兜底），Phase A 后依 Demo 数据评估。
8. **与 M2 的交汇**：generate/validate 的幂等声明天然适配 M2 恢复矩阵；export 非幂等与 file_write 同级——刻意不设计 M2 交互细节，待 M2 契约冻结对齐。

---

## Backend 实现确认清单（实现完成后逐项自查）

- [ ] `src/experiment/schemas.py`：字段与 §②.1 逐字段一致；model_validator V1~V9 全部实现；`paradigm`/`paradigm_params` 保留（Phase A 拒绝非 null / 非空 params，不删字段）。
- [ ] `src/experiment/canonical.py`：`canonical_json` 五参数（sort_keys/ensure_ascii=False/separators/allow_nan=False）一字不差；三指纹计算规则与 §⑥.3 一致（全 64 hex，无 `[:8]` 截断）。
- [ ] `src/experiment/validation.py`：ValidationIssue 四字段；错误码枚举与 §④.4 表逐码一致；C1/C2/C3、UNSAT 各形态、验证顺序（Pydantic → 支持性 → 约束语义 → 逐 block 可满足性）与契约一致；errors 上限 20 + errors_truncated。
- [ ] `src/experiment/generation.py`：`derive_block_seed` = SHA-256(f"{seed}:block:{block.name}") 前 8 字节 big-endian int64；算法 9 步与 §③.3 一致（largest remainder 并列按声明序、每 block 恰一次 shuffle、展开序保序输出）；`ENGINE_SPEC_VERSION="1.0"`；无 set 迭代、无 `random` 模块级函数、无 now/uuid。
- [ ] `src/experiment/export.py`：`build_bundle(spec, *, generated_at=None)`；Bundle 结构与 §⑥.2 键集一致；`bundle_sha256` 剥离两键计算；allocation per-block 口径、被过滤组合不出现。
- [ ] `src/experiment/verify.py`：`verify_bundle` + `python -m src.experiment.verify` CLI（exit 0/1）；不调用生成器。
- [ ] `src/tools/_sandbox_io.py`：五步规则与 `file_write.py:39-79` 同语义；文件头同步义务注释；**未修改 file_write.py**。
- [ ] `src/tools/experiment_tools.py`：三工具 name/description/input_model/idempotency/risk_level 与 §⑤ 一致；领域级失败 ok=True+valid:false（无 ERROR: 前缀）；256KB 与 1MB 护栏；export result 文本 <512 字符。
- [ ] `src/agent/experiment_registry.py`：`build_experiment_registry` 组合注册；`src/agent/__init__.py` 未动。
- [ ] `src/config.py`：仅追加 `experiment_max_search_attempts: int = 100`，既有字段零改动。
- [ ] `scripts/check_layers.py`：LAYER_ORDER 追加 `"experiment": 4` 一行，其余未动。
- [ ] `examples/run_experiment_agent.py`：goal 文本与 §⑨.2 一致；三工具注册；stdout 顺序（task_id / status / result / bundle+指纹行）；exit 0/1/2。
- [ ] M1 零修改复核：`git diff --stat` 确认 M1 文件清单（§⑧.1）无变更。
- [ ] M1 回归：§⑧.2 两条命令全绿。
- [ ] 测试清单 PA-1~PA-13 全部落地，`-k` 选择器可被验收命令命中；黄金文件 spec 与 §⑦.1 一致、generated_at 固定 2026-01-01T00:00:00Z。
- [ ] 无白名单外依赖（pyproject dependencies 未变）；测试与工具代码无任何真实形态密钥。
- [ ] 交接文档 `docs/handoff/backend-phaseA.md`：改动文件清单、运行方式（含 Demo 与 verify 命令）、已知限制（SEARCH_EXHAUSTED 不可触发等）。

> 完成自查后提请 QA 按本契约 §⑦ PA-1~PA-13 执行验收（PA-14 Demo 真实 LLM 项由用户环境执行）。全部通过后由 Lead 提请用户批准将 PA 条目并入 `docs/ACCEPTANCE_CRITERIA.md`。
