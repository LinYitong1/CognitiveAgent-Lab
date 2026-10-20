# Phase B 契约 — GameSpec 与可玩 HTML 游戏生成（B0 Schema + B1 工具 + B2 渲染器：冻结版）

> 作者：Architect Agent ｜ 状态：**冻结**（B0/B1/B2 已获用户批准实施；§2~§9=B0，§10=B1，§11=B2）
> 依据：`docs/plans/phaseB-plan.md`（用户已批准）、`docs/proposals/experiment-tools-design-proposal.md` v2.1 §4.0/§4.5/§7.2（裁剪+精化，差异见 §7）
> 基线：commit `433419b`（Phase A 全绿 128/128 + PA-14 已知问题登记）
> 硬边界：**不修改 M1 与 Phase A 已验收代码**（`game_schemas.py` 为纯新增文件；canonical_json 复用不改动）；不运行真实 LLM；不绑定任何范式/主题/模型；B1/B2/B3 不提前实施。

---

## §1 职责边界（v2.1 §4.0 延伸，机器可查条款）

铁律：**实验逻辑归 ExperimentSpec/Bundle，游戏表现归 GameSpec。** GameSpec 只有"引用"，没有"重算"。

| 关注点 | Bundle（实验层） | GameSpec（表现层） |
|--------|-----------------|-------------------|
| 因素/水平/条件分配/试次序列/正确性判定（`correct_from`）/计时（fixation/stimulus/ISI）/响应变量类型与取值域 | ✅ 权威来源 | ❌ **schema 层不存在对应字段**（§6 GB-2/GB-8 机器查证） |
| 键位映射/反馈有无与样式/场景布局与主题/交互流程（ready/间歇/结束）/游戏化包装 | ❌ | ✅ |

**机器可查条款（防篡改四道防线，B0 落实第 1 道）**：
1. **D-1（B0）**：GameSpec 全部模型 `extra="forbid"`——任何未声明字段（含试图夹带的 trials/correct/约束字段）→ `SCHEMA_INVALID`；且 schema 字段树与禁止名集合（`trials/factors/blocks/constraints/correct/correct_from/seed/timing/responses` 的**拥有权归实验层**）交集为空（测试 GB-8 内省断言）。
2. D-2（B2）：渲染器是 trials 唯一消费者；判定走确定性代码（渲染器产物内嵌，非 LLM 产物）。
3. D-3（B2）：HTML 启动时校验 `bundle_sha256` + `trials_fingerprint`。
4. D-4（B2）：事件日志与 trials 机器对账（pytest 逻辑核）。

## §2 GameSpec schema（实现位置：`src/experiment/game_schemas.py`，纯新增）

```python
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

_HEX64 = r"^[0-9a-f]{64}$"

class _Forbid(BaseModel):
    model_config = ConfigDict(extra="forbid")   # 防线 D-1：拒收一切未声明字段

class GameMeta(_Forbid):
    name: str = Field(min_length=1, max_length=100)
    version: str = "0.1.0"

class ExperimentRef(_Forbid):
    """对 ExperimentBundle 的引用（三重指纹对齐——v2.1 双指纹 + B0 新增整包指纹）。"""
    name: str                                   # 须与 bundle.spec.name 一致（G2）
    version: str                                # 须与 bundle.spec.version 一致（G2）
    seed: int                                   # 须与 bundle.spec.seed 一致（G2）
    config_fingerprint: str = Field(pattern=_HEX64)   # 须与 bundle.reproducibility.config_fingerprint 一致
    trials_fingerprint: str = Field(pattern=_HEX64)   # 须与 bundle.reproducibility.trials_fingerprint 一致
    bundle_sha256: str = Field(pattern=_HEX64)        # B0 新增：整包指纹（覆盖 spec+trials+元数据）

class SceneSpec(_Forbid):
    title: str = Field(default="", max_length=200)        # 展示标题（纯呈现）
    instructions: str = Field(default="", max_length=2000)  # ready 屏说明文案（纯呈现）
    layout: Literal["canvas-center", "rows"] = "canvas-center"  # 试次呈现布局（枚举，渲染器解释）
    theme: Literal["neutral-light", "dark"] = "neutral-light"   # 视觉主题（枚举）
    assets: dict[str, str] = Field(default_factory=dict)  # 静态装饰素材名→内联文本/data-URL；
                                                          # 仅用于界面装饰，禁止参与试次内容（D-2 由渲染器契约落实）

class InputBinding(_Forbid):
    response_name: str          # 必须是 bundle.spec.responses[].name（G3）
    keys: dict[str, str]        # 物理键（小写单字符或 "space" 等命名键）→ 选项值（choice 型取值域内，G4）

class InputSpec(_Forbid):
    modalities: list[Literal["keyboard"]] = ["keyboard"]  # B0 仅 keyboard；pointer/touch 为保留枚举位（扩展走契约修订）
    bindings: list[InputBinding] = Field(default_factory=list)

class FeedbackSpec(_Forbid):
    on_response: Literal["none", "correctness-flash", "outcome-text"] = "none"  # 正确性只读 Bundle 判定，GameSpec 只选样式
    duration_ms: int = Field(default=200, ge=0, le=5000)

class FlowSpec(_Forbid):
    ready_screen: bool = True
    block_breaks: bool = True
    end_screen: Literal["none", "summary"] = "summary"

class GamificationSpec(_Forbid):
    score: bool = False         # 得分由渲染器按 Bundle 正确性累计（呈现层不定义对错）
    progress_bar: bool = True
    streak_bonus: bool = False

class GameSpec(_Forbid):
    schema_version: Literal[1] = 1
    game: GameMeta
    experiment_ref: ExperimentRef
    scene: SceneSpec = SceneSpec()
    input: InputSpec = InputSpec()
    feedback: FeedbackSpec = FeedbackSpec()
    flow: FlowSpec = FlowSpec()
    gamification: GamificationSpec = GamificationSpec()
```

