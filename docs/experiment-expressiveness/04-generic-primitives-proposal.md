# 04 — Generic Primitives Proposal (Experiment Expressiveness Audit — REVISED)

Revision 2026-10-24 (design-only round; no code changed). This revision responds to the
targeted design review: (a) P1 is now proven against a **complete 2-back task** with a
minimal supplement (`lagged exclude`) the original proposal lacked; (b) P2 is redesigned to
**preserve `response.value = null`** and change only the scoring rule; (c) P3 is explicitly
scoped to **block-level** timing override with byte-drift proofs; (d) a no-schema-change plan
for composition-recipe tool documentation is added; (e) the research data layer is specified
separately (06) and explicitly out of ExperimentSpec scope.

**Implementation status (Stage 1, 2026-10-24)**: P2 (withhold, null-preserving form) and P3
(block timing override) are **IMPLEMENTED and runtime-tested** — four Go/No-Go cells verified
on both engines via node DOM-stub tests, missing-answer-key edge covered, old-spec regression
byte-identical, all six quality gates green (434 tests). D1 (composition recipes in the tool
docs + offline content-consistency tests) is **IMPLEMENTED** (config field description +
`test_composition_recipe.py` + eval scenario `s9_relational_content`). P1 (cross-trial lag)
remains **DESIGN ONLY** — explicitly deferred, not implemented this stage.

Status taxonomy used throughout this document:

- **[VERIFIED]** — fact established by committed code/tests or by an audit probe this session.
- **[DESIGN]** — design inference; sound by construction but not yet implemented or tested.
- **[NEEDS-TEST]** — must be proven by the acceptance tests before the primitive ships.

Only gaps with a **demonstrated, reproducible expression failure** (02/03) earn a primitive.
Each proposal answers the mandated questions: real failure · why the current schema can't ·
which experiment classes benefit · determinism impact · verifiability · downstream effects ·
simpler alternatives.

---

## P1 — Cross-trial content reference: `copy_from.lag` + `exclude` lag entries — revised

**Real failure** [VERIFIED]: N-back and any sequence-dependent design cannot express "relate
to the stimulus n trials back" (02 Case 3; per-trial binding isolation is structural:
`stimulus.py::_materialize_variables` rebuilds bindings per trial).

### P1.1 What the original proposal got wrong (and why a supplement is required)

The original proposal (`copy_from.lag` alone) is **insufficient for a full 2-back**. A 2-back
needs *both* directions of the relation:

- match trial: current stimulus **must equal** the stimulus 2 trials back (lagged copy ✓);
- non-match trial: current stimulus **must differ** from the stimulus 2 trials back.

The second direction needs a **lagged exclusion** ("draw from the pool, excluding the value
bound 2 trials ago"). Today's `exclude` accepts only same-trial earlier variable names
[VERIFIED: `V2_VAR_REF_UNKNOWN` on any non-earlier name], so non-match trials can only be
*unsampled* random draws that **coincidentally equal** the 2-back item — a label/content
divergence the T2R lesson forbids us to accept silently.

### P1.2 Revised minimal design

Two additive changes, both paradigm-neutral (no task vocabulary anywhere):

**(a) `VariableCopySpec.lag: int | None = None`**

```jsonc
{"var": "cur", "index": "any", "lag": 2}
// lag null or 0 = today's semantics; lag n > 0 resolves to the binding of
// "cur" at trial (i - n) in the FINAL materialized order
```

**(b) `exclude` entries become `str | {var: str, lag: int}`**

```jsonc
"exclude": ["other_var", {"var": "cur", "lag": 2}]
// a plain string keeps today's exact semantics (lag 0);
// an object excludes all elements of the referenced variable's binding at trial (i - lag)
```

Semantics and scope decisions (each answers a review question):

1. **Resolution scope is GLOBAL (final materialized trial order), crossing block
   boundaries.** [VERIFIED code fact] `generate_trials` performs the per-block shuffle
   during trial-list construction and only then calls `materialize_trials(spec, trials)`
   (`generation.py` steps 7→8): materialization is a single forward pass over the final
   list. Therefore:
   - **Trial reshuffling does not break history references.** Lag reads the binding of the
     trial that *will actually be presented* at position i−n. A different seed produces a
     different order and therefore different content — deterministic, fingerprint-covered,
     and scientifically the *intended* semantics (the participant's sequence is what the
     relation is about).
   - **Block boundaries do not break references either.** Global indices are continuous
     across blocks (`Trial.index = len(trials)`); a trial at the head of block 2 legitimately
     references block 1's tail — stimuli the participant did see. A designer who wants the
     n-back window to **restart** per block expresses it with the head-block pattern below
     (first n trials of each block forced to the non-match condition); the cross-boundary
     reference then exists but is provably irrelevant to the answer.
2. **`lag > 0` copies may self-reference and forward-reference.** Today's "source must be
   declared earlier" rule exists to guarantee same-trial termination [VERIFIED: docstring of
   `_count_choices`]. A `lag > 0` copy never reads the current trial, so it cannot create a
   same-trial cycle; termination is trivial (strictly earlier trial index). The
   earlier-declaration rule stays binding for `lag = 0` only.
