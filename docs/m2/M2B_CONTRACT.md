# M2-B — Final D-M2-1 / D-M2-4 Contract + Implementation Checklist

- **Status**: contract for approval. No source code modified; nothing committed or pushed.
- **Scope of this document**: the definitive D-M2-1 (v2 schema policy) and D-M2-4 (minimal-core scope) contract resulting from the focused review. D-M2-2/3/5/6 remain **provisional** until their respective milestones; approval of M2-B is **not** approval of M2-C..F. R2 block timing / `response_window_ms` stays deferred to M2-F (as proposed).
- **Verified implementation facts this contract is built on** (source-confirmed today):
  - `config_fingerprint = sha256_hex(canonical_json(spec.model_dump()))` — computed identically at **two** call sites: `generation.py:225`, `validation.py:418`.
  - The exported bundle embeds `"spec": spec.model_dump()` (`export.py:58`) and `bundle_sha256` covers it (`export.py:75`).
  - **`model_dump()` fills defaults** → adding fields to `ExperimentSpec` naively would emit `stimulus_spec: null`-style keys *for v1 specs too*, silently breaking every v1 fingerprint and bundle byte. This is the central compatibility hazard; the contract below closes it with a single projection helper.

---

## Part 1 — The D-M2-1 contract (v2 schema policy)

### 1.1 Serialization: the single projection helper (the byte-compatibility mechanism)

One new private function, used at **exactly three** call sites (replacing bare `spec.model_dump()`):

```python
# src/experiment/schemas.py (or canonical.py — implementation choice, one home only)
def spec_dump(spec: ExperimentSpec) -> dict:
    """model_dump() with UNSET v2 fields removed (they are None-defaulted).
    v1-shaped specs -> output byte-identical to the historical model_dump()."""
```

- Call sites: `generation.py:225` (config_fingerprint), `validation.py:418` (config_fingerprint), `export.py:58` (bundle spec section).
- **Rule**: a v2 field appears in the dump **iff it is not None**. v1-shaped specs (schema_version=1, no v2 fields set) therefore produce dumps with **zero new keys** — byte-identical to today.
- `Trial` needs **no schema change at all**: `trial.stimulus` and `trial.derived` already exist as `dict` fields defaulting to `{}`; v1 trials dump `stimulus:{}, derived:{}` today and will dump exactly the same tomorrow. Materialization writes into existing fields.

### 1.2 Fingerprint inclusion policy (exact, per field)

| Content | Class | Fingerprint coverage |
|---|---|---|
| `stimulus_spec` (templates, pools, flags) | researcher config | `config_fingerprint` (via `spec_dump`; only when set) |
| `derived_spec` (op declarations) | researcher config | `config_fingerprint` (via `spec_dump`; only when set) |
| `measures` (measurement-intent metadata) | researcher config | `config_fingerprint` (via `spec_dump`; only when set) |
| Materialized `trial.stimulus` | engine output (deterministic from config+seed) | `trials_fingerprint` (existing `trial.model_dump()` path — no code change on that line) |
| Materialized `trial.derived` | engine output | `trials_fingerprint` (same path) |
| `schema_version` value itself | researcher config | `config_fingerprint` (a v2 spec is a different config than its v1 twin — correct and intended) |

**v1 byte-compatibility demonstration (acceptance-tested, not argued)**:
1. *Fingerprint-form test*: each existing v1 golden spec → `spec_dump()` output `==` the historical `model_dump()` output (asserted directly), and computed `config_fingerprint` `==` the golden value.
2. *Golden regeneration*: existing golden bundle + HTML fixtures reproduce **byte-identical** (external `shasum` cross-check).
3. *All 231 existing tests green, unmodified.*

**Prohibited**: any change to `canonical_json` parameters (frozen contract §6.1); any float in `trial.derived` (canonical trials path discipline — derived ops emit `int | str | bool` only).

### 1.3 Paradigm independence (condition 1) — schema shape

`stimulus_spec` knows **only four generic concepts** — factors, levels, response options, named text pools:

```
stimulus_spec:
  factors: { <factor_name>: {                    # per-factor stimulus definition
      levels: { <level_name>: [template, ...] }, # template = bounded list of line strings (1..4 templates, lines bounded)
      match_line_count: bool = true              # all levels must yield identical line counts (see 1.5)
  } }
  pools: { <pool_name>: [line, ...] }            # optional shared decoy/filler line pools, bounded
```

