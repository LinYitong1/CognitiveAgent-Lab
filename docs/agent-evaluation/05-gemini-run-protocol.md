# 05 — E1-B Real Gemini Run Protocol (Executable, Pending Authorization)

Status: **prepared and preflighted; ZERO paid API calls made.** Executing this
protocol requires explicit user authorization of the budget below. E1-B
preflight (2026-10-25) implemented and mock-verified everything this protocol
required: the client-side output/input ceilings, the budget guard, and the
runner (see 04's dry-run section and 06's freeze manifest).

## Model and endpoint

- **Model**: `gemini-3.8-flash` (identical to the historical T5/T2R runs —
  comparability) via the OpenAI-compatible endpoint
  `https://generativelanguage.googleapis.com/v1beta/openai/`, key from `.env`
  (`CALC_AGENT_ENV_FILE` discipline; the key never enters the conversation,
  the repo, or the run report).
- **Pricing** (checked 2026-10-24, Google AI pricing pages + independent
  index; introductory rates until 2026-12-31):
  - input **$0.75 / 1M tokens**
  - output **$3.75 / 1M tokens** (thinking tokens ARE billed as output —
    the T5 reconciliation: billable output = `total_tokens − prompt_tokens`)
  - cached input $0.07 / 1M; standard rates from 2027-01-01: $1.50 / $7.50.
- Historical empirics on this exact model+endpoint: T5 = 7 requests /
  32,001 tokens / $0.036; T2R = 10 requests / 99,768 tokens / $0.104
  (avg ≈ 9K input + 1K output-billable per call).

## Budget and caps

| Control | Value | Enforcement |
|---|---|---|
| Max model calls per task | **16** (`max_steps`) | **hard, pre-call** — the guard raises before the 17th call; the loop's own step cap (17) is a backstop |
| Total model calls, all 5 tasks | **80** | hard, pre-call (the real bound is 5×16) |
| Per-task estimated cost | ≤ **$0.30** | post-call accounting; exceeded → task stops before its next call |
| Total estimated cost | ≤ **$1.50** expected, **$2.00 hard stop** | post-call accounting; exceeded → NO further task starts |
| Max output tokens per call | **8,192** | **IMPLEMENTED** (`LLMClient(max_tokens=8192)`; mock-verified the parameter reaches the SDK) |
| Max request payload | **96 KB** | **IMPLEMENTED** (`LLMClient(max_input_bytes=96*1024)`; oversized requests refused BEFORE the call) |
| Per-call timeout | 60 s | SDK-level |
| SDK retries | `max_retries=0` (historical practice; no silent double-billing) | SDK-level |
| Loop-level retries | none (the loop never retries an LLM call) | architecture |
| Request pacing | 15 s between calls | runner-level (`BudgetedClient(pacing_s=15)`) |

**What the budget mechanism actually guarantees (updated; no "absolute hard
cap" language).** With the two client-side ceilings now implemented and
mock-verified, each call's cost is bounded PRE-CALL by construction:
input ≤ 96 KB (≈ 24K tokens) and output ≤ 8,192 tokens → worst case ≈ $0.04
per call. Therefore:

- **Per-call cost: hard pre-call bound** (input ceiling + max_tokens).
- **Per-task spend: hard bound** 16 × ≈$0.04 ≈ **$0.64 worst case**, with the
  $0.30 threshold stopping the task earlier in practice (post-call accounting).
- **Total spend: hard bound** 5 × $0.64 ≈ **$3.20 theoretical**, with the
  $2.00 evaluation stop halting remaining tasks (post-call accounting, applied
  before each next call and before each next task).
- **Usage-missing calls are never counted as $0**: the guard assumes a
  conservative worst case ($0.05/call) for stopping purposes while the REPORTED
  cost stays exactly what providers reported, marked as a lower bound
  (`cost_is_lower_bound`).
- The historical caveat ("no pre-call output bound, a single call could emit
  66K tokens") is resolved by the implemented `max_tokens`; the remaining
  residual risk is a provider that ignores the parameter, which the post-call
  accounting and the per-task hard bound still contain.

## Retry policy

- SDK transport retries: **0** (set at client construction).
- Provider 429/5xx after zero retries → the loop terminates with
  `llm_error`; the run is recorded as failed with its failure class and all
  artifacts are kept. No automatic re-run. (A manual re-run of a failed task
  requires fresh authorization and a fresh sandbox.)
- 15 s pacing between requests (historical practice) to stay well under rate
  limits.

## Hard-stop mechanism (runner checklist, per call)

Implemented in `scripts/e1_budget.py` (`BudgetGuard`/`BudgetedClient`) and
mock-verified end-to-end (04):

1. Before each LLM call: if `calls_this_task >= 16` → stop task
   (`budget-stop`); if the guard's conservative estimate (reported + unreported
   × worst-case) `>= $0.30` → stop task (`budget-stop-cost`); if
   `total_spent >= $2.00` → stop the whole evaluation (`budget-stop-total`).
   The input-byte ceiling is enforced inside `LLMClient.chat` (refusal before
   the request; the loop records it as a terminal failure).
2. After each call: accumulate usage from the provider's report (never
   fabricated; a missing usage block counts as an unreported call — conservative
   assumption for stopping, lower-bound marker for reporting).
