# CognitiveAgent Lab — Technical Architecture

> Version: v1.2 ｜ Status: **revised per review feedback** (v1.1 went through two independent reviews — the architecture review and the QA acceptance-criteria check; v1.2 fixes the P0/Major issues they raised)
> Decision records (ADRs) are appended at the end; the v1.0→v1.1 and v1.1→v1.2 changelogs are at the end too.

> **⚠️ Implementation status (added by the Foundation Hardening audit — read this first).**
> This document is the original **design plan**, not a description of the
> current codebase. As of HEAD the following sections describe capabilities
> that are **designed but NOT implemented**:
>
> - §5/§6 task API (`POST /tasks`, `/tasks/{id}/resume`) — not implemented;
>   `src/api/app.py` exposes only `GET /health`.
> - SSE event streaming (`Last-Event-ID` reconnection) — not implemented.
> - SQLite persistence, checkpoints, recovery locks, `src/storage/` — the
>   directory does not exist; the only persistence is the JSONL event log
>   (`src/agent/events.py`), and `AgentLoop` has no resume semantics.
> - The `web/` frontend — not implemented.
>
> What **is** implemented (the audited core): the single AgentLoop
> (`src/agent/loop.py`, max-steps guard, additive observability fields), the
> ToolRegistry with strict Pydantic tool schemas, 9 tools incl. the
> deterministic experiment engine and HTML renderer (`src/experiment/`),
> the pipeline facade with independent bundle verification (`src/pipeline.py`),
> and the JSONL event log. See `docs/agent-foundation/01-baseline-audit.md`
> for the full code-evidenced gap matrix.

## 1. System goal

Build an AI agent system that understands user goals, autonomously decomposes tasks, selects tools, executes multi-step workflows, persists task state, and produces execution results with observable logs. **Purely engineering-oriented**: no R code, cognitive models, or pre-existing experiment data are integrated.

## 2. Technology stack (locked)

| Layer | Choice | Rationale |
|----|------|------|
| Language | Python 3.13 | already available in the environment (managed runtime) |
| Web framework | FastAPI | native async, Pydantic integration, automatic OpenAPI docs |
| Data validation | Pydantic v2 + pydantic-settings | models as contracts; configuration loaded from environment variables |
| Testing | pytest + pytest-asyncio + httpx (TestClient) | layered test system |
| LLM access | the official `openai` SDK (supports a custom `base_url` for compatible endpoints; an `anthropic` SDK adapter slot is reserved) | **real tool-calling**, no rule-based simulation |
| Agent orchestration | **a self-built single main loop** (~300 lines of core code) | meets the "real runtime" bar without introducing a multi-agent framework (constraint 3) |
| State storage | SQLite (`sqlite3` + file-based DB) | zero deployment, persistent, sufficient; a Postgres migration slot is reserved |
| Frontend | native HTML/JS single page (`web/`) + SSE | good enough for task visualization; no React build chain |
| Observability | structured event logs (DB tables + JSONL files) | every step replayable, resumable |

### 2.1 Runtime dependencies and necessity (complete list; nothing beyond this)

| Dependency | Necessity (one sentence) |
|------|------------------|
| fastapi | web framework: routing, validation and OpenAPI docs for the task API and SSE endpoints |
| uvicorn | ASGI server: runs the FastAPI application (incl. long-lived SSE connections) |
| pydantic | data models as contracts: validation and serialization of requests/responses/tool arguments/event payloads |
| pydantic-settings | configuration management: loads keys and runtime parameters from environment variables/.env |
| pytest | test framework: the unit/integration/e2e layered test system |
| pytest-asyncio | async test support: runs async endpoint and agent main-loop tests |
| httpx | HTTP client: TestClient cross-checks + the `http_request` tool implementation |
| openai | LLM access: real tool-calling, supports switching to compatible endpoints via a custom `base_url` |
| pyright | static type checking: gate G-5a; mergeable only at exit code 0 |
| pytest-cov | coverage collection: the pytest plugin behind gate G-2 (provides the `--cov` flag) |

**Dependency red line**: the table above is the entire allow-list (pyright and pytest-cov serve only development checks and test metrics and live in the dev group); introducing any new dependency requires the Architect to update this table and bump the version first.

## 3. Layered architecture

