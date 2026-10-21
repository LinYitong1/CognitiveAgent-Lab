# M2-A — First Prototype Specification: "The Manor Case" (mystery investigation game)

- **Status**: design only. Nothing is implemented or created; no M1 code modified.
- **Purpose**: the smallest *scientifically meaningful* M2 prototype — a playable mystery investigation game for adult participants that demonstrates every proposed M2 layer while remaining a pure **example** built on generic engine primitives (no detective/mystery anything enters the engine — the project's no-paradigm-hardcoding boundary).
- **Playtime target**: 5–10 minutes.

---

## 1. Premise and player experience

You are a detective re-examining a closed case. You explore five rooms of a manor (study, library, parlour, hallway, cellar). Rooms contain objects; most are flavour ("a dusty clock"), some are **clues**. Examining a clue presents it for judgement: **which of three suspects does this clue support?** (keys `1` / `2` / `3`). Some judgements are pressured by a ticking deadline; some clues are buried among decoy details. After the final clue, the case summary states your accuracy and the ending text varies by performance band.

The exploration (rooms, movement, flavour objects) is the **game layer**. The clue judgements are **measurement trials from the bundle**, consumed strictly in bundle order.

## 2. Experimental design (generic ExperimentSpec v2 — all primitives exist or are proposed R-items)

**Design**: 2×2 within-subject + ground-truth factor, balanced.

| Factor | Levels | Manipulates (cognitive variable) |
|---|---|---|
| `clue_salience` | `salient` / `embedded` | perceptual/cognitive load of evidence extraction (R1: embedded clues render with decoy text lines around the clue content) |
| `pressure` | `free` / `deadline` | speed–accuracy tradeoff (R2: `response_window_ms` set for deadline trials via per-block split) |
| `true_suspect` | `a` / `b` / `c` | ground truth for the choice response (uses existing `correct_from`) |

**Structure** (seeded, reproducible):

- Block `briefing` (practice): 6 trials, all `salient`+`free`, feedback on.
- Block `investigation` (main): 24 trials — 2×2×3 fully balanced (each combination twice), 2 sub-blocks so the deadline condition can be timed per-block (R2 block timing override).
- `constraints.balance = true`; `seed = 20261021`.

**Responses**: one response variable `accuse`, kind `choice`, options `[suspect_a, suspect_b, suspect_c]`, `correct_from = true_suspect`, keyboard `1/2/3`.

**Timing**: `fixation_ms=300`; `stimulus_ms=null` (until response) with `response_window_ms=3500` in the deadline blocks (miss → `no_response` event, counted as error); `isi_ms=500` replaced by the exploration phase return (inter-trial interval = player-controlled exploration; this is *declared* in the mapping, and total-trial timestamps remain logged).

**Measurements** (R4 declaration): accuracy (% correct per condition), RT per trial (`performance.now()`-based, demo-grade — README limitation stands), miss rate under deadline, exploration path (room sequence, objects examined, time per room), and the trial-by-trial mapping of condition → behaviour.

**Why this is scientifically meaningful**: it yields a clean 2×2 of load × pressure on accuracy/RT/miss-rate — the speed–accuracy tradeoff and load effects are core, well-replicated cognitive phenomena; the exploration log adds engagement-relevant behavioural traces. It deliberately does **not** require any theory-specific engine field.

## 3. Game↔experiment mapping (the M2 mapping layer, exercised)

| Game mechanic | Experimental role | Controlled? |
|---|---|---|
| Room movement (`n/s` or arrow keys) | none — engagement; logged as `game` events | free (creative_freedom: room labels, descriptions) |
| Inspecting flavour objects | none — engagement; logged | free |
| Examining a clue object | **trigger**: pulls the next measurement trial in bundle order | invariant: trial order |
| Clue judgement screen (`1/2/3`) | the `accuse` response; correctness from `true_suspect` | invariant: conditions, correctness, timing |
| Clue text content | materialized `trial.stimulus` (R1) | invariant: stimulus content (engine-materialized) |
| Deadline ticking banner | `response_window_ms` (R2) rendering | invariant: window duration |
| Decoy lines around embedded clues | R1 stimulus materialization by `clue_salience` level | invariant: materialization is engine-side, seeded |
| Detective "reputation" score | existing gamification `score` (derived from bundle correctness only) | free (presentation of score) |
| Case briefing text between blocks | block break narrative (existing block-break flow point) | free (text only) |
| Ending text by accuracy band | existing end screen + banded narrative text | free (text only) |

Mapping declaration (GameSpec v2 `mapping`): `trial_trigger: "explore-and-encounter"`; encounter objects ≥ 30 (≥ trial count, G8 rule); `controlled_invariants` asserted by `validate_game`; all measurement trials reconciled post-play by `verify_game_events`.

## 4. Acceptance criteria (measurable)

**Engine / determinism**

- AC-1 Same ExperimentSpec + seed → identical fingerprints; same bundle + GameSpec → **byte-identical HTML** (golden test).
- AC-2 v1-shaped specs (no v2 fields) produce identical fingerprints and byte-identical HTML to v1 golden fixtures under the v2 engine (compatibility contract).
- AC-3 Stimulus materialization is deterministic: same seed → identical clue/decoy text assignment (unit test).

**Scientific control**

- AC-4 Every played measurement event reconciles against the bundle: order, conditions, and correctness — zero mismatches allowed by `verify_game_events`; a deliberately tampered log (reordered trial) must be **rejected** (negative test).
- AC-5 No experiment-semantics key is accepted anywhere in `world`/`narrative`/`mechanics` (validation negative tests, one per forbidden key family).
- AC-6 Encounter consumption: N encountered clues == N bundle trials consumed, in order (runtime reconciliation fixture: a scripted full playthrough log).

**Playability / scope**

- AC-7 Single-file HTML, `file://`, zero external URLs, zero new dependencies; plays the full 30-trial session in 5–10 minutes (human playtest timing, checklist protocol).
- AC-8 Keyboard-complete: movement, inspection, `1/2/3` judgement, deadline miss path, block briefings, end summary, event-log download all keyboard-operable (playtest checklist).
- AC-9 Event log contains both classes with the documented schema; download includes a header with the bundle fingerprints (log↔bundle provenance).
- AC-10 All existing 231 tests remain green; new tests cover every M2 milestone (target: suite grows to ~300).

**Agent workflow**

- AC-11 A FakeLLM end-to-end run drives all five stages (spec → game design → render → scripted test log → reconciliation report) and fails loudly on injected faults (missing render, tampered log, out-of-order trials).
- AC-12 The researcher checkpoint presents: artifact paths, verification report, and the playtest checklist link; nothing is reported as "approved" without the human step.

## 5. Alternative implementation architectures (comparison)

| Criterion | **A. Extend deterministic renderer** (recommended) | B. Integrate Phaser (vendored, single-file embed) | C. Agent-editable templates + constrained layer |
|---|---|---|---|
| Implementation complexity | **Low–medium**: ~800–1,200 lines template JS + schema v2; one codebase | High: embed/vendor ~1.2 MB engine, new build/embedding pipeline, Phaser-scene discipline | Highest: safe subset of editable code, AST/sandbox verification of agent edits |
| Flexibility (scenes/sprites/audio) | Medium: text-first world; sprites/audio deferred | High out of the box | Highest in theory |
| Maintainability | **High**: golden tests + pure assembly stay | Medium: engine churn, upgrade path | Low: each edit risks the control boundary |
| Reproducibility | **Preserved**: byte-identity pipeline unchanged | Preserved in principle, heavy golden artifacts (MB-scale), unproven here | Fragile: byte-identity across agent edits is hard to guarantee |
| Scientific control | **Unchanged iron rules**; mapping layer enforceable by schema + reconciliation | Same rules possible, but more surface to audit | Weakest: arbitrary code adjacent to measurement path |
| M1 compatibility | **Full** (additive) | Dependency addition (violates no-deps constraint; needs explicit user waiver) | Partial: new verification machinery |
| Evidence | gamedev-agent validates deterministic-template route; WebGameTemplate validates file:// runtime discipline; our own BR tests already prove byte-identity | OpenGame shows Phaser viability **only with** 27B-class models + free codegen — the route we rejected | OpenGame's route; rejected by prior survey decision (2026-10-20), re-confirmed |

**Recommendation: A.** It is the only option that keeps all five M2-A constraints simultaneously (no deps, single-file, byte-reproducible, controlled boundary, M1-compatible). **Trigger conditions for revisiting B**: a validated need for rich media *after* M2-E, accepted as an explicit dependency waiver, implemented as an *additional registered layout* (vendored engine embedded at render time), never a rewrite. **C stays rejected** unless a verified-safe editable subset emerges — none exists today.

## 6. Explicit non-goals for this prototype

No audio/pointer/touch; no animated sprites; no branching narrative engine (banded static endings only); no formal timing validation (demo-grade RT, stated in-game and in the log header); no participant management/authentication; no auto-persisted logs; no theory-specific parameters anywhere in the engine.

## 7. Smallest scientifically meaningful scope (bridge to the roadmap)

If the full 2×2 prototype proves too large for the first milestone, the **minimal meaningful core** is: R1 stimulus materialization (text clues) + explore-encounter runtime + `verify_game_events` reconciliation, run with a **single-factor** version (`clue_salience` only, 20 main trials). The `pressure` factor and R2 deadline mechanics are cleanly separable into a follow-up milestone because they touch only the engine timing extension, not the mapping or runtime structure. See IMPLEMENTATION_ROADMAP.md (MVP vs extension split).
