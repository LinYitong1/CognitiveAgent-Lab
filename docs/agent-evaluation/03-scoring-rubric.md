# 03 — E1 Scoring Rubric

Implementation: `scripts/e1_scorer.py` (scorer version **e1-scorer-v2**, frozen
for E1-B; regression-locked by `tests/unit/test_e1_scorer.py`). Verdicts:
**PASS / FAIL / INCONCLUSIVE / NOT_APPLICABLE**. INCONCLUSIVE is a first-class
verdict meaning "not machine-checkable for this design — researcher review
required"; it is never silently converted to a pass.

Two scorer entry points, run at different times on different data:

- **artifact scorer** (`score_artifacts`): D3/D4/D5/D6, on the run's bundle
  (+ rendered HTML), after the run completes;
- **run-record scorer** (`score_run`): D1/D2/D7/D8, on the runner's report
  JSON (the same format the historical T5/T2R reports used).

The final per-task report combines both and keeps them visibly separate
(principle 4 of 01: agent self-repair ≠ evaluator findings).

## D1 — Task completion (run record)

- **PASS**: loop status `completed` AND a `render_game` call returned ok AND
  the artifacts exist in the task sandbox (bundle JSON + HTML).
- **FAIL**: anything else (budget-stop, protocol error, no render, missing
  artifacts). The failure class from the run report is quoted verbatim
  (e.g. `budget-stop (request cap reached; NOT a model failure)`).
- **INCONCLUSIVE / N/A**: not used.

## D2 — Tool-call correctness (run record)

- **PASS**: every tool call in the run resolved ok (valid tool name, valid
  arguments, no policy refusal). Domain-level validation failures returned
  inside ok=True payloads (structured `errors`) do NOT fail D2 — they are the
  normal repair loop and feed D7.
- **FAIL**: any not-ok tool call (unknown tool, invalid arguments,
  sandbox/policy refusal).

## D3 — Artifact validity (artifact scorer)

- **PASS**: `verify_bundle` passes (generator-free recomputation of both
  fingerprints) and the HTML carries the integrity anchors
  (BUNDLE_CANONICAL/TRIALS_CANONICAL + the embedded SHA-256 check).
- **FAIL**: any of the above missing.
- **N/A**: no HTML artifact (run did not reach render) — recorded with the
  D1 failure, not scored again here.

## D4 — Real stimulus manipulation (artifact scorer; the T2R detector)

Verdict per the task's declared requirements (02's briefs → the task registry
in the scorer):

1. **Label-masking heuristic** (all content tasks): for each factor, mask
   every occurrence of its level names in the materialized lines and compare
   the masked line-sets across levels. Identical masked sets = nominal
   manipulation → FAIL with the T2R signature message. At least one genuinely
   differing factor is required where the brief demands manipulation.
   - Brief 1 (retest): no content manipulation demanded → this sub-check is
     not applied (NOT_APPLICABLE), because the displayed condition IS the
     task.
2. **Phased presentation** (briefs 3/4/5): all trials phased, at least one
   response window.
3. **Load variation** (briefs 3/5): some factor's levels must differ in the
   token count of the non-window (encoding) phase content — real load, not
   labels.
4. **Cue variation** (brief 4): the first phase's content must differ by some
   factor (a cue that does not signal the task is no cue).
5. **Factor count** (briefs 2/4/5): the brief's design needs ≥2 factors.

- **PASS**: all required sub-checks satisfied.
- **FAIL**: any required sub-check violated (each problem listed with its
  evidence).
- **INCONCLUSIVE**: no materialized stimulus lines to compare at all.
- Known heuristic limits (documented, accepted): timing-only manipulations
  are a false-positive risk; coincidental content differences are a
  false-negative risk; neither occurs in the five E1 briefs' designs.

## D5 — Answer recomputation (artifact scorer)

1. **Key presence**: every trial carries an answer key (content-derived or
   `correct_from`).
2. **correct_from exactness**: key == the trial's level of the referenced
   factor, every trial.
3. **Content→key determinism**: identical displayed stimulus content must map
   to identical keys (the answer must be derivable from what the participant
   sees — catches ambiguous designs).
4. **Probe-membership invariant** (briefs 3/5): with template decoration words
   removed (tokens common to every trial of a phase kind), the relation
   "probe token ∈ memorized tokens" must be a CONSISTENT function of the key;
   when the spec declares a `correct_rule` with op in/eq, the observed mapping
   direction must match the declared true/false_option (catches inverted
   keys).
5. **Task-contingent mapping** (brief 4): within each cued task, the
   displayed word must map consistently to the answer, and the mapping must
   DIFFER between tasks (else no switching demand exists in the content).

- **PASS** / **FAIL** per the above; **INCONCLUSIVE** when the design is
  structurally outside the recognizable families (e.g. an unusual stimulus
  grammar) — researcher review.

## D6 — HTML interaction and event recording (artifact scorer)

