# CognitiveAgent Lab

An engineering-first AI agent system: a single agent main loop drives a **deterministic
experiment-generation pipeline** — starting from an ExperimentSpec it produces a reproducible
trial sequence (ExperimentBundle), then renders it through a GameSpec into a **single-file HTML
game** that opens directly via `file://`, with experiment logic that the presentation layer
cannot tamper with.

```
Natural-language task (researcher prompt)
  → ExperimentSpec ──validate_experiment──┐
  → trial sequence generate_trials (byte-reproducible for the same spec+seed)
  → ExperimentBundle export_experiment (with SHA-256 integrity fingerprints)
  → GameSpec ──validate_game (references six fingerprints; presentation only, cannot alter the experiment)──┘
  → render_game → single-file playable HTML (embedded dual-fingerprint startup check + event log)
```

> **Developer preview.** The first demo shows multi-step tool execution plus the deterministic
> experiment→game pipeline — not a paper-grade research assistant.
> Out of scope: multi-agent collaboration, RAG, authentication, formal data collection
> (timing is demo-grade). See "Validated capabilities vs limitations" below.

## Validated capabilities vs limitations

**Validated** (automated by the 213-test suite, deterministic, no LLM keys required):

- The full ExperimentSpec → trials → ExperimentBundle pipeline, byte-reproducible for the
  same spec+seed (dual SHA-256 fingerprints, independent generator-free verification CLI)
- The GameSpec → validate_game → render_game chain: single-file HTML, byte-identical
  re-renders, embedded fingerprint startup check, anti-tamper schema boundaries
- The end-to-end agent workflow driven by a scripted fake LLM
  (`examples/run_game_agent.py`), with two-layer verification that refuses to pass
  tampered or missing artifacts silently
- Tool-security boundaries (calc AST whitelist, http_request SSRF chain, file_write sandbox)

**Not validated / not working**:

- **Real-LLM end-to-end is unfinished (known issue PA-14)**: on qwen2.5:7b + Ollama
  0.40.6, tool calls are silently dropped. All agent workflows are currently validated
  with FakeLLM only; a real LLM has been exercised only against the M1 basic tools.
  The LLM interface (`LLMClientProtocol`) is swappable, and real-LLM integration is
  deferred. See the detailed limitation notes below for the rest.

## Quick start (no LLM keys required)

```bash
# 1. Python >= 3.13 — create a virtualenv and install
python3.13 -m venv .venv
.venv/bin/pip install -e .

# 2. End-to-end demo: a scripted fake LLM drives the full agent workflow
#    (no network, no keys). A single AgentLoop calls validate_experiment
#    → generate_trials → export_experiment → validate_game → render_game
#    and produces a playable HTML file.
.venv/bin/python examples/run_game_agent.py

# 3. Open it in a browser (file://)
open data/games/demo-agent-game.html        # macOS
# Browser playtest checklist: docs/checklists/browser-playtest-checklist.md

# 4. Independently verify the experiment bundle (generator-free; recomputes both fingerprints)
.venv/bin/python -m src.experiment.verify data/experiments/demo-agent-game.json
```

Other examples:

```bash
.venv/bin/python examples/run_game_render.py      # pure-function game generation, no agent
.venv/bin/python examples/run_experiment_agent.py # Phase A: the three experiment tools workflow
.venv/bin/python examples/run_agent.py            # M1: the three basic tools (requires a real LLM)
```

Connecting a real LLM (optional; needed by `examples/run_agent*.py`): copy `.env.example`
to `.env` and fill in `OPENAI_API_KEY` or any OpenAI-compatible endpoint
(`LLM_BASE_URL` + `LLM_MODEL`). The B3 demo above reads no keys at all.

## Installation

| Item | Details |
|---|---|
| Python | >= 3.13 |
| Install | `.venv/bin/pip install -e .` |
| Dependencies | FastAPI, Pydantic v2, pydantic-settings, httpx, openai SDK (see pyproject.toml) |
| Keys | Optional, only for `examples/run_agent*.py`; the pipeline and tests need zero keys |

## Architecture

