# CognitiveAgent Lab — Development Roadmap

> Version: v1.2 (revised per the architecture review and the QA acceptance-criteria check reports) ｜ Precondition: M0 starts after `docs/ARCHITECTURE.md` (v1.2) is user-approved
> Cadence: at the end of every milestone, QA runs the acceptance commands from ACCEPTANCE_CRITERIA (v1.2); only a pass moves to the next one.

## M0 — Project scaffolding (half a day)

- Set up the `src/ tests/ web/ docs/handoff/` directory structure with empty `__init__` files (tests split into `tests/unit/ tests/integration/ tests/e2e/`).
- Install dependencies into the venv (matching ARCHITECTURE.md §2.1; nothing beyond it): `fastapi uvicorn pydantic pydantic-settings pytest pytest-asyncio httpx openai pyright pytest-cov` (the last two in the dev group).
- `pyproject.toml` + `.env.example` (incl. `CALC_AGENT_ENV_FILE`, see ARCHITECTURE §7) + `.gitignore` (incl. `.env`, `logs/`, `*.db`) + git init.
- `/health` endpoint plus its pytest test (satisfying M0-2 "≥ 1 collected").
- **`scripts/check_layers.py` (Backend implements; Architect supplies the rules)**: the layering check — verifies the one-way `api→services→agent→tools/storage` direction, that `src/models/` is referenced only, and bans reverse imports (the basis of gate G-4).
- CI script `scripts/check.sh`: **the full G-1 + G-2 + G-3 + G-4 + G-5a + G-5b set**, each check **run independently with explicit `if` exit-code branching (no reliance on a `set -e` chain) and per-check reporting**; the aggregate exit code is non-zero if any check fails — consistent with E2E-4, failures are attributable.
- **Acceptance**: M0-1 ~ M0-4 + G-4 (`python -m scripts.check_layers` exits 0, effective from M0).

## M1 — Agent core loop + tool security (2-3 days) ｜ Backend + Architect

- `src/agent/llm.py`: LLMClient (env-based config, timeout, retries; supports the `CALC_AGENT_ENV_FILE` path override).
- `src/agent/registry.py`: tool registration (Pydantic → JSON schema auto-generation) + **mandatory `idempotency` and `risk_level` declarations** (missing values fail registration) + the call-level effective-idempotency override rules (ARCHITECTURE §6.4).
- `src/agent/loop.py`: the main loop (plan→act→observe, step limit, exception capture; stable `tool_call_id` assignment; internal reasoning never enters the event stream).
- The first 3 tools (with **secure implementations**; rules in ARCHITECTURE.md §6):
  - `calc`: AST-whitelist node evaluation (no eval/exec/name resolution), with expression-length and operator-depth limits; declared idempotent.
  - `http_request`: http/https only, host allow-list (**the default allow-list contains example.com**, a prerequisite of E2E-1), blocking of private/reserved IP ranges after DNS resolution (incl. 169.254.169.254), **resolve-then-connect (connect directly to the validated IP; a second resolution is forbidden)**, per-hop redirect re-validation, timeout and response-size caps; declared non-idempotent (GET overridden to idempotent).
  - `file_write`: the `data/` sandbox, realpath-then-prefix validation, rejection of `..` and symlinks at any directory level, a file-size cap; declared non-idempotent.
- `examples/run_agent.py` (**M1 deliverable**): a CLI entry — reads .env itself via pydantic-settings (a missing key is an explicit non-zero exit, never silently passed), prints task_id at startup, and writes output files into the `data/` sandbox.
- Integration tests: a FakeLLM injects preset tool-call sequences to drive the loop; **the key-less environment must be covered** (`env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY CALC_AGENT_ENV_FILE=/dev/null pytest tests/integration`).
- Unit tests: tool-security attack cases (expression injection, SSRF private IP / cloud metadata / redirect bypass / DNS-rebinding fake resolver, path traversal / symlinks).
- **Acceptance**: M1-1 / M1-1b / M1-2 / M1-3 / M1-4 / M1-5 (see ACCEPTANCE_CRITERIA v1.2).

## M2 — Persistence + API + recovery semantics (2-3 days) ｜ Backend, QA writes tests in parallel

- `src/storage/`: the four tables Task/Step/ToolCall/TaskEvent + repository; optimistic concurrency control via Task.version.
- **Recovery-semantics implementation (lives in the `src/services/` orchestration layer — transaction boundaries, checkpoints and the recovery lock belong there; do not scatter them into api/agent layers, or G-4 breaks)**, rules in ARCHITECTURE.md §5.1:
  - checkpoint: persist the full context before a tool call enters running (task state + completed steps + pending calls).
  - Recovery policy matrix: succeeded is reused, not re-executed; failed lets the LLM retry with new arguments (a new call ID); uncertain idempotent tools auto-retry once (same ID + attempt number); **uncertain non-idempotent tools must not auto-retry → the task goes paused**.
  - Confirm API: `POST /tasks/{id}/tool-calls/{tool_call_id}/confirm` (retry / skip).
  - Cancel API: `POST /tasks/{id}/cancel` (applies to running/paused/pending; stops dispatch, marks in-flight calls uncertain, terminal state cancelled — incl. the `paused→cancelled` and `pending→cancelled` transitions).
  - Recovery lock + **fencing**: only one active execution per task at a time; concurrent resumes get 409; the active execution holds a version execution token; dispatch/DB writes use CAS conditional updates; a preempted execution terminates itself.