```
┌───────────────────────────────────────────────────────────────┐
│  web/            task-creation form · execution-trace timeline │  Frontend Agent
│                  (public event stream)                         │
├───────────────────────────────────────────────────────────────┤
│  src/api/        FastAPI routing layer                          │  validation and dispatch only
│    POST /tasks                    create a task (goal)         │
│    GET  /tasks/{id}               task status + steps + result │
│    GET  /tasks/{id}/events        SSE public event stream      │
│                                   (reconnect supported)        │
│    POST /tasks/{id}/resume        resume an interrupted task   │
│                                   (recovery-lock governed)     │
│    POST /tasks/{id}/cancel        cancel a task                │
│    POST /tasks/{id}/tool-calls/{tool_call_id}/confirm          │
│                                   manual confirmation of an    │
│                                   uncertain non-idempotent call│
├───────────────────────────────────────────────────────────────┤
│  src/services/   orchestration layer (transaction boundaries,  │
│                   checkpoints, recovery lock)                  │
├───────────────────────────────────────────────────────────────┤
│  src/agent/      agent core (driven by a real LLM)             │  Backend Agent
│    loop.py       main loop: plan → act → observe               │
│    llm.py        LLMClient (unified wrapper, env config)       │
│    registry.py   tool registry (auto schema generation +       │
│                   idempotency/risk declarations)               │
├───────────────────────────────────────────────────────────────┤
│  src/tools/      tool implementations (Pydantic input +        │
│                   executor; security rules in §6)              │
│    calc.py http_request.py file_write.py …                     │
├───────────────────────────────────────────────────────────────┤
│  src/storage/    SQLite persistence (incl. recovery lock /     │
│                   optimistic-concurrency version)              │
│  src/models/     shared Pydantic schemas                       │
└───────────────────────────────────────────────────────────────┘
```

**Dependency direction** (mandatory, a code-review gate item): `api → services → agent → tools/storage`; `models` is referenced by every layer; reverse imports are forbidden.

### 3.1 SSE endpoint (GET /tasks/{id}/events)

- **Public event types** (converged, complete enumeration): `status | tool_call | tool_result | error | final`. **There is no `thought` event any more**: model-internal reasoning is never persisted to the public event stream (neither the DB event table, JSONL, nor SSE records thoughts).
- **Event payloads**:
  - `tool_call`: `tool_call_id`, `tool_name`, an argument summary (truncation cap, default 512 characters).
  - `tool_result`: `tool_call_id`, a success/failure flag, a result summary (truncation cap, default 512 characters).
  - `status`: task-state changes (incl. the transition reason).
  - `error`: unrecoverable / noteworthy error information.
  - `final`: **always emitted exactly once** at task termination (with the final state and a result summary); clients use it to detect end-of-stream.
- **Event sequence numbers**: a per-task `seq`, monotonically increasing (from 1, assigned atomically by the storage layer on write); the SSE message's `id:` field carries that `seq`.
- **Reconnection**: the endpoint honors the `Last-Event-ID` request header; after reconnecting, streaming resumes from `seq+1`. Events are **persisted first (TaskEvent table), then pushed**, so any persisted event can be replayed without relying on an in-memory buffer.
- On a terminal state (completed/failed/cancelled) the endpoint sends `final` and closes the stream normally; a client reconnecting to an already-terminal task gets all events replayed, ending with `final`.

## 4. Agent main-loop design (core)

```
init: Task(goal) → LLM(system prompt + tool list)
loop (≤ MAX_STEPS=25, per-step timeout configurable):
  1. the LLM returns tool_call(s) or a final_answer
     (the model may attach internal reasoning text, but it never
      enters any public event / persisted event stream)
  2. assign a stable tool_call_id per call → persist a checkpoint
     → the registry validates arguments → the executor runs the tool → exceptions captured
  3. every state change writes a TaskEvent(type ∈ {status, tool_call, tool_result, error}, seq)
  4. the tool result goes back to the LLM as a tool message
terminate: final_answer | step limit reached | unrecoverable error
      → Task.status = completed/failed + emit the final event (always)
```

- **Real LLM**: tool selection is decided by the model's tool-calling; the next step is unpredictable at runtime — this is the essential difference from "static rule simulation", and e2e tests must not hard-code behavior.
- **State persistence**: the four tables Task/Step/ToolCall/TaskEvent, written on every state change; after a process restart, `resume` continues from a checkpoint per the §5.1 recovery semantics.
- **Protections**: max steps, per-tool timeouts, tool exceptions are not fatal (errors go back to the LLM for self-correction).

## 5. Data model (key tables/models)

