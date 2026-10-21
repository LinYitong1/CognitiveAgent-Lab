# M2-B — Implementation Report (Phases 1–3 complete, awaiting review)

- **Status**: implementation complete; **not committed, not pushed** (per authorization).
- **Gates**: 266/266 tests green (231 pre-existing unmodified in behavior + 35 new) · pyright 0 errors · coverage 90% (was 89%) · all six CI gates PASS.
- **Contract**: docs/m2/M2B_CONTRACT.md (approved). This report covers Phase 1 (compatibility foundation), Phase 2 (research extensions), Phase 3 (independent verification).

---

## 1. Files changed

| File | Change |
|---|---|
| `src/experiment/schemas.py` | NEW: v2 models (`StimulusSpec`/`StimulusFactorSpec`, `DerivedOpSpec`, `MeasureSpec`, all `extra="forbid"`); `schema_version: Literal[1, 2]` (widened — v1 specs validate unchanged, D-M2-1 mechanism); three optional `None`-defaulted v2 fields; **`spec_dump()` projection helper** + `_V2_OPTIONAL_FIELDS` |
| `src/experiment/stimulus.py` | NEW (356 lines): slot grammar/parser, `validate_stimulus_spec` / `validate_derived_spec` / `validate_measures` (semantic rules → raw issues), frozen materialization algorithm (`_trial_stimulus_rng`, `_render_line`, derived ops), `materialize_trials`. Pure functions; imports nothing from tools/agent/api/game |
| `src/experiment/generation.py` | `spec_dump` call site (fingerprint); materialization hook before fingerprint computation; module docstring documents the second randomness consumer + ENGINE_SPEC_VERSION rationale |
| `src/experiment/validation.py` | `spec_dump` call site; 21 `V2_*` error codes (additive; v1 table untouched); `_check_v2_fields` (version guard + semantic validators), wired into the frozen validation order |
| `src/experiment/export.py` | `spec_dump` call site (bundle `spec` section) + docstring note |
| `src/tools/experiment_tools.py` | validate_experiment description gains one 58-char v2 mention; **full v2 shape documentation placed on the `config` input-model field description** (travels with the tools JSON schema; see §5 deviation 2) |
| `tests/unit/experiment/test_v1_compatibility.py` | NEW (5 tests): fingerprint baselines ×2 specs, bundle canonical bytes, dump-form equivalence, verify_bundle round-trip, PYTHONHASHSEED subprocess stability |
| `tests/unit/experiment/test_schema_v2.py` | NEW (30 tests): schema acceptance/version guard; one negative test per V2 error-code family; materialization determinism (in-process + subprocess); fingerprint coverage (stimulus edit → trials_fingerprint change; measures → config-only change); explicit-null == absent; import-surface independence |
| `tests/unit/experiment/test_canonical.py` | 1 line updated — see §5 deviation 1 |

Frozen and untouched: `AgentLoop`, `ToolRegistry`, renderer, `game_schemas`, `verify.py` logic, all M1 tools' behavior, all golden fixtures (byte-identical, externally cross-checked).

## 2. Tests passed and coverage

- **266 passed** (231 pre-existing + 35 new: 5 compatibility + 30 v2). Zero pre-existing tests were deleted or skipped.
- Coverage: **90%** total (was 89%); `stimulus.py` itself at ~97%.
- pyright: 0 errors. `check.sh`: all six gates PASS (G-1 pytest, G-2 coverage ≥85%, G-3 secret scan, G-4 layering, G-5a pyright, G-5b compileall).

## 3. Legacy compatibility evidence (Phase 1 + Phase 3)

