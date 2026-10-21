# M2-C — Implementation Report (Phases 1–3 complete)

- **Status**: implementation complete per the approved conditions (C-1b/C-2a/C-3a/C-4a/C-5a); five deviations approved as MVP-level decisions; final acceptance audit passed (seven checks) and committed to main.
- **Gates**: 303/303 tests (266 pre-existing + 37 new) · pyright 0 errors · coverage 90% · all six CI gates PASS.
- **Scope held**: no exploration gameplay / scene transitions / runtime events / post-session verification implemented (M2-D/E); generation engine untouched (zero changes to `generation.py`/`stimulus.py`/`schemas.py`); single-agent; zero dependencies; no M2-D/E/F work.

---

## 1. Files changed

| File | Change |
|---|---|
| `src/experiment/game_schemas.py` | v2 models (`WorldObjectSpec`, `RoomSpec`, `WorldSpec`, `EndingBand`, `NarrativeSpec`, `MechanicsSpec`, `MappingResponseBinding`, `MappingSpec` — all `extra="forbid"`, bounded, paradigm-free); `GameSpec.schema_version: Literal[1, 2]` + four `None`-defaulted sections; **`game_spec_dump()` projection** (unset v2 sections excluded → v1 fingerprints stable); G8 validation family (`_check_world_structure`, `_check_narrative`, `_check_mapping_bindings`, `_check_v2_sections`) wired after G1–G7; module docstring gains the **invariant enforcement map** (static vs runtime per invariant) |
| `tests/unit/experiment/test_game_spec_v2.py` | NEW (37 tests): v1 fingerprint baselines ×2, fixture validity + byte-identical regeneration, version guard, fingerprint stability (set/unset/key-order/PYTHONHASHSEED), 15 G8 negative tests, 6 experiment-semantics smuggling tests, genre-vocabulary grep ban |
| `tests/fixtures/manor-case/` | NEW: `spec.json` (v2 ExperimentSpec, minimal core: salience × true_suspect, 6+20 trials, seed 20261021), `bundle.json` (canonical, fixed `generated_at`), `gamespec.json` (full mapping example: 5 rooms, 26 encounters ≥ 26 trials, narrative bands, mapping with invariants/freedoms), `README.md` (mapping walkthrough), `generate.py` (deterministic regenerator; refuses to write an invalid gamespec) |

**Touched nowhere**: generation engine, stimulus module, M1 ExperimentSpec schemas, renderer, tools, AgentLoop — `git status` shows exactly one modified source file.

## 2. Test results and coverage

- **303 passed** (266 pre-existing behavior-identical + 37 new); zero deletions/skips.
- pyright 0 errors; coverage 90% total; six gates PASS.

## 3. Legacy compatibility evidence

1. **v1 GameSpec fingerprints**: two baselines captured *before* any edit (working tree == `7e9978c`) — the pipeline demo gamespec (`a6327d39…`) and a handcrafted v1 gamespec (`8aeac5b6…`) both reproduce **exactly** after M2-C (hardcoded in tests).
2. **All 266 pre-existing tests green, unmodified** — including the B0 GB-* suites (43 tests over G1–G7) and the B2 golden HTML byte-identity suite.
3. **v1 rendered artifacts unchanged**: B3 demo E2E rerun → HTML sha256 `62740ee0…` byte-identical to the published artifact (renderer consumes GameSpec by attribute access; no serialization surface).
4. **v1 validation results identical**: a v1-shaped GameSpec against the v2 engine produces no G8 errors (G8 is a no-op when no v2 sections are set) — asserted directly.
5. **Explicit null == absent** for all four sections (dump + fingerprint equivalence asserted).

## 4. New functionality demonstrated (Phase 2)