- Slots inside a line: `{<factor_name>}` → the level name assigned to that factor **in this trial**; `{pool:<pool_name>}` → one line drawn from that pool by the trial's seeded stream.
- **No field, key, enum or semantic anywhere references**: suspects, clues, rooms, cases, patients, diagnosis, or any narrative/genre vocabulary. The Manor Case is expressible (clue lines are just lines; suspect names arrive via `{true_suspect}` slot substitution from *factor levels*, not from stimulus_spec), but nothing in the schema is shaped by it.
- MVP content type: **plain text lines only** (no images/audio/positioning — schema has no field for them, so extending later is another additive v2 decision, not a silent widening).

### 1.4 Deterministic materialization (condition 2) — exact algorithm

**Where**: inside `generate_trials`, after trial assignment and **before** the fingerprint computation (`generation.py:226` region) — therefore every materialized stimulus is integrity-covered by `trials_fingerprint`, and `build_bundle` needs no separate pass.

**Per trial (order fixed, no hidden state)**:
1. `stream_seed = sha256_hex(f"{spec.seed}|{trial.index}|stimulus")` → 64-hex; `rng = Random(int(stream_seed[:16], 16))`. (Digest-derived, **not** Python `hash()` — PYTHONHASHSEED-independent by construction.)
2. Template selection: from the assigned level's template list — `rng.choice` (list length 1..4, so bounded consumption; selection order documented in the module docstring).
3. Line rendering: left-to-right; `{factor}` slots substitute the trial's assigned level name (no randomness); `{pool:x}` slots draw `rng.choice(pool)` (consuming exactly one draw per slot, in reading order — consumption order is part of the frozen algorithm).
4. Output: `{"lines": [str, ...]}` into `trial.stimulus`. No other keys (renderer/game layer may later define *its own* consumption; the engine guarantees only this minimal shape).

**Determinism proof obligations** (tests): same spec+seed → identical `trial.stimulus` across runs and across PYTHONHASHSEED=1/2 subprocesses; slot-draw order pinned by a fixture test (changing consumption order = fingerprint change = caught).

### 1.5 Theoretical vs. derived values (condition 3)

| | Researcher-provided (theoretical) | Engine-computed (derived) |
|---|---|---|
| Content | stimulus templates, pool contents, per-level constants inside lines | `derived_spec` op results: MVP whitelist `trial_number`, `block_progress`, `count_factor_level` |
| Validation behavior | **structural/syntactic only**: schema bounds, slot references resolve (factor exists; pool exists), template line counts within bounds, line-count matching per 1.3. The engine **never judges scientific content** — a theoretically meaningless template is *valid* if well-formed; this is stated in the schema docstring | **semantic whitelist**: op ∈ whitelist; args reference defined factors/levels; names unique; output types `int/str/bool`; any unknown op or arg → error. The whitelist is the entire generality claim — nothing escapes it |
| Error codes | `V2_STIM_*` (syntax, unresolvable slot, bounds, line-count mismatch) | `V2_DERIVED_*` (unknown op, bad args, duplicate name, float-producing expression) |