```
src/
├── agent/        AgentLoop (plan→act→observe single loop), ToolRegistry, registry combinators
├── tools/        Tool layer: calc / http_request / file_write (the three M1 tools)
│                 + validate_experiment / generate_trials / export_experiment (Phase A)
│                 + validate_game / render_game (Phase B)
├── experiment/   Deterministic experiment engine: schemas / validation / generation / export /
│                 verify (generator-free independent verification CLI) / game_schemas / game_render
├── models/       Pydantic models (LLM, tool specs, events, results)
└── api/          FastAPI + SSE event stream (M1)
```

**Four anti-tamper defenses** (the game layer cannot change experiment conditions/trials/correctness):

1. The GameSpec schema uses `extra="forbid"` — experiment-semantics fields (e.g. trials) are rejected outright;
2. The renderer is the sole consumer of trials; trials/correct answers are copied only from the ExperimentBundle;
3. The HTML embeds a pure-JS SHA-256 implementation and verifies bundle_sha256 +
   trials_fingerprint at startup, refusing to start on mismatch;
4. pytest logic-core reconciliation (golden-file byte comparison + 100% trial/correctness agreement).

**Two-tier error contract**: tool-level failures → `BLOCKED:` prefix; domain-level failures →
`ok=true, valid:false` structured reports (error_code / path / suggestion) for LLM iteration,
with repeated submissions triggering `ITERATION_STALLED`.

Detailed design: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) ｜
Phase A/B frozen contracts: [docs/handoff/](docs/handoff/) ｜
Roadmap: [docs/ROADMAP.md](docs/ROADMAP.md)

## Tests

```bash
.venv/bin/python -m pytest            # full test suite (213 tests, no keys needed)
.venv/bin/python -m pyright src/      # static typing (0 errors)
.venv/bin/python -m scripts.check_layers  # layering dependency check
scripts/check.sh                      # CI gate (all of the above + secret scan + compile check)
```

Determinism acceptance highlights: rerunning with the same spec+seed → identical bundle
fingerprints and byte-identical HTML (PYTHONHASHSEED-independent, cross-verified with the
external `shasum` tool); golden files live in `tests/golden/`.

## Browser playtest checklist

Manual acceptance of a generated HTML game (keyboard responses, feedback, block transitions,
end summary, event-log download, tamper resistance):
[docs/checklists/browser-playtest-checklist.md](docs/checklists/browser-playtest-checklist.md)

## Known limitations

1. **Real-LLM end-to-end not yet passing (known issue PA-14)**: on qwen2.5:7b + Ollama 0.40.6,
   tool calls are silently dropped (see `docs/handoff/ollama-toolcall-diagnosis-report.md`);
   the current acceptance gate is FakeLLM + pytest, real-LLM integration is deferred, and the
   LLM interface (`LLMClientProtocol`) stays swappable.
2. **Timing not validated**: browser `setTimeout` scheduling is approximate — **not for formal
   experimental data collection**.
3. **Limited game interaction types**: the MVP supports keyboard only (choice keys / text /
   rating input), no pointer/touch/audio; three feedback-style enums; multi-response trials
   do not redraw the stimulus.
4. **Event log is not force-persisted**: it lives in page memory with a manual download on the
   end screen.
5. Browser-automation playability testing (Playwright-style) is deferred (decision D2: the
   manual checklist stands in).

## Documentation

- **User-facing guides** (English, kept current): this README,
  [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) (technical architecture),
  [docs/ROADMAP.md](docs/ROADMAP.md) (development roadmap),
  [docs/ACCEPTANCE_CRITERIA.md](docs/ACCEPTANCE_CRITERIA.md) (executable acceptance
  criteria), [docs/AGENT_ROLES.md](docs/AGENT_ROLES.md) (team roles),
  [docs/checklists/browser-playtest-checklist.md](docs/checklists/browser-playtest-checklist.md)
  (browser playtest checklist).
- **Internal development records** (`docs/handoff/`, `docs/plans/`, `docs/proposals/`,
  `docs/research/`, plus `docs/ENVIRONMENT_AUDIT.md`): milestone contracts, QA reports,
  diagnosis records and planning notes kept for traceability. These are archival working
  documents, mostly in Chinese, and are not maintained as user documentation.

## License

Apache-2.0 — the canonical [LICENSE](LICENSE) file is included in the repository root
for review (byte-identical to the official Apache License 2.0 text). All runtime
dependencies (FastAPI/Pydantic/httpx/openai SDK) are permissive MIT/Apache-family
licenses with no copyleft constraints.