3. **Out-of-range lagged COPY = static validation error (`V2_VAR_LAG_SCOPE`).** A copy must
   produce a value; when `i − lag < 0` there is none. This is checkable **at validation
   time, before generation**, because block start indices are deterministic:
   `start(block_k) = Σ trial_count(block_1..k-1)`, independent of shuffle. Rule: *every
   block whose trials can satisfy the copy binding's guard must start at index ≥ lag*,
   where "can satisfy" = the guard's factor/level is compatible with the block's
   `factor_filter` (or unfiltered). An **unconditional** `lag > 0` copy is therefore always
   rejected (it applies at index 0 < lag) — fail-closed is correct: every sequence design
   has a head, and the schema demands the designer make the head explicit.
4. **Out-of-range lagged EXCLUDE = no-op** (excludes nothing). Asymmetric with (3) by
   design: a copy must yield a value, but an exclusion set may legitimately be empty. This
   is what lets non-match head trials (no 2-back exists) draw freely.
5. **Lagged references consume no randomness** (plain copy semantics), and lagged excludes
   only filter the candidate set — the frozen draw order (variables in declaration order →
   line source → slots left-to-right) is unchanged. A spec that does not opt in therefore
   consumes the identical rng stream as today [DESIGN, NEEDS-TEST via byte-identity].
6. **Lagged references read generated stimulus bindings only** — never responses, never
   runtime state. Adaptive/feedback designs remain out of scope (rejected below).

### P1.3 The complete 2-back, expressed (existence proof)

Every construct below is generic schema vocabulary; nothing names a task.

```jsonc
{
  "schema_version": 2,
  "name": "sequence-reference-demo", "seed": 11,
  "factors": [{"name": "match", "levels": [{"name": "yes"}, {"name": "no"}]}],
  "blocks": [
    {"name": "head", "trial_count": 2, "factor_filter": {"match": ["no"]}},
    {"name": "main", "trial_count": 28}
  ],
  "constraints": {"ratios": [{"factor": "match", "ratios": {"yes": 0.3, "no": 0.7}}]},
  "responses": [{"name": "answer", "kind": "choice",
                 "options": ["yes", "no"], "correct_from": "match"}],
  "stimulus_spec": {
    "pools": {"letters": ["B", "C", "D", "F", "H", "J"]},
    "variables": [
      {"name": "cur", "when": {"match": "yes"},
       "copy_from": {"var": "cur", "lag": 2}},
      {"name": "cur", "when": {"match": "no"},
       "pool": "letters", "exclude": [{"var": "cur", "lag": 2}]}
    ],
    "phases": [{"name": "stim", "lines": ["{var:cur}"],
                "duration_ms": 2000, "response_window": true}]
  }
}
```

How each 2-back requirement is met:

| Requirement | Mechanism | Status |
|---|---|---|
| match/non-match conditions | factor `match` with ratio-controlled allocation (30/70) | [VERIFIED] existing engine (largest remainder; per-block rounding may warn `RATIO_ROUNDED` — expected, documented) |
| prior-trial reference | `copy_from {var: cur, lag: 2}` self-reference on `match=yes` | [DESIGN] P1.2(a) |
| non-match must differ | `exclude [{var: cur, lag: 2}]` on `match=no` | [DESIGN] P1.2(b) |
| match ratio | `constraints.ratios` (head block excluded from the ratio population by `factor_filter`) | [VERIFIED] existing engine |
| correct answer | `correct_from: "match"` — the key follows the condition label; the **content invariant** is guaranteed structurally by (b)+(a) and verified by recomputation (below) | [DESIGN] |
| cross-trial determinism | single forward pass over the final order; per-trial digest rng streams; no new ordering | [VERIFIED] algorithm shape; [NEEDS-TEST] byte-identity + PYTHONHASHSEED sweep |
| head trials (no 2-back exists) | head block `factor_filter {match: [no]}` forces the first 2 trials to non-match — the standard warm-up segment, using **existing schema only** | [DESIGN] |

