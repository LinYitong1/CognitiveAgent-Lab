# M2-A — Proposed M2 Architecture

- **Status**: design proposal. Nothing below is implemented; M1/Phase A/B frozen code is untouched.
- **Labels**: 【exists】 verified today · 【proposed】 new in M2 · 【assumption】 needs validation before reliance.
- **Iron rules carried forward**: experiment/presentation separation (game layer can never alter conditions, trials, stimuli, correctness, timing); no paradigm hardcoding (the mystery prototype is an *example*, never engine logic); single AgentLoop; FakeLLM acceptance gate; single-file `file://` HTML with zero external URLs; no new dependencies.

---

## 1. Layer overview

```
┌──────────────────────────────────────────────────────────────────────┐
│ AGENT WORKFLOW (single AgentLoop, logical stages + gates)            │
│  Research Designer → Game Designer → Game Builder → Game Tester      │
│  with researcher approval checkpoints (pending → approved)           │
├──────────────────────────────────────────────────────────────────────┤
│ RESEARCH LAYER            experiment engine (M1/Phase A core)        │
│  ExperimentSpec v2 → deterministic trials → ExperimentBundle         │
├──────────────────────────────┬───────────────────────────────────────┤
│ GAME DESIGN LAYER            │ RESEARCH–GAME MAPPING LAYER           │
│  GameSpec v2: world,         │  explicit, verifiable mapping:         │
│  narrative, mechanics        │  what maps to what, what may move,     │
│  (presentation only)         │  what must never move                  │
├──────────────────────────────┴───────────────────────────────────────┤
│ GAME RUNTIME LAYER       deterministic single-file HTML renderer v2  │
│  exploration + measurement trials, two-class event log, export       │
└──────────────────────────────────────────────────────────────────────┘
```

## 2. Research Layer (engine extensions — additive, versioned)

【exists】 factors/levels/weights, balance/ratios/mutually-exclusive constraints, blocks (`name/trial_count/factor_filter`), responses (`choice|text|rating`, `options`, `correct_from`), trial-level timing (`fixation_ms/stimulus_ms/isi_ms`), `seed`, `paradigm_params` free-form slot, dual fingerprints, `verify_bundle`.

【proposed】 — all as **optional v2 fields** on `ExperimentSpec` (`schema_version: 2`), absent-by-default:

- **R1 `stimulus_spec`** — declarative stimulus materialization. Per factor level: text templates with slots, or references to embedded assets (MVP: text only). The engine deterministically materializes `trial.stimulus` at generation time (seeded where sampling is needed, e.g. decoy selection). *This closes the biggest verified gap: today `trial.stimulus` is always `{}` and the renderer shows `"factor: level"` strings.*
- **R2 timing extensions** — `BlockSpec.timing?: TimingSpec` (per-block override of the global trial timing) and `TimingSpec.response_window_ms?: int` (enforced response deadline; miss = logged as `no_response`, counts as an error trial; deadline interacts with `stimulus_ms=null` only).
- **R3 `derived` materialization** — optional per-trial derived values computed deterministically at generation (e.g. cumulative block progress), so the runtime never computes experiment-relevant state.
- **R4 measures declaration** — optional `measures: [{name, source}]` describing which logged fields constitute the dataset (RT, accuracy, choice, exploration path). MVP: documentation-level metadata driving the event-log export header, not a new computation.

**Compatibility contract (acceptance-gating)**: a v1-shaped spec (no v2 fields) must produce **identical fingerprints and byte-identical HTML** under the v2 engine as under v1 — proven by adding current golden fixtures as v2 regression tests. The v2 fields are excluded from the canonical fingerprint form when unset, so v1 fingerprints are stable.

## 3. Game Design Layer (GameSpec v2 — presentation only)

【exists】 GameSpec v1 (`game/experiment_ref/scene/input/feedback/flow/gamification`, all `extra="forbid"`, validated by G1–G7).

【proposed】 new **optional** sections (all `extra="forbid"`, all strings bounded, no experiment-semantics fields — the fence from gamedev-agent applied):

- **`world`** — a small scene graph: rooms (id, title, description, text-only "objects" with inspect text), start room, allowed moves (`room_a → room_b`), max ~8 rooms / ~24 objects (schema bounds).
- **`narrative`** — intro text, per-block briefing text (rendered at block breaks), ending text variants keyed by simple outcome (e.g. accuracy band) — pure static strings; no branching engine.
- **`mechanics`** — which registered interaction patterns to enable: MVP vocabulary `{explore: bool, inspect_objects: bool}` mapped to a new runtime layout `"explore-and-encounter"` (registered alongside `canvas-center|rows`; new layouts = new template + tests, core untouched — the v1 registry philosophy).
- Scene v1 fields remain: title/instructions/layout/theme. `input` gains nothing new (keyboard stays the only modality in MVP).

**The LLM's entire creative output remains a small, bounded, validatable JSON document** — never game code.

## 4. Research–Game Mapping Layer (the scientific core of M2)

【proposed】 — this layer is *the* differentiator vs. every reference project. It has three parts:

1. **Mapping declaration** (`GameSpec.mapping`, optional, required when `mechanics.explore=true`):
   - `trial_trigger: "sequential" | "explore-encounter"` — how the next measurement trial is entered (v1 behavior = `sequential`; exploration mode = a designated encounter action pulls the **next trial in bundle order**).
   - `response_bindings` — reuse of v1 `input.bindings` (game action → experimental response variable).
   - `creative_freedom` — machine-readable whitelist of what the game layer may style: `{theme, room_labels, object_labels, narrative_text, feedback_style}`.
   - `controlled_invariants` — fixed list asserted by validation: `{trial_order, conditions, stimulus_content, correct_answers, timing}` — the mapping document *states* the iron rule so it can be *checked*.
2. **Static verification** — `validate_game` v2 rules (new error codes, e.g. `G8_MAPPING_*`): mapping references defined rooms/objects; every response variable has a binding; encounter objects count ≥ trial count of the mapped phase (you cannot run out of encounters before trials); **any experiment-semantics key anywhere in world/narrative/mechanics → reject** (fence maintained).
3. **Dynamic verification (play-time reconciliation)** — new tool `verify_game_events(event_log, bundle)` (generator-free, like `verify_bundle`): asserts every measurement event's conditions/indices match the bundle **in order**, no skipped/inserted/altered trials, RT/response fields present; game-class events are counted and reported but not reconciled. This is the piece that upgrades "render-time anti-tamper" to "play-time evidence" — the event log becomes data you can *prove* corresponds to the design.

## 5. Game Runtime Layer (renderer v2)

【exists】 single-file HTML, pure template assembly, embedded SHA-256 startup check, sequential state machine, in-memory event log with manual download, self-check page, keyboard input, byte-reproducible golden tests.

【proposed】 — additive within the same discipline (pure template assembly, zero dependencies, `file://`):

- **Exploration mode** (only when `mechanics.explore=true`): between measurement trials the player moves through the `world` room graph (keyboard: room moves) and inspects objects; inspecting a designated encounter object **pulls the next bundle trial in fixed order** (its materialized stimulus renders as the clue/judgement screen, existing trial state machine runs unchanged), then returns to exploration. The trial sequence consumed is *by construction* the bundle's order — the game layer cannot reorder, skip, or inject trials.
- **Two-class event log** (adopting the WebGameTemplate split): `measurement` events (`trial_start`, `response`, `no_response`, block markers — reconcilable against the bundle) and `game` events (`room_enter`, `object_inspect`, `encounter_trigger` — logged with timestamps, presentation-only). Export unchanged (manual JSON download on the end screen; auto-persist stays a documented limitation).
- **Narrative surfaces**: intro screen, block-break briefings, banded ending text — static strings from GameSpec, rendered at existing flow points.
- **Self-check page grows** with the new mechanics (rooms reachable, encounters ≥ trials, log-schema check) — the OpenGame "failure knowledge as checklists" pattern, staying zero-dependency.

【assumption】 ~800–1,200 lines of template JS added; single-file size stays well under 1 MB for the prototype (text-only world). Must be confirmed at M2-D.

## 6. Agent Workflow — five logical stages, one AgentLoop

【exists】 single `AgentLoop` + `ToolRegistry`; combinator pattern (`build_game_registry`, 8 tools); two-tier error contract; `ITERATION_STALLED` on repeated identical failures; CLI/API entry points.

【proposed】 stages as **conventions over the same loop** (explicitly *not* separate LLM agents — no multi-agent assumption):

| Stage | Actor | Tools | Gate |
|---|---|---|---|
| 1. Research Designer | LLM proposes ExperimentSpec v2 | `validate_experiment`, `generate_trials`, `export_experiment` 【exists, extended】 | `auto` — engine validation + FakeLLM test fixtures |
| 2. Game Designer | LLM proposes GameSpec v2 (+ mapping) | `design_game` intake + `validate_game` v2 【proposed】 | `auto` — G1–G8 |
| 3. Game Builder | deterministic code | `render_game` 【exists, extended】 | `auto` — byte-identity + golden + self-check |
| 4. Game Tester | deterministic code | `verify_game_events` on played logs 【proposed】; scripted playthrough fixture | `auto` — reconciliation report |
| 5. Researcher approval | human | artifacts + verification report presented at a **checkpoint** | `human_review` |

**Checkpoint semantics** (adopted from WebGameTemplate's guard protocol + game-studio-ai's pending/approved states): a checkpoint presents the artifacts, the verification report, and the browser-playtest checklist link; approval is an explicit user action (CLI confirms / API returns a pending result the caller must accept). A checkpoint that cannot be verified from the presented artifacts **must block with a named reason and concrete remediation options** — it never waves anything through. MVP realizes this as the existing flow (run → artifacts + report → human review → `verify` command); the formal `pending → approved` artifact states are a listed extension, not MVP.

## 7. Non-goals (explicit)

Multi-agent orchestration; LLM-generated game code; generated multimodal assets; pointer/touch/audio modalities; formal RT-grade timing validation; auto-persisted logs; Playwright browser automation (stays deferred, D2); any paradigm-, theory-, or theme-specific engine field; real-LLM E2E (PA-14 stays deferred).

## 8. Alternative architectures considered

See PROTOTYPE_SPEC.md §5 and IMPLEMENTATION_ROADMAP.md §4 for the full comparison of **A. extend the deterministic renderer** (recommended), **B. Phaser integration**, and **C. agent-editable templates** — with the evidence and trade-offs. Recommendation: **A**, for scientific control, reproducibility, zero-dependency and M1 compatibility; B and C remain documented fallbacks with explicit trigger conditions.