体积护栏：GameSpec 序列化字节 > **256KB** → 拒绝（`GAME_SPEC_TOO_LARGE`，镜像 Phase A config 护栏）。

## §3 最小交互契约（状态机与玩家操作）

**交互类型**（由 Bundle `responses[].kind` 驱动，GameSpec 只绑定输入方式）：
- `choice`：按键选择（经 `input.bindings` 键位映射；无绑定 → 不可玩 → G5 报错）；
- `text`：键盘直接输入（无需绑定）；
- `rating`：数字键选择量表值（无需绑定）。

**场景与状态转换**（渲染器确定性实现，B2 冻结细节；B0 冻结抽象）：

```
READY(flow.ready_screen) ──按任意键──► TRIAL_LOOP(block 依序)
TRIAL: FIXATION(timing.fixation_ms) → STIMULUS(timing.stimulus_ms|null=直至响应)
       → [RESPONSE 窗口内记录玩家操作] → FEEDBACK(feedback.on_response≠none 时, duration_ms)
       → ISI(timing.isi_ms) → 下一试次
块末 → BLOCK_BREAK(flow.block_breaks=true 且还有后续块) → 下一块
全部完成 → END_SUMMARY(flow.end_screen=summary) → COMPLETE
```

**玩家操作**：ready 确认键、试次内按键/输入/量表选择。B0 不支持暂停/跳过/重试试次（保计时保真；扩展走契约修订）。

**事件日志**（B2 渲染器产出，格式 B2 冻结）：每玩家操作记录 `{trial_index, response_name, value, timestamp}`；正确性**只**由渲染器内嵌确定性代码按 Bundle `correct_from` 计算。

## §4 验证规则与错误处理（G 系列规则）

校验函数（B0 实现）：`validate_game(game_spec: object, bundle: object) -> GameValidationResult`（纯函数；bundle 为已加载的 ExperimentBundle dict）。

**规则分层**：G1 schema 层（仅 GameSpec 自身，无 bundle 也可查）；G2~G6 跨层（需 bundle）；G7 护栏。

| 规则 | 检查 | 错误码 |
|------|------|--------|
| G1 | Pydantic 校验 + `extra="forbid"` 拒收未声明字段 | `SCHEMA_INVALID` |
| G2 | experiment_ref 的 name/version/seed/config_fingerprint/trials_fingerprint/bundle_sha256 六项逐一与 Bundle 对齐 | `REF_MISMATCH`（path 指明首个失配字段） |
| G3 | `bindings[].response_name` ∈ bundle.spec.responses 名集合 | `UNKNOWN_RESPONSE` |
| G4 | binding 目标必须为 `kind="choice"`（text/rating 不接受绑定） | `INVALID_BINDING_TARGET` |
| G5 | keys 值 ∈ 该 response 的 `options`；物理键不与其他 binding 重复；每个 choice response 且 keyboard 模态下至少一个绑定 | `OPTION_OUT_OF_DOMAIN` / `DUPLICATE_KEY` / `MISSING_BINDING` |
| G6 | 物理键格式：单个小写字符或命名键集合 {space, enter, left, right, up, down} | `INVALID_KEY` |
| G7 | 序列化体积 ≤ 256KB | `GAME_SPEC_TOO_LARGE` |

