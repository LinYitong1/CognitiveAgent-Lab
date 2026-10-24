# 05 — Implementation Roadmap & Architectural Judgment (Experiment Expressiveness Audit)

Revised 2026-10-24 (design round): P1 acceptance criteria rewritten for the revised
primitives (04 rev: lagged exclude supplement; null-preserving withhold; block-scoped
timing); data-layer items point to the new 06; Q8c corrected. Status taxonomy: [VERIFIED]
established · [DESIGN] revised proposal · [NEEDS-TEST] acceptance obligation.

**Stage 1 implementation status (2026-10-24)**: items P1-2 (withhold), P1-3 (block timing)
and P1-4 (composition-recipe documentation + offline content-consistency tests) are
**IMPLEMENTED** — 434 tests green, six quality gates PASS, golden bundle + golden HTML
byte-identical, old-spec runtime behavior regression-tested. P1-1 (cross-trial lag)
remains design-only. Sections below are updated where status changed.

## Roadmap

### P0 — confirmed correctness / data-integrity / control defects
*(none new this audit; the historical P0s — content-driven correctness, phased presentation — are implemented and runtime-tested. The one candidate, null→false scoring, is inseparable from the P2 withhold primitive and is listed there.)*

### P1 — general expressiveness gaps blocking multiple common experiments

1. **Cross-trial content reference** (04 §P1 rev: `copy_from.lag` + lagged `exclude` entries
   + head-block pattern). Acceptance:
   - complete 2-back fixture (04 §P1.3): content-recomputation test proves
     `cur_i == cur_{i-2} ⟺ match_i = yes` for every trial and the head-block filter holds;
   - binding-flip test (seed perturbation → invariant recomputes on the new bundle);
   - PYTHONHASHSEED-independence; golden bundle; one end-to-end golden HTML (recommended);
   - negative validation: `V2_VAR_LAG_SCOPE` (incl. unconditional lag>0 copy),
     `V2_VAR_LAG_SOURCE_COVERAGE`, `V2_VAR_LAG_BOUNDS`, lagged-exclude edge cases
     (out-of-range = no-op);
   - zero-byte-drift: `spec_dump` strips `copy_from.lag` when None/0; existing 402 tests +
     goldens byte-unchanged.
2. **Withhold option, null-preserving** (04 §P2 rev) — **IMPLEMENTED (Stage 1)**:
   - both engines (node DOM-stub): the four cells — no-press no-go → `value: null,
     correct: true, withheld: true` (correct rejection); no-press go → omission; press on
     no-go → commission; press on go → hit (`test_withhold_option.py`, both the
     correct_rule key path and the correct_from path);
   - old-spec regression: without `withhold_option`, timeout events shape-identical
     (`correct: false`, no `withheld` key) and the engine bytes unpatched (golden HTML
     unchanged);
   - missing-answer-key edge: no-press logs `correct: null` (unscored, never a crash);
   - validation units: `V2_WITHHOLD_COLLISION`, `V2_WITHHOLD_KIND`, v1 gating
     (`V2_VERSION_MISMATCH`), rule options may be the withhold value;
   - zero-byte-drift: `spec_dump` strips `withhold_option` when None; run plans include
     the key only when present. The phased-withhold interaction (U-2) remains NEEDS-TEST
     until exercised (no phased withhold fixture yet).
3. **Per-block timing override** (04 §P3, block-level ONLY) — **IMPLEMENTED (Stage 1)**:
   - per-trial `timing` asserted from the bundle (practice short deadline / main
     spec-level); `BLOCK_TIMING_OVERRIDE` warning; explicit null = absent; v1 gating;
   - zero-drift obligations verified: `spec_dump` strips block `timing` when None; golden
     bundle + golden HTML byte-identical (`test_block_timing.py`);
   - condition-level timing explicitly NOT claimed (residual gap T2-3).
4. **Composition-recipe documentation** (04 §D1, no schema change) — **IMPLEMENTED
   (Stage 1)**: recipes in the `config` field description (ASCII, paradigm-name-free,
   includes the withhold scoring recipe); ASCII assertion extended; offline
   content-consistency suite (`test_composition_recipe.py`) + eval scenario
   `s9_relational_content`; real-LLM verification remains gated on the authorized re-run.