The Manor fixture exercises the complete mapping contract and validates green:
- 5-room world, 26 encounter objects = trial count (G8 shortfall satisfied), 1 flavour object, full reachability;
- `narrative` with both block briefings + 3 ascending ending bands;
- `mechanics.layout=explore-and-encounter` agreeing with `mapping.trial_trigger`;
- `mapping` with encounter list, response bindings (identical keys across input/mapping surfaces — consistent, legal), all five creative freedoms, all five controlled invariants;
- bundle is schema_version 2 with materialized stimuli (G8_STIMULUS_SEMANTICS satisfied).

**User condition honored — declarations are not evidence**: `controlled_invariants`/`creative_freedom` are checked for closed-list membership, but the invariants themselves are enforced structurally, documented in the module docstring's enforcement map:

| Invariant | Static enforcement (implemented now) | Runtime/post-session (M2-E, documented) |
|---|---|---|
| trial_order | no trial-selection field exists (smuggling test: `trial_indices` → SCHEMA_INVALID); encounter count ≥ trials (G8); all rooms reachable (orphan check) so every encounter can fire | played-sequence reconciliation |
| conditions | no conditions field anywhere (smuggling test) | trial_start conditions vs bundle |
| stimulus_content | no stimulus field (smuggling test); encounters render `trial.stimulus.lines` verbatim by construction | re-render byte-identity |
| correct_answers | no correctness field (smuggling test); computed only from bundle `correct_from` | response correctness recompute |
| timing | no timing field (smuggling test) | event timestamps vs trial.timing |

**Cursor semantics**: the mapping schema has no ordering/selection surface at all; consumption is bundle-index monotonic by construction (documented in `MappingSpec` docstring and enforced by the shortfall check).

## 5. Deviations / clarifications (all small, none architectural)

1. **One G8 code beyond the contract's §7.1 table**: `G8_MAPPING_BLOCK_COVERAGE` (briefings must cover every declared block — contract §3.2 rule 5 said "(G8)" without assigning a code). Reported for completeness; semantics exactly as contracted.
2. **Ending-band ordering** uses `G8_WORLD_STRUCTURE` (contract named the code for "world structure"; bands are narrative structure — same family, message is precise).
3. **Unknown invariant literals** are reported under `G8_MAPPING_INVARIANT_MISSING` (contract table had no dedicated code; message states "unknown invariant literals" explicitly).
4. **Key-collision rule refined** vs. the naive reading: input.bindings and mapping.response_bindings may share a key **iff** it binds the same response+option on both surfaces (consistent declarations); a collision (same key, different meaning) → `DUPLICATE_KEY`. Two tests cover both sides.
5. **Manor fixture uses keys a/b/c** (not the 1/2/3 of PROTOTYPE_SPEC §2): v1 G6 key grammar allows single lowercase letters only, and G1–G7 behavior is frozen — relabeling keys is presentation-only and measurement-neutral. Noted for the M2-D runtime's on-screen hints.

## 6. Known limitations

- `mechanics.inspect_objects` is stored but has no runtime semantics yet (M2-D defines behaviour; documented).
- `encounter_objects` set with a sequential trigger is accepted and inert (no warning implemented — minimal scope).
- The event vocabulary (Part 4 of the contract) is documented in the fixture README and docstrings only; the event-log schema itself is M2-D/E work (decision C-4a).
- The renderer ignores v2 sections entirely today (v1 rendering path untouched) — the explore runtime is M2-D.
- RATIO_ROUNDED warning appears for the Manor spec (20 trials over 6 balanced combos) — honest design warning, fixture is valid.

## 7. Rollback

Single revert of the M2-C changeset: one source file + two test/fixture paths, all additive; v1 artifacts and fingerprints never depended on v2 sections.

**Acceptance audit (2026-10-21, post-approval)**: 303/303 tests + six gates PASS (verified in a clean environment — the host safe-delete shim's per-turn bulk-delete guard can otherwise spuriously fail sandbox-cleanup tests); v1 golden HTML `62740ee0…` and bundle `9741eb7a…` reproduced byte-identically from a fresh CLI demo run; single source file changed (`game_schemas.py`), no unrelated files touched.