**两级错误契约（沿用 Phase A §5.4 语义）**：工具级失败（非 dict 输入、护栏拒绝）→ `ok=False`；领域级失败（G1~G6）→ `ok=True` + `valid:false`，错误报告结构化：

```json
{"valid": false,
 "game_config_fingerprint": "<64hex 或 null（G1 失败时）>",
 "errors": [{"error_code": "...", "path": "...", "message": "...", "suggestion": "..."}],
 "warnings": []}
```

迭代防死循环：沿用 `previous_errors` 指纹协议与 `ITERATION_STALLED`（B1 工具层接通，规则与 Phase A 相同）。

## §5 确定性要求

1. **GameSpec 自身零随机**：schema 无随机字段；校验为纯函数。
2. **game_config_fingerprint**：`canonical_json(game_spec)`（复用 `src/experiment/canonical.py`，零修改）→ SHA-256。同内容（键序/空白无关）→ 同指纹；任何字段变更 → 指异。（B0 实现 + GB-7 测试）
3. **渲染确定性（B2 契约预告）**：`render(game_spec, bundle)` 为纯函数——同输入**逐字节**相同 HTML；无时钟读取、无非种子随机；黄金渲染文件 + 外部 shasum 交叉验证（复制 PA-2 模式）。
4. **fixture 通用性**：B0 测试 fixture 一律从黄金 Bundle（`tests/golden/generic-2x2-seed7.json`）派生引用；不得构造范式特定 fixture（防硬编码，GB-10）。

## §6 B0 验收测试计划（pytest，FakeLLM 不涉及；实现于 B0 批准后）

| 编号 | 断言 | 对应用户要求 |
|------|------|--------------|
| GB-1 | 最小合法 GameSpec（引用黄金 Bundle 真实六项指纹）通过 G1+G2 | 有效性 |
| GB-2 | 逐模型注入未声明字段（顶层与每个子模型、含 `trials`/`correct_from` 等实验语义键）→ `SCHEMA_INVALID` | 防线 D-1 / 要求 5 |
| GB-3 | 指纹非 64-hex → `SCHEMA_INVALID`；六项引用逐一变异（name/seed/各指纹）→ `REF_MISMATCH` 且 path 正确 | 要求 6 |
| GB-4 | G3/G4/G5/G6 全错误码正反例（未知响应名/绑定到 text/越域选项/重复键/缺绑定/非法键名） | 要求 6 |
| GB-5 | 错误报告结构完整（error_code/path/message/suggestion） | 要求 6 |
| GB-6 | 合法但含警告的场景（如 text 响应无绑定）→ `valid:true` + warning | 要求 6 |
| GB-7 | 指纹确定性：键序打乱/空白变化 → 同指纹；改任一字段 → 异指纹 | 要求 6/确定性 |
| GB-8 | 内省断言：GameSpec 字段树 ∩ 禁止名集合 = ∅（`model_fields` 递归） | 要求 3/5 |
| GB-9 | 体积护栏：>256KB 拒绝 | 护栏 |
| GB-10 | fixture 通用性：测试代码 grep 无 stroop/nback/范式名；全部引用黄金 Bundle | 要求 2 |
| GB-11 | 全量回归：既有 128 项 + B0 新增全部绿；pyright 0 errors；分层检查 PASS | 不破坏既有 |

## §7 与 v2.1 §4.5 草案的差异清单（全部为 B0 精化，逐条可回退）

1. 全模型 `extra="forbid"`（草案未声明 extra 策略）——防线 D-1 的 schema 落实；
2. `ExperimentRef` 新增 `bundle_sha256`（草案双指纹）——整包完整性更强，成本为零；
3. `SceneSpec.layout` 自由字符串 → `Literal` 枚举（+`theme` 枚举、`title`/`instructions` 呈现文案）——可测试性；
4. `InputSpec.modalities` 收窄为 `["keyboard"]`（B0 最小交互；pointer/touch 为保留扩展位）——要求 7 最小性；
5. 指纹字段加 `^[0-9a-f]{64}$` pattern；数值/长度加界——输入健壮性；
6. G2~G7 跨层规则与错误码表形式化（草案仅提及 bindings 引用 responses 一条）；
7. `assets` 限定为"仅界面装饰"（语义条款，B2 渲染器契约机器查证）。

