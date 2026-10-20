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

# 2. Deterministic demo (scripted fake LLM — no network, no keys):
#    the full agent workflow validate_experiment → generate_trials
#    → export_experiment → validate_game → render_game → playable HTML,
#    verified bundle + byte-identical HTML.
cognitive-agent demo

# 3. Open the game in a browser (file://)
open data/games/demo-agent-game.html        # macOS
# Browser playtest checklist: docs/checklists/browser-playtest-checklist.md

# 4. Independently verify the experiment bundle (generator-free; recomputes both fingerprints)
cognitive-agent verify data/experiments/demo-agent-game.json
```

## Installation

| Item | Details |
|---|---|
| Python | >= 3.13 |
| From a clone | `python3.13 -m venv .venv && .venv/bin/pip install -e .` |
| From git | `pip install "cognitive-agent-lab @ git+https://github.com/LinYitong1/CognitiveAgent-Lab.git"` |
| Console script | `cognitive-agent` (installed on PATH by `pip install`) |
| Dependencies | FastAPI, Pydantic v2, pydantic-settings, httpx, openai SDK — nothing else (see pyproject.toml) |
| Keys | Optional; `demo` and the whole test suite need zero keys |

## Configuration

Copy `.env.example` to `.env` and configure your provider (plain environment
variables work too — pydantic-settings reads both):

```bash
cp .env.example .env

# OpenAI or any authenticated OpenAI-compatible provider:
OPENAI_API_KEY=sk-...
LLM_MODEL=gpt-4o          # or the provider's model name

# Keyless local OpenAI-compatible endpoint (e.g. Ollama):
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=qwen2.5:7b      # any model served by your endpoint
# OPENAI_API_KEY can stay empty — a documented placeholder key is used
# automatically for keyless local endpoints. If your endpoint requires
# authentication, set OPENAI_API_KEY as well.
```

## CLI usage

```bash
# Deterministic scripted demo — no network, no keys, fully verified
cognitive-agent demo

# Same demo, all generated files confined to a directory of your choice
cognitive-agent demo --output out/my-first-experiment

# Run a natural-language task with your configured real LLM provider
# (experimental: real-LLM end-to-end reliability is not yet validated —
#  see "Validated capabilities vs limitations" above)
cognitive-agent run "design a 2x2 attention experiment with 80 trials and render a playable game"

# Confine the run's generated files to a directory
cognitive-agent run "design an experiment" --output out/run1

# Independently verify an ExperimentBundle (recomputes both SHA-256 fingerprints)
cognitive-agent verify out/run1/experiments/my-experiment.json
```

Exit codes: `run`/`demo` → 0 success / 1 failure; `run` additionally → 2 when
no credentials are configured. All generated experiment artifacts stay inside
the output directory (default `data/`); agent event logs are runtime logs and
land in `logs/`.

## Python API

```python
import asyncio
from src.pipeline import run_task, run_demo, PipelineResult

# 1) Real provider (credentials resolved from .env / environment per the
#    documented policy; raises MissingCredentialsError when nothing is set)
result = asyncio.run(run_task(
    "design a 2x2 experiment with 60 trials and render a playable game",
))

# 2) Deterministic demo (scripted client; no network, no keys)
result = asyncio.run(run_demo(output_dir="out/demo"))

# 3) Structured result (wraps the unchanged AgentResult contract)
result.status                 # "completed" | "failed"
result.result                  # the full AgentResult: status, result text, steps, events
result.artifacts               # tuple[Path, ...] — files created during the run
result.bundle_verification     # VerifyReport | None — independent bundle check
result.html_verified           # bool | None — byte-identity vs deterministic re-render (demo)
```

Any `LLMClientProtocol` implementation can be injected as `client=` (that is
how the test suite drives the same loop deterministically with FakeLLM).

Other examples (repo clone only):

```bash
.venv/bin/python examples/run_game_render.py      # pure-function game generation, no agent
.venv/bin/python examples/run_experiment_agent.py # Phase A: the three experiment tools workflow
.venv/bin/python examples/run_agent.py            # M1: the three basic tools (requires a real LLM)
.venv/bin/python examples/run_game_agent.py       # B3 end-to-end demo (same flow as `cognitive-agent demo`)
```

**Real-LLM reliability caveat**: `cognitive-agent run` and `run_task` with a
real provider are experimental — real-LLM end-to-end reliability is **not yet
validated** (known issue PA-14, see "Validated capabilities vs limitations").
`cognitive-agent demo` / `run_demo` are the deterministic, fully verified paths.

## Architecture

```
src/
├── cli.py         cognitive-agent CLI entry point (run / demo / verify)
├── pipeline.py    Public Python API facade (run_task / run_demo / PipelineResult)
├── agent/         AgentLoop (plan→act→observe single loop), ToolRegistry, registry combinators
├── tools/         Tool layer: calc / http_request / file_write (the three M1 tools)
│                  + validate_experiment / generate_trials / export_experiment (Phase A)
│                  + validate_game / render_game (Phase B)
├── experiment/    Deterministic experiment engine: schemas / validation / generation / export /
│                  verify (generator-free independent verification CLI) / game_schemas / game_render
├── models/        Pydantic models (LLM, tool specs, events, results)
└── api/           FastAPI + SSE event stream (M1)
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
  `docs/research/`): milestone contracts, QA reports,
  diagnosis records and planning notes kept for traceability. These are archival working
  documents, mostly in Chinese, and are not maintained as user documentation.

## License

Apache-2.0 — the canonical [LICENSE](LICENSE) file is included in the repository root
for review (byte-identical to the official Apache License 2.0 text). All runtime
dependencies (FastAPI/Pydantic/httpx/openai SDK) are permissive MIT/Apache-family
licenses with no copyleft constraints.