`derived_spec` shape: `[{name, op, args?}]`; each declared name appears in `trial.derived[name]` for every materialized trial (deterministic from trial context only — index, block, factor assignment — never from prior trials' *outcomes*).

### 1.6 `measures` metadata honesty (condition 5)

- Shape: `[{name, source, notes?}]`; `source` is a **declared** log-field path string (e.g. `"response.rt_ms"`) — syntactically validated (non-empty, dotted path), **not** verified against any runtime log schema (the event-log schema is an M2-D contract; M2-B explicitly does not claim the runtime collects anything).
- The schema docstring and bundle README text say exactly: *"descriptive statement of measurement intent; carries no runtime collection guarantee; log conformance is verified by M2-D's reconciliation, not by the engine."* No capability language. Error codes `V2_MEASURE_*` (empty name/source, extra keys).

### 1.7 Version guard

`schema_version: Literal[1, 2]`. Any v2 field set on a `schema_version: 1` spec → `V2_VERSION_MISMATCH` (negative test). A `schema_version: 2` spec with no v2 fields is legal (dumps differ from its v1 twin only in the version value — correct, it is a different config).

### 1.8 Engine independence from game concerns (condition 7)

- `src/experiment/stimulus.py` exposes only pure functions (`validate_stimulus_spec`, `materialize_trial`); it imports nothing from `tools/`, `agent/`, `game_schemas`, `game_render` — enforced by the existing layer check (experiment is the lowest layer) and by an introspection test asserting the module's import list.
- The engine has **no concept of encounters, rooms, triggers or pacing**. M2-D's runtime will consume `trial.stimulus` as plain data, exactly as the v1 renderer consumes `trial.factors` today. If M2-B's output turns out to need reshaping for gameplay, that is an M2-C/D additive change — never a rewrite of this contract.

---

## Part 2 — The D-M2-4 contract (minimal-core scope, restated exactly)

**In**: R1 `stimulus_spec` + materialization (with `match_line_count`), R3 `derived_spec` (whitelist above), R4 `measures`, v2 validation rules (`V2_STIM_*`, `V2_DERIVED_*`, `V2_MEASURE_*`, `V2_VERSION_MISMATCH`), `spec_dump` projection, tool-description additions (R2-ASCII pattern; validated examples).
**Out (deferred, unchanged)**: R2 block timing + `response_window_ms` → M2-F; per-block feedback → M2-C; GameSpec v2 / world / mapping → M2-C; runtime/event classes → M2-D; `verify_game_events` / agent stages → M2-E; any non-text stimulus content.

## Part 3 — Negative-test matrix (condition 6, complete list for M2-B)

| Family | Cases (each its own test) |
|---|---|
| Malformed stimuli | unclosed `{`; unknown slot name (factor not defined); `{pool:x}` with undefined pool; empty template line-list; template count > 4; line string over bound; line-count mismatch between levels when `match_line_count=true`; v2 fields on schema_version 1 |
| Unsupported derived | op outside whitelist; `count_factor_level` referencing undefined factor/level; duplicate derived name; args with wrong arity; expression that would produce float |
| Incompatible factor mapping | stimulus_spec defined for a factor that does not exist; per-level template missing for a defined level (partial coverage); slot `{x}` where `x` is a *response* name (not a factor — response slots are out of MVP vocabulary and must be rejected, not coerced) |
| Invalid metadata | empty `name`; empty `source`; extra keys beyond `name/source/notes`; duplicate names |
| Serialization guard | v1-shaped spec: `spec_dump()` == historical dump (per golden fixture); v2 spec with v2 fields unset: no v2 keys in dump; float in derived → canonical serialization path rejected |

Every error code emitted through the existing two-tier contract (structured `error_code/path/message/suggestion`; tool-level BLOCKED unchanged) — PA-14/R2 description discipline applies to the tool text.

## Part 4 — Implementation checklist (execution order, each step test-green before the next)

1. **`spec_dump` helper + three call-site swap** → run v1 golden regeneration + fingerprint-form tests + full suite (231 green) — *this step alone must prove byte-compatibility before anything else lands.*
2. **Schema v2 models** (`StimulusSpec`, `DerivedSpec`, `MeasureSpec`, version guard) + `test_schema_v2.py` (acceptance + version-mismatch negative).
3. **`stimulus.py`**: `validate_stimulus_spec` (structural rules incl. line-count matching) + negative tests.
4. **`stimulus.py`**: `materialize_trial` (seeded algorithm per §1.4) + determinism fixture tests (PYTHONHASHSEED subprocess + pinned draw order).
5. **Generation wiring**: materialization pass in `generate_trials`; `derived` materialization; fingerprint tests for v2 specs (subprocess + external `shasum` cross-check).
6. **`measures`** + metadata tests (§1.6).
7. **Tool descriptions** (validate_experiment / generate_trials / export_experiment gain the v2 optional-fields summary; examples validated against real Pydantic — R2 pattern).
8. **Introspection test**: `stimulus.py` import surface (no tools/agent/game imports).
9. **Full gates**: suite (target ~231→~265), pyright 0, six CI gates; independent QA re-runs golden regeneration externally.
10. **Report + commit** (single M2-B commit after QA), then stop for user review — no M2-C work.

**Rollback** (unchanged from proposal, now sharper): step 1 is the only step touching existing call sites; revert restores v1 exactly. All later steps are additive modules/fields. If step 1's fingerprint-form test cannot be made green without altering v1 canonical bytes → **stop and report** (D-M2-1 violation), do not force.

---

**Stop. Awaiting approval of this contract (D-M2-1/D-M2-4 final form) before any implementation.**