The scientific invariant the acceptance tests must recompute from materialized lines,
independently of the schema verdict (audit discipline):

```
∀ i ≥ 2:  (cur_i == cur_{i-2}) ⟺ match_i == "yes"
∀ i < 2:  match_i == "no"          (head block filter)
```

A binding flip test (change the head seed → downstream match-trial letters flip, keys still
hold) proves the reference is genuinely cross-trial, not coincidental. `correct_from` is
acceptable here (rather than `correct_rule`) because content is *derived from* the condition
by construction, with structural guarantees — but this reasoning MUST be backed by the
recomputation test, never trusted from schema validity alone (T2R lesson).

**Deliberately rejected for minimality**: lag on `correct_rule` operands (label key +
recomputable invariant suffices; revisit only if a demonstrated asymmetric case appears).

### P1.4 Validation additions (closed set)

- `V2_VAR_LAG_BOUNDS` — `lag < 0`, or non-integer.
- `V2_VAR_LAG_SCOPE` — out-of-range risk: a `lag > 0` copy binding whose guard can be
  satisfied in a block starting at index < lag; suggestion names the offending block, the
  computed start index, and the head-block pattern.
- `V2_VAR_LAG_SOURCE_COVERAGE` — `lag > 0` (copy or exclude) requires the source variable
  to bind on EVERY trial (unconditional or full-coverage guards) — otherwise the historical
  binding may be missing.
- Existing checks extended, not replaced: `V2_VAR_REF_UNKNOWN` still applies to names;
  `_count_choices`/pool-feasibility bounds treat a lagged exclude like a same-trial exclude
  of the source's max-count elements (sound upper bound).

### P1.5 Determinism, compatibility, downstream

- **Determinism**: unchanged algorithm class — deterministic forward pass; lag reads
  already-materialized state; fully covered by `trials_fingerprint` [DESIGN; NEEDS-TEST:
  golden bundle + regeneration byte-identity].
- **Zero-byte-drift obligations** [NEEDS-TEST]: `spec_dump` must strip `copy_from.lag`
  when `None` **or `0`** (lag 0 is today's semantics; today's dumps already carry
  `"index": null`, so an unstripped `"lag": null` would shift every existing
  copy_from fingerprint), and object-form exclude entries only ever appear when written.
  No `trial_dump` change (lagged content flows through `lines`/`correct` as ordinary
  content).
- **Downstream**: GameSpec / HTML / runtime / event schema **untouched** — the relation is
  fully resolved at materialization and travels as content [VERIFIED code fact: renderers
  consume `trial.stimulus.lines` verbatim].
- **Classes enabled**: N-back (any n), running-span probes, negative priming,
  sequence-learning manipulations, lag-repetition designs — all with zero paradigm
  hardcoding.
- **Simpler alternative**: none found — sequence plugins (historical proposal §5.3) are
  strictly heavier; hand-enumerating sequences in factor levels breaks balance, ratio
  control, and response semantics.

### P1.6 Acceptance tests (implementation gate)

1. 2-back fixture above: recompute the invariant from `lines` for every trial (must hold
   30/30); head-block filter asserted; match ratio within allocation rounding.
2. Binding-flip: perturb the seed → recomputed invariant still holds for the new bundle
   (proves cross-trial dependence, not fixture luck).
3. `PYTHONHASHSEED` sweep: identical `trials_fingerprint`.
4. Negative validation: unconditional lag>0 copy (`V2_VAR_LAG_SCOPE`); lag exceeding head
   block size; lagged source without full coverage (`V2_VAR_LAG_SOURCE_COVERAGE`);
   `lag: -1` (`V2_VAR_LAG_BOUNDS`); lagged exclude referencing an unbound-at-i−n source.
5. Byte-drift: every existing golden/fingerprint test passes unchanged (402-test suite).
6. One end-to-end golden HTML for the 2-back fixture (recommended, pins the full chain).