3. Stop reasons are distinct and recorded in the run report:
   `budget-stop` (request cap), `budget-stop-cost` (per-task threshold),
   `budget-stop-total` (evaluation stop), `llm_error`, `max_steps_exceeded`
   (loop backstop), `model_final_answer` (completed). Failed (exception) calls
   still count as billed attempts.

## Isolation and artifact retention (per task)

- Fresh sandbox: `data/e1-runs/<run-id>/<task-id>/` created empty before the
  run; the run's export/render outputs live only there. No shared state with
  other tasks; each task gets an independent AgentLoop and a distinct task id
  namespace (`e1-<run-id>-<task-id>`) so event logs never mix.
- Retained per task:
  - the brief as sent (verbatim from 02);
  - full event log `logs/agent-eval-e1-<run-id>-<task-id>.jsonl` (every model
    request/response summary, tool call, tool result, error);
  - per-call usage ledger (prompt/completion/total/thinking tokens, latency);
  - the produced artifacts (bundle JSON, GameSpec, HTML) — even for failed
    runs;
  - the run report JSON (same shape as the historical T5/T2R reports:
    scenario status, tool_calls, llm_calls, wall_s, tokens_*, cost estimate,
    failure_class);
  - the scorer output JSON (D1–D8 verdicts + details).
- Failure logging: every non-ok tool result and every validation error round
  is preserved in the event log; nothing is summarized away.

## Post-run scoring procedure

Automated by the runner (mock-verified in the dry run): after each task the
runner invokes the frozen scorer (`scripts/e1_scorer`) on the task's bundle +
HTML + its own run report and writes `scored.json` next to them. The scorer
reads artifacts only (no writes into the run sandbox); run-side dims (D1/D2/
D7/D8) and evaluator dims (D3/D4/D5/D6) are reported in separate sections,
with INCONCLUSIVE items listed explicitly.

Cross-task comparison table + capability narrative → the E1-B report
(`docs/agent-evaluation/07-real-run-results.md`, to be written in E1-B).

## Expected budget arithmetic (why $1.50 is realistic)

Per call (historical): ~9K input + ~1K output-billable ≈ $0.0104. Per task at
16 calls ≈ $0.17. Five tasks ≈ **$0.83 expected**; the $2.00 hard stop covers
a 2.4× overrun. With the implemented ceilings, the absolute worst case is
5 × 16 × (24K input + 8K output) ≈ $2.40 — above the $2.00 stop, which then
halts the remaining tasks before the theoretical bound is reached; in practice
inputs are ~15% of the ceiling.

## How to run E1-B (the runner is preflighted)

```bash
# zero-cost dry run (always green before a real run)
python -m scripts.e1_runner --dryrun

# a single real task (fresh --run-id each time; refuses non-empty sandboxes)
python -m scripts.e1_runner --task e1_flanker --provider real \
    --run-id e1b-<date> --authorize-budget

# all five, in fixed order 1..5
python -m scripts.e1_runner --all --provider real \
    --run-id e1b-<date> --authorize-budget
```

Per task the runner writes into `data/e1-runs/<run-id>/<task-id>/`:
`brief.txt` (verbatim), `run-report.json` (historical shape + budget ledger +
stop_reason), `scored.json` (D1–D8), and the produced artifacts
(`experiments/…`, `games/…`). The event log lands in
`logs/agent-e1-<run-id>-<task-id>.jsonl`.

## Pre-flight checklist (E1-B day)

- [x] User authorization for the total budget recorded (date + amount) — **pending**
- [x] Code at the frozen baseline (06 freeze manifest; E1-A validated on it)
- [x] `--selfcheck` green (14-sample matrix, `_all_as_expected = True`)
- [x] `tests/unit/test_e1_scorer.py` (22) + budget/runner tests green
- [x] `--dryrun` green (6/6 scenarios)
- [x] `max_tokens=8192` + input ceiling implemented and mock-verified
- [ ] `.env` key present (checked at runner start; run refuses without it)
- [ ] Disk writable under `data/e1-runs/` and `logs/`
- [ ] Runner started with `--run-id e1b-<date>`; no reuse of old sandboxes
      (the runner refuses non-empty sandboxes by itself)
