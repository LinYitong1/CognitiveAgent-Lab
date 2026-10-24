# 04 — Evaluation Report (Agent Foundation Hardening, Phase 1)

Harness: `scripts/agent_eval.py` (added in this change set; see the commit for its tracked status). Runs 8 scripted scenarios through the **real AgentLoop + real 9-tool registry** — only the LLM is scripted. Deterministic: every scenario is run twice and compared (status, termination, call counts) — all 8 reproduced identically. Full machine-readable output: `data/agent-eval/agent-eval-report.json`; the rendered table is appended as `04-evaluation-report-appendix.md`.

## Layer separation (pytest pass-rate is NOT an agent success rate)

- **L1 tool correctness** — delegated to the pytest suite: 402 passed at HEAD of this round (not re-run by the harness).
- **L2 workflow reliability** — from loop events.
- **L3 artifact success** — independent `verify_bundle` recomputation + rendered-HTML presence.
- **L4 experimental quality** — auto-checkable subset recomputed from bundle trials; the rest explicitly marked researcher-review.

## Offline (ScriptedLLM) results — mechanics, NOT capability

| Metric | Value | Note |
|---|---|---|
| Scenarios | 8 | incl. 2 designed-failure probes |
| Execution completion rate | 0.875 | s8 is the designed budget-exhaustion probe |
| Termination reasons | `model_final_answer: 7, max_steps_exceeded: 1` | structured reasons (new P1-1 field) |
| Validation repair rate | 1.0 | s4: invalid trial_count → structured feedback → repaired → completed |
| Error recovery rate (hard tool errors) | None | no hard tool errors in this battery (all failures travel as structured payloads — audit finding) |
| Verified artifact success rate (L3) | 0.625 | s5 (partial by design), s7 (no artifacts by design), s8 (failed) excluded |
| **False success rate** | **0.125** | exactly the designed probe `s6_nominal_manipulation`: completed + bundle verified + HTML rendered, **but L4 detects label-only manipulation** |
| Mean / median model calls | 4.5 / 5.0 | |
| Token usage / cost | null | scripts report no usage; never fabricated |
| Runtime | ~1s total | |

The headline result: the **label-masking heuristic check works as designed** — `s6` is schema-valid, executes cleanly, exports a fingerprint-verified bundle, and renders a game, yet the L4 heuristic (masking each factor's level names in the materialized stimulus lines, then comparing across levels — the exact T2R signature) flags `content_differs_by_load = false`. This reproduces the T2R false-success class deterministically offline.

**Scope of the L4 heuristic: offline / post-hoc only.** It runs inside this evaluation harness, on exported bundles, after a scenario completes. It is **not** wired into the AgentLoop runtime: there is no in-run detection during a real agent task, no automatic rejection of a nominal bundle at generation time, and **no claim that the agent autonomously detects or repairs this defect class during a run** — in-run checking depends entirely on the model following the design-first prompt's file_read verification step. The harness only makes the defect class *measurable* offline.

**What the L4 label-masking check is and is not.** It is a *heuristic check*, not a general scientific-validity verifier:

- Applicability: only for designs whose intended manipulation should appear in the materialized stimulus **text lines**, and only when trials carry materialized lines (specs without `stimulus_spec` are N/A, not failures).
- False positive: a factor whose real manipulation is non-textual (e.g., timing-only differences) produces identical masked lines and would be flagged as nominal.
- False negative: content may differ across levels *by coincidence* (random pool draws uncorrelated with the factor) and pass the check even though the factor does not causally control the content.
- Over-masking: a level name that is a common substring (e.g. `"a"`) masks unrelated occurrences, biasing toward flagging.
- None of the L4 checks say anything about construct validity; they are a cheap screen for the one failure class actually observed in a real run (T2R).

L4 items that remain **researcher review** (not auto-checkable): construct validity, load/retention calibration, cue leakage, counterbalancing across participants.

## Real LLM: **pending (by design)**

No paid API calls were made this round. ScriptedLLM rates measure workflow mechanics, not agent capability. Real-model evaluation (same model/config/tasks/budget, T5-success + T2R-failure re-runs under the new observability) requires explicit user authorization; the harness's real-LLM section is emitted as `pending` so no offline number can be mistaken for a capability claim.

## Threats to validity

- ScriptedLLM completion/success rates are **offline scenario pass rates, not real-LLM success probabilities** — the scripts encode intended behavior, so they verify loop/tool/check mechanics, not model autonomy or capability.
- Metrics are computed **per scenario** (one row per scenario; each scenario is executed twice purely as a determinism check — reported metrics come from the first run only). Denominators: completion/L3/false-success rates divide by all executed scenarios (including the two designed non-render probes s5/s7 and the failure probe s8); the repair rate divides by scenarios that received structured validation feedback; the recovery rate divides by scenarios with hard tool errors (None when there are none).
- 512-char event summaries are parsed for validation verdicts; a pathological payload shape could evade the repair-rate heuristic (acceptable: repair behavior is additionally covered by `test_agent_design_flow.py` case B).
- L4 label-masking is a heuristic (false-positive/false-negative scope above); it is not a scientific-validity oracle.
- Cumulative token usage sums **only the rounds that reported usage** — rounds reporting nothing contribute zero and are indistinguishable from absence at the total level; totals from partially reporting providers are therefore lower bounds, not exact totals.