---

## P2 — Withhold option, redesigned: keep `value: null`, change only the scoring rule

**Real failure** [VERIFIED]: Go/No-Go inhibition scoring — withholding is unrepresentable;
both engines' `computeCorrect` returns `false` for `value === null` unconditionally
(`game_render.py`, `explore_render.py`).

### P2.1 Why the original design was changed

The original proposal substituted a **string** (`withhold_option`) for the non-response at
deadline expiry. The review correctly objects: an analyst reading `value: "<withhold>"`
cannot distinguish "participant deliberately withheld" from "participant produced the value
by some other path" without re-deriving engine rules; and the substitution invents a value
the participant never produced — the event should record **what happened** (no keypress),
and **scoring** should interpret it. Revised principle: *the event log records behavior;
correctness interprets it.*

### P2.2 Revised design

**Schema** — `responses[].withhold_option: str | None = None` (v2-style optional field on
the response):

- declares that *no response* is a meaningful answer for this response, and names the
  **answer-key value** that represents it (e.g. `"withhold"`);
- must NOT collide with `options` (new check `V2_WITHHOLD_COLLISION`); `kind = "choice"`
  only;
- `correct_rule.true_option / false_option` may now be **either** a declared option **or**
  the response's `withhold_option` (extends `V2_RULE_OPTION_UNKNOWN` — the key can now say
  "withhold is correct on this trial").

**Answer key for Go/No-Go** (design inversion + rule):

```jsonc
"responses": [{"name": "press", "kind": "choice", "options": ["go"],
  "withhold_option": "withhold",
  "correct_rule": {"op": "eq", "left": {"factor": "trial_type"},
                   "right": {"literal": "no_go"},
                   "true_option": "withhold", "false_option": "go"}}]
// go trial:   key = "go"      no_go trial: key = "withhold"
```

**Runtime scoring (both engines, single change point each)**:

```js
// today:  if (value === null) { return false; }  return value === expected;
// revised:
return value === expected ||
       (value === null && expected === resp.withhold_option);
```

`value` stays `null` on deadline expiry. The second clause can fire only when the response
declares `withhold_option` and the key is the withhold value — for every existing spec the
behavior is **bit-for-bit today's** (`expected` is always a declared option string, `null`
never equals it) [DESIGN; NEEDS-TEST: old-spec runtime regression].

**Event data — the four Go/No-Go cells, unambiguous from the event log alone**:

| Trial (from `conditions`) | Behavior (`value`) | `correct` | Scoring name |
|---|---|---|---|
| go | `"go"` | true | hit |
| go | `null` | false | **omission** |
| no_go | `"go"` | false | **commission error** (false alarm) |
| no_go | `null` | true | **correct rejection** |

Every cell is a unique `(conditions, value, correct)` triple — no bundle lookup required for
basic QC. **Timeout vs missed** [VERIFIED code facts]: a deadline expiry logs
`value: null` with a measured `rt_ms` (≈ deadline); a response with no window phase logs
`value: null, rt_ms: null`. These never collide. One additive marker is proposed:
`withheld: true` on a deadline-expiry response event **only when the response declares
`withhold_option`** — gated so every existing spec's event stream is shape-identical
[DESIGN]. (Note for the docs: a deliberate withhold and an attentional lapse both present
as `null` — indistinguishable in ANY event log; that is inherent to the paradigm, not a
data-contract defect.)

**Feedback**: today `value === null` shows "missed". Revised: when the response declares
`withhold_option`, a null value is a real answer and shows "correct"/"incorrect"; "missed"
remains for non-withhold responses. Gated identically.

### P2.3 Compatibility obligations [NEEDS-TEST]

- `spec_dump`: strip `withhold_option` from responses when `None` (mirror of the
  `correct_rule` strip rule) — otherwise every existing response dict gains a `"withhold_option": null`
  key and all config fingerprints shift.
- `build_run_plan` / `build_explore_plan`: include `withhold_option` in the plan's response
  projection **only when present** — the plan JSON is embedded in the HTML, so an
  unconditional key would break every golden HTML for old specs.
- Runtime additions (`withheld` marker, feedback branch) gated on `resp.withhold_option`
  being declared — old-spec event streams and screens unchanged.

### P2.4 Test plan — classic and explore runtimes

