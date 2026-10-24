# 06 — Final Acceptance Review (independent, pre-commit)

Date: 2026-10-24 ｜ Reviewer pass over the Phase 1 hardening changes. Review-only round: no new features, no refactor, no paid LLM calls, no git commit/push.

## 1. Real git diff reconciliation

- Tracked modifications: **4 files, +98/−11** (`docs/ARCHITECTURE.md`, `src/agent/loop.py`, `src/agent/registry.py`, `src/models/agent_result.py`).
- New files: **9** — `docs/agent-foundation/` (6: 01–05 + 04 appendix), `scripts/agent_eval.py`, `tests/integration/test_lifecycle_baseline.py`, `tests/integration/test_loop_observability.py`.
- The earlier "4 modified + 5 new" counted **git-status entries**, not files: `docs/agent-foundation/` is one untracked directory entry containing 6 files. Correct statement: 4 modified + 9 new files, of which 8 are committable and 1 (`docs/m3/M3A_T2R_REPORT.md`) is intentionally local-only.
- `src/experiment/`, `tests/fixtures/`, `tests/golden/`: **zero diffs** (engine/fixture/golden untouched).
- **⚠️ Commit-time precaution (the one open item):** `docs/m3/M3A_T2R_REPORT.md` is NOT gitignored — `git add .` would stage it. The commit round must either add explicit paths or gitignore that file first. No other unintentional inclusions found; all 8 committable new files are correctly trackable (verified via check-ignore).

## 2. ReAct behavior compatibility (old loop from git HEAD vs new, identical scripts)

| Property | Result |
|---|---|
| LLM message sequences (all rounds, sorted-key JSON) | **byte-exact identical** |
| status / result / steps | identical |
| Event type sequence & count | identical |
| tool_call_id sequence (`call_0002/0004/0006`) | identical |
| tool_result `result_summary` values | identical |
| provider_extra round-trip (Gemini thought_signature shape) | verbatim (initial "False" was a test-input error on the reviewer's side; re-verified with the correct inner-dict shape) |
| Payload keys | strictly additive: `+duration_ms` (tool_result), `+error_category` (failed tool_result), `+termination_reason/model_calls/tool_calls_total/usage` (final) |
| Termination semantics | unchanged; `termination_reason` asserted on all three paths (model_final_answer / max_steps_exceeded / llm_error) by `test_loop_observability.py` |

## 3. Evaluation-metric correctness (corrections applied this round)

- **Framing**: ScriptedLLM completion/success rates are offline scenario pass rates — not real-LLM success probabilities. Real-LLM section permanently `pending`. (Already stated; now also in threats-to-validity.)
- **Denominators** (now documented in 04): rates are per-scenario, first run only (the second run is a determinism check); completion/L3/false-success divide by all 8 executed scenarios (including designed probes); repair rate divides by feedback-seen scenarios; recovery rate divides by hard-error scenarios (None when empty).
- **L4 rename**: the label-masking check is now explicitly a **heuristic check**, not a "detector" or validity oracle. Documented false-positive (timing-only real manipulations), false-negative (coincidental content differences uncorrelated with the factor), over-masking (common-substring level names), and applicability (text-line designs with materialized stimulus only). **No claim of general scientific-validity verification** — it is a cheap screen for the one failure class observed in a real run (T2R).
- **Usage accumulation semantics**: verified empirically — only rounds that report usage contribute; mixed-reporting totals are **lower bounds**, now documented as such. Provider-never-reports → `null`, never fabricated.
- **error_category for unknown errors**: closed-set `other` fallback, asserted in `test_classify_tool_error_closed_set`.

## 4. Final regression

- Full suite: **402/402 passed** (390 pre-existing unmodified + 12 new).
- `scripts/check.sh`: all six gates PASS (pytest, coverage ≥85%, secret scan, layering, pyright 0, compileall).
- Security tests (calc/http_request/file_write/file_read incl. traversal, symlink, SSRF, DNS-rebinding cases): 51/51 passed — no degradation.
- Golden HTML byte-identity and bundle fingerprints: covered by the suite, zero unexpected changes.
- No paid API calls this round (harness and all tests are offline; network tools use fake resolvers).

## 5. Acceptance classification

**A. Genuinely improved engineering capability (behavior-changing, tested):**
- Termination cause is now a typed, closed-set field on every path (was text-only).
- Tool failures carry deterministic error categories (frozen-prefix mapping) and durations.
- A repeatable, deterministic offline evaluation harness now exists (added in this change set) with 4-layer metrics and a designed false-success probe that the offline L4 heuristic correctly flags.
- ARCHITECTURE.md no longer presents unimplemented persistence/SSE/API as current architecture.

**B. Observability added, reliability improvement NOT yet proven:**
- Cumulative token usage (needs a real reporting provider to be meaningful; lower-bound semantics).
- Validation-repair-rate metric (scripted evidence only).
- L4 label-masking heuristic (deterministic on the observed T2R class; unproven on real LLM outputs).

**C. Open, deliberately not implemented this phase (P2 backlog, see 05):**
- Context overflow handling/compaction; prompt-injection hardening (needs real-LLM red-teaming); SQLite persistence/resume; separate tool-call budget; `validation` event type (public schema change); real-LLM re-evaluation (needs authorization).

**D. Commit readiness: YES, with one precaution.**
All gates green, compatibility proven byte-exact, engine/security/golden untouched, metrics honestly framed. The commit round must stage paths **explicitly** (or gitignore `docs/m3/M3A_T2R_REPORT.md`) so the intentionally-local T2R report is not swept in by `git add .`.
