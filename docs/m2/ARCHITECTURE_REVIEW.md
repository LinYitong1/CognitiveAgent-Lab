# M2-A — Architecture Review of the Current Repository

- **Document status**: read-only audit. No M1/Phase A/B code was modified; this document and its siblings under `docs/m2/` are the only new files.
- **Date**: 2026-10-21 · **Baseline**: commit `9911eae` (231 tests, 89% coverage, six CI gates green, public repo + Codex Skill live)
- **Verification labels used below**:
  - ✅ **VERIFIED** — asserted by the automated test suite or confirmed by direct source inspection (file references given).
  - ⚠️ **ASSUMPTION** — plausible but not yet machine-verified; must be validated before being relied upon.

---

## 1. Reusable components (what M2 inherits for free)

| Component | Location | M2 relevance |
|---|---|---|
| `AgentLoop` (plan→act→observe, task persistence via events, stalled detection) | `src/agent/loop.py` | M2 agent workflow runs as **logical stages inside the same single loop** — no new framework needed |
| `ToolRegistry` + `ToolSpec` contract (risk levels, idempotency, two-tier error contract) | `src/agent/registry.py`, `src/models/tool_spec.py` | New M2 tools (game design/test/reconcile) register through the same combinator pattern (`build_game_registry`) |
| Experiment engine (deterministic generation, balance/ratios/mutually-exclusive constraints, dual SHA-256 fingerprints) | `src/experiment/{schemas,validation,generation,export}.py` | Research layer core; M2 extends additively |
| Generator-free verification (`verify_bundle` recomputes fingerprints without the engine) | `src/experiment/verify.py` | Template for the proposed event-log reconciliation verifier |
| GameSpec v1 + `validate_game` (G1–G7, `extra="forbid"` everywhere, 9 error codes) | `src/experiment/game_schemas.py` | Boundary contract M2 must preserve; v2 extends with **new optional sections** |
| Deterministic single-file HTML renderer (pure template assembly, embedded pure-JS SHA-256, startup fingerprint check, self-check page, manual event-log download) | `src/experiment/game_render.py` | Runtime layer v1; M2 runtime extends this code path, not a replacement |
| Sandbox I/O (`_sandbox_io`: path validation + write, shared by all file-writing tools) | `src/tools/_sandbox_io.py` | All M2 artifact writes reuse it |
| ScriptedLLM / FakeLLM acceptance discipline + golden-file testing | `src/pipeline.py`, `tests/golden/`, `tests/integration/` | Every M2 milestone keeps the FakeLLM gate + byte-reproducibility tests |
| CLI + public Python API (`cognitive-agent run/demo/verify`, `run_task`/`run_demo`) | `src/cli.py`, `src/pipeline.py` | M2 stages surface through the same entry points |

## 2. Schema and validation boundaries (VERIFIED)

- `ExperimentSpec` (frozen semantics): `factors` (name + levels with sampling `weight`), `constraints` (`balance`, `ratios`, `mutually_exclusive`), `blocks` (name / `trial_count` / `factor_filter`, ≤ 32 blocks), `responses` (kind ∈ `choice|text|rating`, `options`, `correct_from`), `timing` (**trial-level only**: `fixation_ms` / `stimulus_ms` (null = until response) / `isi_ms`), `seed` (int64 max), and a **generic free-form `paradigm_params: dict`** slot already present (`src/experiment/schemas.py:132–152`).
- `Trial`: `index` (global order), `block`, `factors` (name→level map), `stimulus` (**always an empty dict in Phase A** — `schemas.py:274–282`), `derived` (empty), `timing`.
- `GameSpec` v1 root: `game` / `experiment_ref` (six verbatim bundle references) / `scene` (title, instructions, `layout ∈ {canvas-center, rows}`, `theme ∈ {neutral-light, dark}`) / `input` (**`modalities` accepts only `keyboard`**; `bindings` map keys→options per response) / `feedback` (`none|correctness-flash|outcome-text`) / `flow` (`ready_screen`, `block_breaks`, `end_screen ∈ {none, summary}`) / `gamification` (`score`, `progress_bar`, `streak_bonus`). All models `extra="forbid"`; `validate_game` additionally enforces the experiment-ref match (G2), bindings ⊆ responses, and rejects any experiment-semantics field (verified by GB/BT/BR test families).
- Renderer anti-tamper chain: schema `extra="forbid"` → renderer as sole consumer of trials/correctness from the bundle → embedded dual-fingerprint startup check → golden-file + 48/48 trial reconciliation tests (BR-*).

## 3. Current rendering and interaction capabilities (VERIFIED)

