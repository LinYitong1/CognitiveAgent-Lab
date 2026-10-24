# 02 — Experiment Case Matrix (Experiment Expressiveness Audit)

Nine representative cases driven through the REAL chain (`validate_spec → build_bundle → content recomputation`; rendering/runtime claims additionally backed by the existing node DOM-stub runtime test suite). Probes ran in isolated sandboxes; no core code was modified. **Content checks recompute the scientific invariant from the materialized trials independently of the schema verdict** — schema-valid-but-nominal outcomes would be caught (see Go/No-Go and the T2R history).

Notation: ✅ verified by probe this audit · ✅✅ verified by committed test suite · ⚠️ partial/workaround · ❌ not expressible.

## Case 1 — Stroop ✅ (semantics) / ⚠️ (presentation)

- **Required mechanism**: word–ink congruency manipulation; correct answer = ink color; multi-attribute stimulus (word text × ink color).
- **Probe**: factors `congruency × ink(3)`; variables `inkw` (singleton pools per ink level) → `word` (congruent: `copy_from inkw`; incongruent: pool colors `exclude [inkw]`); `correct_from: "ink"`.
- **Result**: valid spec; **all 12 trials satisfy word==ink ⟺ congruent** (recomputed from materialized lines).
- **Limitation (presentation, Type 3)**: stimuli are text lines — the ink color renders as the *label* "ink: red", not a colored glyph. Semantic conflict is fully expressed and scored; the classic visual Stroop conflict is not renderable (no per-trial styling primitive).

## Case 2 — Flanker ✅✅ (probe)

- **Required mechanism**: target + flanking distractors; congruency; correct = target direction; relational content (flankers same-as vs different-from target).
- **Probe**: factors `congruency × target`; `tchar` (singleton pools), `flank` (congruent: `copy_from tchar`; incongruent: pool `exclude [tchar]`); template `"{var:flank}{var:flank}{var:tchar}{var:flank}{var:flank}"`; `correct_from: "target"`.
- **Result**: valid; **all 8 trials: middle char == target AND flank-congruency relation holds** (e.g. `>>>>>` / `<<><<`).
- **Note**: an earlier hypothesis "cross-factor conditional content is missing" is DISPROVEN — the single-factor-when + copy + exclude composition covers it. First discovery of this audit; no schema extension needed.

## Case 3 — N-back ❌ (Type 2 — cross-trial state) — design now exists, not implemented

- **Required mechanism**: stimulus at trial i must be constrained by the stimulus at trial i−n; correct answer = match/non-match with history.
- **Evidence of impossibility** (code, `src/experiment/stimulus.py`): `_materialize_variables(spec, trial, rng)` runs per trial with a fresh bindings dict and a per-trial isolated rng (`_trial_stimulus_rng(seed, index)`); `copy_from` resolves only earlier variables of the SAME trial. There is no slot, variable, or rule operand that can address another trial's content or response. Minimal reproduction: any spec where trial i's content must equal/relate to trial i−n's content — no legal schema construct exists (attempts fail at validation or silently degrade to independent draws).
- **Classification**: Type 2 (schema expressiveness). The historical proposal's sequence-plugin layer (§5.3 kind="sequence") was never implemented and is explicitly out of scope.
- **Revision (2026-10-24)**: a complete 2-back is now *designed* — `copy_from.lag` + lagged `exclude` entries + the head-block pattern, with the shuffle/block-boundary analysis and acceptance tests, in 04 §P1. Status: design only; the engine verdict above stands until implemented and tested.

## Case 4 — Go/No-Go ⚠️ (Type 2 primary + Type 3 secondary)

- **Required mechanism**: response deadline; on no-go trials, *withholding* is the correct action; inhibition scoring (correct rejections vs false alarms).
- **What works**: deadlines (stimulus_ms / phase duration) exist; timeout expiry records a `response` event with `value: null` (never dropped) — verified from the rendered engine (`collectChoice` + `computeCorrect`).
- **What fails**:
  1. **Schema**: `responses[].options` has no "no-response" value; correctness is defined over options only, so "withhold is correct on no-go" cannot be declared. (Type 2)
  2. **Runtime**: `computeCorrect` returns `false` for `value === null` unconditionally — a correctly withheld no-go trial is scored incorrect. (Type 3, but downstream of 1)
- **Minimal repro**: the rendered Go/No-Go probe (`data/.test-sandbox/audit/gonogo.html`, generated this audit) — a no-keypress trial logs `correct: false` even when the design intends withholding to be right.
- **Workaround (degrades the science)**: force a 2AFC ("go"/"stay" keys) — removes the inhibition construct. Not counted as support.
- **Revision (2026-10-24)**: the withhold primitive is redesigned to preserve `value: null` and change only the scoring rule (event log records behavior; correctness interprets it) — the four inhibition cells (hit / omission / commission / correct rejection) become unambiguous from the event log alone. Design and both-engine test plans in 04 §P2; **implemented and runtime-tested in Stage 1** (`test_withhold_option.py`): verdict upgraded from ⚠️ to ✅ for the inhibition-scoring semantics (deadlines, four-cell scoring, withheld marker; no stop-signal race-model claims).

