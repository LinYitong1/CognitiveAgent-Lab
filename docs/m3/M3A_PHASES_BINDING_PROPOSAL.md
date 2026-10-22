# M3-A — Phased Stimuli, Intra-Trial Binding, Content-Driven Correctness
## Bounded design & feasibility analysis (NOT implemented; no API calls, no engine changes)

**Why**: T2R showed the engine can only express *nominal* sequential-memory tasks. For the
working-memory case the probe was a condition label and no sequence content existed, because
three capabilities are missing: (1) multi-phase presentation inside a trial, (2) binding and
reusing materialized content across phases, (3) correctness derived from that content instead
of from condition labels.

**Design goal**: generic composition primitives — the engine must never learn N-back, DMTS, or
any paradigm vocabulary. Anything a researcher/agent composes from these primitives is their
design; the engine only guarantees determinism, validation, and content-consistent scoring.

---

## 1. Reuse baseline (verified in code)

| Mechanism | Current state | Reused as-is |
|---|---|---|
| Per-trial random stream | `_trial_stimulus_rng(seed, index)` = `sha256("seed|index|stimulus")[:16]` | yes — no new randomness source |
| Slot rendering | `{pool:x}` = one `rng.choice`; `{factor}` = substitution, no draw | extended with `{var:...}`, same pass |
| `materialize_trials` | no-op for every unset v2 feature → **v1 byte-identical** | the backward-compat hinge: every new feature must be a no-op when unset |
| `Trial` model | index, block, factors, stimulus, derived, timing | + optional `correct` (additive) |
| Correctness path | both renderers compute `correct[resp] = factors[correct_from]` | they prefer `trial.correct[resp]` when present |
| Fingerprints | materialization runs *before* fingerprinting | content and scoring stay inside `trials_fingerprint` / `bundle_sha256` |
| validate-before-generate | tool layer guarantees validation precedes generation | unresolved references become validation errors, never runtime surprises |

---

## 2. Capability 1 — Multi-phase trial presentation

**Where**: measurement side (ExperimentSpec v2 → bundle), not GameSpec — phase timing is an
experimental variable and must be covered by the bundle fingerprint.

```jsonc
// stimulus_spec (additive: phases is None by default)
"phases": [
  {"name": "encoding",
   "lines": ["Memorize: {var:seq[0]} {var:seq[1]} {var:seq[2]}"],
   "duration_ms": 1500, "advance": "auto", "response_window": false},
  {"name": "retention",
   "lines": ["Hold"], "duration_ms": 900, "advance": "auto", "response_window": false},
  {"name": "probe",
   "lines": ["Probe: {var:probe}"], "duration_ms": null, "advance": "auto", "response_window": true}
]
```

Materialized trial:

```jsonc
"stimulus": {
  "lines": ["Memorize: K7 R2 M4", "Hold", "Probe: R2"],   // concatenation = today's shape
  "phases": [
    {"name": "encoding", "lines": ["Memorize: K7 R2 M4"], "duration_ms": 1500, "advance": "auto", "response_window": false},
    {"name": "retention", "lines": ["Hold"], "duration_ms": 900, "advance": "auto", "response_window": false},
    {"name": "probe", "lines": ["Probe: R2"], "duration_ms": null, "advance": "auto", "response_window": true}
  ]
}
```

Rules: `lines` stays the concatenation in phase order (existing consumers unchanged); a
renderer without phase support renders `lines` exactly as today. When `phases` is declared,
per-factor template levels are rejected (`V2_PHASE_TEMPLATE_CONFLICT`) so there is exactly one
line source — no ambiguity, no hidden merge.

---

## 3. Capability 2 — Intra-trial variables (binding & reference)

Four generic primitives; no paradigm semantics.

```jsonc
"variables": [
  {"name": "seq", "pool": "callsigns",
   "count": {"factor": "length", "levels": {"short": 2, "long": 5}}},
  {"name": "probe", "when": {"probe_type": "same"},
   "copy": {"var": "seq", "index": "any"}},
  {"name": "probe", "when": {"probe_type": "different"},
   "pool": "callsigns", "exclude": ["seq"]}
]
```

- `pool` + `count`: N i.i.d. draws from a declared pool (count may be a constant or a
  factor-level map → load manipulation becomes *real*, not a label)
- `exclude`: constrained draw — never returns a value already bound in the listed variables
- `copy` with `index` ("any" or integer): reference an earlier binding (reuse / transformation
  base); `index: "any"` is one additional bounded draw over the referenced variable's indices
- `when`: factor-level guard, so the same variable name can be bound differently per condition

**Draw order (documented, frozen when adopted)**: variables (declaration order) → phase
template selection → slot rendering left-to-right. `{var:seq[0]}` and `{factor}` substitute
without drawing; only `pool`/`exclude`/`copy index:"any"` consume draws. Referencing consumes
nothing, so reuse is free and reproducible.

---

## 4. Capability 3 — Content-driven correctness

```jsonc
"responses": [{"name": "match", "kind": "choice", "options": ["same", "different"],
  "correct_rule": {"op": "in",
                   "left":  {"var": "probe"},
                   "right": {"var": "seq"},
                   "true_option": "same", "false_option": "different"}}]
```

- Closed op set (task-agnostic relations over bound content): `eq`, `neq`, `in`
- Operands: `{"var": name}`, `{"var": name, "index": k}`, `{"literal": str}`, `{"factor": name}`
- Boolean result → mapped to an option via `true_option`/`false_option` (must exist in `options`)
- Evaluated during materialization → `trial.correct[response_name]`; renderers and
  `verify_bundle` consume it like today's `correct`, so scoring is no longer a label lookup
