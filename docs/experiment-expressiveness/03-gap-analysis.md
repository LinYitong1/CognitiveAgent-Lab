# 03 — Expressiveness Gap Analysis (Experiment Expressiveness Audit)

Every gap below carries a classification (Type 1–4), evidence, and the fix's home layer. The audit's discipline: **agent non-use is not a schema gap; schema legality is not scientific validity.**

Revised 2026-10-24 (design round): T2-1/T2-2/T2-3 updated to the revised primitive designs (04); T3-3 corrected (client wall-clock timestamps exist). Status markers: [VERIFIED] code/test-established · [DESIGN] revised proposal, not implemented · [NEEDS-TEST] acceptance-test obligation.

## Type 1 — Agent Planning Gaps (schema/tools suffice; the LLM misused them)

### T1-1: Nominal-manipulation designs (T2R)
- **Evidence**: real-Gemini T2R produced a schema-valid spec where short/long conditions rendered identical content (labels only), answers readable off-screen. The engine could express the required design (P0 primitives existed by then for the re-run; at T2R time partially).
- **Current mitigation**: design-first system prompt (M3-B), v2 tool docs (variables/copy_from/correct_rule/phases), offline label-masking heuristic in `scripts/agent_eval.py` (catches the exact T2R signature).
- **Status**: mitigated, NOT verified — needs the authorized real-LLM re-run. Fix home: prompt/tooling/eval, **not schema**.

### T1-2: Discoverability of the composition pattern
- **Evidence**: this audit needed deliberate search to find the `when`+singleton-pool+`copy_from`+`exclude` composition that unlocks Flanker/Stroop/Task-Switch. Tool docs document the primitives but not the *composition recipe* for relational content.
- **Fix home**: tool documentation / few-shot example in the experiment-tools description budget, or an eval scenario encoding it. No schema change.

## Type 2 — Schema Expressiveness Gaps

### T2-1: Cross-trial state (HIGH — blocks N-back, sequence learning, priming designs)
- **Evidence**: per-trial isolated bindings + per-trial rng (`stimulus.py::_materialize_variables`, `_trial_stimulus_rng`); no construct addresses trial i−n. Case 3 of 02.
- **Why existing schema can't solve it**: `copy_from` resolves only same-trial earlier variables; `correct_rule` operands likewise; generator emits trials independently.
- **Primitive**: see 04 §P1 (revised) — `copy_from` with `lag` **plus lagged `exclude` entries**. The original lag-alone proposal was insufficient: a full 2-back also needs the *non-match* direction (current stimulus must DIFFER from n-back), which requires excluding the lagged value from the pool draw. Materialization already runs in index order (shuffle precedes materialization [VERIFIED]), so determinism is preserved by construction and lag resolves against the final presented order — trial reshuffling and block boundaries do not break history references (analysis in 04 §P1.2). Status: [DESIGN].

### T2-2: Withhold-as-correct (HIGH — blocks Go/No-Go, recognition-with-pass designs)
- **Evidence**: options are strings only; `computeCorrect(value===null) → false` in both engines. Case 4 of 02.
- **Primitive (revised 2026-10-24)**: a declared `withhold_option` on the response that the ANSWER KEY may take, while the runtime event **preserves `value: null`** and only the scoring rule changes (`null` compares against the key; it equals only the withhold value). The event log keeps recording behavior (no keypress); correctness interprets it. The four inhibition cells (hit/omission/commission/correct-rejection) are unambiguous from `(conditions, value, correct)` — 04 §P2.2 truth table. **Status: implemented and runtime-tested (Stage 1)** — `test_withhold_option.py` covers both engines, the missing-answer-key edge, and the old-spec regression; the null→false scoring defect (T3-2) is closed for declared-withhold responses and unchanged for all others.

### T2-3: Per-block / per-condition timing override (MEDIUM)
- **Evidence**: `TimingSpec` global to the spec, copied verbatim onto every trial (`BlockSpec` has no timing). Practice blocks commonly need shorter deadlines; condition-specific SOAs are common in cueing designs.
- **Primitive (scope-clarified 2026-10-24)**: optional `BlockSpec.timing` override, materialized per trial (runtime already consumes `trial.timing` — schema+materialization only). **Block-level ONLY** — this does not solve condition-level timing variation, which remains a residual gap (workaround: restructure conditions into blocks via `factor_filter`, at the cost of within-block mixing). **Status: implemented (Stage 1)** — `test_block_timing.py` (materialization, warning, v1 gating, zero-drift incl. golden bundle + golden HTML).

### T2-4: Between-subject / participant constructs (MEDIUM — blocks formal data collection)
- **Evidence**: no participant/session/group identifier in spec, bundle, or event schema (0 hits in rendered engine).
- **Primitive direction**: NOT an ExperimentSpec change (a bundle is one condition-set by design); a session/participant envelope at the data-collection layer + per-session seed derivation. Deliberately out of ExperimentSpec scope — see 05 P1.