## §8 边界外（本契约不做）

- B1 `validate_game` 工具 ToolSpec/组合器、B2 渲染器与 HTML 结构、B3 Demo 与开源整理——各自里程碑另订契约节；
- 不实现 pointer/touch、暂停/重试、素材动画、多语言；
- 不接真实 LLM、不做 Ollama 兼容测试（已知问题 PA-14 处置不变）。

## §9 B0 实施澄清（Architect 补充，2026-10-20 实施前）

1. **状态机标记（用户要求 6）**：§3 状态机（READY→…→END_SUMMARY）为 **MVP 支持的流程**，非永久架构限制。未来新交互类型（暂停/跳过/pointer/touch/多阶段试次）经契约修订进入，不影响 GameSpec 其余部分。
2. **bundle_sha256 计算对象（用户要求 7）**：与 Phase A 完全一致、不重定义——`SHA-256(canonical_json(bundle 剥离 "bundle_sha256" 与 "generated_at" 两键))`（见 `src/experiment/export.py`）。三指纹区别：`config_fingerprint` 只覆盖 **spec 配置**（条件设计）；`trials_fingerprint` 只覆盖 **试次序列**（顺序+分配）；`bundle_sha256` 覆盖**整包**（spec+trials+reproducibility+summary），`generated_at` 时间戳不参与任何指纹。G2 验证时**重算整包指纹**并与 `ref.bundle_sha256` 及 `bundle["bundle_sha256"]` 两者比对——验证过程可复现且能检出 Bundle 被篡改。
3. **GB-8 内省豁免（草案内部不一致修正，如实报告）**：§1 D-1 禁止名集合含 `seed`，但 §2 `ExperimentRef.seed` 是 v2.1 已冻结的**引用复制字段**（只读指针，非实验逻辑所有权）。修正：GB-8 的禁止名交集检查**排除 ExperimentRef 子树**（其全部字段均为引用）；其余字段树与禁止名集合交集必须为空。此为 B0 草案自纠，不涉及 Phase A 契约。
4. **GB-6 警告场景明确**：采用 `PARTIAL_OPTION_COVERAGE`（choice 响应的键位绑定未覆盖全部 options——合法但可能有选项不可达）。

## §10 B1：validate_game 工具与 FakeLLM 工作流（冻结）

实现位置：`src/tools/game_tools.py` + `src/agent/game_registry.py`（均纯新增，零修改 M1/Phase A/B0）。

**输入模型**：

```python
class ValidateGameInput(BaseModel):
    game_config: dict[str, object]        # GameSpec JSON 对象（LLM 直接内联生成）
    bundle_path: str = Field(min_length=1)  # 相对 data/ 沙箱根的 ExperimentBundle JSON 路径
    previous_errors: list[str] = Field(default_factory=list)  # error_code:path 指纹（防死循环，同 Phase A §5.4）
```

**ToolSpec 声明（冻结；description 纯 ASCII——R2 教训前置）**：

```
name="validate_game", idempotency="idempotent", risk_level="low"
description:
"Validate GameSpec JSON (presentation layer) against an ExperimentBundle already
exported in data/ sandbox. game_config must be the GameSpec object itself, no
wrapper. Top keys: schema_version(=1),game{name,version},experiment_ref{name,
version,seed,config_fingerprint,trials_fingerprint,bundle_sha256},scene{title,
instructions,layout,theme,assets},input{modalities,bindings[{response_name,keys}]},
feedback{on_response,duration_ms},flow{ready_screen,block_breaks,end_screen},
gamification{score,progress_bar,streak_bonus}. Copy experiment_ref values exactly
from the bundle file. bundle_path is the bundle file path inside data/ sandbox."
```

