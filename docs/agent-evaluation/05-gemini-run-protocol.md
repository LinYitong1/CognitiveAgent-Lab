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
| Max model calls per task | **16** | **hard, pre-call, mechanical** — the guard raises before the 17th call; the request is never sent (the loop's own step cap of 17 is a backstop) |
| Total model calls, all 5 tasks | **80** (5×16) | hard, pre-call, mechanical |
| Max request payload | **96 KB** | **hard, pre-call, mechanical** (`LLMClient(max_input_bytes=96*1024)`; oversized requests refused BEFORE the call) |
| Max output tokens per call | **8,192** | per-call API parameter (`max_tokens`; mock-verified it reaches the SDK) — **enforced by the provider**, strict only if the provider honors it |
| Per-task cost threshold | **$0.30** | **post-call accounting** — checked before each next call of the task; exceeded → task stops |
| Total cost threshold | **$1.50 expected, $2.00 total stop** | **post-call accounting, cumulative across tasks** — checked before each next call and before each next task; exceeded → NO further task starts |
| Per-call timeout | 60 s | SDK-level |
| SDK retries | `max_retries=0` (historical practice; no silent double-billing) | SDK-level |
| Loop-level retries | none (the loop never retries an LLM call) | architecture |
| Request pacing | 15 s between calls | runner-level (`BudgetedClient(pacing_s=15)`) |

**What the budget mechanism actually guarantees.** Four mechanisms with four
DIFFERENT guarantee strengths — none of them alone is an "absolute payment
cap", and this protocol does not claim one:

1. **Request-count cap (16/task, 80 total)** — strict, mechanical, pre-call:
   the guard raises before the capped call; it is the only strict guarantee on
   the NUMBER of billable events.
2. **Request-payload ceiling (96 KB)** — strict, mechanical, pre-call: an
   oversized request is refused before it is sent. It bounds what we SEND
   (bytes), not what the provider bills (tokens).
3. **Output-token ceiling (`max_tokens=8192`)** — a per-call API parameter,
   forwarded to the SDK (mock-verified). It bounds the output cost
   arithmetically at 8,192 × $3.75/1M = **$0.03072 per call**, but ONLY IF
   the provider honors the parameter (outside our control).
4. **Cost thresholds ($0.30/task, $2.00 total)** — post-call accounting,
   checked before the next call and, via a shared accumulator, before the next
   task (see below). They are STOP thresholds, not a payment ceiling: cost is
   known only after a call completes, so actual spend can exceed $2.00 by the
   accounting drift of the in-flight task.

**Cost arithmetic (honest, with its assumptions stated):**

- Input part: the 96 KB ceiling bounds payload BYTES, not tokens. The
  byte→token conversion is provider-dependent (English JSON is roughly
  3.5–4 bytes/token, i.e. roughly 24–27K tokens), so the input cost per call
  is an **estimate** (≈ $0.018–0.021 at $0.75/1M), not a proven bound.
- Per-call estimated worst case: ≈ 24K input + 8,192 output ≈
  $0.018 + $0.03072 ≈ **$0.049** (estimate, assumes the provider honors
  `max_tokens`).
- Per-task estimated worst case: 16 × $0.049 ≈ **$0.78**; five tasks ≈
  **$3.90 — an estimate, NOT a cap.** The $2.00 total stop halts remaining
  tasks well before that in practice, but because it is post-call accounting,
  it does not make $2.00 (or $3.90) an absolute payment ceiling. In theory
  only a provider ignoring `max_tokens` could exceed the estimate materially;
  the 60 s timeout, `max_retries=0`, and the historical observation of ≤ ~1K
  output tokens per call on this workload mitigate that residual risk.
- **Cross-task accumulation**: every task's guard shares ONE `total_spent`
  accumulator (reported usage + the conservative assumption for unreported
  calls); the total stop is checked before every call of every task, so a
  later task cannot start once the accumulator crosses $2.00.
- **Usage-missing calls are never counted as $0**: the guard assumes a
  conservative worst case ($0.05/call) for STOPPING purposes while the
  REPORTED cost stays exactly what providers reported, marked as a lower
  bound (`cost_is_lower_bound`).

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
16 calls ≈ $0.17. Five tasks ≈ **$0.83 expected**; the $2.00 total stop covers
a 2.4× overrun of that expectation. The ESTIMATED worst case with all ceilings
honored is ≈ $3.90 (see the cost-arithmetic block above — an estimate, not a
cap); the total stop halts remaining tasks before it is approached, and
historical inputs run ~15% of the payload ceiling.

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

- [ ] **User authorization for the total budget recorded (date + amount) —
      PENDING; nothing below authorizes a paid call by itself**
- [ ] Code at the final freeze HEAD (06's freeze manifest; the runner records
      the executing HEAD into every run report's `commit` field)
- [x] `--selfcheck` green (14-sample matrix, `_all_as_expected = True`)
- [x] `tests/unit/test_e1_scorer.py` (22) + budget/runner tests green
- [x] `--dryrun` green (6/6 scenarios)
- [x] `max_tokens=8192` + 96 KB input ceiling implemented and mock-verified
- [ ] `.env` key present (checked at runner start; run refuses without it)
- [ ] Disk writable under `data/e1-runs/` and `logs/`
- [ ] Runner started with `--run-id e1b-<date>`; no reuse of old sandboxes
      (the runner refuses non-empty sandboxes by itself)