- `Task`: id, goal, status(`pending|running|completed|failed|paused|cancelled`), result, version (optimistic concurrency control / execution fencing token), created_at, updated_at
- `Step`: id, task_id, seq (step number within the task), tool_call_id (**no thought field** — model-internal reasoning is neither collected nor persisted)
- `ToolCall`: tool_call_id (stable call ID), task_id, seq (task-level event number, the same number space as TaskEvent.seq, assigned atomically by storage on write), tool_name, tool_args, status(`pending|running|succeeded|failed|uncertain`), result, error, idempotency (a snapshot of the **effective** idempotency of this call, see §6.4), created_at, updated_at
- `TaskEvent`: id, task_id, seq, type(`status|tool_call|tool_result|error|final`), payload (JSON), ts

Legal task-state-machine transitions:

```
pending → running → (completed | failed | paused | cancelled)
pending → cancelled                       (cancel an unstarted task directly)
paused  → running                         (resume, recovery-lock governed, see §5.1)
paused  → cancelled                       (a task awaiting confirmation can be cancelled, see §5.1 cancel semantics)
running → cancelled                       (see §5.1 cancel semantics)
```

`completed / failed / cancelled` are terminal states with no further transitions.

The event sequence number `seq`: per-task, monotonically increasing, assigned atomically by storage on write; within a task, events are persisted before being pushed (the SSE `id:` carries it; `Last-Event-ID` replay supported).

### 5.1 Task recovery and idempotency