- `correct_from` remains supported; declaring both is `V2_RULE_CONFLICT`. Using `correct_from`
  stays legal (it is legitimate when correctness really is condition-defined), but the tool
  description should say plainly: *label-derived scoring cannot demonstrate a stimulus relation*
- Missing/unresolvable operands → `V2_RULE_REF_UNKNOWN` at validation (before any artifact)

---

## 5. Runtime & event log

- Both renderers: if `stimulus.phases` is present, play phases in order (duration, or wait for
  a keypress when `duration_ms` is null); the response window opens only on the phase flagged
  `response_window`; RT is anchored at that phase's onset. **Unphased trials: byte-identical
  output to today** (no `phases` key → code path untouched).
- Measurement events stay authoritative; phase onsets add one additive event
  (`trial_phase`: trial_index, phase, planned_duration_ms, t_epoch_ms) — provisional vocabulary,
  M2-E owns the final schema. Response events keep conditions/value/correct/rt_ms unchanged.
- Presentation timing in a browser remains approximate — this extension does **not** make
  timing research-grade; that limitation is unchanged and stays documented.

---

## 6. Files involved (all additive)

| File | Change |
|---|---|
| `src/experiment/schemas.py` | + `StimulusVariableSpec`, `StimulusPhaseSpec`, `CorrectRuleSpec`; + optional `StimulusSpec.variables`, `StimulusSpec.phases`, `ResponseVar.correct_rule`, `Trial.correct` |
| `src/experiment/stimulus.py` | validation (new `V2_VAR_*`, `V2_PHASE_*`, `V2_RULE_*` codes) + materialization: variables → phases → slots (`{var:...}`) → rule evaluation |
| `src/experiment/validation.py` | wire the new error codes (existing pattern) |
| `src/experiment/generation.py` | none (materialize already runs pre-fingerprint) |
| `src/experiment/export.py`, `verify.py` | none (trials serialize as-is; verification is fingerprint + re-derivation) |
| `src/experiment/game_render.py` (classic) | prefer `trial.correct`; phased playback |
| `src/experiment/explore_render.py` (v2 explore) | same for encounter trials |
| tests | new generic fixture, determinism/HASHSEED, negative cases, golden byte-identity |

---

## 7. Backward compatibility

Every new key is optional and `extra=forbid` stays: absent ⇒ no-op ⇒ identical code path and
identical canonical JSON ⇒ **v1 demo golden HTML, Manor fixture, T5 and T2R bundles and all
fingerprints unchanged**. Only specs that opt in get new behavior and new fingerprints.

## 8. Risks

1. **Draw-order coupling** — variables consume stream draws; any reordering changes content.
   Mitigated by freezing the order in the docstring and covering it with fingerprints.
2. **Constrained/exclusion draws can fail** (pool too small) — static validation checks pool
   size vs exclusion set; runtime uses bounded retries → `V2_VAR_DRAW_EXHAUSTED`.
3. **Rule complexity creep** — keep the op set closed (`eq`/`neq`/`in`); anything richer is a
   future milestone, never ad-hoc in the engine.
4. **Two renderers** must both implement phase playback — share one small helper (no framework).
5. **Confounds are not the engine's job** — e.g. unequal phase durations across conditions, cue
   leakage via variable reuse, or a retention interval too short to matter are design choices;
   the engine cannot detect them (see §10).

## 9. Minimal viable slices

- **P0 (research layer only, no renderer change)**: variables + references + content-driven
  correctness → the T2R failure is fixed at the *measurement* level (correctness follows
  content; load becomes real). Renderers still show all lines at once.
- **P1 (presentation)**: `phases` in the bundle + phased playback + response window in both
  renderers → the trial actually presents memorize → hold → probe.
- **P2 (measurement events)**: phase-onset events for RT anchoring (schema owned by M2-E).

## 10. Responsibilities (explicit)

| Layer | Owns | Does NOT own |
|---|---|---|
| Agent / spec author | composing factors, variables, phases, rules | deciding whether the design is scientifically sound |
| Engine | deterministic materialization, validation, content-consistent scoring, phase playback, event logging | judging construct validity, load calibration, timing adequacy, counterbalancing |
| Researcher | construct validity: does `count` map really load memory? is the retention interval meaningful? is scoring free of cue leakage? | engine internals |

Even with all three capabilities, "structurally valid" ≠ "experimentally valid" — the T2R
lesson. The engine can now prove *the answer key follows the materialized content*; only a
researcher can prove *the content instantiates the intended cognitive process*.

## 11. Minimal acceptance criteria

1. All 331 existing tests pass; v1 golden HTML + demo/Manor fingerprints byte-identical.
2. New generic fixture (sequence-match composed from the primitives, **zero WM vocabulary in
   engine code**): bundle reproducible across runs and `PYTHONHASHSEED`; `trial.correct`
   flips when the probe binding flips; `verify_bundle` green.
3. Phased trial renders phases in order; the response window opens only on the flagged phase;
   unphased specs render byte-identically to today.
4. Negative cases: unknown variable reference, unresolved rule operand, impossible exclusion
   draw, `phases` combined with per-factor templates → `V2_*` errors, no artifacts written.
5. Both renderers consume `trial.correct` without recomputing from labels when a rule exists.