**执行流程（冻结）**：
1. 工具级护栏（→ `ok=False`，`BLOCKED:` 前缀）：
   a. `game_config` 非 dict → `BLOCKED: game_config must be a JSON object`；
   b. 序列化体积 > 256KB（复用 B0 `MAX_GAME_SPEC_BYTES`）→ `BLOCKED: game config too large`；
   c. `bundle_path` 沙箱路径校验失败 → `BLOCKED: <原因>`（复用 `_sandbox_io.validate_sandbox_path` 第 1~3 步，只读用途）；
   d. bundle 文件不存在 / JSON 解析失败 / 顶层非 dict → `BLOCKED: bundle not loadable ...`；
2. 领域级（→ `ok=True`）：调用 B0 `validate_game(game_config, bundle)`（**规则不重复实现**）；
3. stalled 判定：当次 errors 的 `error_code:path` 指纹，任一在 `previous_errors` 出现 ≥2 次 → `stalled: true` 且 errors 追加 `ITERATION_STALLED`（suggestion 同 Phase A："停止重复提交，总结未解决冲突并请用户裁决"）；
4. 输出（`ToolResult(ok=True, result=<紧凑 JSON>)`）：

```json
{"valid": false, "stalled": false, "game_config_fingerprint": "<64hex 或 null>",
 "errors": [{"error_code": "...", "path": "...", "message": "...", "suggestion": "..."}],
 "warnings": [...]}
```

**组合器**：`build_game_registry(settings) -> ToolRegistry` = 实验三工具（validate_experiment / generate_trials / export_experiment）+ validate_game（复制 `build_experiment_registry` 组合模式；`build_registry` 零改动）。

**边界（冻结）**：
- validate_game 对 data/ 沙箱**只读**（唯一写动作是 None——不写任何文件）；
- ExperimentBundle 在任何路径下都不可被游戏工具修改（集成测试断言前后 sha256 不变）；
- 不实现 design_game/render_game（B2+）；不接真实 LLM。

**B1 验收（QA 以此验收）**：
- BT-1 工具级：非 dict / 超大 / 路径逃逸 / bundle 缺失 / bundle 损坏 → 全部 `ok=False` BLOCKED；
- BT-2 领域级：G1~G6 错误经工具路径返回结构化报告（`ok=True` + `valid:false`），错误码与 B0 单测一致；
- BT-3 stalled：同一错误指纹第 3 次提交 → `stalled:true` + `ITERATION_STALLED`；
- BT-4 FakeLLM 全流程（集成）：export_experiment（写 bundle）→ validate_game（错 ref）→ 收到结构化报告 → validate_game（修正 + previous_errors）→ `valid:true` → final 文本；断言事件序列、bundle 文件前后逐字节不变；
- BT-5 FakeLLM description 进 tools schema；纯 ASCII；组合器注册 4 工具；
- BT-6 全量回归（171+ 新增全绿）、pyright 0、分层 PASS。

## §11 B2：确定性 HTML 游戏渲染器与 render_game 工具（冻结）

实现位置：`src/experiment/game_render.py`（渲染器，纯新增）+ `src/tools/game_tools.py`（追加 render_game 工具）+ `src/agent/game_registry.py`（追加注册）。M1 / Phase A / B0 / B1 既有行为零修改。

### 11.1 前置与复用

- 渲染入口 `render_game_html(bundle, game_spec) -> str` 为**纯函数**：不读时钟、无随机、无 I/O；
- `render_game` 工具执行时**先调用 B0 `validate_game`**（规则零重复）：不通过 → `ok=True` + `valid:false` 报告（含 stalled），**不渲染、不写文件**；通过 → 渲染并写盘；
- 试次/条件/刺激/正确答案**只**来自 `bundle`（D-2：渲染器是 trials 唯一消费者）；GameSpec 仅提供呈现参数。

### 11.2 运行计划（run plan）

`build_run_plan(bundle, game_spec) -> dict`（纯函数，pytest 可测的状态机与数据完整性载体）：

```json
{"meta": {"game_name","title","instructions","theme","layout",
          "feedback":{"on_response","duration_ms"},
          "flow":{"ready_screen","block_breaks","end_screen"},
          "gamification":{"score","progress_bar","streak_bonus"},
          "responses":[{"name","kind","options","scale","correct_from"}],   // 源自 bundle.spec.responses，顺序保留
          "bindings":{"<response_name>":{"<物理键>":"<选项>"}},              // 源自 GameSpec（已过 G3~G6）
          "total_trials","blocks":["practice","main"],
          "integrity":{"bundle_sha256","trials_fingerprint","config_fingerprint"}},
 "steps": [
   {"type":"ready"},
   {"type":"block_start"(隐式:引擎按 block 变化记录事件；无独立 step)},
   {"type":"trial","index","block","display":[["factor","level"],...],"timing":{...},"correct":{"<response>":"<期望值>"}},
   {"type":"block_break","completed_block","next_block","done_trials","total_trials"},
   {"type":"end","summary":true|false}]}
```