**Stable call IDs**: every tool call gets a globally unique `tool_call_id` assigned before dispatch (event-sequence or UUID — one implementation, invariant for the call's lifetime). This ID is the single anchor for recovery, idempotency decisions, SSE event alignment, and manual confirmation.

**Tool-call state machine**:

```
pending → running → (succeeded | failed | uncertain)
```

- `succeeded/failed`: the executor returned normally (including the tool's own failures).
- `uncertain`: the call was dispatched but the outcome is unknown (e.g. the process was killed mid-execution; after a timeout it cannot be confirmed whether side effects occurred).

**Checkpoint semantics**: a checkpoint = the complete context persisted **before** a tool call enters `running` (task state + completed steps + the pending call with its tool_call_id). Recovery rebuilds the loop context from the last checkpoint.

**Idempotency tiers**: the tool registry must declare `idempotency: idempotent | non-idempotent` for every tool (see §6.4). The recovery policy follows the state × idempotency matrix:

| Call state | Idempotent tool | Non-idempotent tool |
|----------|----------|------------|
| `succeeded` | reuse the stored result directly, **no re-execution** | reuse the stored result directly, **no re-execution** |
| `failed` | the LLM decides whether to retry with new arguments (**a new call ID**) | the LLM decides whether to retry with new arguments (**a new call ID**) |
| `uncertain` | **may auto-retry once** (the original call ID re-enters running; the event stream carries the same tool_call_id + an attempt number; the frontend renders the latest round; if the retry is still uncertain → paused) | **auto-retry forbidden**: the task goes `paused`, awaiting user confirmation |

**Recovery triggering**: recovery is **manually triggered** (`POST /tasks/{id}/resume`); after a service restart, interrupted tasks are **not** auto-scanned.

**Manual confirmation API** (for uncertain non-idempotent calls only):

```
POST /tasks/{id}/tool-calls/{tool_call_id}/confirm
body: { "action": "retry" | "skip" }
```

- `retry`: the user confirms the call produced no side effects (or they are acceptable); it re-executes under a **new call ID** with the confirmer/time recorded.
- `skip`: the call is marked `failed` (error="skipped-by-user"); the result goes back to the LLM, which decides the next step.
- After confirmation the task moves `paused → running`, still governed by the recovery lock.

**Task cancellation (cancel)**:

```
POST /tasks/{id}/cancel
```

- Semantics: **stop dispatching new calls**; all `pending` calls are marked `failed` (error="cancelled"); **in-flight `running` calls are marked `uncertain`** (because it cannot be confirmed whether they already produced side effects).
- Applicable states: `running | paused | pending`. For `paused` (awaiting an uncertain confirmation) and `pending` (unstarted) tasks, cancel is equally legal — with no `running` calls the task goes straight to a terminal state; `pending` calls are likewise marked failed(cancelled).
- After cancellation the task enters the terminal state `cancelled` and emits a `final` event (with the state and a result summary of the completed portion).
- For non-idempotent calls marked `uncertain`, the result summary explicitly notes "side effects unknown, cancelled" so the user can handle them manually afterwards. **Declaration**: `cancelled` is terminal and its uncertain calls have no in-system continuation path (the confirm API serves only paused tasks); "handling" means the user verifying side effects outside the system.

**Concurrent-recovery control**:

- Only **one active execution per task at a time**.
- Implementation: optimistic concurrency control on the Task row's `version` field — a resume validates and increments the version inside a transaction; `POST /tasks/{id}/resume` returns `409 Conflict` for a task already holding the recovery lock (version mismatch with the requester / an active execution heartbeat exists), **rejecting double recovery**.
- The active execution must heartbeat periodically (updating `updated_at`); a holder whose heartbeat expired can be preempted by a new resume (still via the version optimistic lock, guaranteeing a single winner).
- **Fencing (against zombie executors)**: the active execution holds the version value it acquired as its **execution token**; every tool-call dispatch and every state write must carry that token as a conditional update (`UPDATE … WHERE id=? AND version=?`, CAS semantics). Zero rows affected means preemption was detected (a new holder has bumped the version); the old executor **immediately terminates dispatch and never writes again** (self-termination) — even if a delayed heartbeat got it wrongly declared dead, it can no longer produce the side effects of a double active execution.

**Test requirements**: the acceptance items for these recovery semantics are in `docs/ACCEPTANCE_CRITERIA.md` M2 (M2-5/M2-6/M2-7).

## 6. Tool security rules

### 6.1 calc — safe expression evaluation

- **AST-based safe expression parsing** (the Python `ast` module): whitelist nodes only — numeric constants, binary operations (`+ - * / % **`), unary operations (`+ -`), whitelisted function calls (`abs / min / max / round / sqrt` etc.).
- **Forbidden**: `eval` / `exec` / name resolution (Name nodes are always rejected; only whitelisted Call targets match function names).
- Limits on expression length (default ≤ 256 characters) and operator depth (AST depth default ≤ 32).

### 6.2 http_request — SSRF protection

- Protocols: only `http` / `https` allowed.
- **Host allow-list** (extensible via configuration; contains example hosts by default).
- **IP validation**: after DNS resolution, the actual IPs are validated and private/intranet/reserved addresses are blocked:
  - IPv4: `127.0.0.0/8`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `169.254.0.0/16`, plus the cloud-metadata address `169.254.169.254`.
  - IPv6: `::1`, `fc00::/7`, `fe80::/10`.
- **resolve-then-connect (defends against the DNS-rebinding TOCTOU)**: after validation, the connection **must bind to the validated IP directly** (the HTTP `Host` header keeps the original hostname), and **resolving the hostname a second time at connect time is forbidden** — otherwise an attacker could switch the DNS answer between the validation and connection resolutions and bypass the blocks above.
- **Redirects**: automatically following unvalidated redirects is forbidden — every hop re-runs the full "host allow-list + IP validation" chain; failing validation blocks the hop; a hop-count cap applies (default 3).
- Timeout and response-size caps (default 10s / 1MB; overruns are truncated and flagged).
- Idempotency declaration: **non-idempotent** (GET requests count as idempotent; the registry distinguishes by the method argument).

### 6.3 file_write — sandboxed writes

- Writes are confined to the workspace's **`data/` sandbox directory**.
- Path handling: **normalize first (`realpath`), then validate the prefix** — the normalized path must start with the sandbox root prefix, otherwise it is rejected; paths containing `..` are explicitly rejected as traversal.
- **Symlinks rejected**: before writing, `lstat` checks that **every directory level** of the target path contains no symlink; any found → rejection.
- File-size cap (default 1MB).
- Idempotency declaration: **non-idempotent**.

### 6.4 New registry fields

The registration declarations in `src/agent/registry.py` **must** include, beyond the existing fields (name, description, Pydantic argument schema):

| Field | Values | Notes |
|------|------|------|
| `idempotency` | `idempotent \| non-idempotent` | the basis of the §5.1 recovery decisions; missing → registration fails |
| `risk_level` | `low \| medium \| high` | grading for security audits and code-review attention (e.g. file_write/http_request are medium and above) |

**Call-level effective idempotency**: recovery decisions (the §5.1 matrix) use the **call-level effective idempotency** = the registry's default declaration, overridable by argument rules — e.g. `http_request` declares non-idempotent by default but is overridden to idempotent when the method is GET. At dispatch, the effective value is snapshotted into `ToolCall.idempotency`; recovery uses that snapshot (never recomputed).

## 7. Configuration and secrets

`.env` (gitignored) → read by `pydantic-settings`:

```
OPENAI_API_KEY=…          # or ANTHROPIC_API_KEY
LLM_BASE_URL=…            # optional, compatible endpoints
LLM_MODEL=gpt-4o          # default model
CALC_AGENT_MAX_STEPS=25
CALC_AGENT_ENV_FILE=.env  # pydantic-settings env_file path override (default .env)
HTTP_ALLOWED_HOSTS=…      # http_request host allow-list (comma-separated; contains example.com by default)
DATA_SANDBOX_DIR=data/    # file_write sandbox root
```

**`CALC_AGENT_ENV_FILE` semantics**: pydantic-settings reads its env_file path from this variable (default `.env`). **Setting it to `/dev/null` bypasses the .env file entirely** — used for key-less acceptance (M0-3/M1-1b/E2E-3) and test fixtures, without moving/deleting a real `.env` (environment variables still take precedence over env_file; both channels must be cleared for a valid "no keys" condition).

**Red line**: any secret appearing in code/tests/logs is a code-review Blocker.

## 8. Observability

- Every state change produces a structured `TaskEvent` (DB; type ∈ `status|tool_call|tool_result|error|final`, see §3.1) + a synchronous JSONL append (`logs/agent-<task_id>.jsonl`, incl. seq). **Thoughts never enter any observability channel.**
- The SSE endpoint pushes public events live to the frontend timeline; `id:` carries the seq; `Last-Event-ID` supports reconnection (events are persisted before being pushed, hence replayable).
- Task termination always emits a `final` event (final state + result summary); clients use `final` to detect end-of-stream.
- Replay command: `python -m cli.replay <task_id>` prints the full trace in time order.

## Appendix: ADRs

- **ADR-001 a self-built single loop instead of a framework**: the requirements (decomposition/tools/state/logs) are all single-agent semantics; the graph orchestration and multi-agent abstractions a LangGraph would bring are pure overhead and violate constraint 3.
- **ADR-002 the openai SDK first**: a custom `base_url` covers most compatible endpoints domestic and abroad; the LLMClient abstraction isolates the provider — switching to anthropic touches one file.
- **ADR-003 start with SQLite**: single file, zero deployment; the storage layer uses the repository pattern, so migrating to Postgres swaps one implementation.
- **ADR-004 checkpoint-recovery and idempotency semantics** (v1.1, revised in v1.2): every tool call gets a stable `tool_call_id` and the `pending→running→(succeeded|failed|uncertain)` state machine; checkpoints persist the full context before a call enters running; the recovery policy follows the "state × idempotency" matrix — succeeded is reused, failed lets the LLM retry with new arguments (a new call ID), uncertain idempotent tools may auto-retry once (same ID + attempt number), uncertain non-idempotent tools must not auto-retry and go paused awaiting user confirmation (the confirm API); cancel stops dispatch and marks in-flight calls uncertain (paused/pending tasks can also be cancelled); only one active execution per task at a time (version-based optimistic concurrency; double recovery returns 409). **v1.2 adds fencing**: the active execution holds the version value as an execution token; dispatches and DB writes are CAS conditional updates carrying the token; zero rows affected means preemption and the old executor self-terminates — even with a delayed heartbeat wrongly declaring it dead, no double-execution side effects can occur. These semantics are the dividing line between "safe recovery" and "dangerous replay": rather pause for a human than silently repeat side effects.
- **ADR-005 tool security boundaries** (v1.1, revised in v1.2): calc uses AST-whitelist node parsing, no eval/exec/name resolution, with expression-length and operator-depth limits; http_request is http/https only + a host allow-list + blocking of private/reserved IP ranges after DNS resolution (incl. 169.254.169.254 cloud metadata) + **resolve-then-connect (connect directly to the validated IP; a second resolution is forbidden, defending against the DNS-rebinding TOCTOU)** + per-hop redirect re-validation + timeout and response-size caps; file_write is confined to the data/ sandbox with realpath-then-prefix validation, rejection of `..` and of symlinks at any directory level, and a file-size cap; the registry mandates `idempotency` (call-level effective idempotency = the default declaration, overridable per arguments, e.g. the GET override) and `risk_level` declarations. An agent may autonomously execute calls derived from untrusted input, so the security boundary must be enforced inside the tool executors, not left to the LLM's good behavior.
- **ADR-006 the public event model (de-thought-ified)** (v1.1): public event types converge to `status | tool_call | tool_result | error | final`; model-internal reasoning is never persisted to any public channel (DB event table/JSONL/SSE). Rationale: ① thoughts are model-internal intermediates — exposing them has neither stable contract value nor is it risk-free; ② the converged event types can be asserted precisely by the frontend and tests; ③ tool_call/tool_result align via `tool_call_id` and payloads carry truncation caps, keeping the stream parseable and replayable. The SSE `id:` carries the per-task monotonically increasing seq; `Last-Event-ID` reconnection resumes at seq+1 (events are persisted before being pushed, hence replayable); the final event is always emitted at task termination as the sole end-of-stream signal for clients.

## Changelog

### v1.0 → v1.1 (revised per review feedback; fixed 4 key + 3 minor items)

1. **Checkpoint-recovery security semantics** (review key issue 1): §5's data model gained the `ToolCall` table with stable `tool_call_id` and the call state machine (incl. `uncertain`); added §5.1 "Task recovery and idempotency" (checkpoint semantics, the idempotency-tiered recovery policy matrix, uncertain non-idempotent tools forbidden to auto-retry and paused awaiting user confirmation, the confirm API, cancel semantics, concurrent-recovery control/optimistic locking, and the pointer to the M2 test requirements).
2. **Tool security boundaries** (review key issue 2): added §6 "Tool security rules" — the calc AST whitelist, http_request SSRF protection (IP range blacklist, per-hop redirect validation), the file_write sandbox and symlink rejection; §6.4 added the registry's `idempotency`/`risk_level` fields; the §3 registry description synchronized.
3. **De-thought-ified event model + SSE mechanics** (review key issue 3): §3.1's SSE public event types converged to `status|tool_call|tool_result|error|final`; `Step.thought` was removed from the data model (marked as not collected); tool_call/tool_result payload definitions (tool_call_id + truncated summaries); a monotonically increasing seq carried by `id:`, `Last-Event-ID` resumption, events persisted before being pushed; final always emitted; §4's main loop and §8's observability synchronized.
4. **Runtime dependency list** (review minor issue 3): §2.1 gained the "runtime dependencies and necessity" table (fastapi/uvicorn/pydantic/pydantic-settings/pytest/pytest-asyncio/httpx/openai/pyright), declaring nothing beyond it.
5. The API endpoint list gained `POST /tasks/{id}/cancel` and `POST /tasks/{id}/tool-calls/{tool_call_id}/confirm`; the task state machine gained the `cancelled` terminal state.
6. Added ADR-004 / ADR-005 / ADR-006.
7. The technology stack and remaining sections were synchronized for consistency (no selection changes).

### v1.1 → v1.2 (revised per the architecture review + QA acceptance-criteria check reports)

1. **[P0-1]** §2.1's dependency allow-list gained `pytest-cov` (the pytest plugin behind coverage gate G-2, dev group), resolving the contradiction between the G-2 command and the dependency red line.
2. **[M-3]** §6.2 gained resolve-then-connect: the validated IP is used directly for the connection (the Host header keeps the original hostname) and a second resolution is forbidden, closing the DNS-rebinding TOCTOU gap; ADR-005 synchronized.
3. **[M-4]** §5.1's concurrent-recovery control gained fencing: the active execution holds the version value as an execution token; dispatches and DB writes are CAS conditional updates; zero rows affected means preemption and self-termination; ADR-004 synchronized.
4. **[M-5]** §5's task state machine gained `paused → cancelled` (cancellable while awaiting confirmation) and `pending → cancelled` (direct cancellation of an unstarted task); the cancel-semantics section states the applicable states and the declaration that uncertain calls under the terminal cancelled state have no in-system continuation path.
5. **[P1-6 linked]** §7 gained the `CALC_AGENT_ENV_FILE` configuration (env_file path override; `/dev/null` bypasses .env), providing the documentary basis for the dual-channel clearing in the key-less acceptance commands (M0-3/M1-1b/E2E-3); `HTTP_ALLOWED_HOSTS` notes the default includes example.com (a prerequisite of E2E-1).
6. **[Minor]** §6.4 gained the "call-level effective idempotency" rule (the default declaration overridable per arguments; ToolCall.idempotency is the snapshot of the effective value); §5.1's uncertain idempotent retry gained "same tool_call_id + attempt number, the frontend renders the latest round"; recovery is explicitly manually triggered (no auto-scan on restart); §5 gained the Step.seq / ToolCall.seq field semantics.
7. Version bumped v1.1 → v1.2; this changelog appended.
