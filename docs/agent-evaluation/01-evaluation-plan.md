# 01 — Real LLM Capability Evaluation Plan (Phase E1)

Status: **E1-A complete; E1-B preflight complete (both zero paid API calls)** —
evaluation plan, task briefs, scoring rubric, offline-validated scorer (v2),
budget guard, and the preflighted runner are ready. **E1-B (the actual paid
Gemini runs) awaits explicit user authorization.**

## Code baselines (two distinct points — do not conflate)

- **E1-A baseline (historical, 2026-10-24)**: local commit `fdf671d`
  (Expressiveness Stage 1 — composition recipes in tool docs,
  `withhold_option`, `BlockSpec.timing`; **438 tests**, six gates PASS). E1-A's
  original scorer (v1, 10-test lock) and offline validation ran HERE.
- **E1-B evaluation baseline (current, 2026-10-25)**: preflight commit
  `0baaab6` (scorer v2 with task-level invariants, 22-test lock; budget guard;
  runner; **477 tests**, coverage 91%) plus the budget-documentation
  correction commit — the final freeze HEAD recorded in 06's freeze manifest.
  The paid runs must execute on that HEAD; the runner records the actual
  executing HEAD into every run report, so each run self-documents its
  baseline. Any engine/tool change after the freeze invalidates the comparison
  and requires re-running the offline validation.

## What E1 measures (and what it does not)

E1 measures **real-LLM agent capability on the current surface**: can a
production model, given ONLY a researcher's natural-language brief and the
normal tool documentation, produce a scientifically valid, playable experiment
end-to-end — and repair its own mistakes from structured tool feedback?

E1 does NOT measure: the engine's expressiveness (that was the
expressiveness audit), ScriptedLLM workflow mechanics (that is
`scripts/agent_eval.py`'s offline harness), or scientific construct validity
beyond what is recomputable from artifacts (researcher review items stay
researcher review items).

## Phase structure

- **E1-A (done, offline)**: five task briefs; an independent scorer
  (`scripts/e1_scorer.py`) with a fixed validation matrix (known-good AND
  known-bad samples, including the REAL historical T2R artifact); the real-run
  budget protocol (05).
- **E1-B (pending authorization)**: execute the five briefs against real
  Gemini per 05-gemini-run-protocol.md, score every run with the frozen
  scorer, deliver the capability report.

## Non-negotiable evaluation principles

1. **The agent sees only the brief and the normal tools.** No pre-written
   ExperimentSpec/GameSpec, no tool-call answers, no scorer internals, no
   hints derived from the reference designs (02 documents the briefs verbatim;
   the scorer's reference fixtures live only in `scripts/e1_scorer.py`).
2. **Verdicts are separated by dimension** (03): task completion, tool
   correctness, artifact validity, real manipulation, answer recomputation,
   HTML interaction, self-repair, efficiency. A schema-valid bundle with a
   rendered HTML is NOT a scientific success (the T2R lesson — and E1-A's
   scorer demonstrably catches it, see 04).
3. **Every run is isolated**: fresh per-task sandbox, independent AgentLoop
   instance, separate task-id/log namespaces; the scorer reads artifact
   copies. A run cannot contaminate the next task's sandbox, logs, or the
   scorer's fixtures.
4. **Agent self-repair ≠ evaluator findings**: D7 reads ONLY the run's own
   tool-feedback history (errors seen → repaired → completed). The evaluator's
   post-hoc findings (D4/D5/D6) are computed independently afterwards and
   reported in separate sections of the report. Both are recorded per run.
5. **Honesty about heuristics**: the label-masking detector is a heuristic
   with known false-positive (timing-only manipulations) and false-negative
   (coincidental content differences) modes; INCONCLUSIVE is a first-class
   verdict meaning "not machine-checkable — researcher review required".

## Historical context this evaluation builds on

- **T5 (2026-10-21, paid)**: simple color-discrimination brief → 7 requests,
  $0.036, completed with a playable HTML; runtime-verified 10/10 consistent
  (display ↔ condition ↔ answer). The E1-A retest brief reproduces this task
  family.
- **T2R (2026-10-22, paid)**: working-memory brief → 10 requests, $0.104,
  budget-stopped before render; the exported bundle was schema-valid but
  scientifically nominal (load factor label-only, no phases, answer readable
  off-screen). This artifact is preserved locally and is E1-A's primary
  known-bad validation sample.
- Artifacts: `data/.test-sandbox/model-eval-real/` (T5),
  `data/.test-sandbox/model-eval-t2-real/` (T2R), event logs under `logs/`
  (gitignored, local only; full narrative in `docs/m3/M3A_T2R_REPORT.md`,
  local only).

## Deliverables

E1-A round (baseline `fdf671d`, scorer v1):

- `02-task-briefs.md` — the five natural-language briefs (verbatim, the ONLY
  task input the agent receives)
- `03-scoring-rubric.md` — the eight dimensions and their verdict criteria
- `04-offline-validation.md` — the scorer's fixed-sample validation results
- `05-gemini-run-protocol.md` — the executable paid-run protocol (budget,
  caps, stops, artifact retention)
- `scripts/e1_scorer.py` + `tests/unit/test_e1_scorer.py` — the scorer and its
  regression lock (10 tests at E1-A)

E1-B preflight round (baseline `0baaab6` + corrections; scorer v2):

- task-level acceptance invariants + 12 adversarial samples (03/04; 22-test
  lock), `tests/unit/test_llm_client_budget.py` (6) and
  `tests/unit/test_e1_budget.py` (8) for the budget mechanisms,
  `scripts/e1_budget.py` (guard), `scripts/e1_runner.py` (runner, zero-cost
  dry run locked by `tests/integration/test_e1_runner_dryrun.py`), and
  `06-preflight-and-freeze.md` (results + freeze manifest)
