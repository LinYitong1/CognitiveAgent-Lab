# 03 — Implementation Report (Agent Foundation Hardening, Phase 1)

## Files changed

| File | Change | Behavior difference |
|---|---|---|
| `src/models/agent_result.py` | + `termination_reason: str = ""`, `usage: dict[str, int] | None = None` | additive fields; absent/legacy constructions unchanged |

**`termination_reason` typing convention (no refactor made or needed).** The static type is plain `str` — deliberately not a `Literal`/`Enum`, so existing consumers and serializations see no schema churn. The closed set `{model_final_answer, max_steps_exceeded, llm_error}` is a **documented runtime convention**: the AgentLoop is the only writer and emits only these three values (asserted per path in `test_loop_observability.py`); `""` means legacy/absent. Consumers needing exhaustiveness should treat unknown non-empty strings as forward-compatible future reasons, not errors.
| `src/agent/registry.py` | + `classify_tool_error()` + `TOOL_ERROR_CATEGORIES` (frozen prefix → closed category mapping) | pure addition; `execute()` untouched |
| `src/agent/loop.py` | accumulate usage per round; `duration_ms` (perf_counter) on tool_result; `error_category` on failures; structured `termination_reason`; enriched `final` payload (`termination_reason`, `model_calls`, `tool_calls_total`, `usage`) | message flow, tool execution, termination semantics, event types, seq scheme — all unchanged; only additive payload keys/result fields |
| `docs/ARCHITECTURE.md` | implementation-status banner (P0-1) | readers can no longer mistake the design plan for the implementation |
| `scripts/agent_eval.py` | new offline evaluation harness (P1-4) | see 04 |
| `tests/integration/test_lifecycle_baseline.py` | new, 6 tests (Phase B baseline) | pins current lifecycle behavior |
| `tests/integration/test_loop_observability.py` | new, 6 tests | covers every new field/key |

## What was NOT changed (verified)

- Experiment engine, validators, fingerprints, golden files: **zero diffs under `src/experiment/`**; golden HTML + v1/manor fingerprints byte-identical (402/402 incl. all golden tests).
- ReAct autonomy: the loop still lets the model choose every tool, order, and stop point; no if-else planning, no hardcoded sequences.
- Security controls: sandbox path rule, SSRF chain, AST whitelist untouched (their dedicated attack tests pass).
- Event semantics: same five event types, same seq continuity, same disk-first JSONL; new keys are additive.
- Provider compatibility: `provider_extra` round-trip untouched; no-usage providers (FakeLLM, scripts) yield `usage: null`, never fabricated numbers.

## Test evidence

- Pre-change suite (390) passes unmodified → no regression.
- +12 new tests (6 lifecycle baseline + 6 observability) → **402 passed**, coverage 89.28% (gate 85%), pyright 0 errors, `scripts/check.sh` six gates PASS.
- Termination reasons asserted for all three paths; usage accumulation asserted across rounds (incl. a `reasoning_tokens` extra key); error categories asserted for `unknown_tool` / `invalid_arguments` / `policy_blocked`; `duration_ms >= 0` on every tool_result; category absent on success.

## Known limitations after this round

1. Token usage is only as good as provider reporting; FakeLLM/scripted runs record `null` by design.
2. `validate_experiment`/`validate_game` verdicts still travel inside `ok=True` payloads — event-level `ok` cannot distinguish them (audit finding; the eval harness parses payloads; a future `validation` event type would be a public-schema change, deferred).
3. Context growth unbounded (P2); long real-LLM tasks can still hit provider limits — now at least observable via usage totals, and termination stays explicit.
4. Prompt-injection resistance untested (needs real-LLM red-teaming). Tightened risk statement: untrusted tool-result content — notably `http_request` responses (host allow-listed but content unfiltered) and any file the model reads back — enters the conversation as plain tool messages. A cross-tool leakage chain is possible: injected instructions → `file_read` of sandbox data → smuggling that data out via a crafted GET URL/query to an allow-listed host (HTTP is GET-only; no request body, and hosts are exact-match allow-listed before DNS — default `example.com` only). Blast radius is therefore *narrowed*, not eliminated: URL-parameter-sized exfiltration to allow-listed hosts plus in-sandbox writes. Documented in 02/05; hardening deferred.
