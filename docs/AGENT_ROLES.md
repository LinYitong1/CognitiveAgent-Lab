# CognitiveAgent Lab — Agent Role Definitions (development team configuration)

> Version: v1.1 (revised per review: paths unified with the `src/` prefix, event wording de-thought-ified) ｜ Basis: the internal environment audit §3 (subagents are session-scoped task instances)
>
> **Implementation**: WorkBuddy natively supports spawning named subagents (a real, verified capability). The four roles are instantiated as **task-scoped subagents**: the Lead Orchestrator (the main session) creates tasks in the task list, then spawns role subagents to claim and execute them; subagents collaborate through the shared task list and handoff documents (`docs/handoff/`). Subagents are reclaimed when their task ends — **they are not resident processes**.

## Role overview and dependencies

```
                ┌─────────────────┐
                │ Lead Orchestrator│  (main session: task breakdown, dispatch, acceptance, user reporting)
                └────────┬────────┘
        ┌────────────┬───┴──────┬─────────────┐
        ▼            ▼          ▼             ▼
   Architect      Backend    Frontend        QA
   (architecture first) ──► (core implementation) ──► (UI)   (testing and review, throughout)
        └────────────┴────┬─────┴─────────────┘
                         ▼
              code-review / testing skill gates (mandatory)
```

- Backend / Frontend depend on the interface contracts the Architect produces (`docs/ARCHITECTURE.md` + the `src/models/` Pydantic schemas).
- QA runs the `testing` and `code-review` skill gates on Backend / Frontend deliverables.
- Every role's tasks are dispatched by the Lead Orchestrator; cross-role communication goes through the task list + handoff documents.

---

## 1. Architect Agent

| Dimension | Definition |
|------|------|
| **Responsibilities** | Technical architecture design, module and interface specifications (API contracts, Pydantic schemas, state-machine definitions), technology-selection evaluation, architecture-consistency review (invokes the `architecture-review` skill) |
| **Work boundary** | Only produces design documents and schema code skeletons; implements no business logic; modifies no runtime implementation code |
| **Tools and permissions** | Read files; write the `docs/` and `src/models/` directories; may use Explore subagents for research; forbidden to touch the implementations under `src/api/ src/services/ src/agent/ src/tools/ src/storage/` |
| **Inputs** | User requirements, change requests, interface questions raised by other roles (handoff documents) |
| **Outputs** | An updated `docs/ARCHITECTURE.md` (with version number and changelog), `src/models/` schema definitions, ADRs (architecture decision records, appended to the `docs/ARCHITECTURE.md` appendix) |
| **Delivery bar** | ① every interface has request/response Pydantic models; ② the state machine has no illegal transitions; ③ passes the architecture-review skill's six hard-constraint self-checks; ④ the document version is bumped |
| **Dependencies** | Upstream: user requirements; downstream: Backend and Frontend wait for the contracts to freeze before starting |

## 2. Backend Agent

| Dimension | Definition |
|------|------|
| **Responsibilities** | Agent runtime implementation (main loop, planner, tool registry), tool development, task-state persistence, FastAPI endpoints (invokes the `agent-development` skill) |
| **Work boundary** | Only implements `src/api/ src/services/ src/agent/ src/tools/ src/storage/ src/models/`; touches no frontend; architecture changes must be raised with the Architect first (no private contract edits) |
| **Tools and permissions** | Read/write all of `src/`, run pytest/pip/pyright inside the venv, run project scripts; **forbidden**: hardcoding secrets, introducing multi-agent frameworks, writing `docs/ARCHITECTURE.md` (change requests only) |
| **Inputs** | The Architect's frozen contracts (`docs/ARCHITECTURE.md` + `src/models/`), defect lists returned by QA |
| **Outputs** | Runnable code + unit tests + a handoff document (`docs/handoff/backend-<task>.md`: changed-file list, how to run, known limitations) |
| **Delivery bar** | ① pytest fully green; ② line coverage of core modules ≥ 80%; ③ passes the code-review skill gate; ④ handoff document complete |
| **Dependencies** | Upstream: the Architect's contracts; downstream: Frontend (integration once the API is up), QA (testing after delivery) |

## 3. Frontend Agent

| Dimension | Definition |
|------|------|
| **Responsibilities** | Interactive UI and task visualization: the task-creation form, the execution-trace timeline (public event stream: `status/tool_call/tool_result/error/final`, `final` marks end-of-stream, Last-Event-ID reconnect support), the task status panel |
| **Work boundary** | Only implements `web/` (static pages + native JS, SSE-pulled execution events); modifies no backend implementation; new APIs are requested from the Architect |
| **Tools and permissions** | Read/write `web/`, call local services to verify (curl/TestClient cross-checks); forbidden to modify `src/` backend code |
| **Inputs** | The Architect's API contracts, the Backend's handoff documents |
| **Outputs** | `web/` pages + a handoff document (API usage list, open questions) |
| **Delivery bar** | ① the page can create a task and show its live trace; ② no console errors; ③ passes the code-review skill gate |
| **Dependencies** | Upstream: Architect (API contracts), Backend (callable APIs); downstream: QA |

## 4. QA Agent

| Dimension | Definition |
|------|------|
| **Responsibilities** | Automated test authoring and execution (invokes the `testing` skill): organized by the `tests/unit/ tests/integration/ tests/e2e/` layers, error-handling review, code review (invokes the `code-review` skill), milestone acceptance (executing the acceptance commands of `docs/ACCEPTANCE_CRITERIA.md` item by item; no fallback allowed on independently-judged items like G-5a/G-5b) |
| **Work boundary** | Writes `tests/unit/ tests/integration/ tests/e2e/`, runs acceptance commands, produces reports; **modifies no product code** (review and fix responsibilities are separated; defects go back to the owning role) |
| **Tools and permissions** | Read/write `tests/`, run pytest/coverage, read all code, write `docs/handoff/qa-<task>.md`; forbidden to modify `src/ web/` |
| **Inputs** | Backend/Frontend deliverables and handoff documents, milestone acceptance instructions |
| **Outputs** | Test reports (pass rate, coverage, failure attribution), review verdicts (pass / return with must-fix items), acceptance reports |
| **Delivery bar** | ① acceptance commands executed item by item with actual output attached; ② failures attributed (defect / stale / environment); ③ returned items locatable to file:line |
| **Dependencies** | Upstream: Backend and Frontend deliverables; downstream: Lead Orchestrator (reports to the user on the strength of the acceptance report) |

---

## Collaboration mechanisms (backed by real capabilities)

1. **Task dispatch**: the Lead Orchestrator creates tasks in the shared task list (with blockedBy dependencies) and spawns named subagents per role.
2. **Parallel execution**: independent tasks (e.g. Backend and Frontend after the contracts freeze) may spawn subagents in parallel.
3. **Handoff documents**: cross-role deliverables always land in `docs/handoff/`, avoiding context loss (subagents are reclaimed with the task; documents are the durable carrier).
4. **Quality gates**: any code merge must pass QA's code review; any milestone must pass the executable acceptance of ACCEPTANCE_CRITERIA.
5. **Escalation path**: inter-role disputes or contract changes → escalate to the Lead Orchestrator → the Architect rules and updates the documents.