Node DOM-stub tests, both engines (classic via `runTrial`; explore via `__CA_DEBUG__`
events, `channel: "measurement"`):

1. **Correct rejection** — no-go trial, no keypress: `value: null`, `correct: true`,
   `withheld: true`, counted in `correctApplicable` (explore: assertion on `game_end`).
2. **Omission** — go trial, no keypress: `value: null`, `correct: false`.
3. **Commission** — no-go trial, keypress "go": `value: "go"`, `correct: false`.
4. **Hit** — go trial, keypress "go": `correct: true`.
5. **Old-spec regression** — identical spec without `withhold_option`: timeout event has
   `correct: false`, **no** `withheld` key, feedback "missed"; golden HTML byte-identical.
6. **Phased variant (classic + explore)** — withhold with a `response_window` phase
   deadline (resolves U-2 partially); decoy keypresses outside the window still ignored.
7. **Validation units** — option collision (`V2_WITHHOLD_COLLISION`); rule options may be
  the withhold value; non-choice kind rejected; correct_from + withhold interaction
  (correct_from cannot produce the withhold value — documented, not an error).
8. **Cross-check** — offline reconciliation of the four cells from the downloaded event
   log alone (conditions + value + correct), no bundle access.

**Classes enabled**: Go/No-Go, recognition-with-pass, yes/no-with-abstain. **Explicitly NOT
claimed**: stop-signal race-model timing (needs a second, competing response channel — out
of scope).

---

## P3 — Per-BLOCK timing override: `BlockSpec.timing` — scope-clarified

**Real failure** [VERIFIED]: `TimingSpec` is global; `BlockSpec` has no timing; practice
blocks cannot shorten deadlines (01 §7).

### P3.1 Scope statement (the review's demand)

**This primitive supports BLOCK-level timing override only.** It does **not** claim to solve
condition-level timing variation (e.g. a shorter deadline on incongruent trials only) — that
remains open and is re-listed as a residual gap (03 T2-3-residual). Documented workaround
within existing semantics: restructure conditions into blocks (one condition per block via
`factor_filter`, each with its own timing) — viable but changes the randomization structure
(no within-block mixing), and the docs must say so.

### P3.2 Design

- `BlockSpec.timing: TimingSpec | None = None`.
- Semantics: **whole-object replacement** — when present, every trial of that block carries
  the block timing; when absent, the spec-level timing (today's behavior). Because
  `TimingSpec` fields have defaults, a partial override silently resets unspecified fields
  to defaults; the replacement semantics are documented, and validation emits an
  informational **warning** (`BLOCK_TIMING_OVERRIDE`) whenever a block overrides timing,
  reminding the author to set all three fields deliberately [DESIGN — warning is optional,
  cheapest anti-footgun].
- Materialization: `Trial.timing = block.timing if present else spec.timing` — one line in
  `generate_trials`'s trial construction; **zero engine change** [VERIFIED: both runtimes
  already consume per-trial `trial.timing` via `step.timing` / `trial.timing`].

### P3.3 Zero-drift proof obligations [NEEDS-TEST]

Default-absent `BlockSpec.timing` would add `"timing": null` to every block in
`spec.model_dump()` — and blocks are **v1 surface**, so this touches every existing spec
unless stripped. Obligations:

1. `spec_dump`: strip `timing` from each block dict when `None` → `config_fingerprint`
   unchanged for every existing spec.
2. Trials of non-overriding specs carry the spec timing exactly as today →
   `trials_fingerprint` unchanged.
3. Run plans embed per-trial timing from the bundle and block *names* only → plan JSON
   byte-identical → **golden HTML byte-identical** for every committed fixture.
4. Opt-in specs get new fingerprints (expected; recorded reason in the golden update).

### P3.4 Acceptance tests

Practice block (short `stimulus_ms`) + main block (long): per-trial `timing` asserted from
the bundle; runtime deadline behavior via one node test per engine (key accepted before the
short deadline, timeout enforced); all four zero-drift obligations above; negative: none
(shape-only field) — the warning path tested in validation units.

---

## D1 — Composition-recipe tool documentation (NO schema change) — IMPLEMENTED (Stage 1)

**Real failure** [VERIFIED this audit]: the `when` + singleton-pool + `copy_from` +
`exclude` composition that unlocks Flanker/semantic-Stroop/task-switching (02 Cases 1/2/5)
required deliberate search to discover; tool docs document the primitives but not the
*composition* (03 T1-2). This is the highest value-per-risk item (05 Q7).