### T2-5: Conditional correctness as a first-class rule (LOW)
- **Evidence**: Task-Switching required design inversion (sample the answer, derive the stimulus) because `correct_rule` is a single boolean mapping and `correct_from` reads one factor.
- **Assessment**: the inversion pattern is legitimate and general (symmetric designs); a multi-branch rule primitive would add schema complexity for marginal gain. Document the pattern instead (T1-2 fix covers it). **Recommendation: no schema change now.**

### T2-6: Arbitrary trial sequences (LOW)
- Fixed alternation / blocked runs (AABBAABB) inexpressible: only shuffle (`shuffle_within`) or declaration order. Affects switch-cost designs wanting controlled transition frequencies. Possible future primitive: per-block `sequence_pattern`. Low priority — random cueing with offline switch-coding covers most designs.

## Type 3 — Runtime / Renderer Gaps

### T3-1: Non-textual stimulus attributes (MEDIUM — Stroop visual conflict, spatial cueing)
- **Evidence**: stimuli are text lines; per-trial styling (color/position/size) has no GameSpec primitive (`scene` is global). Stroop probe rendered "ink: red" as a label.
- **Direction**: a per-line style token in stimulus materialization + a GameSpec scene capability flag; must stay presentation-only (no experiment semantics in GameSpec — boundary table §4.0 of the proposal, still binding).

### T3-2: Null-response scoring (paired with T2-2)
- `computeCorrect` hard-codes null→false. Once T2-2 gives withhold a first-class value, both engines' scoring must treat null as a *response value* compared against the key. Verified current behavior documented in 01 §4.

### T3-3: Phase-onset events / trusted timestamps (MEDIUM for data analysis)
- **Evidence (corrected 2026-10-24)**: the original audit said "no wall-clock timestamps (rt_ms only)" — imprecise. Every event carries `t_epoch_ms = Date.now()` [VERIFIED]. What is genuinely missing: phase-onset events (timeline reconstruction per phase) and a *trusted* timestamp (client clock is unskew'd, unsynced, tamperable). RT anchoring itself is correct (window onset).
- This is the deferred P2 of M3-A (phase onset events) plus the data-layer trust model (06 §4). Data-layer change; rendering semantics untouched.

### T3-4: Event log transport (HIGH for formal data collection, LOW for the current preview scope)
- In-page JSONL with manual download; no server-side persistence, no force-flush on tab close. By design for the preview; blocks real data collection until a collection endpoint exists (see 05 P1).

## Type 4 — Scientific Validation / Data Gaps

### T4-1: Manipulation fidelity is only screened, not proven
- The label-masking heuristic (offline eval) catches "levels rename labels" — the one observed real failure class. It does NOT prove construct validity (false positives: timing-only manipulations; false negatives: coincidental content differences). Researcher review remains mandatory (documented in `docs/agent-foundation/04`).
- **Deliberate stance**: no pseudo-scientific auto-validators beyond auditable heuristics.

### T4-2: Data contract for analysis
- Event schema records conditions/value/correct/rt_ms per trial — sufficient for accuracy/RT ANOVAs on within-subject factors. Missing for publishable pipelines: participant IDs, session metadata, trusted timestamps, server-side receipt, and between-subject assignment (all Type 3/T2-4 items). **The full future data-layer contract is now specified in 06** (Participant/Session/event envelope/timestamps/persistence requirements; design only, ExperimentSpec untouched).

### T4-3: Timing precision
- Browser setTimeout ≈ gameplay-grade; documented everywhere (README, renderers, phase player). Not fixable inside a browser-only architecture; a native runtime would be a new deployment mode.

## Unresolved / needs-a-test items

- **U-1**: whether real LLMs spontaneously find the composition pattern (T1-2) — resolvable only by the authorized real-model re-run with an eval scenario requiring relational content (e.g. a Flanker brief). The recipe documentation plan (04 §D1) is gated on the same re-run for verification, but the doc change itself is offline-safe.
- **U-2**: multi-phase + explore layout + withhold-option interactions — untestable until T2-2 lands; the phased withhold case is now an explicit acceptance test (04 §P2.4 item 6).
- **U-3 (new, 2026-10-24)**: lag + `max_repeat`/ratio interactions — the 2-back design (04 §P1.3) relies on ratio allocation; whether `max_repeat` (currently UNSUPPORTED_CONSTRAINT [VERIFIED]) and lag compose once supported is untested. Note also: the 2-back invariant relies on shuffle order; no constraint today prevents pathological runs (e.g. long match streaks) — acceptable (random designs allow this), documented.

## Non-gaps (explicitly NOT problems)

- **Determinism/reproducibility**: byte-identical regeneration, generator-free verification — solved and frozen (golden tests).
- **Presentation-layer tamper resistance**: G8 + dual fingerprints + monotonic cursor — solved and runtime-tested.
- **Structured iteration feedback**: error_code/path/suggestion loop, previous_errors anti-stall — solved.
- **Multi-factor balance/statistics**: solved (largest remainder, exact integer assertions).