### P2 — advanced / needs further validation
- Phase-onset events + trusted timestamps (06 §4: `t_epoch_ms` exists but is a client clock; needs server receipt time + `seq` ordering; phase-onset events deferred M3-A P2).
- Session/participant envelope + minimal collection endpoint — **full contract now specified in 06** (Participant/Session/event envelope/persistence; server hosting posture is a product decision, 06 §7).
- Per-trial stimulus styling via closed style tokens + GameSpec scene capability (Stroop visual conflict).
- Sequence patterns for controlled transition schedules (lag covers content dependence, not transition schedules — 04 "rejected" note).
- Adaptive session contract (architecture decision required; conflicts with generate-then-execute unless runtime-side and bounded).

### Not needed (solved — do not rebuild)
Determinism/reproducibility; presentation tamper-resistance; structured validation feedback & anti-stall; multi-factor balancing; content-driven correctness; multi-phase presentation; explore-game invariant protection; rating input; timeout logging (recording itself).

## Final architectural judgment (the eight questions)

1. **Fully realizable today**: within-subject factorial designs (any factor/level count within limits), choice/rating/text response tasks with deadlines, content-driven correctness, multi-phase (encode–delay–probe) designs, relational-content designs via the composition pattern (Flanker, semantic Stroop, task switching with inversion), load manipulations with genuinely different content, gamified explorable delivery with invariant protection.
2. **Nominally supported (looks supported, isn't)**: Go/No-Go (deadlines and timeout logging exist, but inhibition scoring is semantically wrong — null always incorrect); visual Stroop (semantics + scoring right, visual conflict not renderable); "adaptive" anything (no runtime loop at all); between-subject designs (no participant layer).
3. **Agent-planning limitations (Type 1)**: nominal-manipulation designs (T2R history — mitigated by design-first prompt + tool docs + offline heuristic, real-model re-test pending); discoverability of the composition pattern (recipe not yet in the tool surface — plan in 04 §D1).
4. **True expressiveness limitations (Type 2/3)**: cross-trial state (designed, 04 §P1 — not implemented); withhold-as-correct (implemented Stage 1); per-block timing (implemented Stage 1; condition-level timing still open); non-textual stimulus attributes; participant/session constructs (contract specified in 06); runtime feedback (adaptive); phase-onset events.
5. **Top three primitives worth adding**: unchanged ranking — (1) cross-trial content reference (now with the lagged-exclude supplement the original proposal lacked); (2) withhold option (null-preserving form); (3) per-block timing override. Styling and trusted timestamps are honest fourth/fifth, deliberately deferred.
6. **Original proposal status**: implemented — factorial combinator + largest remainder, dual-fingerprint bundle + generator-free verify, structured errors with locate–revise–revalidate, previous_errors anti-stall, canonical JSON; replaced/superseded — plugins layer dropped in favor of the general v2 stimulus layer, which the audit shows covers Stroop/Flanker/switching without plugins; no longer necessary — the sequence-plugin design is now needed only for cross-trial state, where the lighter lag + lagged-exclude primitives (04 §P1) suffice.
7. **Extend ExperimentSpec now, or improve Agent usage first?** Both, in that order of dependency: the composition-recipe documentation (P1-4, no schema change) remains the highest value-per-risk item and directly addresses the observed Type-1 failure; the three schema primitives are each small, additive, and evidence-backed — none requires the other. What should NOT happen: expanding before the authorized real-LLM re-run, because T2R's lesson is that agent behavior under the current surface is the least-verified link.
8. **Direct blockers for formal scientific data collection**: (a) no participant/session identifiers or session metadata; (b) no server-side data receipt (manual in-page download only); (c) **corrected**: events DO carry `t_epoch_ms` (client wall clock [VERIFIED]) — what is missing is a *trusted* timestamp, per-session ordering (`seq`), and phase-onset events; (d) browser timing precision; (e) withhold scoring — **resolved in Stage 1** (Go/No-Go-class inhibition measurement now works); (f) between-subject assignment absent. Items (a)–(c) are a data-collection layer decision — the contract is now specified in 06 (design only); (d) is architectural (native runtime).

**Bottom line**: the engine's within-subject, text-stimulus expressiveness is materially stronger than the pre-audit assumption (three presumed gaps disproven by probes); the genuine deficits are concentrated in cross-trial state, withhold semantics, participant/data infrastructure, and non-text attributes — each now carrying a minimal, paradigm-neutral, acceptance-testable proposal, with the revision round adding the missing non-match direction (lagged exclude), the behavior-preserving withhold semantics (null + scoring rule), and the block-only timing scope with explicit byte-drift proofs.
