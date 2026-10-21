# M2-D Phase 1 — Final Acceptance Report

- **Verdict**: all checks pass; the changeset is **staged and ready for a single commit**
  (not committed, not pushed — awaiting explicit approval).
- **Review scope of this document**: Part 1 finalization only. Gameplay criticism and
  the Phase 2 proposal live in `M2D_GAMEPLAY_REVIEW.md` and `M2D_PHASE2_PROPOSAL.md`.

## 1. Test suite and quality gates

| Check | Result |
|---|---|
| G-1 all tests | **325/325 passed** (303 pre-existing behavior-identical + 22 new) |
| G-2 coverage gate | **90.33% ≥ 85%** |
| G-3 secret scan | PASS (no hits) |
| G-4 layering | PASS (no reverse imports) |
| G-5a pyright | 0 errors |
| G-5b compileall | PASS |

## 2. Backward compatibility (M1 / M2-B / M2-C)

| Baseline | Evidence |
|---|---|
| M1 v1 golden HTML | `test_dispatch_v1_golden_html_unchanged` + the B2 golden suite re-run green — `render_game_html` output for v1 specs is byte-identical |
| B3 demo artifact | fresh `cli demo` run reproduces HTML sha256 `62740ee0cb1482d6…` (external `shasum`, byte-identical to the published artifact) |
| M2-B v2 research layer | `test_schema_v2.py` (30 tests) green — stimulus materialization, derived ops, measures untouched |
| M2-C GameSpec v2 + G8 | `test_game_spec_v2.py` (37 tests) green — v1 gamespec fingerprints `a6327d39…` / `8aeac5b6…` and the Manor fixture byte-regeneration untouched |
| Classic renderer path | dispatch is additive: only `schema_version==2` + `mechanics.layout=="explore-and-encounter"` routes to the new renderer; a v2-sequential spec still renders through the classic pipeline (tested) |

No experiment engine or schema file was modified (see §5).

## 3. Experiment-integrity verification (runtime, node-driven)

From the rendered HTML itself (engine JS executed under node with a DOM stub):

- **Monotonic trial cursor**: 4 encounters driven across 2 rooms in mixed object order →
  `trial_start` indices strictly `[0,1,2,3]`; a re-examined encounter object never
  re-fires (inspect-only).
- **Response bindings**: keypress `b` → value `"b"`; synthetic game keys `j`/`k` →
  options `x`/`y` — resolution strictly from `mapping.response_bindings`.
- **Stimulus integrity**: every `trial.stimulus.lines` entry asserted present verbatim
  in the DOM at trial time; correctness computed from bundle `correct_from` factors
  (asserted against the bundle for every response).
- **Event logging**: channel discipline verified (`measurement`: game_end/block_start/
  trial_start/response; `game`: game_start/room_enter/object_inspect/encounter_trigger);
  the end-of-session runtime self-check passes (`Self-check OK`).

## 4. HTML reproducibility

`examples/run_manor_prototype.py` run twice → sha256 `8323ba6d4971924576dab91c217ff301c
cf12e2c6e38435187f94fae0157cf73f` both times — **byte-identical across regenerations**;
additionally asserted hash-seed-independent in tests (PYTHONHASHSEED 1 vs 2).

## 5. Final diff review

| File | Change | Nature |
|---|---|---|
| `src/experiment/game_render.py` | +39/−2 | v2 layout registry + guarded dispatch; classic path byte-identical |
| `src/experiment/explore_render.py` | new | the explore-and-encounter renderer (plan builder + HTML/JS template) |
| `examples/run_manor_prototype.py` | new | fixture → playable HTML generator |
| `tests/unit/experiment/test_explore_render.py` | new | 17 renderer tests |
| `tests/unit/experiment/test_explore_runtime.py` | new | 5 node-driven runtime tests |
| `docs/m2/M2D_PHASE1_REPORT.md` | new | Phase 1 implementation report |

No unrelated files modified, deleted, or reset (reflog clean; `data/` outputs are
gitignored). No changes to ExperimentBundle, generation, stimulus, schemas, G1–G8
validation, tools, or AgentLoop.

## 6. Known limitations carried into the record

1. **Runtime-test sandbox sharing**: two concurrent pytest processes writing the shared
  `data/.test-sandbox/explore-runtime/driver.js` can cross-contaminate (observed once
  when a foreground pytest ran against a background gate run). Sequential execution
  (CI, `check.sh`, default pytest) is unaffected; single-process runs verified 5/5.
2. Browser-automation limitation (recorded in M2D_PHASE1_REPORT §3): node + DOM stub
  verifies the state machine, not visual layout/CSS/real keyboard semantics.
3. Phase 1 functional limits: choice responses only; conclusion requires all trials
  consumed; provisional event vocabulary (M2-E owns the final schema).

## 7. Commit readiness

Staged: 6 files above (one commit message drafted, referencing this report). **Blocked
on explicit user approval — nothing committed, nothing pushed.**
