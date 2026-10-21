# M2-B — Implementation Proposal (for approval)

- **Status**: proposal only. Nothing implemented; no M1 source, tests, or schemas modified; nothing committed or pushed.
- **Precondition**: M2-A design review accepted in principle; six blocking decisions presented below for final sign-off (recommendations from DESIGN_REVIEW §6).
- **Scope rule applied**: minimal-core-first (D-M2-4a) — **R2 timing extensions (block timing override + `response_window_ms`) are deferred to M2-F**, shrinking M2-B to what the minimal prototype actually needs.

---

## 1. The six blocking decisions (final sign-off items)

| # | Decision | Alternatives | Recommended | M1 compatibility implication |
|---|---|---|---|---|
| D-M2-1 | v2 schema policy | (a) additive optional fields on `ExperimentSpec` (`schema_version: 2`), v1 byte-compat as hard gate · (b) parallel `ExperimentSpecV2` type · (c) reuse free-form `paradigm_params` | **(a)** | (b) forks validation/fingerprint paths — rejected. (c) bypasses the validation boundary — rejected. (a) enforces M1 compatibility as an *executable acceptance test* (v1 fixtures byte-identical under v2); frozen v1 code semantics untouched. |
| D-M2-2 | `no_response` scoring (deadline miss = error) | (a) miss = error in accuracy · (b) miss excluded · (c) separate tracking | **(a)** with (c) at log level | No M1 impact (R2 deferred; no deadline field exists in M2-B scope). Decision recorded now so M2-F has no ambiguity. |
| D-M2-3 | Exploration events = logged but not reconciled | (a) two-class split · (b) all reconciled · (c) optional logging | **(a)** | No M1 impact (no game-event class in v1). Governs M2-D; recorded for completeness. |
| D-M2-4 | Prototype scope | (a) minimal single-factor core first, R2 → M2-F · (b) full 2×2 now | **(a)** | Directly shrinks this proposal's scope. Same v2 schema policy either way. |
| D-M2-5 | Ending-text bands | (a) Architect drafts 3 bands, review at M2-E · (b) user supplies now · (c) single neutral ending | **(a)**, fallback (c) | None (presentation-only, M2-E concern). |
| D-M2-6 | Example publication timing | (a) in-repo until playtest + approval · (b) public at M2-E | **(a)** | None. |

**M2-B only strictly requires D-M2-1 and D-M2-4 to be approved; D-M2-2/3/5/6 are recorded to lock context.**

## 2. Smallest independently testable M2-B scope

**In scope** (each item independently testable, no renderer/agent changes):

1. **R1 `stimulus_spec`** — new optional field on `ExperimentSpec`: per-factor-level stimulus mapping (text templates with `{slot}` placeholders; bounded line counts; MVP: text-only). 
2. **R1 materialization** — engine deterministically fills `trial.stimulus` at generation time: template render + seeded slot fill (e.g. decoy selection) + **length-matching guarantee** between compared levels (DESIGN_REVIEW §2 control, hard requirement).
3. **R3 `derived_spec`** (minimal) — optional declarative derived values materialized at generation (e.g. block progress counter). Only the mechanism; the prototype may not even use it.
4. **R4 `measures`** — optional metadata list (`name`, `source`, `notes`) included in the bundle; documentation-level, drives nothing yet.
5. **v2 validation rules** — `validate_experiment` extensions: stimulus template syntax, slot references resolve to defined levels/options, line-count bounds, length-match assertion between levels *when a declared contrast exists* (new error codes, e.g. `V2_STIM_*`, `V2_DERIVED_*`).
6. **Fingerprint policy** — v2 fields included in `config_fingerprint` **when set**; absent v2 fields leave the canonical form identical to v1 (this is what makes E-2 possible).

**Explicitly out of scope (deferred)**: R2 block timing + response window (→ M2-F); GameSpec v2 / world / mapping (→ M2-C); any renderer change (→ M2-D); agent tools or workflow (→ M2-E); assets beyond text; per-block feedback field (M2-C, recorded requirement from DESIGN_REVIEW §2).

## 3. Modules: changed vs. new

**Changed (all additive; frozen semantics untouched):**