## Case 5 — Task Switching ✅ (probe) / ⚠️ (sequence control)

- **Required mechanism**: task cue per trial; response mapping flips by task; correct answer = mapping(task, stimulus); switch-cost analysis.
- **Probe (design inversion)**: factors `task × answer`; `aword` (singleton pools per answer), `word` (task A: `copy_from aword`; task B: pool `exclude [aword]`); cue phase displays `{task}`, stimulus phase displays the word; `correct_from: "answer"`. **All 16 trials: mapping holds** (cue A: answer==word; cue B: answer!=word).
- **Key mappings note**: GameSpec key bindings are static — which is *fine* here: the cue-to-key remapping lives in the participant's head (that is the switching demand); the recorded answer is the pressed option and correctness follows `answer`.
- **Switch-cost analysis**: task sequence is logged per trial (`conditions.task`), so switch vs repeat trials are computable offline (probe: sequence ABBBAABB…, 8 switch points identifiable). ✔
- **Limitation**: no control over arbitrary task *sequences* (fixed alternation AABBAABB is inexpressible — only shuffle or declaration order); no cue-blocking (alternating runs) primitive. (Type 2, minor)

## Case 6 — Working Memory Delay ✅✅ (committed runtime tests)

- **Required mechanism**: encoding → retention interval → probe; response window only at probe; load manipulation with genuinely different content.
- **Evidence**: M3-A P1 node runtime tests (`tests/unit/experiment/test_stimulus_phases_p1.py`): phased playback, closed-window decoy keypresses ignored, one response per trial, RT anchored at probe onset, 8/8 content-driven accuracy; load maps (count 3 vs 5) verified in `test_stimulus_binding_p0.py`.
- **Limitation**: browser timing is approximate (documented); retention intervals are phase durations — fine for gameplay-grade, not ms-grade science. **No schema extension needed.**

## Case 7 — Adaptive Psychophysics ❌ (Type 2/3 — architectural)

- **Required mechanism**: subsequent stimulus parameters depend on the participant's response history (staircase etc.), with defined update and stopping rules.
- **Evidence**: trials are fully materialized at export (deterministic bundle); the HTML runtime consumes trials via a monotonic cursor with `trial_order` a controlled G8 invariant; no channel exists from runtime responses back to stimulus selection. Adaptation is structurally excluded by the generate-then-execute architecture (the anti-tampering design's direct consequence).
- **Classification**: Type 2 (no primitive) AND Type 3 (no runtime loop); root cause is architectural, deliberate (reproducibility/anti-tampering). Any support requires a new runtime-side procedure contract, not a field.

## Case 8 — Multi-factor Experiment ✅✅ (committed evidence)

- 2×2 with balance, weighted ratios, per-block counts, factor filtering: engine tests + golden files + T5 real-LLM run + offline eval scenarios. **No schema extension needed** (within-subject).

## Case 9 — Narrative-Based Cognitive Game ✅✅ (committed evidence, with T2R caveat)

- **Evidence**: Manor fixture (explore GameSpec v2, byte-reproducible HTML, runtime tests with `__CA_DEBUG__`), G8 validation (reachability, encounter coverage, invariants vs creative freedoms), measurement/game channel separation.
- **Verified invariants**: exploration order never changes conditions, trial count, order, or correct answers (runtime-tested); game events do not pollute measurement events.
- **Caveat (Type 1 history)**: the real-LLM T2R attempt produced a schema-valid but scientifically nominal design — an Agent-planning failure, not an engine gap (engine could express the required design; the model didn't produce it). Design-first prompt + P0/P1 tool docs added since; real-model re-test pending authorization.

## Matrix summary

| Case | Schema | Generated content | Rendering | Data recording | Verdict |
|---|---|---|---|---|---|
| Stroop | ✅ | ✅ (12/12 recomputed) | ⚠️ text-only ink | ✅ | Supported (semantic) — presentation-limited |
| Flanker | ✅ | ✅ (8/8 recomputed) | ✅ | ✅ | Supported end-to-end |
| N-back | ❌ | — | — | — | Not expressible (cross-trial) |
| Go/No-Go | ⚠️ no withhold option | ✅ | ⚠️ null→false | ✅ timeouts logged | Partial — inhibition scoring broken |
| Task Switching | ✅ (inversion) | ✅ (16/16) | ✅ | ✅ (+offline switch coding) | Supported; no sequence control |
| WM Delay | ✅ | ✅ | ✅✅ runtime-tested | ✅ | Supported end-to-end |
| Adaptive | ❌ | — | ❌ no runtime loop | — | Not expressible (architectural) |
| Multi-factor | ✅ | ✅✅ | ✅✅ | ✅✅ | Supported end-to-end |
| Narrative game | ✅ | ✅✅ | ✅✅ | ✅ | Supported end-to-end (engine); Agent-design caveat |
