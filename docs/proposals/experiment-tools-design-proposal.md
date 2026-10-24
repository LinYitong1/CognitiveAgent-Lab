# Proposal: Experiment Tools Extension Design — generate_trials / validate_experiment / export_experiment

> Status: **proposal v2.1 — not implemented and no code is written until user approval** (v2 revised per the user's 6 points of feedback; v2.1 fixes 3 Major + 7 Minor + adopts 4 Suggestions from the QA review)
> Author: Architect Agent | v1 date: 2026-10-20 | v2 revision date: 2026-10-20 | v2.1 revision date: 2026-10-20 (QA review fix round, per docs/handoff/qa-proposal-v2-review.md)
> Product direction: CognitiveAgent Lab — an **independent, open-source, general-purpose** Game-Based Cognitive Experiment Agent (gamified cognitive experiment design and evaluation)
> Product boundaries (clarified by the user; all design in this proposal is constrained by them): **not compatible with** the user's existing cognitive-model/experiment projects; **no hardcoding for** any specific cognitive theory; **not extended into** a full game engine; **no development of** any specific experimental paradigm (paradigms appear only as optional plugin examples).
> Ground truth (the real code has been read; all signatures/paths below are based on it):
> - `src/models/tool_spec.py` — `ToolSpec(BaseModel)`: `name / description / input_model: type[BaseModel] / idempotency: Literal["idempotent","non-idempotent"] / risk_level: Literal["low","medium","high"] / executor: Callable[[BaseModel], Awaitable[ToolResult]]`, with an `effective_idempotency(args)` method
> - `src/agent/registry.py` — `ToolRegistry.register(spec) -> None` (validation failure raises `ToolRegistryError`), `execute(name, args) -> ToolResult` (unknown tool / argument-validation failure / executor exception all return `ToolResult(ok=False)`; nothing escapes)
> - `src/agent/loop.py` — `AgentLoop.run_task(goal)`: tool failures go back to the LLM as tool messages prefixed with `ERROR:` for self-correction; `settings.calc_agent_max_steps` is the hard cap; the `final` event is always emitted on termination
> - `src/tools/calc.py` / `src/tools/file_write.py` — the tool implementation style to follow: `XxxInput(BaseModel)` + internal `_XxxBlocked` exception + `BLOCKED:` prefix + a `build_tool_spec(settings: Settings) -> ToolSpec` factory
> - `src/agent/__init__.py` — `build_registry(settings) -> ToolRegistry` (registers the three M1 tools)
> - This proposal is **independent of milestones** (it does not advance the M2 SQLite persistence design); it is design input for a future "experiment tools extension" phase.
> The changelog is at the end (v1→v2, v2→v2.1). All fingerprint values in this document are **illustrative placeholders** (real values are computed via canonical JSON, §5.4).

---

## ① Product Positioning and Scope

**Positioning**: the Agent acts as a "cognitive experiment designer" — it understands research intent through dialogue with the user, produces a structured experiment specification (`ExperimentSpec`; named ExperimentConfig in v1, unified as ExperimentSpec in v2), validates and expands it via a **general deterministic engine** into a trial sequence, and exports a self-contained, independently verifiable experiment bundle; the game presentation layer (`GameSpec`) is decoupled from the experiment logic layer (§④).

**Scope (covered by this proposal)**:
- Three new tools: `generate_trials` (trial generation), `validate_experiment` (spec validation), `export_experiment` (bundle export);
- Draft schemas and the responsibility boundary for both `ExperimentSpec` and `GameSpec`;
- The general factorial combination generator (system core) and optional paradigm plugins (extension);
- The deterministic generation/validation engine and the reproducibility contract;
- Validation-iteration loop, testing, and an acceptance strategy draft.

**Explicitly out of scope for this proposal**: the web game itself (M3+ or later), a concrete game-mechanics DSL for GameSpec, participant data collection/evaluation analysis, M2 persistence, multi-experiment management, and formal development of any specific paradigm (Stroop/N-back appear only as plugin examples, §⑤).

## ② Overall Approach: Responsibility Boundaries and the Generality Red Lines (the Proposal's Core)

```
LLM (design decisions)          Deterministic Python code (generation & validation)
┌──────────────────┐          ┌──────────────────────────────────┐
│ understand        │          │ validate_experiment: validate spec │
│  research intent  │          │ generate_trials: general factorial │
│ write/modify spec │ ──tool──►│   combinator (core)                │
│ iterate on errors │ ◄─back── │                  + optional plugin │
│ report the design │          │ export_experiment: materialize     │
└──────────────────┘          │ probability/randomization/arithmetic│
                              │   all live here                    │
                              └──────────────────────────────────┘
```

**Division-of-labor iron rules**:
1. **The LLM does no arithmetic** — probabilities, frequencies, balancing, and randomization are all executed by deterministic code (numbers the LLM emits are merely declarations of intent, always verified/computed by the engine). This continues the established M1 fact: the whole point of the `calc` tool is "arithmetic does not trust the LLM".
2. **The engine makes no decisions** — which factors to choose and what ratios to set are products of the LLM–user dialogue; the engine only faithfully, reproducibly materializes.
3. **Same spec + same seed → byte-identical output** — reproducibility is the baseline of scientific research, guaranteed by a pure-function engine (§⑤).
4. **Experiment logic is decoupled from game presentation** — condition assignment and correctness rules belong to ExperimentSpec; presentation and interaction belong to GameSpec (§④).

**Generality red lines (implementing the product boundaries; new in v2)**:
- **Zero paradigm/theory terms in the core schema (ExperimentSpec), validators, and the general combinator** — only general structure (factors/levels/combinations/constraints/timing/response variables);
- **Paradigm knowledge exists only in the optional plugin layer** (§5.3) and in the spec's two free-form fields `paradigm`/`paradigm_params` — plugins are an enhancement, not a dependency: with `paradigm` absent, the purely general path is fully usable (§4.1 example);
- **The engine embeds no cognitive-theory assumptions** (Bayesian updating, evidence sampling, sequential decision making, or any other theory's computational model) — theoretical assumptions belong to the user's research design, expressed through the general structure; the engine knows nothing about them;
- The plugin examples (Stroop, N-back) are **sample code** demonstrating expressiveness, not system components, and do not limit system generality.

Consequently, the three tools are, as far as M1's `ToolRegistry` is concerned, **three new registrations**; the AgentLoop, event model, and error-feedback mechanism are all reused unchanged.

## ③ The Three ToolSpec Designs

New module: `src/tools/experiment_tools.py` (three tools in one file, styled after `calc.py`/`file_write.py`: Input model + `BLOCKED:` prefix + a `build_tool_spec(settings)` factory). Shared engine code lives in the new package `src/experiment/` (§⑤); `src/tools/` depends on it (layering direction `agent → tools → experiment → models/config`, see §⑨).

### 3.1 validate_experiment — spec validation (idempotent, read-only)

```python
class ValidateExperimentInput(BaseModel):
    config: dict[str, object]      # the ExperimentSpec JSON object (the LLM generates it inline; no need to write it to disk first)
    previous_errors: list[str] = Field(default_factory=list)  # optional: error_code:path fingerprints of previous rounds (§6.3 anti-stall)

# build_tool_spec returns:
ToolSpec(
    name="validate_experiment",
    description="Validate an experiment spec's schema legality and semantic constraints "
                "(ratio sums, constraint conflicts, trial counts, satisfiability). Returns a "
                "machine-readable validation report (errors carry error_code/path/suggestion) "
                "for spec revision and re-validation.",
    input_model=ValidateExperimentInput,
    idempotency="idempotent",      # pure function, no side effects
    risk_level="low",
    executor=...,
)
```

**Output structure** (`ToolResult.result`, a JSON string; keep the errors array preferentially before the 512-char truncation):

```json
{
  "valid": true,
  "fingerprint": "1a2b3c4d",       // sha256(canonical_json(spec))[:8] (illustrative; this example is the §4.2 spec, same value as §7.1)
  "engine_spec_version": "1.0",    // semantic version of the engine algorithm spec (§5.4 reproducibility contract)
  "warnings": [{"code": "RATIO_ROUNDED", "path": "constraints.ratios", "message": "..."}],
  "stats": {"trial_count": 88, "factor_count": 2, "blocks": 2, "plugin": null}
}
```

**Error-return contract (two levels, frozen)**:
- **Domain level (validation failure)**: `ToolResult(ok=True)` + `result` containing `"valid": false` and the `errors` array (the machine-readable error structure of §⑥). Rationale: a spec problem found by validation is a **valid result**, not a tool failure; it goes back to the LLM without the `ERROR:` prefix, clearly distinguished from "the tool is broken".
- **Tool-level failure**: limited to infrastructure errors such as non-dict input or JSON serialization failure — using `registry.execute`'s existing `ok=False` path (`invalid arguments: ...`), never escaping. Security refusals (e.g., config size over the 256KB cap) → `BLOCKED: config too large`.

### 3.2 generate_trials — trial generation (idempotent, pure function, no disk writes)

```python
class GenerateTrialsInput(BaseModel):
    config: dict[str, object]
    max_preview_trials: int = Field(default=8, ge=0, le=50)   # number of preview trials returned to the LLM

ToolSpec(
    name="generate_trials",
    description="Deterministically generate the full trial sequence from an experiment spec "
                "(general factorial path; if a paradigm is declared and the plugin is available, "
                "paradigm derivation is appended. Same spec+seed yields byte-identical output). "
                "Returns the sequence fingerprint, per-factor level frequency statistics, and a "
                "trial preview; writes no files — the full sequence is materialized by "
                "export_experiment from the same spec+seed.",
    input_model=GenerateTrialsInput,
    idempotency="idempotent",      # pure function: same input → same output, no side effects (safe to retry; M2 recovery-matrix friendly)
    risk_level="low",
    executor=...,
)
```

**Output structure**:

```json
{
  "fingerprint": "5d21e0f7",            // sha256(canonical_json(trials))[:8]
  "trial_count": 88,
  "frequency": {                         // statistical summary (the basis for the LLM to check design intent)
    "cue_type": {"valid": 44, "invalid": 44},
    "target_side": {"left": 44, "right": 44}
  },
  "preview": [ {"index": 0, "block": "practice", "factors": {...}, "derived": {...}}, ... ],
  "plugin_used": null,                   // or "stroop@1.0" (plugin name@version, §5.3)
  "note": "full sequence reproducible via export_experiment with identical spec"
}
```

**Design point**: the full trial sequence **never enters ToolResult.result** (potentially hundreds of KB — beyond the 512-char summary contract and it pollutes the LLM context) — result carries only the fingerprint and statistics. The delivery channel for the full sequence is `export_experiment` (the pure-function property guarantees both tools produce identical output from the same spec+seed). **Consistency is assertable**: `generate_trials.fingerprint == the trials_fingerprint inside the export_experiment bundle`; tests and acceptance both assert this.

**Error-return contract**: invalid spec (schema/semantics/unsatisfiable constraints) → `ok=True` + `"valid": false` + errors (same structure as validate_experiment; the same validation function is directly reused in the implementation); tool-level failures take the registry path.

### 3.3 export_experiment — bundle export (non-idempotent, writes to disk)

```python
class ExportExperimentInput(BaseModel):
    config: dict[str, object]
    path: str = Field(min_length=1)   # output path relative to the data/ sandbox root (.json suffix recommended)

ToolSpec(
    name="export_experiment",
    description="Materialize an experiment spec into a self-contained experiment bundle "
                "(ExperimentBundle: original spec + full trials + reproducibility metadata), "
                "written to the given path inside the data/ sandbox. The game side carries zero "
                "experiment logic and presents strictly per the sequence.",
    input_model=ExportExperimentInput,
    idempotency="non-idempotent",    # file write (overwrite semantics), same class as file_write
    risk_level="medium",             # same class as file_write (sandbox write)
    executor=...,
)
```

**Output**: `ToolResult(ok=True, result=f"wrote {path} ({bytes} bytes, trials_fingerprint={fp})")`.

**Disk-write safety rules**: fully reuse `file_write`'s five-step sandbox rule (reject `..` → realpath + `is_relative_to` component-boundary check → lstat every level for symlinks → size cap → auto-create directories inside the sandbox). Exports must pass a 1MB cap (oversized export fails → `BLOCKED: export too large`, suggesting chunked export — open question §⑩). Implementation path in §⑨ (shared helper, **no modification of file_write.py itself**).

**Error-return contract**: invalid spec → validate first; `ok=True` + valid:false (never export an invalid experiment); sandbox violations → `BLOCKED:` prefix (aligned with M1 convention); other tool-level failures take the registry path.

### 3.4 Registration with the existing ToolRegistry (integration point, real signatures)

```python
# New file src/agent/experiment_registry.py (src/agent/__init__.py untouched, see §⑨):
from src.agent import build_registry          # reuse the M1 assembly (agent → agent same-package import is legal)
from src.tools import experiment_tools

def build_experiment_registry(settings: Settings) -> ToolRegistry:
    """M1 three tools + the three experiment tools (combinator registration: zero changes to the existing build_registry)."""
    registry = build_registry(settings)
    registry.register(experiment_tools.build_validate_spec(settings))
    registry.register(experiment_tools.build_generate_spec(settings))
    registry.register(experiment_tools.build_export_spec(settings, sandbox=Path(settings.data_sandbox_dir)))
    return registry
```

`ToolRegistry.register`'s existing checks (`src/agent/registry.py:24-33`: non-empty unique name, `input_model` a BaseModel subclass, executor an async callable) apply equally to the new tools — all three naturally satisfy them; no registry changes needed.

## ④ The Two Schemas: ExperimentSpec and GameSpec

**Core decoupling iron rule: experiment logic belongs to ExperimentSpec; game presentation belongs to GameSpec.** The two layers are aligned via dual-fingerprint references (§⑦).

### 4.0 Responsibility boundary table (field ownership, frozen)

| Concern | ExperimentSpec (experiment layer) | GameSpec (presentation layer) |
|---------|-----------------------------------|-------------------------------|
| Factors/levels/condition assignment | ✅ `factors`/`constraints` | ❌ (not visible) |
| Trial sequence and order | ✅ materialized in the exported bundle `trials` | referenced (aligned via `experiment_ref`) |
| Correctness rules | ✅ `correct_from` | ❌ (defines no right/wrong; presents feedback styling only) |
| Experiment timing (fixation/stimulus/ISI) | ✅ `timing` (materialized per trial) | ❌ |
| Response variable types and value domains | ✅ `responses` (kind/options/scale) | ❌ |
| Input modality and key mapping | ❌ | ✅ `input.bindings` (bound per response-variable name) |
| Feedback presence/timing/style | ❌ | ✅ `feedback` |
| Scene presentation/layout/assets | ❌ | ✅ `scene` |
| Interaction flow (ready/block breaks/end screen) | ❌ | ✅ `flow` |
| Gamification wrapping (score/progress/streak) | ❌ | ✅ `gamification` |

**Export relationship**: ExperimentSpec → (materialized by `export_experiment`) → **ExperimentBundle** (original spec + full trials + reproducibility metadata); GameSpec is an **independent document** referencing the Bundle's trial sequence via `experiment_ref` (name/version/seed + dual fingerprints) and layering interaction descriptions on top (§⑦). The two layers evolve independently — changing presentation never touches the experiment; changing the experiment (requiring re-export) is detected by the presentation layer through the fingerprints.

### 4.1 ExperimentSpec schema draft (`src/experiment/schemas.py`, Pydantic v2)

```python
class Level(BaseModel):
    name: str
    weight: float = Field(default=1.0, gt=0)          # level sampling weight (intent declaration; the engine integerizes it; ignored when balance=true → warning)

class Factor(BaseModel):
    name: str = Field(min_length=1)
    levels: list[Level] = Field(min_length=1)          # levels (ordered — the source of expansion-order determinism)

class RatioRule(BaseModel):
    factor: str
    ratios: dict[str, float]                            # level name -> ratio; the sum must be ≈1.0 (tolerance 1e-6)

class Constraints(BaseModel):
    balance: bool = False                               # equal weight for all levels of all factors (mutually exclusive with ratios, rule C1 in §6.1)
    ratios: list[RatioRule] = Field(default_factory=list)
    max_repeat: int | None = None                       # cap on consecutive occurrences of the same level (anti-streak, e.g. 3)
    mutually_exclusive: list[list[str]] = Field(default_factory=list)  # forbidden co-occurring level-name pairs (across factors)

class ResponseVar(BaseModel):
    name: str
    kind: Literal["choice", "text", "rating"]
    options: list[str] = Field(default_factory=list)    # for choice
    scale: tuple[int, int] | None = None                # for rating (min, max)
    correct_from: str | None = None                     # correct-answer source: a factor name (general path) or a plugin-derived field name (§5.3)

class BlockSpec(BaseModel):
    name: str                                           # unique across the spec (duplicate → SCHEMA_INVALID; §5.1 sub-stream derivation keys depend on uniqueness)
    trial_count: int = Field(gt=0)
    factor_filter: dict[str, list[str]] = Field(default_factory=dict)  # this block contains only the specified levels
    shuffle_within: bool = True

class TimingSpec(BaseModel):
    fixation_ms: int = 500
    stimulus_ms: int | None = None                      # None = until response
    isi_ms: int = 1000

class ExperimentSpec(BaseModel):                        # named ExperimentConfig in v1; unified naming in v2
    schema_version: Literal[1] = 1
    name: str = Field(min_length=1)
    version: str = "0.1.0"
    seed: int                                           # required — the source of determinism (§5.1)
    paradigm: str | None = None                         # optional plugin key (§5.3); None = purely general path (core; no plugin needed)
    paradigm_params: dict[str, object] = Field(default_factory=dict)  # plugin free-form parameters (n, alphabet, etc.)
    factors: list[Factor] = Field(min_length=1)
    blocks: list[BlockSpec] = Field(min_length=1)
    constraints: Constraints = Constraints()
    responses: list[ResponseVar] = Field(min_length=1)
    timing: TimingSpec = TimingSpec()
```

**Generality statement (the schema-level implementation of the §② red lines)**: the structure above contains only general concepts; `paradigm`/`paradigm_params` are **free-form fields** — the core engine does not interpret their contents; only the corresponding plugin (if it exists and is declared) consumes them. `correct_from` may point to a factor name (the correctness criterion of the purely general path, see the §4.2 example) or to a plugin-derived field name (§4.3/4.4 examples).

### 4.2 Example 1: purely general path (no plugin; the minimal example of core capability)

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

**Self-consistency**: 2 factors × 2 levels → 4 combinations; `balance: true` with no `ratios` and no explicit weights → no constraint conflict (rule C1, §6.1). Practice 8 trials = 4 combinations × 2; main 80 = 4 × 20; 88 trials total, 22 per combination (2+20). `correct_from: "target_side"` points at a **factor name** — the purely general path defines correct answers without any derivation logic; `stimulus` is an empty object (the general combinator does no stimulus materialization; the game side renders from `factors` per the GameSpec's `scene` rules). This example demonstrates: **the core path depends on no paradigm code**.

### 4.3 Example 2: Stroop (optional plugin example)

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

**Self-consistency**: congruency(2) × ink_color(3) → 6 combinations; `balance: true`, no ratios, no explicit weights → no conflict (C1). Practice 12 = 6 × 2; test 96 = 6 × 16; 108 total. Within the test block: congruency 48/48, ink_color 32/32/32 (the §8.2 statistical assertions use exactly these numbers). Plugin responsibilities (§5.3): derive `word_color` from (congruency, ink_color) (congruent → same color; incongruent → one of the other two colors chosen by rng), materialize `stimulus` ({word, color}) and the derived field `correct_ink`; `correct_from` points at the plugin-derived field. **Design note**: congruency is modeled as an **explicit factor** rather than an implicit derived quantity — the standard way for a general schema to balance a derived quantity (the distribution of an implicitly derived quantity is only a projection of the combination distribution and is not controlled by constraints).

### 4.4 Example 3: N-back (optional plugin example, sequence-type)

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

**Self-consistency**: `balance: false` with no `ratios` → effective weights = Level.weight (0.3/0.7, summing to 1.0; no ratios declaration needed) → no conflict (C1). N-back is a **sequence-type plugin** (§5.3 `kind: "sequence"`): match positions and frequencies are **arranged by the plugin per the effective weights 0.3/0.7** (120 × 0.3 = 36 match / 84 nonmatch, exact integers) — the core combinator's largest-remainder allocation path **does not participate**; the core's responsibility is **post-generation frequency verification** (measured frequencies deviating from the effective-weight expectation beyond tolerance → `PLUGIN_FREQUENCY_DEVIATION`, §5.3). `shuffle_within: false` signals the sequence type: the plugin arranges match positions per the N-back sequence constraint (the first n trials are necessarily nonmatch — a structural fact of sequence generation), generates the letter stream, and derives `correct_match` ("yes"/"no"); the `trial_count ≥ n+1` check is performed by **the example plugin's validate hook** (§5.3 — the rule's content belongs to the plugin layer; the core has no concept of `n`; the red line closes). **Semantic-mapping declaration (SG boundary)**: this plugin maps the general constraint `max_repeat: 3` (general semantics: "cap on consecutive occurrences of the same level") to "cap on consecutive presentations of the same **letter**" — a plugin's paradigm-level semantic mapping of a general constraint field must be explicitly declared in its own documentation (§5.3). This example demonstrates the sequence-type plugin's **sequence-construction override** capability (the core is "combination expansion + shuffle" semantics; sequence-dependent logic and frequency implementation belong to the plugin; the core's post-hoc verification is the backstop).

### 4.5 GameSpec schema draft (presentation layer, `src/experiment/game_schemas.py`)

```python
class ExperimentRef(BaseModel):                  # reference to the ExperimentBundle (dual-fingerprint alignment)
    name: str
    version: str
    seed: int
    config_fingerprint: str                      # §5.4 canonical JSON fingerprint
    trials_fingerprint: str

class SceneSpec(BaseModel):
    layout: str = "canvas-fullscreen"            # presentation layout type (free-form string, interpreted by the game side)
    assets: dict[str, str] = Field(default_factory=dict)   # asset name → path/inline description

class InputBinding(BaseModel):
    response_name: str                           # which response variable in ExperimentSpec.responses this binds to
    keys: dict[str, str]                         # key → option value (choice kind), e.g. {"r": "red", ...}

class InputSpec(BaseModel):
    modalities: list[Literal["keyboard", "pointer", "touch"]] = ["keyboard"]
    bindings: list[InputBinding] = Field(default_factory=list)

class FeedbackSpec(BaseModel):
    on_response: Literal["none", "correctness-flash", "outcome-text"] = "none"   # feedback presence and form
    duration_ms: int = 200

class FlowSpec(BaseModel):
    ready_screen: bool = True
    block_breaks: bool = True                    # breaks between blocks
    end_screen: Literal["none", "summary"] = "summary"

class GamificationSpec(BaseModel):               # gamification wrapping (all optional; can be fully off)
    score: bool = False
    progress_bar: bool = True
    streak_bonus: bool = False

class GameMeta(BaseModel):                       # strongly typed (v2.1: replaces the weak dict[str, str], gaining Pydantic validation)
    name: str = Field(min_length=1)
    version: str = "0.1.0"

class GameSpec(BaseModel):
    schema_version: Literal[1] = 1
    game: GameMeta = Field(...)                  # game name/version (presentation-layer self-identification)
    experiment_ref: ExperimentRef
    scene: SceneSpec = SceneSpec()
    input: InputSpec = InputSpec()
    feedback: FeedbackSpec = FeedbackSpec()
    flow: FlowSpec = FlowSpec()
    gamification: GamificationSpec = GamificationSpec()
```

**Boundary constraints**: GameSpec contains **no** condition-assignment, trial-generation, or correctness fields (the "❌" side of the §4.0 table); `input.bindings` may reference only `responses` names declared in the ExperimentSpec (a cross-schema validation rule); `feedback.on_response: "none"` is the cognitive-experiment default (no feedback does not affect the experiment itself). This proposal defines only the schemas and reference relationship — **the production channel for GameSpec** (LLM generates it directly? a future dedicated tool?) is an open question in §⑩.

## ⑤ Deterministic Engine Design

New package `src/experiment/`: `schemas.py` (§4.1), `game_schemas.py` (§4.5), `validation.py` (§⑥), `generation.py`, `export.py`, `plugins/` (optional plugins: `stroop.py`, `nback.py` — **example-grade**).

### 5.1 Seed propagation through the whole chain

```
ExperimentSpec.seed (int, required)
  └─ one root rng per experiment: random.Random(spec.seed)           # created at the engine entry; the global random module is never touched
       └─ one derived sub-stream per block: random.Random(f"{seed}:block:{block.name}")
            └─ (if a plugin is used) all random decisions inside the plugin consume the passed-in rng instance
```

- **Single source of randomness**: engine and plugin code are **forbidden** from calling module-level `random` functions (`random.random()` etc.); only `random.Random` instances are allowed; a code-review gate item (regex-checkable).
- **Derived sub-streams are stable across processes**: CPython's `random.Random(str)` derives string seeds via sha512 (documented behavior, independent of `PYTHONHASHSEED`), and the root seed being an int is completely unambiguous — reproducible across processes and `PYTHONHASHSEED` values (verification method in §8.1).
- Why sub-streams instead of one stream through everything: per-block derivation means "adding or removing a block does not disturb the other blocks' sequences" (friendly to research iteration), and the derivation formula can be written into documentation for third-party reproduction.

### 5.2 The core: general factorial combination generator (the system's core)

**Pure function, zero paradigm knowledge, driven directly by factors/levels/blocks/constraints**:

```python
# src/experiment/generation.py (signature frozen)
def generate_trials(spec: ExperimentSpec) -> GeneratedExperiment:
    """Pure function: no IO, no time dependence, no hidden state.
    Same spec (including same seed) → byte-identical return value (canonical JSON comparison, §5.4).
    Purely general path when spec.paradigm is None or the plugin is not registered;
    when a plugin is declared it only appends derivation logic."""

class GeneratedExperiment(BaseModel):
    config_fingerprint: str       # sha256(canonical_json(spec))[:8]
    trials_fingerprint: str       # sha256(canonical_json(trials))[:8]
    engine_spec_version: str      # semantic version of the engine algorithm spec (§5.4)
    plugin_used: str | None       # e.g. "stroop@1.0"; None = purely general path

class Trial(BaseModel):
    index: int                    # global order (0-based)
    block: str
    factors: dict[str, str]       # factor → level name
    stimulus: dict[str, object]   # {} on the general path; plugins may materialize (e.g. stroop: {"word": "red", "color": "blue"})
    derived: dict[str, object]    # {} on the general path; plugin-derived fields (correct_ink, correct_match, ...)
    timing: TimingSpec            # materialized timing parameters
```

**General-path algorithm (deterministic implementation spec, item by item, frozen)**:
1. Combination expansion: cartesian product in `factors` declaration order (`itertools.product`), levels in `levels` declaration order — declaration order is the source of determinism;
2. **Effective weights** (per level): factors declared in `constraints.ratios` use the ratios; undeclared factors use `Level.weight` (default 1.0) normalized within the factor. Combination weight = the product of the per-factor level effective weights;
3. Combination count allocation: within a block, **largest-remainder integer allocation** of `trial_count` by combination weights (deterministic; on remainder ties, the first k combinations in declaration order receive them — the frozen tie-break rule);
4. Block splitting: `factor_filter` filters the usable combinations (empty after filtering → `BLOCK_FILTER_EMPTY` validation error); each block completes its allocation independently;
5. Ordering: `shuffle_within: true` → shuffle with the block's derived rng; `false` → output in declaration order (combination-expansion order);
6. Constraint enforcement: `max_repeat` / `mutually_exclusive` via rejection sampling (re-shuffle up to `max_attempts=100` per round; over the limit → `CONSTRAINT_INFEASIBLE` validation error — deterministic failure, not a random hang);
7. **Iterating over `set` is forbidden** (iteration order is unstable) — any set is `sorted()` before use; dicts rely on Python's documented order-preserving semantics;
8. All probability computation (frequencies, ratio checks) happens inside the engine with deterministic code — **weights/ratios output by the LLM are intent declarations only; the engine is the sole computational authority**;
9. Zero contact with `datetime.now()` / `uuid` / global state throughout (timestamps appear only in the export bundle's `generated_at` meta field and **never participate in any fingerprint**).

### 5.3 Optional: paradigm plugins (enhancement, not dependency)

```python
# src/experiment/plugins/base.py
class ParadigmPlugin(Protocol):
    name: str                                          # e.g. "stroop"
    version: str                                       # plugin semantic version (recorded on export, §5.4)
    kind: Literal["derive", "sequence"]                # capability declaration (new in v2.1; distinguishes the two plugin semantics, see below)
    def derived_fields(self) -> list[str]: ...         # derived field names this plugin produces (the basis for correct_from validation)
    def validate(self, spec: ExperimentSpec) -> list[ValidationIssue] | None: ...
    # paradigm-level validation hook (new in v2.1): after general validation, the core validator calls this hook
    # on the declared plugin and merges the results — paradigm knowledge (e.g. n-back's trial_count >= n+1)
    # stays in the plugin layer; the core validation.py has zero paradigm knowledge (§② red line closes)
    def derive(self, spec: ExperimentSpec, trials: list[Trial],
               rng: random.Random) -> list[Trial]: ... # append stimulus/derived to the core-generated trials (factor assignment untouched)
    def generate_sequence(self, spec: ExperimentSpec,
                          rng: random.Random) -> list[Trial] | None: ...
    # implemented and returning a list only when kind="sequence" (overrides the whole trial construction);
    # kind="derive" returns None (the core combination path runs)

PLUGINS: dict[str, ParadigmPlugin] = {}
# The registry starts as an empty dict; the example plugin modules (plugins/stroop.py, plugins/nback.py)
# self-register at import time; whether example plugins are loaded at runtime is a §⑩ governance decision
# (two deployment shapes: pure core with an empty registry / full distribution including the example plugins)
```

**Core–plugin relationship (frozen)**:
- `spec.paradigm is None` → purely general path (§4.2 example), **no plugin code is touched**;
- `spec.paradigm` set and the plugin registered → dispatch by `kind` (below);
- `spec.paradigm` set but the plugin **not registered** → validation error `UNKNOWN_PARADIGM` (listing the registered plugins) — **the system's usability never depends on any plugin**: the core path is always available to all users;
- A new plugin = a new file + one registry line; zero changes to the schemas, the three tools, or the core generator. Stroop/N-back are **example plugins** distributed with the proposal, demonstrating the plugin protocol's expressiveness; they are not system components.

**The two plugin kinds' capability boundaries and statistical-guarantee channels (v2.1 revision, resolving v2's contradiction)**:

| | `kind="derive"` (augmenting, e.g. stroop) | `kind="sequence"` (sequence, e.g. nback) |
|---|---|---|
| Trial construction | **core combinator** (combination expansion + largest-remainder allocation + shuffle/ordering + constraint enforcement) | **the plugin's `generate_sequence` takes over** |
| Factor assignment & frequencies | **enforced by the core** — the plugin only appends stimulus/derived; it cannot alter frequencies | **implemented by the plugin per the effective weights** — the core does not participate in allocation |
| Statistical guarantee | guaranteed a priori by the core algorithm (largest remainder + rejection sampling) | **core post-generation verification**: measured frequency deviating from the effective-weight expectation beyond tolerance → validation error `PLUGIN_FREQUENCY_DEVIATION` (generation fails rather than silently accepting) |
| Paradigm-level constraint checks | plugin `validate` hook (optional) | plugin `validate` hook (e.g. the example plugin's trial_count ≥ n+1) |

That is: **statistical properties have an enforcement channel on both paths** (derive-type enforced a priori; sequence-type verified a posteriori) — a plugin cannot silently break balance on either path; but the sequence type's frequency exactness is a contract between "plugin implementation + core verification", not a direct product of the core allocation algorithm (v2 attributing §4.4's 36/84 to largest remainder was wrong; v2.1 restates it).

**Semantic-mapping boundary for general constraints (new in v2.1)**: a plugin may apply a **paradigm-level semantic mapping** to a general constraint field (e.g. the N-back example mapping `max_repeat` — general semantics "cap on consecutive occurrences of the same level" — to "cap on consecutive presentations of the same letter"), but the mapping must be explicitly declared in the plugin's own documentation and must not weaken the constraint's **strength semantics** (a cap stays a cap; it may not be relaxed into a suggestion).

### 5.4 Reproducibility contract (v2's refined core)

**Exported artifacts must support independent verification and regeneration**. Four contract elements:

| Element | Content | Location |
|----------|---------|----------|
| Original ExperimentSpec | the complete spec (**including seed**) — the sole input to regeneration | the export bundle's `spec` section (§⑦) |
| Engine spec version | `engine_spec_version` (e.g. `"1.0"`) — **the semantic version of the algorithm spec, not a code hash**: an open-source project must be reproducible across implementations; any compatible implementation (Python/C/JS following the same spec document) produces the same fingerprints | the bundle + validate/generate outputs |
| Plugin version | `plugin_used` (e.g. `"stroop@1.0"`); null on the purely general path | the bundle + generate output |
| Trials fingerprint | `trials_fingerprint` = sha256(canonical JSON of trials)[:8] | the bundle + all tool outputs |

**Canonical JSON spec (frozen; the foundation of cross-implementation reproducibility)**: `json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))`; floats use the shortest round-trip decimal representation (`repr` semantics); NaN/Inf are **forbidden** in trials. This spec is versioned with `engine_spec_version` — a spec change = a version bump = an explicit breaking event.

**Conformance test-vector set (v2.1: promoted from open question to a release requirement for `engine_spec_version` 1.0)**: when the engine spec is released it must ship a set of **authoritative vectors** — a list of `(spec, canonical_json(trials), trials_fingerprint)` triples (covering: the purely general path, the derive-plugin path, the sequence-plugin path, remainder allocation, rejection-sampling edges). Any third-party implementation claiming compatibility must reproduce identical canonical JSON and fingerprints for the full vector set before it may call itself compatible. Rationale: cross-language reproduction implicitly requires replicating `random.Random`'s MT19937 initialization, string-seed sha512 derivation, and shuffle consumption order, plus the shortest-round-trip-float edge differences across languages — without an authoritative vector set, "independent, open-source, cross-implementation reproducible" is unfalsifiable. The vector set is exported directly from this engine's golden files (§8.4) and versioned with `engine_spec_version`.

**Two paths of independent verification (precise meaning)**:
1. **Regeneration verification**: a third party regenerates with the same spec (including seed) + a compatible version (same `engine_spec_version`, same plugin version) and compares `trials_fingerprint` for equality → proves the sequence is independently reproducible;
2. **Verify-only (no regeneration)**: sha256 over the exported bundle's `trials` array per the canonical JSON spec → compare with the in-bundle `trials_fingerprint` → proves the exported file was not tampered with or corrupted (an integrity check requiring no generator implementation at all).

**Verification methods (test design, implemented in §8.1)**: two generations in the same process produce identical canonical JSON; cross-`PYTHONHASHSEED` subprocess diff is empty; generate and export fingerprints are equal; golden-file diff.

## ⑥ The Validation–Iteration Loop

### 6.1 Machine-readable validation-error structure and constraint rules (frozen)

```python
# src/experiment/validation.py
class ValidationIssue(BaseModel):        # shared by warnings and errors
    error_code: str                      # stable enum (table below)
    path: str                            # JSON path, e.g. "constraints.ratios[0].ratios" / "factors[1].levels"
    message: str                         # human-readable description (including actual values)
    suggestion: str                      # fix suggestion (an action instruction for the LLM)
```

**Constraint semantics rules (C1–C3; v2 revised, v2.1 refined for scope of effect — eliminating undefined behavior on balance/ratios conflicts)**:
- **C1 (mutual exclusion)**: `constraints.balance == true` with non-empty `ratios` → **validation error** `CONSTRAINT_CONFLICT` (path: `constraints`; message states the two are mutually exclusive; suggestion: pick one);
- **C2 (override warning; v2.1 extended scope)**: both of the following "explicit weight overridden" situations emit warning `WEIGHT_IGNORED` (does not affect the valid verdict, so "passes validation" and "design intent overridden" can both hold): (1) `balance == true` with any `Level.weight ≠ 1.0` (overridden by equal weights); (2) `balance == false`, a factor declared in `ratios`, and an explicit `Level.weight ≠ 1.0` on that factor (overridden by the ratios — effective weights take the ratios per C3);
- **C3 (effective weights)**: with `balance == false`, a factor-level effective weight = `ratios` (if the factor is declared) > `Level.weight` (default 1.0, normalized within the factor); ratio values may be 0.0 (explicitly excluding that level), and the sum must be ≈1.0 (tolerance 1e-6), else `RATIO_SUM`.

**Stable error_code enum (initial edition, v2.1 revised)**: `SCHEMA_INVALID` (Pydantic-layer error wrapping + **duplicate block names** — `BlockSpec.name` must be unique across the spec; duplicates would collide with the §5.1 sub-stream derivation keys) | `RATIO_SUM` | `CONSTRAINT_CONFLICT` (C1) | `TRIAL_COUNT_MISMATCH` (**v2.1 clarified trigger**: a block filtered by `factor_filter` and effective weights (including levels zeroed by ratios) leaves zero usable positive-weight combinations — trial_count > 0 is requested but the combination space is empty) | `CONSTRAINT_INFEASIBLE` (general constraints such as max_repeat / mutually_exclusive cannot be satisfied) | `PLUGIN_FREQUENCY_DEVIATION` (**new in v2.1**: a sequence-type plugin's output frequencies deviate beyond tolerance from the effective weights — core post-generation verification, §5.3) | `UNKNOWN_PARADIGM` (the declared plugin is not registered — the core path needs no plugins; this error only means "declared but absent from the environment") | `CORRECT_FROM_UNKNOWN` (correct_from is neither a factor name nor a derived field of the declared plugin; the purely general path allows only factor names) | `MUTEX_VIOLATION` (a mutually_exclusive declaration combined with the factor structure empties the usable combinations, or the declaration names two levels of the same factor — a meaningless declaration) | `BLOCK_FILTER_EMPTY` (the levels circumscribed by factor_filter have no matching combinations in that block) | `ITERATION_STALLED` (§6.3). **Plugin-level validation**: paradigm-specific rules (e.g. the example plugin's trial_count ≥ n+1) produce issues via the `ParadigmPlugin.validate` hook, merged isomorphically with the general errors above — **the rule content belongs to the plugin layer; the core validation.py has zero paradigm knowledge (§② red line)**. Warning codes: `WEIGHT_IGNORED` (both C2 situations), `RATIO_ROUNDED` (the allocation involved remainder rounding).

`validate_experiment`'s `ToolResult.result` (the tool-message content the LLM actually receives):

```json
{"valid": false, "fingerprint": "9f3ab2c1", "engine_spec_version": "1.0",
 "errors": [
   {"error_code": "CONSTRAINT_CONFLICT", "path": "constraints",
    "message": "balance=true and a non-empty ratios declaration are mutually exclusive (ratios currently declare 1 factor)",
    "suggestion": "remove ratios (equal weights) or set balance to false (custom ratios)"}
 ]}
```

> Note: this example is a different spec (with a constraint conflict), so its fingerprint differs from §4.2/§7.1 (`1a2b3c4d`) — both are illustrative placeholders (see the header note).

The LLM locates the field via `path`, revises the spec via `suggestion`, and classifies the fix via `error_code` — together these form the locate–revise–revalidate closed loop. **All three examples of §4.2/4.3/4.4 self-check against these rules** (self-consistency numbers in each section's "self-consistency" paragraph).

### 6.2 Reusing the existing AgentLoop (zero-change argument)

- The tool-result return path (`src/agent/loop.py:129-144`): `registry.execute` → `ToolResult` → tool message (with `ok=True`, content is the result verbatim, i.e. the JSON above) → the next LLM round's input. **Validation reports enter the conversation as normal tool results, naturally readable and actionable by the LLM** — no loop changes needed.
- Iteration is bounded: `settings.calc_agent_max_steps` (M1 default 25) is the hard cap. A typical loop: `validate(fail) → LLM revises spec → validate(pass) → generate → export → final`, done within 5–8 steps; the worst case is truncated by max_steps → `failed` + final always emitted — **an infinite loop is impossible under the M1 mechanism**.
- Validation failures carry no `ERROR:` prefix (§3.1's two-level domain/tool contract), so the LLM will not mistake "the design is not yet valid" for "the tool is broken" and bypass validation to export directly.

### 6.3 Anti-stall: repeated-error termination strategy

The AgentLoop has no cross-round memory and the tools are pure functions (idempotency requirement, §3.2); **no server-side session state is introduced**. Anti-stall uses three combined layers:

1. **Hard cap (existing)**: max_steps truncation — the backstop guaranteeing termination;
2. **Soft guidance (prompt layer)**: the goal/system-prompt template for experiment-design tasks advises "if the same validation error appears twice, make a substantial revision or ask the user, rather than resubmitting";
3. **Protocol-level deduplication (optional input field; v2.1 revised trigger semantics)**: `ValidateExperimentInput.previous_errors` (already in §3.1) — the LLM passes a **list** of `error_code:path` fingerprints from prior rounds (appending the current round's fingerprints each time). The tool stays stateless; the rule: **any fingerprint already appearing ≥ 2 times in `previous_errors` → `"stalled": true` + error `ITERATION_STALLED`** (suggestion: "stop resubmitting; summarize the unresolved conflict and ask the user to arbitrate"). Walkthrough (aligned round-by-round with the §8.5 test script): the same error f1 resubmitted — 1st time prev=[] (f1 appears 0 times; passes and returns the error); 2nd time prev=[f1] (appears 1 time < 2; still returned); 3rd time prev=[f1, f1] (appears 2 times ≥ 2 → stalled). This semantics matches layer 2's soft guidance ("revise substantially once the same validation error appears twice"); the state is maintained LLM-side and the tool remains a pure function.

FakeLLM integration tests must cover both paths: normal iteration (fail → revise → pass) and stalling (repeated error → `ITERATION_STALLED` or max_steps → terminates, does not hang) (§8.5).

## ⑦ Export Format Design: ExperimentBundle and Its Relationship to GameSpec

The artifact written by `export_experiment` is the **ExperimentBundle** — self-contained and independently verifiable (§5.4). GameSpec is an independent document referencing the Bundle via dual fingerprints.

### 7.1 ExperimentBundle structure (exported form of the §4.2 purely general example)

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

**Format contract points**:
- **The `spec` section = the complete ExperimentSpec after normalization** (v2.1 wording precision): Pydantic-default fields may be omitted (in the example, paradigm_params/factor_filter/shuffle_within take their defaults when omitted); **the fingerprint is computed over the parsed, normalized object** — so "omitting default fields" and "filling them in" produce the same config_fingerprint; regeneration does not depend on the literal "original text";
- **The `reproducibility` section**: dual fingerprints, `engine_spec_version` (the algorithm spec's semantic version), `plugin_used` (with version), and a **parameter digest** (`effective_weights` — the actual normalized effective weights — plus `allocation` — the actual per-combination allocation counts **keyed per block**; v2.1 adds the practice block, making the per-block basis explicit) — the parameter digest makes the "intent → actual allocation" conversion transparent and auditable;
- **`trials` fully materialized**: byte-identical to `GeneratedExperiment.trials` (canonical JSON + sha256 == `trials_fingerprint`, the basis of §5.4 path 2's verify-only mode); all derived quantities (plugin stimulus/derived, timing) are precomputed — the game side has zero experiment logic;
- **Location**: inside the `data/` sandbox (following `file_write`'s five-step rule, §3.3); recommended naming `experiments/<name>-v<version>-seed<seed>.json`;
- On the general path `stimulus/derived` are empty objects — presentation material is rendered by the GameSpec's `scene` rules from `factors` (the embodiment of experiment–presentation decoupling).

### 7.2 GameSpec's reference to the Bundle (export relationship)

```
ExperimentSpec ──(export_experiment: materialize)──► ExperimentBundle ──(referenced via trials_fingerprint)──► GameSpec
```

- The GameSpec's (§4.5 schema) `experiment_ref` carries name/version/seed + **dual fingerprints** — the game side validates the ref against the Bundle before starting (preventing presentation-layer/experiment version mismatch);
- At runtime the game side reads the Bundle's `trials` (presented in order) + `responses`/`timing` (scoring and timing), and presents/interacts per the GameSpec's `scene/input/feedback/flow/gamification` — **the runtime implementation of the two-layer responsibilities, i.e. the §4.0 boundary table**;
- This proposal defines only the formats and reference relationship; **it does not implement a game, nor design the deeper details of a game-mechanics DSL**; GameSpec's production channel is an open question in §⑩.

## ⑧ Testing and Acceptance Strategy

**Test layout** (aligned with the existing `tests/unit|integration`): `tests/unit/experiment/` (schema/engine/statistics/tools/purely general path) + `tests/integration/` (FakeLLM design-iteration loops) + `tests/golden/` (golden files).

### 8.1 Determinism/reproducibility tests

| Test | Assertion |
|------|-----------|
| `test_generation_same_seed_byte_identical` | two `generate_trials` calls with the same spec produce identical canonical JSON (same process) |
| `test_generation_cross_process_stable` | subprocesses with `PYTHONHASHSEED=1` / `=2` each run the generation script; the output JSON `diff` is empty |
| `test_generate_export_fingerprint_match` | `generate_trials.fingerprint == the exported bundle's reproducibility.trials_fingerprint` |
| `test_bundle_integrity_no_regen` | verify-only path: canonical-JSON sha256 over the exported bundle's trials == the in-bundle fingerprint (§5.4 path 2) |
| `test_block_isolation` | after adding or removing one block, the other blocks' trial subsequences are byte-unchanged (evidence for the §5.1 sub-stream design) |

### 8.2 Statistical-property tests (fixed seeds; asserted numbers consistent with the §4 examples)

| Test | Assertion |
|------|-----------|
| `test_frequency_balance_generic` | the §4.2 general example, seed=11, 88 trials: 4 combinations × 22 each; both factors' levels at 44/44 |
| `test_frequency_balance_stroop` | the §4.3 example, seed=42, test block 96 trials: congruency 48/48; ink_color 32/32/32 (exact integer-allocation assertion; largest remainder with zero remainder) |
| `test_frequency_weight_nback` | the §4.4 example, seed=7, 120 trials: exactly 36 match / 84 nonmatch (a **sequence-type plugin** arranges positions per the effective weights 0.3/0.7 — the attribution is plugin behavior; the core's largest remainder does not participate; its role is post-generation frequency verification, §5.3) |
| `test_sequence_plugin_frequency_guard` | with a test-stub plugin (a sequence output deliberately deviating from the weights) → the core's post-generation verification reports `PLUGIN_FREQUENCY_DEVIATION` (evidence of the a-posteriori channel) |
| `test_max_repeat_respected` | no level occurs consecutively more than max_repeat times (full-sequence scan) |
| `test_deterministic_rejection_sampling` | a tightly-constrained spec (max_repeat=1) converges within 100 re-shuffles or deterministically reports `CONSTRAINT_INFEASIBLE` |

Statistical assertions use exact integers or ratio tolerances (no scipy; a hardcoded chi-square critical-value table is an optional enhancement, open question §⑩).

### 8.3 Schema-validation tests

The `test_spec_rejects_*` series (invalid-spec rejection cases): missing seed; ratios summing to 0.9 (`RATIO_SUM`); **balance=true with non-empty ratios (`CONSTRAINT_CONFLICT`, rule C1)**; **duplicate block names (`SCHEMA_INVALID`; §5.1 sub-stream keys depend on uniqueness)**; **ratios zeroing all of a block's factor_filter levels → the block's positive-weight combination space is empty (`TRIAL_COUNT_MISMATCH`, constructible per the §6.1 clarification)**; unknown paradigm (`UNKNOWN_PARADIGM` — note the purely general path with paradigm=null is legal and does not trigger it); `correct_from` being neither a factor name nor a plugin-derived field (`CORRECT_FROM_UNKNOWN`); factor_filter producing no combinations (`BLOCK_FILTER_EMPTY`); **a mutually_exclusive declaration emptying the usable combinations (`MUTEX_VIOLATION`) or naming two levels of the same factor (`MUTEX_VIOLATION`, meaningless declaration)**; **the example-plugin path with trial_count < n+1 (`CONSTRAINT_INFEASIBLE` — triggered via the example plugin's validate hook; the core has no concept of n, §5.3)**; **a test-stub sequence plugin deviating from the weights (`PLUGIN_FREQUENCY_DEVIATION`)**. Plus warning cases: balance=true + explicit weight (`WEIGHT_IGNORED` situation (1), C2); balance=false + explicit weight on a ratios-declared factor (`WEIGHT_IGNORED` situation (2), v2.1 extension). Assert `valid==false` (or the warning present) and errors contain the corresponding `error_code`/`path`/`suggestion`.

### 8.4 Golden-file strategy

- `tests/golden/cueing-generic-seed11.json`, `tests/golden/stroop-plugin-demo-seed42.json`, `tests/golden/nback-plugin-demo-seed7.json` (complete export bundles of the three §4.2/4.3/4.4 examples) — **at least one golden file each for the general and the plugin paths**;
- Test `test_golden_export_unchanged`: generate the export → compare against golden (semantic diff: parse the JSON and compare, ignoring `generated_at`);
- **Update flow**: `UPDATE_GOLDEN=1 pytest tests/golden` rewrites the files → human review of the diff (the blast radius of seed/algorithm changes) → commit. Golden-file changes must state the reason in the PR description (engine algorithm change / plugin logic fix — `engine_spec_version`/plugin version must be bumped in step).

### 8.5 FakeLLM integration tests (the full design-iteration loop)

Reusing the M1 FakeLLM injection pattern (`AgentLoop(client=FakeLLM(script), registry=build_experiment_registry(settings), ...)`):

| Test | Script and assertions |
|------|----------------------|
| `test_design_iteration_success` | script: [validate(spec with balance+ratios conflict) → valid:false + CONSTRAINT_CONFLICT, validate(revised) → valid:true, generate, export, final]; asserts: final completed, the export bundle exists under `data/` with matching fingerprints, and round 2's FakeLLM messages contain round 1's validation JSON (iteration evidence) |
| `test_design_iteration_stalled` | script: three submissions of the same erroneous spec with previous_errors accumulating round by round ([] → [f1] → [f1,f1]) → the 3rd triggers (f1 appears 2 times ≥ 2, the §6.3 new threshold is mathematically triggerable) and receives `ITERATION_STALLED` → final; asserts termination without export |
| `test_design_iteration_max_steps` | script always returns validate(the same bad spec) → truncated by max_steps → failed + final always emitted (backstop evidence against hangs) |
| `test_generic_path_no_plugin_end_to_end` | script uses the §4.2 purely general spec throughout (validate→generate→export→final); asserts plugin_used==null, the bundle's stimulus/derived are empty objects, and the correctness criterion comes from a factor name — **end-to-end evidence that the core path needs no plugin** |

### 8.6 Draft acceptance items (to be merged into the formal acceptance criteria at implementation time; recorded here only)

| ID | Item | Command (illustrative) | Criterion |
|----|------|------------------------|-----------|
| EX-1 | Determinism | `pytest tests/unit/experiment -k determinism or cross_process` | empty diff for two same-seed generations |
| EX-2 | Statistical properties | `pytest tests/unit/experiment -k frequency` | fixed-seed frequency exact/tolerance assertions all green |
| EX-3 | Invalid-spec rejection | `pytest tests/unit/experiment -k rejects` | all return machine-readable errors (incl. CONSTRAINT_CONFLICT); warning codes asserted separately |
| EX-4 | Golden files | `pytest tests/golden` | empty semantic diff; updates go through the UPDATE_GOLDEN flow |
| EX-5 | Full iteration loop | `pytest tests/integration -k design_iteration` | fail → revise → pass → export, full-chain FakeLLM assertions |
| EX-6 | Export materialization integrity | `pytest tests/unit/experiment -k export` | the bundle contains the original spec, reproducibility metadata (dual fingerprints/engine_spec_version/plugin_used/parameter digest), and full trials; the verify-only sha256 check passes |
| EX-7 | Layering & idempotency declarations | `python -m scripts.check_layers` + registry self-check | the three tools' idempotency/risk_level declarations are correct; no reverse imports |
| EX-8 | Purely general path | `pytest tests/unit/experiment tests/integration -k generic` | paradigm=null works end-to-end (the core depends on no plugin) |

## ⑨ Impact Assessment on the Existing M1 Code

**Conclusion: zero modifications to existing M1 files; new files only (v2 reiterates: nothing anywhere in this document requires touching M1).**

| Action | File | Nature |
|--------|------|--------|
| New | `src/experiment/` (schemas/game_schemas/validation/generation/export/plugins/) | new package, depends on `src/models`, `src/config` |
| New | `src/tools/experiment_tools.py` | the three tools (depend on `src/experiment` + `src/models`) |
| New | `src/agent/experiment_registry.py` | combinator registration (imports the existing `build_registry`; does not modify it) |
| New | `tests/unit/experiment/`, `tests/golden/`, integration tests | tests |
| **Unchanged** | `src/agent/loop.py`, `src/agent/registry.py`, `src/agent/llm.py`, `src/models/*`, `src/tools/calc.py`, `src/tools/http_request.py`, `src/tools/file_write.py`, `src/agent/__init__.py`, `src/config.py` | AgentLoop/Registry/three tools/event model reused as-is (zero-change argument in §6.2) |

Two implementation-time notes (declared honestly; neither **touches M1 code**):
1. **G-4 layering rule**: the new `experiment` layer sits below tools (`agent → tools → experiment → models/config`). If `scripts/check_layers.py` (the M0 gate script) is implemented with an explicit layer whitelist, it needs a one-line rule extension — **this is a gate-configuration change, not an M1 product-code modification**; at implementation time it goes to the Lead as a separate small change for approval; if the script infers layers by directory convention, zero changes.
2. **Sandbox-write rule reuse**: `export_experiment`'s disk writes must follow the same rule as `file_write`. Default plan: add `src/tools/_sandbox_io.py`, a shared helper (new file implementing file_write's five-step rule as reusable functions; export uses it); `file_write.py` is **not migrated and not modified** (the helper exists in parallel with its logic, with the sync obligation noted).

## ⑩ Open Questions and Risks (left for user decision)

> v2.1: former item 5, "canonical JSON cross-implementation spec maintenance / conformance vector set", has per the QA suggestion (SG-1) been **promoted to a release requirement for `engine_spec_version` 1.0** (§5.4) and is no longer an open question.

1. **GameSpec's production channel**: does the LLM generate the GameSpec JSON directly in conversation (same pattern as ExperimentSpec), or will future `design_game`/`export_game` tools exist? This proposal freezes only the schema and reference relationship (§4.5/§7.2).
2. **Plugin governance and distribution**: are the example plugins (stroop/nback) distributed with the repo, or moved to a separate examples directory to avoid being mistaken for "official paradigm support"? Are example plugins loaded at runtime by default (the two deployment shapes of §5.3)? Must new plugins ship golden files and statistical tests before merging?
3. **Whether to introduce numpy**: designed **not to be introduced** (`random.Random` + the standard library cover current needs, constrained by the ARCHITECTURE §2.1 dependency red line). Future needs for complex sampling (stratified/exact Latin squares) must first go through the dependency-change process. Risk: largest remainder deviates from "perfect balance" by ±1 under extreme ratios — explicitly exposed by the golden files.
4. **The `ITERATION_STALLED` previous_errors protocol**: keeping the state LLM-side preserves pure-function tools (§6.3 option 3) but relies on the LLM faithfully echoing it — a "soft protocol". Accept, or rely on max_steps + prompting only?
5. **Export size cap**: 1MB (as for file_write) holds roughly ~5k trials. Do oversized experiments need chunked export or a multi-file bundle (a bundle directory)?
6. **Intersection with M2**: the idempotent declarations of `generate_trials`/`validate_experiment` naturally fit the M2 recovery matrix (uncertain → safe auto-retry); `export_experiment` is non-idempotent, same class as file_write. This proposal deliberately designs no M2 interaction details; alignment happens when the M2 contract freezes.

## Changelog

### v2 → v2.1 (QA review fix round, per docs/handoff/qa-proposal-v2-review.md)

**Major fixes (3/3)**:
1. **MA-1**: the §6.3 ITERATION_STALLED trigger changed from "the intersection of current errors with previous_errors ≥ 3 fingerprints" (mathematically untriggerable for a single repeated fingerprint) to "**any fingerprint appearing ≥ 2 times in previous_errors**", with a round-by-round walkthrough ([]→[f1]→[f1,f1], triggering on the 3rd) aligned with the §8.5 test script; semantics consistent with the layer-2 soft guidance.
2. **MA-2**: §5.3 rewritten on plugin capability boundaries — added the `kind: Literal["derive","sequence"]` capability-declaration field and the two-kind boundary table (derive: factor assignment and frequencies enforced a priori by the core combinator; sequence: frequencies implemented by the plugin per the effective weights, **verified post-generation by the core**, deviation beyond tolerance → new error code `PLUGIN_FREQUENCY_DEVIATION`); "plugins cannot break balance" became "statistical properties have an enforcement channel on both paths (a priori enforcement / a posteriori verification)"; §4.4 N-back's 36/84 attribution changed from "largest remainder with zero remainder" (wrong: the sequence type does not take that path) to "the plugin arranges positions per 0.3/0.7; the core verifies a posteriori"; §8.2 attribution updated and `test_sequence_plugin_frequency_guard` added.
3. **MA-3**: the `ParadigmPlugin` protocol gained a `validate(spec) -> list[ValidationIssue] | None` hook — the core validator calls the declared plugin's hook after general validation and merges the results; paradigm knowledge (e.g. n-back's trial_count ≥ n+1) stays in the plugin layer, closing the §② generality red line; the sequence-type validation wording of §4.4/§6.1/§8.3 changed to "triggered via the example plugin's validate hook; the core has no concept of n".

**Minor fixes (7/7, all adopted)**:
- MI-1: unified fingerprint placeholders — the §3.1 example now uses the same value as §7.1 (`1a2b3c4d`, the same §4.2 spec); the header declares all fingerprints in the document are illustrative placeholders.
- MI-2: §7.1's "the original spec verbatim" became "**the complete spec after normalization** (defaults may be omitted; the fingerprint is computed over the parsed object)", removing the contradiction with the example's omitted defaults.
- MI-3: §8.3 gained `MUTEX_VIOLATION` cases (a mutex declaration emptying the combinations / two levels of the same factor).
- MI-4: `TRIAL_COUNT_MISMATCH`'s trigger semantics clarified as "after a block is filtered by factor_filter and effective weights (including ratios-zeroed levels), zero positive-weight combinations remain"; §8.3 gives a constructible input (ratios zeroed + filter circumscribed); C3 adds "ratio values may be 0.0".
- MI-5: the `BlockSpec.name` uniqueness constraint (duplicate → `SCHEMA_INVALID`; §5.1 sub-stream keys depend on it), synchronized in §4.1/§6.1/§8.3.
- MI-6: the C2/`WEIGHT_IGNORED` warning scope extended to both situations (balance overrides weight / ratios override weight); §8.3 adds the situation-(2) warning case.
- MI-7: §7.1's `allocation` explicitly **per-block** with the practice block added (2 per combination).

**Suggestion handling (4/4)**:
- SG-1 **adopted** (user instruction): the conformance test-vector set was **promoted from open question §⑩.5 to a release requirement for `engine_spec_version` 1.0** (new §5.4 paragraph: authoritative `(spec, canonical_json, fingerprint)` triples exported from the golden files; compatible implementations must pass the full set); §⑩ renumbered with the promotion noted.
- SG-2 **adopted**: `GameSpec.game` changed from the weakly typed `dict[str, str]` to the strongly typed nested model `GameMeta(name, version)` (§4.5).
- SG-3 **adopted**: the `PLUGINS` registry comment clarified as "the code starts as an empty dict; example plugin modules self-register at import; whether they load at runtime is a §⑩ governance decision" (§5.3).
- SG-4 **adopted**: §5.3 gained the "semantic-mapping boundary for general constraints" section + §4.4 notes the max_repeat letter-semantics mapping example; constraint strength semantics may not be relaxed.

**Consistency sync**: the §8.5 stalled script, the §8.2 attributions and the new guard test, the §8.3 rejection-case set, the renumbered §⑩ list; a full re-scan of terminology and numbers across the document (placeholder fingerprints, attribution wording, and the error-code loop are all aligned).

### v1 → v2 (revised per the user's 6 points)

1. **Separation of the general combination generator from paradigm plugins** (revision 1): §⑤ restructured into the §5.2 core factorial combinator (zero paradigm knowledge, purely schema-driven) + §5.3 optional plugins (the `ParadigmPlugin` protocol, registry initially empty, paradigm=None taking the purely general path, plugin unavailability not affecting system usability); new §4.2 purely-general-path example; new "generality red lines" in §②; Stroop/N-back demoted document-wide to "plugin examples" (§4.3/4.4 titles and the §⑩ governance question).
2. **ExperimentSpec/GameSpec layering** (revision 2): ExperimentConfig renamed uniformly to ExperimentSpec; new §4.0 responsibility boundary table (field ownership frozen) and the §4.5 GameSpec schema draft; §⑦ restructured as ExperimentBundle + GameSpec referencing it via dual fingerprints, implementing the "experiment logic decoupled from game presentation" iron rule.
3. **Fixed the balance/ratios conflict** (revision 3): §6.1 gained constraint rules C1 (balance and ratios mutually exclusive → `CONSTRAINT_CONFLICT` error) / C2 (balance overriding weight → `WEIGHT_IGNORED` warning) / C3 (effective-weight precedence); all §4 examples rewritten with self-checked, self-consistent numbers (§4.2: 4 combinations × 22; §4.3: 6 combinations, congruency 48/48, ink 32/32/32; §4.4: 0.3×120=36 exact integer); §8.2/8.3 statistical assertions and rejection cases updated in step.
4. **Completed the reproducibility contract** (revision 4): §5.4 rewritten as the four contract elements (original spec including seed; engine_spec_version as the algorithm spec's semantic version, not a code hash; plugin version; trials fingerprint) + the frozen canonical JSON spec + the two independent-verification paths (regeneration comparing fingerprints / verify-only sha256 integrity); §⑦'s bundle gained the `spec` section and the `reproducibility` section (with the effective_weights/allocation parameter digest); §8.1/8.6 gained the corresponding tests and acceptance items.
5. **No-theory-hardcoding declaration** (revision 5): the §② generality red lines state explicitly that the core schema/validators/core generator contain zero paradigm and zero theory terms and the engine embeds no cognitive-theory assumptions; a full-document scan confirms paradigm knowledge exists only in the plugin layer and the paradigm/paradigm_params free-form fields.
6. **Zero-M1-modification reiterated** (revision 6): §⑨ states explicitly "nothing in this document requires touching M1"; the check_layers rule extension is explicitly a gate-configuration change to be submitted for approval at implementation time (not an M1 code modification).
7. Naming unification: ExperimentConfig → ExperimentSpec; the error-code enum gained `CONSTRAINT_CONFLICT`/`ITERATION_STALLED` and the warning code `WEIGHT_IGNORED`; the header updated with the product boundaries and the v2 status line.

---

> **Restated: this document is proposal v2.1. It is not implemented until the user approves — no code is written, no formal documents (ARCHITECTURE/ROADMAP/ACCEPTANCE_CRITERIA) are modified, and M2 is not advanced. Upon approval, the Architect promotes the essentials of this proposal into a formal contract (version bumped then, with the changelog recorded in ARCHITECTURE.md), and Backend implements per the contract.**