- `display`：因素按 spec 声明序 + stimulus 键按字典序（确定性）；`correct` 仅含声明了 `correct_from` 的响应，值 = `trial.factors[correct_from]`（**来自 Bundle，非 GameSpec**）；
- flow 开关裁剪 steps：`ready_screen=false` → 无 ready step；`block_breaks=false` → 无 block_break step；**end step 恒存在**（事件日志必须可导出），`summary` 标志控制统计区显示。

### 11.3 HTML 形态与安全

- 单文件 HTML，`file://` 直开；**零外部资源**（无 CDN/字体/网络请求）；内联 CSS + 两个 `<script>` 块；
- script 块 1（数据+完整性，**无 DOM 引用**——可被 node 独立执行验证）：`PLAN`/`EXPECTED` 经 `JSON.parse("<JSON 文本>")` 载入，`TRIALS_CANONICAL`/`BUNDLE_CANONICAL` 为 canonical JSON 字符串字面量；
- 嵌入转义：全部动态文本经 `json.dumps(ensure_ascii=True)` + `<` → `\u003c`（防 `</script>` 逃逸）；`<title>` 经 `html.escape`；
- 模板组装用**模板 split + 内容交错**（禁止链式 replace——防用户文本含占位符注入）；
- script 块 2（引擎）：**仅 textContent/createElement** 更新 DOM；禁止 `innerHTML`/`insertAdjacentHTML`/`document.write`/`eval`（测试 grep 断言）；theme/layout 为 Pydantic Literal 枚举 → 静态 body class。

### 11.4 启动完整性校验（防线 D-3）

- HTML 内嵌**纯 JS SHA-256 实现**（标准算法，无依赖）；
- 启动时校验：`sha256(BUNDLE_CANONICAL) === bundle_sha256` 且 `sha256(TRIALS_CANONICAL) === trials_fingerprint`（BUNDLE_CANONICAL = canonical JSON(bundle 剥离 bundle_sha256/generated_at)，与 Phase A 计算口径逐字节一致）；
- 任一失配 → 显示 integrity error 屏，**拒绝启动**；
- Python 侧在渲染时重算两指纹与嵌入值比对（构建时防线）；node 探针执行 script 块 1 验证运行时判定（自动化 BR-8，node 缺失时 skip）。

### 11.5 状态机执行语义（MVP）

```
READY(任意键) → 每试次: FIXATION(fixation_ms>0) → STIMULUS(display=因素水平行)
  → 依 spec.responses 顺序逐响应采集 → FEEDBACK(on_response≠none 且 duration_ms>0) → ISI(isi_ms>0)
块间(还有后续块): BLOCK_BREAK(任意键) → 全部完成 → END(统计+自检+事件日志导出)
```

- `choice`：绑定物理键（named: space/enter/left/right/up/down；单字母）；`text`/`rating`：输入框 + Enter（rating 校验整数 ∈ scale，否则提示重输）；
- `stimulus_ms` 语义（MVP）：**每个响应的采集时限**（自该响应开始采集起算）；`null` = 无限等待；超时记 `value=null`；
- 正确性：`value === step.correct[response]`（correct 缺失 → `null`=不适用；value=null → `false`）；得分/连击仅由该判定累计。

### 11.6 事件日志（冻结格式）

每事件含 `t_epoch_ms`（Date.now()，运行时数据不参与 HTML 确定性）；事件集：`game_start` / `block_start` / `trial_start`（含 conditions）/ `response` / `game_end`。`response` 事件字段：

```json
{"event":"response","trial_index":0,"block":"main","conditions":{"f":"v"},
 "response_name":"judge","value":"a","correct":true,"rt_ms":812,"t_epoch_ms":...}
```

结束屏含**自检**（每试次响应事件数=声明响应数、响应名顺序一致、无未知 trial_index——运行时对账）；事件日志以只读 textarea 展示 + Blob 下载（`<game_name>-events.json`）。