- **Presentation**: the "stimulus" shown on screen is a list of `"factor: level"` **text lines** (`game_render.py:528–530`, `step.display` pairs). No images, no audio, no positioning — text on a centered canvas, two layouts, two themes.
- **State machine** (MVP, frozen as B2 deliverable): READY → [per trial: FIXATION → STIMULUS → responses (sequential over the response list) → FEEDBACK] → ISI → BLOCK_BREAK between blocks → END_SUMMARY. Strictly sequential; **no free exploration, no branching, no interleaving of non-trial interaction**.
- **Input**: keyboard only. `choice` via single-key binding; `text` via inline input; `rating` via keys. Multi-response trials are supported but do not redraw the stimulus between responses.
- **Feedback/gamification**: correctness flash or outcome text; header score/progress derived exclusively from bundle correctness; no streaks rendering beyond the flag.
- **Timing**: browser `setTimeout` scheduling; RT stamped with `performance.now()` relative to stimulus onset (`game_render.py:534,545`); epoch via `Date.now()` in each event. **Demo-grade accuracy, explicitly not for formal data collection** (README limitation #2).

## 4. Limitations relevant to M2 (VERIFIED — these are the real gaps)

1. **No stimulus materialization.** `trial.stimulus` is always `{}`; what the player sees is factor-level text. A mystery game needs per-trial clue content — this is the single largest research-layer gap.
2. **No block-level timing or response deadline.** One global `TimingSpec`; `BlockSpec` carries no timing override; `stimulus_ms=null` means "until response" but there is **no enforced response window** (speed-pressure conditions are impossible today).
3. **No free-roam interaction.** Every moment is a bundle trial; there is no runtime concept of "player is exploring, not being measured".
4. **Event log is single-class and volatile.** All events are measurement events (`trial_start`, `response`, block/end markers) in page memory; download is manual on the end screen; no separation of measurement vs. presentation events; no reconciliation tool that checks a **played** log against the bundle (verification today is render-time, not play-time).
5. **Interaction vocabulary**: keyboard-only, 3 feedback styles, no dialogue, no scenes/rooms, no sprites/audio.
6. **No mechanism for narrative or scene data anywhere in GameSpec v1** (by design — it was the MVP).

## 5. Constraints imposed by frozen M1 / Phase A / B contracts (VERIFIED)

- **Import-path packaging**: public API is `from src.… import …`; a rename to `cognitive_agent` is deferred to a future incompatible version (user decision, 2026-10-21). M2 documents and examples must use `src.*`.
- **Frozen code**: `AgentLoop`, `ToolRegistry`, `LLMClient(Protocol)`, M1 tools, Phase A engine semantics, B0–B2 GameSpec v1 semantics and renderer v1 behavior. M2 changes must be **additive** and keep v1 inputs producing byte-identical outputs (see PROPOSED_ARCHITECTURE §6 for the compatibility contract).
- **Determinism contract**: same inputs → identical fingerprints and byte-identical HTML (bundle file bytes exempted via `generated_at`, documented). Any new runtime code must stay in the pure-template-assembly + golden-test discipline.
- **Single-file HTML, file:// playable, zero external URLs, zero new dependencies** (B2 contract; the M2-A brief reaffirms "do not add dependencies").
- **Tool descriptions are LLM-facing contract surface** (PA-14 lesson: ASCII, compact, with validated examples). New tools must follow the R2 pattern.
- **FakeLLM is the acceptance gate**; real-LLM E2E stays deferred (PA-14 known issue).
- **No paradigm hardcoding** (project boundary, user-confirmed 2026-10-20): no mystery/detective-specific anything in the engine. The M2 prototype is an *example*, exactly like Stroop/N-back are examples.

## 6. Verified capabilities vs. assumptions for the M2 vision

| Claim | Status |
|---|---|
| Deterministic ExperimentSpec → trials → fingerprinted bundle | ✅ VERIFIED (225→231-test suite, golden files, cross-checked with external `shasum`) |
| GameSpec validation boundary + render-time anti-tamper chain | ✅ VERIFIED (GB/BT/BR tests) |
| Single-file HTML playable offline with embedded event log | ✅ VERIFIED (browser checklist + self-check page; manual playtests recorded) |
| Agent workflow shape (tool ordering, error iteration, fail-loud verification) | ✅ VERIFIED **with FakeLLM only**; real-LLM E2E ⚠️ NOT VALIDATED (PA-14) |
| Timing precision sufficient for formal RT research | ⚠️ ASSUMED INSUFFICIENT — browser-grade; no validation study performed |
| "Researchers can describe an experiment in natural language and the agent designs it" | ⚠️ NOT SUPPORTED TODAY — deterministic API/CLI and scripted demo are the proven surface; NL→spec with a real LLM is the deferred PA-14 path |
| Event log integrity reflects what was actually played | ⚠️ PARTIAL — events are logged at play time, but no play-time reconciliation tool exists yet (proposed in M2-D) |

## 7. What this means for M2 (bridge to PROPOSED_ARCHITECTURE.md)

The dependable core to build on is the **deterministic engine + validation boundary + single-file renderer**. The four real gaps — stimulus materialization, block/deadline timing, exploration-capable runtime, play-time event reconciliation — are precisely scoped, additive extensions. The agent workflow needs **no new framework**: it is new tools + stage conventions inside the existing single `AgentLoop`, with researcher approval surfaced as explicit checkpoints in the CLI/API flow.
