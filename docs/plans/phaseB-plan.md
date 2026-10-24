# Phase B Plan — GameSpec and Playable HTML Game Generation (Concise Edition v1.0)

> Author: Lead (based on the Architect survey report + user strategy-adjustment instructions) | Status: **awaiting user approval**
> Basis: `docs/research/game-prototype-survey.md` (recommended route approved in principle by the user), user decisions D1–D5, the 2026-10-20 evening strategy-adjustment instructions (8 items)
> Baseline: commit `c6ede05` (Phase A + R2, 128/128 tests green)

## 0. Strategy Adjustment Record (user instructions, 2026-10-20)

1. PA-14 (qwen2.5:7b + Ollama real-LLM end-to-end): stop repeated fixing; register as a known issue (see the appended section of `pa14-r1-reevaluation-report.md`: R2 restored tool-call emission and correct spec structure; a single wording ambiguity remains, deferred to the integration phase).
2. From Phase B onward, **FakeLLM + pytest + deterministic tests** is the acceptance gate; do not call a real LLM unless necessary.
3. Keep the LLM interface swappable (the existing `LLMClientProtocol` already supports this: FakeLLM and the real client share the same interface; a local Ollama or any OpenAI-compatible API can be attached in the future).
4. Do not hardcode experiment paradigms, game themes, or model names into the product.
5. Real-LLM end-to-end testing is deferred to the **integration phase** after core functionality is complete.

## 1. Goal and Minimum Playable Prototype Scope

**One-sentence goal**: starting from an ExperimentSpec, through a GameSpec and a deterministic renderer, produce a single-file HTML game prototype that opens directly via `file://` and whose experiment logic cannot be tampered with.

**Minimum prototype chain** (inside a single AgentLoop):

```
Researcher Prompt
  → design_game / validate_game (LLM produces a shallow GameSpec; structured validation)
  → render_game (deterministic renderer: GameSpec + ExperimentBundle → single-file HTML)
  → dual-track verification (pytest logic core + browser self-check page)
```

**In scope**:
- GameSpec: a **shallow enumeration-style** presentation-layer description (following the v2.1 §4.5 draft) — stimulus presentation, response collection (keyboard key mapping), visual theme enum, feedback display toggles, copy templates. **References only, no recomputation**: trials, correctness rules, and constraints all come from the ExperimentBundle.
- 2 new tools: `validate_game`, `render_game` (copying the Phase A combinator pattern; add `build_game_registry`; do not touch M1).
- Renderer: **in-repo Python code** (not an LLM artifact), emitting a zero-dependency single-file HTML (embedded trials data, deterministic scoring logic, event log, dual-fingerprint startup check).
- Browser self-check page: built into the HTML (data-load check, fingerprint check, sampled self-test of the scoring logic, event-log export button). Per D2: the self-check page ≠ full playability verification; Playwright-style automated interaction testing is a later optional item.

**Out of scope (hard boundaries)**:
- No complex game logic beyond GameSpec; no multi-agent runtime; no M2 (database) / M3 (frontend service) / MCP / public Skill;
- No hardcoding of Stroop/N-back or any paradigm — the renderer knows only GameSpec enums, not specific experiments;
- Timing precision is demo-grade (D3: not for formal data collection);
- Zero modification of already-accepted M1 and Phase A code (GameSpec tools are purely additive).

**Four anti-tampering lines of defense** (from the survey report):
1. The GameSpec schema rejects experiment-semantics fields (out-of-bounds keys → SCHEMA_INVALID);
2. The renderer is the sole consumer of trials; scoring runs deterministic code (embedded in the HTML, not an LLM artifact);
3. The HTML validates bundle_sha256 + trials_fingerprint at startup;
4. The event log is machine-reconciled against trials (pytest replay core).

## 2. Milestones and Acceptance Criteria (all FakeLLM/deterministic acceptance)

### B0 — GameSpec Schema and Contract Freeze (Architect)
- Deliverables: GameSpec Pydantic schema, responsibility boundary table (extension of §4.0), Phase B contract document (including machine-checkable anti-tampering clauses).
- Acceptance (pytest): (1) GameSpec unit tests all green (enum validation, out-of-bounds field rejection); (2) the boundary table is executable — the renderer rejects a GameSpec containing experiment-semantics fields and returns a structured error; (3) zero field-coupling leakage with ExperimentSpec (cross-reference check).

### B1 — validate_game Tool and the FakeLLM Design Loop (Backend)
- Deliverables: the `validate_game` tool (validates GameSpec + referenced Bundle fingerprint consistency), the `build_game_registry` combinator, FakeLLM integration tests (produce → validation failure → fix → pass; copies the PA-8 pattern).
- Acceptance: (1) FakeLLM integration tests all green; (2) structured error reporting (error_code/path/suggestion); (3) full regression 128+ tests all green; (4) pyright 0 errors.

### B2 — Deterministic Renderer and Playable HTML (Backend)
- Deliverables: the `render_game` tool (GameSpec + Bundle → single-file HTML inside the data/ sandbox); the HTML includes the self-check page and event log.
- Acceptance: (1) **render golden file**: byte-reproducible for the same input (external shasum cross-check, copying the PA-2 pattern); (2) **logic core (no browser)**: pytest parses the embedded data and scoring logic from the HTML, replays and reconciles the correctness scoring of all trials — 100% consistent with the Bundle; (3) the self-check page passes data-load/fingerprint/sampled self-tests (one manual file:// confirmation + screenshot record); (4) renderer grep shows no hardcoded paradigm names (copying PA-12).

### B3 — End-to-End Demo (FakeLLM) and Open-Source Cleanup
- Deliverables: `examples/run_game_agent.py` (default FakeLLM mode); README (positioning/install/quick start/example/tests/known issues incl. PA-14); pyproject install configuration; LICENSE check (existing dependencies are all permissive).
- Acceptance: (1) one command runs ExperimentSpec→GameSpec→HTML→dual-fingerprint verify; (2) README steps can be copied and executed successfully in a clean venv; (3) full test suite green; (4) GitHub open-source checklist (no secrets, no internal paths) review passed.

### Integration Phase (deferred; a separate request after the core is complete)
- Real-LLM end-to-end (re-trying PA-14: the one-line wording-disambiguation fix is on file / OpenAI-compatible API switching verification); optional Playwright automated playability testing.

## 3. Process Conventions

- Continue the Architect frozen contract → Backend implementation → QA independent verification → user approval flow; one commit + briefing per milestone, **avoiding repeated long reports** (QA conclusions folded into milestone briefs).
- Stop and wait for user approval at the end of every milestone; no auto-advancing.
- LLM call policy: zero real LLM calls during development (FakeLLM coverage); a one-time budget request at the integration phase.

## 4. Main Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| R-1 GameSpec expressiveness vs paradigm-neutrality tension | enums insufficient → logic smuggled in | B0 freezes the enum set; if insufficient, go through a contract revision — no generic escape hatch |
| R-2 HTML timing precision | scientific validity | D3 already ruled demo-grade; README states it is not for data collection |
| R-3 Degree of playability-test automation | self-check page ≠ real verification | in the dual track the logic core is the hard gate; Playwright listed as later-optional |
| R-4 PA-14 residue | blocks the integration phase | narrowed to a single wording ambiguity; the FakeLLM gate is unaffected |
| R-5 HTML size bloat | single file out of control | reuse the 1MB export-guard magnitude cap |

— End of planning; no code changes executed. Awaiting user approval to start B0.
