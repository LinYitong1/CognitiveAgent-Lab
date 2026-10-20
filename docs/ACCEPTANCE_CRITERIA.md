# CognitiveAgent Lab — Acceptance Criteria (executable)

> Version: v1.2 (revised per the architecture review + QA acceptance-criteria check reports) ｜ Principle: every criterion ships with a **directly executable acceptance command**; QA runs each one and attaches the actual output.
> Anti-false-positive principle: acceptance commands run **independently and are judged independently**; masking a failure into a pass via `||` fallbacks is forbidden; for multi-line commands, the code block below the table is authoritative (the block's exit code is the verdict).

## General gates (every milestone, every merge)

| ID | Criterion | Acceptance command | Pass condition |
|----|------|----------|----------|
| G-1 | all tests green | `bash scripts/check.sh` | check.sh **runs each check independently and prints per-check results** (aggregate exit code + per-check report); the verdict is **all checks pass** — a failure is attributable from the per-check report to a specific sub-gate; the aggregate exit code alone is not the verdict |
| G-2 | coverage | `pytest --cov=src --cov-report=term-missing` | line coverage of agent/ tools/ storage/ ≥ 80% (**effective from M1** — in M0 those three modules do not exist yet, so only the command running without error is required; term-missing eases per-file review) |
| G-3 | no hardcoded secrets | see the G-3 command block below | **a failure blocks**: grep exit code 1 (no match) → the block exits 0 = pass; exit code 0 (a match) or 2 (a scan error) → the block exits 1 = blocked. `|| echo CLEAN`-style fallbacks are forbidden |
| G-4 | layering dependencies correct | `python -m scripts.check_layers` (provided in M0; see the ROADMAP M0 deliverables) | **exit code 0 and no reverse-import output** (run from the project root) |
| G-5a | static type check | `python -m pyright src/` | the exit code must be 0 (pyright is on the M0 dependency list; if the local Node.js runtime is missing so pyright cannot run, the dependency counts as unmet and the gate fails) |
| G-5b | syntax compile check | `python -m compileall -q src/` | the exit code must be 0 |

**G-5a and G-5b are two independent checks that must be run and judged separately; merging them into something like `pyright ... || compileall ...` is forbidden — either failing fails the gate.** M4 optional enhancement: introduce `gitleaks` or `detect-secrets` for dependency-based secret scanning (the Architect must update the §2.1 dependency list first).

### G-3 command block (the whole block's exit code is the verdict)

```bash
grep -rniE "(sk-[a-z0-9_-]{8,}|api[_-]?key[[:space:]]*=[[:space:]]*[\"'][^\"']+)" src/ tests/ web/
rc=$?
[ "$rc" -eq 1 ]
```

> The regex contains `sk-[a-z0-9_-]{8,}` (covering the `sk-proj-…` / `sk-ant-…` prefix shapes). Semantics: grep rc=1 (no match) → pass; rc=0 (a match) or rc=2 (a scan error) → blocked. When integrating into check.sh, the exit code must be judged with an explicit `if`; a `set -e` chain cannot be relied on (grep rc=1 is the pass state and would abort a `set -e` script). Placeholder keys in test fixtures must use obviously non-real shapes (e.g. `test-key-not-real`) to avoid false positives from this scan.

## M0 — Scaffolding

| ID | Criterion | Acceptance command | Pass condition |
|----|------|----------|----------|
| M0-1 | the service starts | see the M0-1 command block below | within 30 readiness probes `/health` returns `{"status":"ok"}` (exact body match) and the service process is cleaned up |
| M0-2 | test skeleton (with a real test) | `pytest` | 0 failed and **collected ≥ 1** — at least one real test must be collected and pass (the `/health` endpoint test); 0 collected is no longer allowed |
| M0-3 | configuration read from the environment (starts without keys) | see the M0-3 command block below | after dual-channel clearing (unset environment variables + `CALC_AGENT_ENV_FILE=/dev/null` bypassing .env, see ARCHITECTURE §7), the service becomes ready and `/health` returns `{"status":"ok"}` |
| M0-4 | pyright dependency in place | `python -m pyright --version` | prints a version number with exit code 0; a missing Node.js runtime counts as the dependency being unmet |

### M0-1 command block (readiness wait + flag-based finish, guarding against the sleep false positive)

```bash
uvicorn src.api.app:app --port 8000 >/tmp/m0-uvicorn.log 2>&1 &
APP_PID=$!
ok=0
for i in $(seq 1 30); do
  curl -sf localhost:8000/health | grep -q '"status":"ok"' && { ok=1; break; }
  sleep 0.5
done
kill "$APP_PID" 2>/dev/null
[ "$ok" -eq 1 ]
```

> Key points: the readiness wait removes the race; **the verdict must come from the flag at the end** (if the loop body ends with `curl && break; sleep`, an all-failed run ends with sleep and exit 0 — a false positive); the body is matched exactly with grep for machine judgment; the service process is cleaned up at the end.

### M0-3 command block (key-less environment, dual-channel clearing)

```bash
env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY CALC_AGENT_ENV_FILE=/dev/null \
  uvicorn src.api.app:app --port 8000 >/tmp/m0-nokey.log 2>&1 &
APP_PID=$!
ok=0
for i in $(seq 1 30); do
  curl -sf localhost:8000/health | grep -q '"status":"ok"' && { ok=1; break; }
  sleep 0.5
done
kill "$APP_PID" 2>/dev/null
[ "$ok" -eq 1 ]
```

> Key points: in pydantic-settings, environment variables take precedence over .env — unsetting without bypassing .env (or moving .env without unsetting) does not constitute a valid "no keys" condition; `CALC_AGENT_ENV_FILE=/dev/null` (ARCHITECTURE §7) explicitly bypasses the .env file without moving a real `.env`.

## M1 — Agent core loop

| ID | Criterion | Acceptance command | Pass condition |
|----|------|----------|----------|
| M1-1 | FakeLLM loop integration tests | `pytest tests/integration -k loop` | all green; asserts the step limit and the event sequence |
| M1-1b | FakeLLM does not depend on real keys | `env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY CALC_AGENT_ENV_FILE=/dev/null python -m pytest tests/integration` | all green — a key-less process environment **and** .env bypassed (dual-channel clearing), proving the integration tests do not depend on a real API |
| M1-2 | real-LLM multi-step task | see the M1-2 command block below | ① run_agent exits 0; ② tool_call events ≥ 2 with ≥ 2 distinct tools (counted from `logs/agent-<task_id>.jsonl`, see ARCHITECTURE §8); ③ `data/out.txt` matches the actual calc result (QA recomputes: 123×456=56088, 56088÷7≈8012.57, compared against calc's actual output format); **passing off hardcoded output is forbidden** |
| M1-3 | tool failure is not fatal | `pytest tests/unit -k tool_failure` | tool exceptions are captured and returned to the LLM; the task does not hang |
| M1-4 | step limit | `pytest tests/integration -k max_steps` | on exceeding the limit, Task.status=failed with the reason recorded |
| M1-5 | tool security boundaries | `pytest tests/unit -k tool_security` | calc rejects non-whitelisted expressions (name/function injection); http_request blocks private IPs / cloud metadata / unvalidated redirects / DNS rebinding (with injected fake-resolver cases); file_write rejects `..` traversal and out-of-sandbox symlinks |

### M1-2 command block (event observation channel + sandbox output path)

```bash
python examples/run_agent.py "compute (123*456)/7 and write the result to out.txt"
echo "exit=$?"
# run_agent convention: task_id is printed at startup; events land in logs/agent-<task_id>.jsonl (ARCHITECTURE §8)
TASK_ID=<the task ID printed by run_agent>
jq -r 'select(.type=="tool_call") | .payload.tool_name' "logs/agent-${TASK_ID}.jsonl" | sort | uniq -c
cat "data/out.txt"
```

> Key points: ① `examples/run_agent.py` **reads .env itself** via pydantic-settings (subject to the `CALC_AGENT_ENV_FILE` path override) — with .env missing and no keys in the environment it **must fail loudly with a non-zero exit, never silently pass** (the `export $(grep … | xargs)` pattern is deprecated: its empty-argument exit 0 masks load failures and truncates values containing spaces); ② the event observation channel is the JSONL event log (`logs/agent-<task_id>.jsonl`); ③ the output file lives in the file_write sandbox at `data/out.txt` (ARCHITECTURE §6.3); ④ jq is a system tool (macOS `brew install jq`), outside the Python dependency allow-list, and a `python -c` equivalent may replace it.

## M2 — Persistence + API (incl. recovery semantics)

| ID | Criterion | Acceptance command | Pass condition |
|----|------|----------|----------|
| M2-1 | state written to the DB on change | `pytest tests/unit -k storage` | every state change has a corresponding record |
| M2-2 | checkpoint recovery | manual drill: start a task → `kill -9` the service mid-run → restart → `curl -sf -X POST localhost:8000/tasks/<id>/resume`; automated: `pytest tests/integration -k resume` | the task continues from the checkpoint and completes; succeeded calls reuse their results without re-execution (the test asserts no new tool_call_id and an unchanged updated_at for succeeded calls in the ToolCall table) |
| M2-3 | SSE event stream | `curl -sfN localhost:8000/tasks/<id>/events \| tee /tmp/sse.log` (while the task runs) | `status/tool_call/tool_result` events arrive in order (no thought); event `id:` carries a monotonically increasing seq; `final` arrives at termination; after saving, seq monotonicity and the presence of final are machine-checkable |
| M2-3b | SSE reconnection | see the M2-3b command block below; automated: `pytest tests/integration -k sse_reconnect` | the first event after reconnecting has `id:` == MAX_SEQ+1; the two segments join into a continuous seq with nothing lost or duplicated |
| M2-4 | API contract | `curl -sf localhost:8000/openapi.json` | the schema matches ARCHITECTURE.md §3 (incl. the cancel/confirm endpoints; path-parameter names may be compared semantically, e.g. `{id}` vs `{task_id}`). Machine check suggested: `curl -sf localhost:8000/openapi.json \| jq -r '.paths \| keys[]'` to verify endpoint presence |
| M2-5 | uncertain non-idempotent recovery → paused | automated: `pytest tests/integration -k uncertain_nonidempotent`; supporting manual drill: simulate a `file_write` call being `kill -9`ed mid-execution → restart → `POST /tasks/<id>/resume` (**recovery is manually triggered**; no auto-scan on restart, see ARCHITECTURE §5.1) | the recovery flow finds the uncertain non-idempotent call and sets the task to `paused` (**no auto-retry**); only after `POST /tasks/<id>/tool-calls/<tool_call_id>/confirm` does it continue (retry creates a new call ID / skip marks failed and returns to the LLM) |
| M2-6 | uncertain idempotent tool auto-retry | `pytest tests/integration -k uncertain_idempotent` | a GET-style http_request (call-level effective idempotency = idempotent, see ARCHITECTURE §6.4) that went uncertain auto-retries once on resume and completes; if the retry is still uncertain → paused |
| M2-7 | concurrent resume rejected | see the M2-7 command block below; automated: `pytest tests/integration -k concurrent_resume` | two concurrent resume requests yield **exactly one 200 and one 409** — only one active execution per task at a time |
| M2-8 | task cancellation | happy path: while the task runs, `curl -sf -X POST localhost:8000/tasks/<id>/cancel`; internal-state and event assertions: `pytest tests/integration -k cancel` | dispatch of new calls stops; pending calls are marked failed(cancelled); in-flight calls are marked uncertain; the task reaches the terminal state cancelled and a final event arrives; cancelling paused/pending tasks is equally legal (ARCHITECTURE §5.1) |

### M2-3b command block (Last-Event-ID reconnection)

```bash
# first connection; after receiving some events, disconnect with Ctrl-C
curl -sfN localhost:8000/tasks/<id>/events | tee /tmp/sse1.log
MAX_SEQ=$(grep '^id:' /tmp/sse1.log | tail -1 | awk '{print $2}')
# reconnect carrying Last-Event-ID
curl -sfN -H "Last-Event-ID: ${MAX_SEQ}" localhost:8000/tasks/<id>/events | tee /tmp/sse2.log
```

> Verdict: the first event in sse2.log has `id:` == MAX_SEQ+1; the two segments join into a continuous seq, nothing lost or duplicated.

### M2-7 command block (the 409 verdict — note: no `-f`)

```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST localhost:8000/tasks/<id>/resume &
curl -s -o /dev/null -w '%{http_code}\n' -X POST localhost:8000/tasks/<id>/resume
wait
```

> Verdict: the two output lines are exactly {200, 409}, one each. **No `-f`**: with `-f`, curl exits 22 on 409, so the exit code cannot distinguish "the expected 409" from "an unexpected error"; the status code must be captured with `-w '%{http_code}'` and judged on that.

## M3 — Frontend

| ID | Criterion | Acceptance command | Pass condition |
|----|------|----------|----------|
| M3-1 | end-to-end visualization | a browser (or a Playwright script — **Playwright is not on the §2.1 dependency allow-list; the Architect must update the list before adoption; manual browser acceptance suffices**) creates a task | the timeline renders ≥ 2 tool-call events live plus the final result (`final` marks end-of-stream) |
| M3-2 | no frontend errors | the browser console | 0 errors |

## M4 — End-to-end acceptance (project level)

| ID | Criterion | Acceptance command | Pass condition |
|----|------|----------|----------|
| E2E-1 | full chain on a real LLM | `python examples/run_agent.py "fetch the example.com title with http_request, count the characters with calc, and write the result to report.txt"` (run_agent reads .env itself, see the M1-2 key points; event counting via the jq approach of the M1-2 block) | **tool_call events ≥ 3 with exactly 3 distinct tools (http_request/calc/file_write all present)**; `data/report.txt` matches the actual HTTP response content and calc's actual computation (QA cross-checks); **passing off hardcoded output is forbidden**. Prerequisite: example.com must be on the `HTTP_ALLOWED_HOSTS` default allow-list (delivered with M1) |
| E2E-2 | trace replayable | `python -m cli.replay <task_id>` (cli.replay is the M2 observability deliverable, see ROADMAP) | the full event sequence matches the DB records (no thought events; compared as replay output vs a TaskEvent table query) |
| E2E-3 | robust in a key-less environment | see the E2E-3 command block below | e2e skips rather than erroring (key-less process environment with .env bypassed, so the verdict is not distorted); everything else green |
| E2E-4 | full G-1~G-5 gate | `bash scripts/check.sh` | check.sh covers **all of G-1 + G-2 + G-3 + G-4 + G-5a + G-5b**, each run independently with per-check results, all checks passing; no `\|\|` fallbacks (QA confirms by reading the check.sh source) |

### E2E-3 command block (key-less environment, .env bypassed)

```bash
env -i PATH="$PATH" HOME="$HOME" CALC_AGENT_ENV_FILE=/dev/null python -m pytest tests/e2e
```

> Key points: `env -i` clears only the process environment, not the .env file — if .env holds real keys, e2e would really run instead of skipping, distorting the verdict; hence `CALC_AGENT_ENV_FILE=/dev/null` must bypass .env. `HOME` is kept to avoid cache/temp-dir errors producing false negatives.

## Acceptance report template

QA produces `docs/handoff/qa-<milestone>.md`: every ID → a summary of the actual command output → pass/fail → failure attribution and the party it is returned to.

## Changelog

### v1.0 → v1.1

1. G-5 split into G-5a (pyright, exit code must be 0) and G-5b (compileall, exit code must be 0), run and judged independently; `||` fallbacks forbidden (fixing a false positive).
2. G-3's secret scan switched to fail-blocking semantics (grep exit 1 = pass, 0 = blocked, 2 = blocked); the `|| echo CLEAN` fallback removed; the optional M4 adoption of gitleaks/detect-secrets noted.
3. M0-2 no longer allows 0 collected; at least one real test must be collected and pass (the /health endpoint test); M0-4 (pyright dependency in place) added.
4. M1-1b added: FakeLLM integration tests must pass in an environment without real keys.
5. M1-2 / E2E-1 strengthened: actually occurring tool calls must be asserted, output-file content must match the actual computation, and hardcoded output must not be passed off.
6. M1-5 (tool security boundaries) added.
7. Recovery-semantics acceptance added: M2-3b (SSE Last-Event-ID reconnection), M2-5 (uncertain non-idempotent recovery → paused awaiting confirmation), M2-6 (uncertain idempotent auto-retry once), M2-7 (concurrent resume rejected with 409), M2-8 (cancel semantics); M2-2/M2-3 verdicts refined.

### v1.1 → v1.2 (revised per the architecture review + QA acceptance-criteria check reports)

1. **[P0-1]** G-2's command switched to `--cov-report=term-missing` with the verdict noting it takes effect from M1 (M0 only requires the command to run); pytest-cov added to the ARCHITECTURE §2.1 dependency allow-list and the ROADMAP M0 install list.
2. **[P0-2]** G-4's verdict quantified as "exit code 0 and no reverse-import output"; `scripts/check_layers.py` listed among the ROADMAP M0 deliverables (Backend implements); check.sh's content list gained G-4, consistent with E2E-4.
3. **[P0-3]** G-1's verdict changed to "check.sh runs each check independently and prints per-check results (aggregate exit code + per-check report), all checks passing" — failures are attributable; pytest is no longer judged on the aggregate exit code alone.
4. **[P1] G-3**: the command switched to the machine-judgeable `rc=$?; [ "$rc" -eq 1 ]` form (dropping `; echo "exit=$?"`); the regex gained `sk-[a-z0-9_-]{8,}` covering the `sk-proj-`/`sk-ant-` prefixes; notes added on check.sh integration (mind set -e) and the fixture placeholder-key exemption.
5. **[P1] M0-1**: readiness-wait loop + flag-based verdict (guarding against the all-failed run ending in sleep with exit 0) + exact body match + process cleanup.
6. **[P1] M0-3 / M1-1b / E2E-3**: adopted `CALC_AGENT_ENV_FILE=/dev/null` (newly defined in ARCHITECTURE §7) to explicitly bypass .env, forming dual-channel clearing together with the environment-variable unset; E2E-3 keeps `HOME` to prevent false negatives.
7. **[P1] M1-2**: deprecated `export $(grep … | xargs)` in favor of run_agent reading .env itself and failing loudly on a missing key; the event observation channel fixed as `logs/agent-<task_id>.jsonl` (jq counting, with its system-tool nature noted); the output path changed to the sandbox `data/out.txt`.
8. **[P1/P2] M2-3b / M2-5 / M2-6 / M2-7 / M2-8**: executable commands and pytest selectors added (`-k sse_reconnect / uncertain_nonidempotent / uncertain_idempotent / concurrent_resume / cancel`); M2-5's wording drops "auto resume" (recovery is manually triggered); M2-7 captures the code with `-w '%{http_code}'` (without `-f`, since curl exits 22 on 409); M2-2/M2-4/M2-3 verdicts gained automated carriers and machine-check suggestions.
9. **[P1] E2E-1**: the verdict corrected to "tool_call events ≥ 3 with exactly 3 distinct tools" (resolving the self-contradiction between ≥2 and all-three-present); added the event observation channel, the `data/report.txt` sandbox path, the example.com allow-list prerequisite, and unified key loading (run_agent reads .env itself); E2E-2 notes cli.replay belongs to M2.
10. M0-4 / G-5a gained the missing-Node.js-runtime-counts-as-unmet judgment; M3-1's Playwright note gained the dependency red-line parenthetical.
