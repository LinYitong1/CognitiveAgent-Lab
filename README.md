# CognitiveAgent Lab

A deterministic pipeline that turns a structured experiment specification into a
reproducible trial sequence and a **single-file, browser-playable HTML game** — with
the experiment logic sealed off from the presentation layer. Two game shapes are
supported: a classic sequential layout and an **explorable spatial game**
(GameSpec v2: rooms, objects, narrative — where examining marked objects triggers
controlled trials).

It also ships a small single-loop agent runtime (tool registry + agent loop) that
drives this pipeline. The agent path is validated end-to-end with a scripted fake
LLM in the test suite, and — as of October 2026 — with one **real Gemini run (T5)**
that autonomously generated, validated and rendered a complete experiment game from
a natural-language task. A second, harder real-Gemini task (an explorable
working-memory game) did not complete within its API budget; see
[status](#status-what-is-validated-what-is-not).

> **Developer preview** — a deterministic, byte-reproducible
> experiment-generation scaffold, not a general agent framework and not a
> research-grade data-collection tool.

```
ExperimentSpec (JSON, validated)
  → deterministic trial sequence (same spec + seed → byte-identical trials, always)
  → ExperimentBundle (JSON artifact with SHA-256 integrity fingerprints)
  → GameSpec (presentation-only description, validated against the bundle)
  → single-file HTML game (classic or explorable; keyboard input; embedded event log)
```

The v2 research layer adds three paradigm-neutral capabilities on the measurement
side: **intra-trial variables** (factor levels can bind different amounts of
generated content — a real content difference, not a label), **content references**
(later stimulus lines can reuse earlier generated content without re-drawing), and
**content-driven correctness** (the answer key is computed from the materialized
stimulus relationship, not from condition names). Trials can also be split into
ordered **presentation phases** (e.g. show → hold → probe) where the response
window opens only on designated phases.

## What this is — and is not

**This is:**

- A deterministic generator for game-based cognitive experiments: you describe
  factors, levels, blocks, responses and timing; it produces a reproducible trial
  sequence and a playable single-file HTML game — classic sequential or
  explorable-spatial (GameSpec v2).
- A scaffold that keeps the game/presentation layer from touching experiment
  logic (trials, conditions, correct answers) — verified, not just promised.
- A research layer for generic experiment content: intra-trial variables,
  references to earlier generated content, content-driven answer keys, and
  multi-phase trial presentation with per-phase response windows. All of it is
  composed from paradigm-neutral primitives — the engine contains no
  N-back/DMTS/working-memory vocabulary.
- A single-loop agent runtime with a tool registry, which the deterministic
  pipeline is wired into as tools — exercised end-to-end with a scripted fake
  LLM in tests, plus one successful real-Gemini end-to-end run (T5).

**This is not:**

- A general-purpose AI agent framework (one loop, a fixed tool set, no planning
  subsystem, no memory, no multi-agent anything).
- A validated natural-language assistant: one real-LLM task (T5) fully passed;
  a harder one (T2, explorable working-memory game) did not complete — see the
  status section.
- A claim that all experimental paradigms are supported: the engine offers
  generic composition primitives; whether a composed design is *scientifically
  valid* (real memory load, meaningful intervals, no cue leakage) is a
  researcher's judgement the engine cannot make.
- A security mechanism: the "experiment/presentation separation" below is about
  design integrity (the game layer cannot silently redefine your experiment),
  not about defending against a hostile user who edits the HTML file.
- A data-collection instrument: browser timing is approximate, event logs are
  not force-persisted. Do not use it for formal experimental data.

## Status: what is validated, what is not

**Validated** (automated by the 381-test suite; deterministic; no LLM keys required):

- The full ExperimentSpec → trials → ExperimentBundle pipeline: byte-reproducible
  for the same spec+seed, with dual SHA-256 fingerprints and an independent
  verification CLI that recomputes them without the generator.
- The GameSpec → validate → render chain for both layouts: single-file HTML,
  byte-identical re-renders, fingerprint startup check inside the HTML,
  schema-level separation of experiment semantics from presentation.
- GameSpec v2 explorable games: rooms/objects/narrative validated (G8 rules),
  monotonic trial cursor — exploration order provably cannot change conditions,
  stimuli, trial count or correct answers.
- Intra-trial variables, content references and content-driven answer keys:
  factor levels produce genuinely different materialized content; the answer
  key follows the materialized stimulus relationship (verified by recomputing
  it from the rendered text in tests).
- Multi-phase trials: phase order, timed/keyed advance, response-window gating
  (keypresses outside a window are never recorded), RT anchored at the window
  phase onset, no skipped or double-counted responses — runtime-verified for
  both renderers under node with a DOM stub.
- Backward compatibility: v1 specs, golden HTML files and all pre-v2
  fingerprints are byte-identical after every extension (enforced by tests).
- The agent workflow shape (tool call order, error iteration, verification)
  driven by a scripted fake LLM — including that tampered or missing artifacts
  fail loudly instead of passing silently.
- Tool-security boundaries (calc AST whitelist, http_request SSRF chain,
  file_write sandbox).

**Validated with a real LLM (once, bounded):**

- **T5 (real Gemini, October 2026)**: from a natural-language task, the agent
  autonomously authored an ExperimentSpec, validated and exported the bundle,
  wrote a valid GameSpec, and rendered a playable HTML game — with
  self-correction loops on validation errors. All artifacts verified.
  This is a single successful run, not a reliability claim.

**Not validated / incomplete:**

- **T2 (real Gemini): incomplete.** Generating an explorable *working-memory*
  game from a natural-language brief stopped at the API budget boundary
  (≈2–3 tool calls short of rendering). The deeper finding was scientific, not
  technical: the engine at that time could only express a *nominal* memory task
  (condition labels without real sequence content). The P0/P1 research-layer
  extensions (variables, references, content-driven correctness, phases) were
  built specifically to close that gap — but a real-LLM re-run has not yet
  been performed.
- **Scientific validity is not automated.** The engine proves the answer key
  follows the materialized content; it cannot prove the content instantiates
  the intended cognitive process (load calibration, retention intervals, cue
  leakage, counterbalancing remain researcher responsibilities).
- Real-LLM reliability beyond the two bounded runs above (qwen2.5:7b +
  Ollama tool-calls remain broken, known issue PA-14); every agent workflow in
  the test suite runs against FakeLLM.

## Quick start (no LLM keys required)

```bash
# 1. Python >= 3.13 — create a virtualenv and install
python3.13 -m venv .venv
.venv/bin/pip install -e .

# 2. Deterministic demo (scripted fake LLM — no network, no keys):
#    the full workflow validate_experiment → generate_trials
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
# (experimental: one bounded Gemini run passed end-to-end; general real-LLM
#  reliability is not established — see "Status" above)
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

You can also skip the agent entirely and call the engine directly —
`build_bundle` / `validate_game` / `render_game_html` / `verify_bundle` are
pure functions (see `examples/run_game_render.py` and the
[Codex skill](#codex-agent-skill) for a complete worked example).

Other examples (repo clone only):

```bash
.venv/bin/python examples/run_game_render.py      # pure-function game generation, no agent
.venv/bin/python examples/run_experiment_agent.py # the three experiment tools workflow
.venv/bin/python examples/run_agent.py            # the three basic tools (requires a real LLM)
.venv/bin/python examples/run_game_agent.py       # end-to-end demo (same flow as `cognitive-agent demo`)
```

## Codex Agent Skill

The repository ships a ready-made [Codex Agent Skill](skills/cognitive-agent/SKILL.md)
that lets external coding agents (OpenAI Codex CLI and other SKILL.md-compatible
tools) run the same deterministic workflows — experiment generation, validation,
HTML rendering and bundle verification — **without invoking any LLM themselves**:
the agent translates your request into tool calls; the deterministic Python
engine does the actual work.

Install (copy the skill directory into your agent's skills folder — directory
structure must be preserved):

```bash
git clone --depth 1 https://github.com/LinYitong1/CognitiveAgent-Lab.git /tmp/cal
mkdir -p ~/.codex/skills                       # user-level (all projects)
cp -r /tmp/cal/skills/cognitive-agent ~/.codex/skills/
rm -rf /tmp/cal
# project-level instead: copy to <project>/.codex/skills/cognitive-agent/
# then restart Codex so the skill list reloads
```

Usage — mention the skill explicitly (`$cognitive-agent ...`) or just describe
the task and let the skill's description trigger it:

```
$cognitive-agent generate a red/blue colour-judgement experiment:
practice 8 trials + main 40 trials, and render a playable HTML game
```

The skill instructs the agent to use the deterministic paths only
(`cognitive-agent demo` / the Python API / `cognitive-agent verify`); the
real-LLM path is explicitly fenced as opt-in. Requires the package installed
(see [Installation](#installation)).

## Architecture

```
src/
├── cli.py         cognitive-agent CLI entry point (run / demo / verify)
├── pipeline.py    Public Python API facade (run_task / run_demo / PipelineResult)
├── agent/         AgentLoop (plan→act→observe single loop), ToolRegistry, registry combinators
├── tools/         Tool layer: calc / http_request / file_write (the three M1 tools)
│                  + validate_experiment / generate_trials / export_experiment
│                  + validate_game / render_game
├── experiment/    Deterministic experiment engine: schemas / validation / generation / export /
│                  verify (generator-free independent verification CLI) / game_schemas /
│                  game_render (classic) / explore_render (v2 explorable) /
│                  stimulus (v2 materialization: variables, phases, correctness rules) /
│                  phase_player (shared phased-playback JS for both renderers)
├── models/        Pydantic models (LLM, tool specs, events, results)
└── api/           FastAPI + SSE event stream
```

**Experiment/presentation separation** — how the game layer is kept from
redefining the experiment (a design-integrity mechanism, *not* a security
feature against a user who edits the HTML):

1. The GameSpec schema rejects experiment-semantics fields outright
   (`extra="forbid"` — a smuggled `trials` key fails validation);
2. The renderer takes trials and correct answers **only** from the
   ExperimentBundle — the GameSpec has no way to express them;
3. The rendered HTML checks its embedded bundle fingerprints at startup and
   refuses to start on mismatch (so accidental divergence is caught, though a
   deliberate editor can of course remove the check);
4. pytest reconciliation: golden-file byte comparison plus 100% agreement of
   rendered trials/correctness with the bundle.

Internal error-handling details (two-tier tool/domain error contract,
`ITERATION_STALLED` on repeated failed submissions) are documented in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

Detailed design: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) ｜
Phase A/B frozen contracts: [docs/handoff/](docs/handoff/) ｜
Roadmap: [docs/ROADMAP.md](docs/ROADMAP.md)

## Tests

```bash
.venv/bin/python -m pytest            # full test suite (381 tests, no keys needed)
.venv/bin/python -m pyright src/      # static typing (0 errors)
.venv/bin/python -m scripts.check_layers  # layering dependency check
scripts/check.sh                      # CI gate (all of the above + secret scan + compile check)
```

What the suite covers: deterministic generation, schema boundaries,
tool-security rules, golden files, the FakeLLM-driven agent workflow, and —
since the v2 research layer — variable binding, content-driven correctness,
multi-phase playback (node runtime tests for both renderers) and byte-level
backward compatibility of all pre-v2 output. It is reproducibility evidence
for the scaffold — read it alongside the
[status section](#status-what-is-validated-what-is-not), not as evidence of
real-LLM capability beyond the bounded runs described there.

Determinism, precisely scoped: rerunning with the same spec+seed produces the
**identical trial sequence, identical config/trials/bundle fingerprints, and
byte-identical rendered HTML** (PYTHONHASHSEED-independent, cross-verified with
the external `shasum` tool; golden files live in `tests/golden/`). The bundle
**file bytes** are not byte-stable across exports — the JSON embeds a
`generated_at` timestamp; strip that one field and separate exports compare
byte-for-byte.

## Browser playtest checklist

Manual acceptance of a generated HTML game (keyboard responses, feedback, block transitions,
end summary, event-log download, tamper resistance):
[docs/checklists/browser-playtest-checklist.md](docs/checklists/browser-playtest-checklist.md)

## Known limitations

1. **Real-LLM coverage is thin**: one bounded Gemini run (T5) passed end-to-end; the harder T2
   task stopped at the API budget boundary and has not been re-run since the P0/P1 engine
   extensions. On qwen2.5:7b + Ollama tool calls are silently dropped (known issue PA-14,
   `docs/handoff/ollama-toolcall-diagnosis-report.md`). The default acceptance gate remains
   FakeLLM + pytest; `LLMClientProtocol` stays swappable.
2. **Scientific validity needs researcher review**: the engine verifies structural
   reproducibility and content-consistent scoring, but whether a composed design measures
   what it claims (memory load, retention intervals, cue leakage, counterbalancing) is
   outside what it can check. T2's "nominal working-memory task" failure is the cautionary
   example.
3. **Timing not validated**: browser `setTimeout` scheduling is approximate — **not for formal
   experimental data collection**. This applies to phase durations too; the phased playback
   is gameplay-grade sequencing, not millisecond-accurate stimulus timing.
4. **Limited game interaction types**: the MVP supports keyboard only (choice keys / text /
   rating input), no pointer/touch/audio in the classic layout (the explore layout adds
   click-to-act); three feedback-style enums.
5. **Event log is not force-persisted**: it lives in page memory with a manual download on the
   end screen. Phase-onset timestamps for offline RT auditing are not yet emitted (planned).
6. Browser-automation playability testing (Playwright-style) is deferred (decision D2: the
   manual checklist stands in; node DOM-stub runtime tests cover the engine logic).

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