**Implemented (Stage 1)**: the recipes were appended to the `config` field description of
`validate_experiment` (ASCII, paradigm-name-free: relational content via singleton pools +
copy_from/exclude; design inversion for conditional correctness; count maps for real content
differences; withhold scoring), pinned by tests in `test_tool_description_example.py` (ASCII
assertion extended to the field description; ToolSpec-level budget unchanged). Offline
content-consistency evidence: `test_composition_recipe.py` recomputes the relational
invariant from materialized lines (center↔target mapping, flank↔congruency relation,
balance, seed-flip); eval scenario `s9_relational_content` in `scripts/agent_eval.py`
drives the pattern through the real AgentLoop (L3 verified, L4 all-pass).

**Deferred**: whether real LLMs spontaneously USE the documented recipes — resolvable only
by the authorized real-model re-run (05 Q7 gate).

**Constraints** [VERIFIED]: `validate_experiment` ToolSpec description — pure ASCII, soft
≤700 / hard ≤900 chars (tested); the example `_SPEC_EXAMPLE_JSON` is frozen and
test-pinned; the v2 documentation surface is the `config` **field** description of the
input model (no length test, but same ASCII discipline applies).

**Minimal-change plan**:

1. Append a compact recipe block (~450 ASCII chars) to the `config` field description,
   pattern-level, paradigm-name-free:

   > "Composition recipes (v2): (1) relational content across factors (e.g. congruent vs
   > incongruent): bind a singleton pool per level of the content factor guarded by
   > when={factor:level}; the related side reuses it via copy_from, the unrelated side
   > draws from the full pool with exclude=[that variable]. (2) conditional correctness:
   > sample the intended answer as a factor, derive stimulus content from it via
   > when-guards, and set correct_from to that factor. (3) different content per condition:
   > count={factor,levels} makes levels differ in real materialized content, not labels."

2. **Honest-docs rule**: recipes may only describe implemented features. The lag recipe
   (sequence-dependent content) is appended **when P1 lands**, not before.
3. Behavioral acceptance (code, deferred to implementation): one offline eval scenario in
   `scripts/agent_eval.py` (a relational-content brief in the Flanker shape, FakeLLM) whose
   success criterion is a spec that passes the content-recomputation check — plus the
   existing L4 label-masking heuristic. The real-LLM verification remains gated on the
   authorized re-run (05 Q7: do not expand before that re-run).
4. Tests: extend the ASCII assertion to the field description (cheap guard); no other test
   changes (description content itself is not pinned beyond the example constant).

## Research data layer — moved out of this document

Participant / session / event-envelope / timestamp / persistence contracts are now specified
in **06-research-data-layer.md**. ExperimentSpec is not modified: a bundle is one
within-subject condition set by design (03 T2-4; 05 Q8).

## Considered and rejected (unchanged, with revision notes)

- **Conditional/multi-branch correctness rules** — the design-inversion pattern stays the
  answer; now also carries the Go/No-Go key recipe (P2.2). Revisit only on a demonstrated
  asymmetric case.
- **Adaptive procedures** — unchanged rejection (architectural conflict with
  generate-then-execute).
- **Participant envelope in ExperimentSpec** — wrong layer; now fully specified at 06.
- **Per-trial stimulus styling** — unchanged (T3-1, deferred).
- **Sequence patterns (`sequence_pattern`)** — note: P1's lag covers *content dependence*;
  controlled *transition schedules* (fixed alternation) remain uncovered and stay a low
  priority with offline switch-coding as the workaround.
- **Lag on `correct_rule` operands** — rejected for minimality (P1.3); label key +
  structural invariant + recomputation test suffices.

## Compatibility summary

All changes are optional, default-absent, and follow the zero-byte-drift rule with these
**new strip obligations** (the concrete proof list for implementation):
`copy_from.lag` (None or 0) · object-form `exclude` entries (only when written) ·
`responses[].withhold_option` (None) · `BlockSpec.timing` (None) · conditional plan-projection
keys (`withhold_option` in run plans). Each carries the same proof obligations as the P0/P1
changes: strip-in-`spec_dump`/`trial_dump`, ASCII/length budgets for tool docs, negative
validation cases, engine-vocabulary guard.