| Module | Change |
|---|---|
| `src/experiment/schemas.py` | `schema_version: Literal[1, 2]`; new **optional** models `StimulusSpec`, `DerivedSpec`, `MeasureSpec` + fields on `ExperimentSpec` (default = absent) |
| `src/experiment/generation.py` | materialization pass after trial assignment (pure, seed-derived; writes `trial.stimulus` / `trial.derived`) |
| `src/experiment/validation.py` | v2 rules (only when v2 fields present); all v1 rule paths untouched |
| `src/experiment/canonical.py` | canonical JSON form extended: v2 fields serialized **only when set** (v1 form byte-identical when absent) |
| `src/tools/experiment_tools.py` | tool descriptions gain the v2 optional-fields summary (R2-ASCII pattern; additive text only) |

**New:**

| Module | Content |
|---|---|
| `src/experiment/stimulus.py` | template parser + renderer + seeded slot fill + length-match enforcement (pure functions; independently unit-testable) |
| `tests/unit/experiment/test_stimulus.py` | materialization determinism, bounds, syntax errors, length-match |
| `tests/unit/experiment/test_schema_v2.py` | v2 schema/validation rules incl. negative tests per error code |
| `tests/unit/experiment/test_v1_compatibility.py` | the backward-compat gate (see §4) |

**Unchanged (verified by the compat gate)**: `src/agent/**`, `src/tools/_sandbox_io.py`, `src/experiment/{export,verify,game_schemas,game_render}.py`, all M1 tests, all golden fixtures.

## 4. Required tests

**Schema/validation**: v2 field acceptance; every new error code has ≥1 negative test (invalid template syntax, unresolvable slot, line-count overflow, length-mismatch between declared-contrast levels); `extra="forbid"` still rejects unknown keys (existing behavior test extended to v2 fields).

**Determinism/fingerprint**: same v2 spec+seed → identical `trials_fingerprint` and `bundle_sha256` (subprocess, PYTHONHASHSEED=1/2, external `shasum` cross-check — mirrors existing golden discipline); materialization output byte-stable across runs; **fingerprint-form test**: v1-shaped spec under v2 engine → `config_fingerprint` byte-equal to the v1 golden value.

**Backward compatibility (the hard gate, E-2)**: 
- All existing golden fixtures (bundle JSON, demo HTML) reproduce **byte-identical** under the v2 engine + unchanged renderer;
- All 231 existing tests green, unmodified;
- `verify_bundle` accepts all existing bundles unchanged (generator-free re-verification).

**Bundled-artifact check**: exported v2 bundle contains materialized `trial.stimulus` and `measures` metadata; `verify_bundle` recomputes both fingerprints over the v2 canonical form correctly.

## 5. How M2-B prepares interactive gameplay without premature mechanics

M2-B deliberately builds **only the data side** of interactivity: materialized per-trial content is *the* prerequisite for clue encounters (M2-D renders `trial.stimulus`; today it would render nothing, since v1 stimuli are empty dicts). By landing R1 in the engine with length-matching and seeded determinism, M2-C can validate mappings against real stimulus shapes, and M2-D's runtime consumes a finished data contract. **No game mechanic, layout, event class, or agent tool is introduced** — so nothing needs to be undone if the runtime design shifts after M2-C review. The three renderer-agnostic contracts named in DESIGN_REVIEW §4 (bundle / GameSpec / event schema) get their first extension here, on the bundle side only.

## 6. Acceptance criteria (E-item mapping) and rollback

**Acceptance** (all machine-checked; per DESIGN_REVIEW §7):
- E-2 v1 compatibility: golden fixtures byte-identical; 231 existing tests green, unmodified; existing bundles still `verify_bundle`-clean.
- E-3 materialization: deterministic (PYTHONHASHSEED-independent, cross-`shasum`); length-match enforced; bounds enforced; one negative test per error code.
- E-8 suite & statics: all tests green (target 231 → ~260), pyright 0 errors, six CI gates PASS.
- Contract checks: fingerprint-form equivalence test (v1 form unchanged when v2 fields absent) present and green; tool descriptions ASCII-bounded, examples validated against real Pydantic (PA-14/R2 lesson).

**QA gates**: independent QA pass on the compat results (re-running golden reproduction + `shasum` verification externally) before user review; no milestone auto-advance.

**Rollback strategy**: M2-B is additive at every level — schema fields optional, new module isolated, fingerprints v1-stable. Rollback = revert the M2-B commit(s); no data or artifact format depends on it (v1 bundles and HTML never gain v2 content). If a fingerprint-form incompatibility surfaces that cannot be fixed without changing v1 canonical bytes, **stop and report** rather than force a fix — that would be a D-M2-1 policy violation, not an engineering bug.

---

**Stop. Implementation of M2-B begins only after your approval of this proposal and the six decisions above (recommendations: 1a · 2a · 3a · 4a · 5a · 6a).**