### 11.7 确定性

- `render_game_html` 纯函数：同 Bundle + GameSpec → **逐字节相同** HTML；所有 dict 迭代来源为 list 序或排序键（hash-seed 无关）；
- 黄金渲染文件 `tests/golden/game-generic-demo.html`：重渲染与提交文件字节相等（复制 PA-2 模式，QA 以外部 shasum + PYTHONHASHSEED 子进程交叉验证）。

### 11.8 render_game 工具（ToolSpec）

```
name="render_game", idempotency="non-idempotent", risk_level="medium"   # 写盘，对齐 export_experiment
Input: {game_config: dict, bundle_path: str, output_path: str, previous_errors: list[str]}
description: 纯 ASCII（R2 教训），说明 GameSpec 结构同 validate_game + 前置校验 + output_path 语义
```

执行流程：① game_config 体积护栏（256KB，复用 B0）→ BLOCKED；② bundle 只读加载（沙箱 1~3 步）→ BLOCKED；③ `validate_game` 不通过 → `ok=True` + `{"rendered":false,"valid":false,...}`（不写文件）；④ 渲染 → HTML 字节 > `MAX_RENDERED_HTML_BYTES`(1MB) → BLOCKED；⑤ `validate_sandbox_path(output_path)` + `write_sandbox_file`（沙箱五步规则 1~3+5，第 4 步即 ④）→ BLOCKED；⑥ 成功 payload：

```json
{"rendered":true,"path":"games/x.html","html_sha256":"<64hex>","bytes":12345,"total_trials":48}
```

### 11.9 计时精度声明（诚实边界）

HTML footer 与结束屏双处固定声明：浏览器原型计时为近似值（setTimeout 调度非毫秒精度），**不得用于正式数据收集**。产品文档同口径。

### 11.10 B2 验收测试计划（pytest；FakeLLM 仅 BR-11 集成）

| 编号 | 断言 |
|------|------|
| BR-1 | 渲染确定性：两次渲染逐字节相同；与提交黄金 HTML 文件逐字节相等 |
| BR-2 | run plan 数据完整性（D-4 逻辑核）：trial steps 与 bundle.trials 一一对应（index/block/timing/display/correct 逐字段复制，顺序一致） |
| BR-3 | 状态机裁剪：ready/block_breaks/end_screen 开关语义；block_break 仅出现在块间且字段正确；end step 恒存在 |
| BR-4 | 表现层隔离：仅改 GameSpec 呈现字段（theme/feedback/title）→ trial steps 逐字节不变 |
| BR-5 | 输出安全：恶意 `</script>`/`<img onerror>` 文本仅以转义形态出现；`</script>` 计数=模板固有数；引擎无 innerHTML/eval/document.write/insertAdjacentHTML |
| BR-6 | render_game 工具：BLOCKED 五路（超大/路径逃逸 bundle/缺 bundle/坏 bundle/输出路径逃逸）；invalid spec → rendered:false 且零写盘；valid → 文件内容=渲染输出、html_sha256 与文件一致、bundle 前后逐字节不变 |
| BR-7 | 嵌入锚点：TRIALS_CANONICAL 的 sha256 = trials_fingerprint 且 JSON 往返=bundle.trials；BUNDLE_CANONICAL 的 sha256 = bundle_sha256 |
| BR-8 | 运行时完整性（node 可用则执行，缺失 skip）：执行 script 块 1 → integrity.ok=true；篡改输入 → 判定 false |
| BR-9 | 组合器注册 5 工具；render_game description 进 tools schema 且纯 ASCII |
| BR-10 | 通用性：新增源码 grep 无范式名（延续 GB-10 模式） |
| BR-11 | FakeLLM 集成：export → validate_game(通过) → render_game → HTML 文件真实产生且以 `<!DOCTYPE html>` 开头、bundle 不变 |
| BR-12 | 全量回归（185+新增）全绿；pyright 0 errors；分层 PASS |

### 11.11 边界外（B2 不做）

- pointer/touch、暂停/跳过/重试、动画素材、多语言、音频；
- 浏览器自动化交互测试（Playwright 等——推迟到集成阶段，D2 决策不变）；
- B3（README/开源整理/发布）；真实 LLM 调用。
- 已知限制登记（如实）：浏览器 setTimeout 计时近似；事件日志依赖运行时（无强制落盘）；单响应串行采集（MVP）。


