# 01 — Current Capability Map (Experiment Expressiveness Audit)

Date: 2026-10-24 ｜ Head audited: `be7aa75` ｜ Method: code reading + isolated sandbox probes through the real `validate_spec → build_bundle → render_game_html` chain (probe scripts run in-session; no core code modified). Revised 2026-10-24 (design round): item 6 below corrected; design revisions live in 04/06.

Pipeline audited: **Schema → Generator → Validator → Bundle → GameSpec → HTML Runtime → Data Recording**.

## Module map (code path → role → status)

| Stage | Code | Status |
|---|---|---|
| ExperimentSpec v1 | `src/experiment/schemas.py` (factors/levels/blocks/constraints/responses/timing) | implemented, frozen |
| ExperimentSpec v2 research layer | `schemas.py` (`stimulus_spec` incl. variables/phases, `derived_spec`, `measures`, `responses[].correct_rule`) | implemented (M2 + M3-A P0/P1) |
| Validation | `src/experiment/validation.py` + `stimulus.py` (40+ structured v2 error codes) | implemented |
| Generation | `src/experiment/generation.py` (factorial combinator, largest-remainder allocation, per-block derived rng streams) | implemented, deterministic (byte-reproducible; golden tests) |
| Stimulus materialization | `src/experiment/stimulus.py` (per-trial isolated rng; variables pool+count/copy_from/exclude/when; phases; correct_rule evaluation) | implemented |
| Bundle export | `src/experiment/export.py` (dual SHA-256 fingerprints) + `verify.py` (generator-free verification CLI) | implemented |
| GameSpec v1/v2 | `src/experiment/game_schemas.py` (classic + explorable world/narrative/mechanics/mapping; G8 validation) | implemented |
| HTML renderers | `game_render.py` (classic), `explore_render.py` (explore), `phase_player.py` (shared phase playback) | implemented |
| Runtime event recording | embedded JS: `trial_start{trial_index, block, conditions}` / `response{value, correct, rt_ms}` / `game_end{correct, applicable}`; explore adds channel separation (measurement vs game) | implemented, in-page JSONL, manual download |
| Agent-facing tools | `src/tools/experiment_tools.py`, `game_tools.py` (9-tool registry) | implemented, documented for LLM |

Test evidence baseline: 402 tests, golden byte-identity, fingerprint cross-checks, node DOM-stub runtime tests for both engines, offline eval harness with false-success probe (`scripts/agent_eval.py`, `docs/agent-foundation/`).

## Key verified behaviors (this audit's probes)

1. **Per-trial variable isolation** (`stimulus.py::_materialize_variables`): bindings dict is rebuilt per trial; rng = `_trial_stimulus_rng(seed, trial.index)`. `copy_from` resolves only EARLIER variables within the SAME trial. **Cross-trial references are structurally impossible** — the definitive N-back blocker.
2. **`when` guards are single-factor only** (`V2_VAR_WHEN_SHAPE`) and must cover ALL levels of the guarded factor (`V2_VAR_WHEN_COVERAGE`); `exclude` cannot forward-reference.
3. **Composition pattern confirmed**: single-factor `when` + singleton pools + `copy_from` + `exclude` suffices to express cross-factor relational content (Flanker/Stroop/Task-Switch probes below all PASS with content recomputed per trial).
4. **Deadline/timeout semantics** (classic engine, verified from rendered JS): `stimulus_ms` is the response deadline; expiry records a `response` event with `value: null` and **`correct: false` unconditionally** (`computeCorrect`: `if (value === null) return false`). Timeouts are logged, never dropped.
5. **Rating responses**: numeric input with scale bounds enforced in-engine (rejects out-of-range, re-prompts) — supported, not a bare text field.
6. **No participant/session identifiers** anywhere in the event schema (0 hits); no server-side persistence (manual event-log download). **Correction (2026-10-24 revision)**: the original audit said "no absolute timestamps (rt_ms only)" — that was imprecise. Every event DOES carry `t_epoch_ms = Date.now()`, a client wall-clock timestamp [VERIFIED: `logEvent`/`logGame`/`logMeasurement`]. What is genuinely missing: a *trusted* (server-side, clock-synced) timestamp, phase-onset events, and any session/participant envelope — see 06 §4.
7. **TimingSpec is global**: one timing per spec, materialized onto every trial; `BlockSpec` has no timing override (schema fact).
8. **Trial-level event content**: `trial_start` carries conditions but NOT the materialized stimulus text; presented content is reconstructable deterministically from the bundle (fingerprint-anchored), not logged verbatim.
9. **derived_spec** materializes trial_number / block_progress / count_factor_level into `trial.derived` (verified live); **measures** is declared metadata only (no runtime collection claim — by design).
10. **Explore engine** separates `channel: measurement` from game events; monotonic trial cursor + G8 invariants guarantee exploration never alters conditions/order/answers (verified by runtime tests).

## End-to-end capability summary (the map)

**Fully working chain, verified end-to-end (generation + validation + rendering + runtime event recording):**

- Multi-factor factorial designs with balance / weighted ratios / mutually_exclusive constraints (**not** max_repeat: it is a reserved field — a non-None declaration is rejected with `UNSUPPORTED_CONSTRAINT`, verified by `test_unsupported_constraint_max_repeat`; sequence constraints remain unimplemented Phase B scope)
- Per-block trial counts and factor filtering; practice blocks (as ordinary blocks)
- Text-line stimulus materialization: pools, per-factor templates, intra-trial variables (conditional draw, constrained exclusion, content reuse), multi-phase presentation (encoding/delay/probe) with per-phase response windows
- Content-driven correctness (`correct_rule` eq/neq/in over materialized content) and label-derived correctness (`correct_from`)
- Choice (key-mapped), rating (scale-checked), text responses; deadlines via stimulus_ms / phase duration; RT anchored at stimulus/window onset; timeout logging (value null)
- Single-file HTML (classic + explorable), dual-fingerprint startup check, event log download; explore games with narrative/rooms/encounters preserving trial invariants

**Present but partial / indirect (see 02/03 for case evidence):**

- Conditional correctness across factors — achievable via design inversion (sample the answer as a factor, derive the stimulus), not via a direct rule primitive
- Presented-stimulus provenance in the data stream — via deterministic reconstruction, not logged verbatim
- Switch-cost / sequence analyses — offline from logged conditions; no control over arbitrary task sequences (only shuffle or declaration order)

**Absent (structurally):**

- Cross-trial stimulus/response references (per-trial isolation — N-back, sequence learning)
- Withhold-as-correct response semantics (Go/No-Go inhibition scoring)
- Between-subject constructs: participant/group identifiers, per-participant condition assignment
- Per-block / per-condition timing overrides
- Adaptive procedures (runtime feedback into generation) — generation and execution are deliberately separated (anti-tampering architecture)
- Non-textual stimulus attributes (per-trial color/position/size styling in rendering)
- Conditional trial transitions / branching at runtime