- `src/api/`: task CRUD + the SSE event-stream endpoint (public events `status|tool_call|tool_result|error|final`; `id:` carries a per-task monotonically increasing seq; `Last-Event-ID` reconnection with events persisted before being pushed; final is always sent).
- The `cli.replay` command (**the M2 observability deliverable**, an E2E-2 dependency): `python -m cli.replay <task_id>` prints the full trace in time order.
- Tests: M2-2 ~ M2-8 (incl. kill -9 interruption recovery, uncertain non-idempotent → paused, concurrent resume 409, SSE reconnection, cancel incl. the paused/pending paths).
- **Acceptance**: M2-1 ~ M2-8 (see ACCEPTANCE_CRITERIA v1.2).

## M3 — Frontend visualization (1-2 days) ｜ Frontend

- Task-creation form, task list, execution-trace timeline (SSE-driven public event stream `status|tool_call|tool_result|error|final`, `final` marks end-of-stream, Last-Event-ID reconnect support), status panel.
- **Acceptance**: create a task in the browser and watch the live trace and final result; no console errors (manual browser acceptance suffices; before introducing Playwright the Architect must update the dependency list).

## M4 — End-to-end and hardening (1-2 days) ｜ QA-led

- E2E tests (real LLM, auto-skip without keys — use `CALC_AGENT_ENV_FILE=/dev/null` to bypass .env); fault-injection tests (tool failures, LLM timeouts, process interruption, recovery-preemption fencing).
- Coverage targets met (core modules ≥ 80%, G-2 effective from M1); `scripts/check.sh` fully green (G-1~G-4 + G-5a/G-5b judged independently per check).
- Optional enhancement: introduce `gitleaks` or `detect-secrets` for secret scanning (the Architect must update the dependency list first).
- **Acceptance**: every item of the ACCEPTANCE_CRITERIA v1.2 checklist passes, with an acceptance report produced.

## Ongoing mechanisms outside the milestones

- Every PR/task passes the code-review skill gate (run by QA).
- Architecture changes go through the architecture-review skill + an ARCHITECTURE.md version bump.
- Handoff documents land in `docs/handoff/`, traceable across sessions.

## Explicitly out of scope

- Multi-agent collaboration frameworks, RAG, integrating R code / cognitive models / experiment data, refactoring the pre-existing game projects, user authentication.

## Changelog

### v1.0 → v1.1

1. M0: the dependency list gained `pyright` (gate G-5a); added the `/health` test (M0-2 ≥ 1 collected); check.sh gained independent G-3/G-5a/G-5b judgments.
2. M1: title changed to "Agent core loop + tool security"; added the three tools' security-implementation tasks (calc AST whitelist, http_request SSRF protection, file_write sandbox) and the registry idempotency/risk fields; added the key-less integration tests and tool-security attack cases.
3. M2: title changed to "Persistence + API + recovery semantics"; added the recovery-semantics implementation (checkpoint, the recovery policy matrix, the confirm/cancel APIs, the recovery lock/optimistic concurrency); SSE gained seq/Last-Event-ID/final semantics and tests.
4. Path notation unified with the `src/` prefix (src/agent/, src/storage/, src/api/, etc.) and `tests/unit|integration|e2e`.

### v1.1 → v1.2 (revised per the architecture review and the QA acceptance-criteria check report)

1. **[P0-1]** M0's install list gained `pytest-cov` (dev group, the basis of gate G-2), synchronized with the ARCHITECTURE §2.1 allow-list.
2. **[P0-2]** M0's deliverables gained `scripts/check_layers.py` (Backend implements, Architect supplies the rules); the check.sh definition became **the full G-1~G-4 + G-5a/G-5b set**, run per check independently with per-check reports (explicit if branching, no set -e chain), consistent with E2E-4; M0's acceptance gained G-4.
3. **[P0-3 linked]** check.sh's per-check output requirement makes G-1 failures attributable (aggregate exit code + per-check report).
4. **[M-3]** M1's http_request task gained resolve-then-connect (connect directly to the validated IP, defending against the DNS-rebinding TOCTOU); the attack cases gained a fake-resolver rebinding case.
5. **[M-4]** M2's recovery-lock task gained fencing (a version execution token + CAS conditional updates + self-termination when preempted); M4's fault injection gained the "recovery-preemption fencing" scenario.
6. **[M-5]** M2's cancel task gained the applicable states (running/paused/pending, incl. the `paused→cancelled` and `pending→cancelled` transitions).
7. **[P1-6 linked]** M0's `.env.example` contains `CALC_AGENT_ENV_FILE`; M1's key-less test command and LLMClient use `CALC_AGENT_ENV_FILE=/dev/null` to bypass .env.
8. **[P1-7 linked]** M1's deliverables gained `examples/run_agent.py` (self-reading .env, explicit error on a missing key, prints task_id, output lands in the data/ sandbox); http_request's default allow-list notes it contains example.com (a prerequisite of E2E-1).
9. **[Minor]** M2's recovery-semantics implementation is explicitly owned by the `src/services/` orchestration layer; `cli.replay` is explicitly the M2 observability deliverable; the uncertain idempotent retry gained "same ID + attempt number".
