# 06 — E1-B Preflight Results & Evaluation Freeze Manifest

Date: 2026-10-25. This round made ZERO paid API calls, did not touch the
experiment engine, and did not start Stage 2 (no `copy_from.lag`, no lagged
exclude, no research data layer).

## What the preflight added

1. **Task-level scorer checks** (`scripts/e1_scorer.py`, scorer version
   **e1-scorer-v2**): per-brief acceptance invariants for all five tasks
   (documented in 03), merged into D4/D5 without relaxing any generic check.
   Twelve adversarial samples (schema-valid, brief-violating) are pinned in
   the selfcheck matrix and in `tests/unit/test_e1_scorer.py` (22 tests).
   Notable catches only the new checks make: a flanker keyed by congruency
   instead of the middle arrow (D5); a task-switch design whose mappings are
   consistent, inverted AND balanced but literally flipped (only the brief's
   direction requirement catches it); an explore game with 2 rooms (D4, from
   the rendered HTML's PLAN).
2. **Budget limits implemented and mock-verified**:
   `LLMClient` now supports `max_tokens` (output ceiling) and `max_input_bytes`
   (request-payload ceiling, refused before the call) — defaults keep the
   historical byte-identical behavior; `tests/unit/test_llm_client_budget.py`
   (6) pins parameter forwarding, pre-call refusal, and the unchanged
   thought_signature round trip.
   `scripts/e1_budget.py` (`BudgetGuard`/`BudgetedClient`): call-count cap is
   the pre-call hard stop; cost caps are post-call accounting checked before
   the next call; missing usage is NEVER counted as $0 (conservative
   worst-case assumption for stopping; reported cost stays a marked lower
   bound); distinct stop reasons; failed calls count as billed attempts.
   Pinned in `tests/unit/test_e1_budget.py` (8).
3. **E1-B runner** (`scripts/e1_runner.py`, runner version **e1-runner-v1**):
   five frozen briefs (briefs version **e1-briefs-v1**), fresh sandbox per
   task (reuse refused), nothing injected beyond the brief, full call
   trace/usage/latency/artifact retention, independent scoring after the run,
   single-task execution supported, real-run mode requires
   `--provider real --authorize-budget` and a non-empty key.
4. **Zero-cost end-to-end dry run** (`--dryrun`, 6 scenarios, all green,
   regression-locked in `tests/integration/test_e1_runner_dryrun.py`):
   success (D1/D3/D6 PASS incl. the node driver playing the rendered HTML),
   validation-failure (no artifacts → D1 FAIL), budget-stop (call cap, 3
   calls), budget-stop-cost (post-call accounting), usage-missing (not $0),
   API error (failed call billed, clean failure record).

## Freeze manifest (recorded for the E1-B authorization)

| Item | Value |
|---|---|
| Engine/experiment code | unchanged from Stage 1 commit `fdf671d` (E1 preflight rounds touched only the agent LLM client budget params, scripts, tests, docs) |
| E1-A baseline (historical, 2026-10-24) | `fdf671d` — scorer v1 (10-test lock), 438 tests, six gates PASS. E1-A's original offline validation ran HERE; its numbers are not the E1-B numbers |
| E1-B preflight implementation (2026-10-25) | `0baaab6` — scorer v2, budget guard, runner, 477 tests, coverage 91%, six gates PASS |
| Budget-documentation corrections (this revision) | the commit containing this manifest revision (`docs(e1): budget corrections and freeze unification`) — removes the unproven per-call/per-task dollar "hard bound" claims, unifies the cost arithmetic, and adds run-time HEAD capture to the runner |
| **Final freeze HEAD for E1-B** | the commit containing this revision (the manifest cannot embed its own hash; verify at authorization time with `git log --oneline -1` — it must be the correction commit above). The runner records the ACTUAL executing HEAD and a dirty flag into every run report (`commit` / `commit_dirty`), so each run self-documents its baseline regardless of what this table says |
| Model | `gemini-3.8-flash` via OpenAI-compatible endpoint (`v1beta/openai/`) |
| Prices assumed | $0.75 / 1M input, $3.75 / 1M output-billable (thinking billed as output; intro rates to 2026-12-31) |
| Briefs version | `e1-briefs-v1` (runner-embedded verbatim; docs/agent-evaluation/02 is the rendered copy) |
| Scorer version | `e1-scorer-v2` |
| Runner version | `e1-runner-v1` (+ run-time HEAD capture) |
| Budget (defaults) | strict pre-call, mechanical: 16 calls/task (80 total), 96 KB request-payload ceiling; provider-enforced: max_tokens 8192 (output cost arithmetically ≤ $0.03072/call IF honored); post-call accounting stop thresholds: $0.30/task and $2.00 total (cumulative across tasks via a shared accumulator; NOT an absolute payment ceiling — see 05); usage-missing calls counted at a conservative $0.05 assumption for stopping, reported cost stays a marked lower bound; 60 s timeout, 0 SDK retries, 15 s pacing |
| Quality gates at freeze | 477/477 tests, coverage 91%, six gates PASS (G1 pytest / G2 coverage / G3 secrets / G4 layering / G5a pyright / G5b compileall) |
| Offline validation | selfcheck `_all_as_expected = True` (14-sample matrix + historical artifacts + adversarial samples); dry run 6/6 |
| Pending authorization | total budget (recommended ≤ $2.00 total-stop threshold; expected ≈ $0.83), then E1-B real run via `scripts.e1_runner --provider real --authorize-budget` |

### Cost-arithmetic correction (this revision, for the audit trail)

The preflight revision of 05 claimed a "per-call hard cost bound ≈ $0.04" and
per-task/total "hard bounds" ($0.64 / $3.20, elsewhere $2.40). Those were
wrong or unproven: 96 KB bounds payload BYTES, not tokens (the byte→token
conversion is provider-dependent), and the correct per-call estimate at
~24K input + 8,192 output is **≈ $0.049** ($0.018 + $0.03072). All dollar
figures in 05/06 now use these corrected numbers and are labeled estimates;
the only STRICT guarantees are the request-count cap and the two client-side
ceilings (with `max_tokens` strict only if the provider honors it).

## Residual blind spots (stated, not hidden)

- D4/D5 heuristics are text-line based; a timing-only manipulation remains a
  theoretical false-positive risk (not present in the five briefs' designs).
- The explore runtime is not driven automatically: brief 5's runtime
  exploration-order invariance and playability are INCONCLUSIVE → manual
  acceptance by the researcher (static PLAN checks are automated).
- Non-yes/no task-switch options downgrade the literal-direction check to an
  INCONCLUSIVE note (the inversion requirement still holds).
- Whether the real model USES the documented composition recipes is exactly
  what E1-B measures; the offline harness cannot answer it.