A generic node driver plays the produced classic game (ready screen → press
the first bound key of each response through all trials → end screen) and
checks the event log: trial_start count == total trials, response count ==
trials × responses, every response event carries value/correct/rt_ms/
conditions, engine self-check OK.

- **PASS**: all structural checks hold on a fully automated playthrough.
- **FAIL**: driver crashed, event counts wrong, or fields missing.
- **INCONCLUSIVE**: explore-layout games (the generic driver does not
  navigate rooms; brief 5's explore renders get manual play review) or node
  unavailable.

This dimension is an INTERACTION/RECORDING check, not a scientific one —
scientific content is D4/D5.

## D7 — Self-repair from tool feedback (run record)

- **PASS**: the run's own tool feedback shows validation errors were seen and
  the run ultimately completed (e.g. validate_game repair rounds → final
  success). Reads only the run's tool-call history — never the evaluator's
  post-hoc findings.
- **FAIL**: errors were seen but the run never completed, or the run
  completed without ever validating (no repair evidence AND no D2 failures —
  first-try success records as PASS via the no-errors path only when D2 shows
  zero failed validations; otherwise FAIL records "did not complete").
- **N/A**: no tool calls at all.

## D8 — Efficiency (run record)

- **PASS**: the provider's usage is reported: model calls, tool calls, wall
  time, tokens (input/output-billable per the Gemini total−prompt rule),
  estimated cost. (Verdict PASS = "measured and within the per-task budget";
  the raw numbers are always quoted.)
- **N/A**: provider reported no usage — numbers are never fabricated.

## Task-level acceptance invariants (E1-B preflight addition)

On top of the generic D1–D8 checks, each brief now carries INDEPENDENT
acceptance conditions (`check_task_invariants` in the scorer, merged into the
D4/D5 verdicts; reference designs must pass BOTH generic and task checks, and
each has adversarial schema-valid-but-brief-violating counterparts that must
FAIL — see 04). Nothing below relaxes a generic check.

**Flanker (brief 2)**
- every trial displays EXACTLY five arrow characters; the middle one is the
  decision target;
- flanks uniformly equal (congruent) or uniformly opposite (incongruent) to
  the middle arrow — mixed flanks FAIL;
- congruency and middle direction both occur and are STRICTLY balanced;
- a declared factor's levels must partition trials exactly onto the
  content-computed congruency classes (the condition is analyzable from the log);
- the middle arrow's direction must determine the key (one direction → one key,
  the two directions → different keys).

**Working memory (brief 3)**
- the encoding set contains EXACTLY 2 or 4 memorized words per trial
  (decoration words — tokens constant across trials — excluded);
- the probe phase shows EXACTLY one content word (the study set must never be
  on screen with the probe → simultaneous presentation FAILs);
- probe membership (recomputed from content) determines the key, with distinct
  keys for in-set vs novel;
- load × membership fully crossed and balanced;
- a declared factor must align with the computed load (per-load analysis
  possible from the logged conditions).

**Task switching (brief 4)**
- the cue (first phase, non-window, before the word) maps one-to-one onto a
  logged task factor;
- the stimulus words are literally "same"/"different" (the brief's vocabulary);
- within each task, word→key is a consistent function and both words are
  realized;
- the two tasks' mappings must be the REQUIRED INVERSION of each other (task B
  answers "yes" exactly where task A answers "no") — merely "two different
  mappings" is NOT accepted;
- when the options are literally yes/no, the direction must match the brief
  (task A: "same" → "yes"); non-yes/no options → INCONCLUSIVE note on the
  literal direction (inversion still enforced);
- tasks and answers strictly balanced.

**T2R regression (brief 5)**
- computed sequence-length classes (encoding sizes) distinct, aligned with a
  logged factor, membership determines the key, length × membership balanced;
- from the rendered HTML's embedded PLAN: ≥ 3 explorable rooms, encounter
  objects cover the trial count, s/d response keys present, explore layout
  (a classic single-screen render FAILs the brief);
- runtime exploration-order invariance: guaranteed by the engine's monotonic
  cursor + declared controlled_invariants, but NOT re-verified by an automated
  explore-runtime driver → explicit INCONCLUSIVE + MANUAL ACCEPTANCE marker.

**T5 retest (brief 1)**
- exactly 10 trials, the two colors strictly balanced;
- displayed content must actually differ between the colors (anti-nominal);
- evidence chain stated explicitly: the event log records
  conditions/value/correct/rt_ms — NOT the stimulus text; "what was shown" is
  reconstructed from the bundle trials (v2 lines, or the factor display for
  v1 specs), which the HTML embeds and self-verifies via
  BUNDLE_CANONICAL/TRIALS_CANONICAL + SHA-256. No claim is made that the log
  itself records the stimulus.

## Researcher-review items (explicitly NOT automated)

Construct validity of the manipulation; load/retention calibration; cue
leakage beyond the label-masking detector; counterbalancing adequacy;
anything the scorer marked INCONCLUSIVE.