1. **Pre-change baselines** captured before any edit (two fixed specs: seed11 demo, seed7 example) — all four values each (config/trials fingerprint, bundle_sha256, canonical-text sha) reproduce **exactly** after M2-B (hardcoded in `test_v1_compatibility.py`; seed11's `bundle_sha256 9741eb7a…` matches the B3 delivery record).
2. **Golden fixtures**: `tests/golden/generic-2x2-seed7.json` regenerates **byte-identical** (external `shasum 4fd916918e8846be…` == regenerated); golden HTML fixture untouched (`f69942d3…`, unchanged since B2); `verify_bundle` (generator-free) accepts it.
3. **B3 demo E2E** (`examples/run_game_agent.py`) rerun during Phase 1: `[E2E OK]`, HTML `62740ee0…` byte-identical to the published artifact.
4. **PYTHONHASHSEED independence**: v1 and v2 bundles both proven byte-stable across seed=1/2 subprocesses.
5. **Field-state handling** (authorization item 3): absent → None → removed from dump; explicit null → same as absent (asserted: no v2 keys in dump); populated → kept + fingerprint-covered. Verified by tests in both files.

## 4. New functionality demonstrated (Phase 2)

A schema_version 2 spec with all three features validates, generates, exports and verifies:

- `stimulus_spec` materializes per-trial `stimulus = {"lines": [...]}` — length-matched levels enforced (`V2_STIM_LINE_COUNT_MISMATCH` when violated), `{factor}` substitution + `{pool:name}` seeded draws, draw order pinned, `{"lines"}` is the only key;
- `derived_spec` computes whitelisted ops (`trial_number`, `block_progress`, `count_factor_level`) as ints from trial context only;
- `measures` rides in the bundle as validated metadata;
- **Fingerprint coverage proven both ways**: editing one stimulus template changes `trials_fingerprint` (and `config_fingerprint`); adding `measures` changes only `config_fingerprint`; `verify_bundle` accepts the v2 bundle;
- Engine independence: introspection test asserts `stimulus.py` imports nothing from tools/agent/api/game layers.

**Not yet consuming the data**: the renderer does not read `trial.stimulus` yet (M2-D scope, by design — this milestone is the data side only).

## 5. Deviations from the approved contract (reported, none architectural)

1. **`tests/unit/experiment/test_canonical.py` — 1 line changed.** The test's final assertion referenced the fingerprint *formula* using bare `model_dump()`; it now uses `spec_dump()`. The test's actual contract (omitted-vs-default fields produce the same fingerprint) is unchanged and still asserted; the in-line comment documents why. This is a reference-formula update required by the approved projection mechanism, not a weakening — the equality assertions are untouched.
2. **v2 tool documentation placement.** The ToolSpec description gains only a 58-char mention (keeping the description within the existing 700-char soft budget test, which was NOT modified); the full v2 shape documentation lives on the `config` input-model field description, which travels with the tools JSON schema to the LLM. Net LLM-facing surface is *larger* than before; no test was weakened.
3. **`ENGINE_SPEC_VERSION` stays `"1.0"`.** The v1 code path is byte-identical (proven); v2 materialization is fully determined by spec content and covered by fingerprints. The bump rule ("any algorithm change") applies to the v1 path, which did not change. Rationale documented in `generation.py`'s docstring. Flagging for your review since the contract mentioned version discipline.
4. `schema_version` literal widened from `Literal[1]` to `Literal[1, 2]` — this *is* the approved D-M2-1 mechanism (listed for completeness; v1 inputs validate identically).

## 6. Known limitations

- Text-only stimulus lines (MVP contract); response-name slots rejected; pool contents bounded (≤8 pools × ≤12 lines).
- Derived whitelist = 3 ops; values always int (float banned by canonical discipline).
- `measures` is metadata only — no runtime collection claim anywhere (docstrings + error suggestions say so).
- Materialized stimulus is not rendered yet (M2-D); real-LLM E2E remains deferred (PA-14).
- The v2 LLM-facing description surface is compact by budget; rich iteration guidance comes from V2_* error suggestions (the two-tier error contract), consistent with the R2 lesson.

## 7. Rollback

Single `git revert` of the M2-B changeset (once committed) restores v1 exactly: the only pre-existing lines touched are the three serialization call sites + one test reference formula + one description string; everything else is additive files/fields. No artifact format depends on v2.

**Stopped. Awaiting your review. No commit or push has been made.**
