# 02 — Hardening Plan (Agent Foundation Hardening, Phase 1)

## Priorities (from the 01 audit; only audit-confirmed items enter implementation)

### P0 — correctness / honesty defects

| # | Item | Why necessary | Change |
|---|---|---|---|
| P0-1 | `docs/ARCHITECTURE.md` presents unimplemented SQLite persistence, `/tasks` API, SSE reconnection, `src/storage/`, `web/` as the locked architecture with no status marking | The hardening brief explicitly forbids describing unimplemented capabilities as current; the doc is the first thing a reader opens | Implementation-status banner at the top (design-plan vs implemented core), pointing to `01-baseline-audit.md`; no content rewrite |

### P1 — clear reliability benefit, minimal implementation

| # | Item | Why necessary | Change | Before → after |
|---|---|---|---|---|
| P1-1 | Structured termination reason | "Termination reason distribution" is a required eval metric; currently buried in `result` text and `status` conflates incomplete with failed | `AgentResult.termination_reason` (closed set: `model_final_answer \| max_steps_exceeded \| llm_error`), mirrored in the `final` event; `status` unchanged for compatibility | callers parsed text → typed field |
| P1-2 | Cumulative token usage + call counts | `LLMResponse.usage` (M3) is captured then dropped by the loop; resource accounting impossible from logs | accumulate per-round usage; expose on `final` payload + `AgentResult.usage`; `null` when the provider never reports (FakeLLM) — never fabricated | usage invisible → recorded or null |
| P1-3 | Tool duration + error category | observability metrics (durations, error taxonomy) required by the brief; error strings already carry frozen prefixes | `duration_ms` on every `tool_result`; `error_category` on failures via `classify_tool_error` (prefix mapping, `src/agent/registry.py`) — no new exception system | plain summaries → tagged events |
| P1-4 | Offline evaluation harness | pytest pass-rate ≠ agent success rate; no committed repeatable agent-level eval existed | `scripts/agent_eval.py`: 8 scripted scenarios through the real loop + real tools, 4-layer metrics, JSON+MD reports, real-LLM section always "pending" | no eval → repeatable offline baseline |

### P2 — documented, deliberately NOT implemented this round

| Item | Trigger for a later phase |
|---|---|
| Context overflow detection / compaction | long-horizon tasks actually hitting provider context limits; compaction must provably preserve tool_call/tool_result pairing + provider metadata (Gemini protocol) — not attempted without a correctness proof |
| Prompt-injection hardening | requires real-LLM red-teaming; see the tightened risk statement in 01 §security — untrusted tool-result content (incl. HTTP responses) enters the conversation unfiltered, and a cross-tool chain exists (http_request response → injected instructions → file_read of sandbox data → data smuggled out via GET URL/query to an allow-listed host). Mitigating facts: HTTP is GET-only (no request body) and outbound hosts are exact-match allow-listed **before DNS** (default `example.com` only) — so exfiltration bandwidth is limited to URL path/query construction and file_write inside the sandbox; an operator widening the allow-list (or allowing a host that logs URLs) enlarges the channel |
| SQLite persistence / resume / checkpoints | multi-session task management becomes a real requirement; design already sketched in ARCHITECTURE.md |
| Tool-call budget separate from model-step budget | observed abuse pattern (many calls per round) in real traces |
| HITL approval for irreversible actions | when tools gain genuinely irreversible reach beyond the sandbox |

## Explicitly rejected changes

- **No framework migration** (LangChain/LangGraph/Agents SDK/PydanticAI) — the loop is 171 lines and audited; framework abstractions remove exactly the controls this project froze (byte-exact tool docs, history fidelity).
- **No new exception taxonomy** — the four frozen error-string prefixes already carry the categories; classification is derived, not duplicated.
- **No auto context compaction** — cannot yet prove pairing/metadata preservation; monitoring + explicit failure preferred over silent corruption.
- **No changes to the experiment engine, validators, fingerprints, or golden files** — deterministic core untouched (verified byte-identical in 03).

## Compatibility strategy

All changes are additive: new `AgentResult` fields default (`""`, `None`); new event-payload keys coexist with existing ones; `status` values unchanged; existing event consumers parse payloads additively (the local real-LLM eval harness verified unaffected). The 390-test pre-change suite passes unmodified (plus 12 new tests).
