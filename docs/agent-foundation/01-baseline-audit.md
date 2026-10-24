# 01 — Baseline Audit (Agent Foundation Hardening, Phase 1)

Date: 2026-10-24 ｜ Git: `5719f3274adf7f6f5f5b3d3ed0e147d74519e` (== origin/main) ｜ Workspace clean (one intentionally-untracked local report)

Method: read-only code audit of the actual implementation (not README/ARCHITECTURE claims), cross-checked against the three reference frameworks' engineering practices (OpenAI Agents SDK runner lifecycle/guardrails, PydanticAI tool validation/retries/usage limits, LangGraph persistence semantics — patterns only, no framework adoption).

## Pre-change baseline

| Item | Value |
|---|---|
| Tests | 390 passed (before this round's additions) |
| Coverage | 89.28% (gate 85%) |
| pyright | 0 errors |
| `scripts/check.sh` | all six gates PASS |
| Real-LLM evidence | T5 success (1 run, $0.036), T2R budget-stopped (10 requests, $0.1043) — archived traces |

## Gap matrix (code evidence)

| Dimension | Existing implementation | Reference practice | Gap | Severity | Recommendation |
|---|---|---|---|---|---|
| Agent lifecycle | `src/agent/loop.py` `run_task`: single while-loop, 3 termination paths, max-steps guard (default 25, `src/config.py:30`) | runner lifecycle with structured run status | termination cause only in result text | P1 | add structured `termination_reason` |
| LLM protocol | `src/agent/llm.py`: OpenAI-compat client, timeout 60s, SDK retries 2, `LLMProtocolError` for protocol violations; provider_extra round-trip (Gemini thought_signature) verified by tests | client protocol + retries | **meets/exceeds** for this scope | — | none |
| Tool calling | `src/agent/registry.py:50-64`: unknown tool / ValidationError / executor exceptions all become `ToolResult(ok=False)`; strict Pydantic schemas (`extra=forbid`); multi-call ordering + ID pairing tested (`tests/integration/test_lifecycle_baseline.py`) | tool validation contracts | **implemented** | — | none |
| Argument validation | input-model `model_validate` per call, extra fields rejected | same | **implemented** | — | none |
| Tool error handling | error strings with frozen prefixes (`unknown tool:` / `invalid arguments:` / `tool execution failed:` / `BLOCKED:`) | typed error taxonomy | categories not exposed on events | P1 | classify into closed set (no new exception system) |
| Retry policy | transport retries at SDK layer only; loop never retries side-effecting tools; security refusals never retried; step cap prevents loops | bounded retries per class | **implemented** (minimal & correct) | — | none |
| Run status | `AgentResult.status`: `"completed" \| "failed"`; pipeline layer separates artifact verification (`PipelineResult.bundle_verification`, `src/pipeline.py:65-88`) | execution vs verification status | binary at loop level; pipeline layer already separates | Partially | keep status; add `termination_reason` (compat) |
| Artifact verification | `verify_bundle` recomputes fingerprints without the generator; `run_demo` fails loudly (`PipelineVerificationError`); GameSpec G8 vs bundle | independent verification | **implemented** | — | none |
| Context management | messages appended in full, no trimming/compaction | context budget management | unbounded growth | P2 (this phase) | monitor + document; no auto-compaction without correctness proof |
| Resource limits | `calc_agent_max_steps` (model calls); per-tool caps (file 64KB read, HTTP 1MB/10s, export size cap) | usage limits + budgets | model-call limit = step limit; **no token accounting at loop level** (usage captured in `LLMResponse.usage` but dropped by the loop) | P1 | record cumulative usage (null when unreported — never fabricated) |
| Observability | JSONL event log, disk-first, no thought events, 512-char summaries; seq continuity tested | tracing with durations/usage | no tool duration, no usage on events, no error categories | P1 | additive payload keys + result fields |
| Security boundaries | five-step sandbox path rule (realpath + per-level lstat), SSRF six-step chain (resolve-then-connect, DNS-rebinding test; **GET-only**, hosts exact-match allow-listed **before DNS**, default `example.com`), calc AST whitelist, all under dedicated attack tests | sandboxing + policy | **implemented and tested**; prompt-injection via tool results untested (needs real LLM). Known cross-tool chain (unmitigated, documented): untrusted HTTP/file content → injected instructions → `file_read` sandbox data → exfiltration via GET URL/query to an allow-listed host — narrowed (no request body, host-gated) but not eliminated | P2 (injection) | document precisely as untested risk (02/03/05) |
| Evaluation | 390-test suite + FakeLLM workflow tests + local (uncommitted) real-LLM eval harness | layered eval with metrics | no committed, structured, repeatable agent-level eval; pytest pass ≠ agent success rate | P1 | offline harness with 4-layer metrics |

## Documentation vs implementation (the P0 finding)

`docs/ARCHITECTURE.md` (v1.2 design plan) describes SQLite persistence, `POST /tasks` API, SSE streaming with `Last-Event-ID` reconnection, checkpoints/recovery locks, and `src/storage/` — **none of which exist** (`src/api/app.py` has only `GET /health`; `src/storage/` is absent; `AgentLoop` docstring says "no persistence, no recovery semantics"). README makes no such claims (verified). Fixed in this round by an implementation-status banner on ARCHITECTURE.md; the full SQLite/resume/SSE stack remains **planned, not implemented** (P2, see 05).

## Lifecycle baseline (10 scenarios, pre-change)

Four scenarios already covered by `tests/integration/test_loop.py` (normal completion, step limit, tool failure not fatal, LLM error). Six added in `tests/integration/test_lifecycle_baseline.py` (unknown tool; schema-invalid arguments; structured validation failure via `validate_experiment`; partial artifacts then stop; two tool calls in one round incl. message history shape; direct answer round 1). All pass against the pre-change code — **no pre-existing lifecycle defect found**. One audit finding recorded: `validate_experiment` returns `ok=True` with the verdict inside the payload, so validation failures are invisible at the event `ok` level (evaluation must parse payloads; harness does).
