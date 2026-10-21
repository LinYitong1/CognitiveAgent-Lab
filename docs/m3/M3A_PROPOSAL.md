# M3-A Proposal — End-to-End Agent Autonomy: Researcher Prompt → Playable Game

Status: **proposal only — nothing implemented**. This document is the capability-gap
assessment the user requested plus the definition of the next milestone. Approval of
this document authorizes M3-A implementation; nothing else does.

---

## Part 1 — Capability-gap assessment (the researcher's journey, step by step)

The journey as it should be, with each step marked AUTONOMOUS (works today, driven by
code+LLM, no hand-written inputs), ASSISTED (mechanism exists but a human supplies
the critical input), or MANUAL (hand-written fixture/script is the only path).

| Step | What the researcher does | Status today | Evidence / gap |
|---|---|---|---|
| 1. Describe the experiment | Writes a natural-language description | **NOT BUILT** | No prompt→spec guidance exists for the agent. The AgentLoop accepts any goal, but nothing instructs the LLM *how* to map research intent onto ExperimentSpec/GameSpec fields |
| 2. Agent interprets requirements | LLM reads the description | **PARTIAL** | AgentLoop + tool-calling work (M1, FakeLLM-proven; real-key path untested — PA-14). But the system prompt is task-neutral: no experiment-design knowledge, no schema-authoring guidance |
| 3. Agent generates ExperimentSpec | `generate_spec` tool call | **AUTONOMOUS MECHANISM / UNGUIDED CONTENT** | The tool validates loudly (21 V2_* codes), so the agent gets error feedback. But the *content* — factors, levels, blocks, stimulus_spec templates, balance — has only ever been written by humans: the demo script, the example, the Manor fixture. Zero evidence an LLM can author a valid v2 spec unprompted |
| 4. Agent generates GameSpec | `validate_game` iteration | **AUTONOMOUS MECHANISM / UNGUIDED CONTENT** | Same shape: G1–G8 give rich error feedback and the stalled-iteration guard exists, but every valid GameSpec to date is human-authored (demo script, Manor). The v2 world/narrative/mechanics/mapping sections have **no LLM-facing documentation** — the tool descriptions say "schema_version(=1)" and don't mention v2 at all |
| 5. System creates the playable game | `export_spec` → `render_game` | **AUTONOMOUS** | Fully working: bundle export, validation, v2 explore renderer, byte-reproducible HTML. `run_task(goal, settings, client)` wires the whole loop; `run_demo` proves it end-to-end (with a script) |
| 6. Controlled variables & measurements traceable | Fingerprints + verify | **AUTONOMOUS** | config/trials fingerprints, bundle_sha256, SHA-256 startup check in-game, `verify_bundle` (generator-free), `cli verify`. Controlled invariants are structural (schema absence) — traceability is the strongest part of the system |
| 7. Deliverables: game + config + verification | Artifact set | **AUTONOMOUS** | Bundle JSON + GameSpec JSON + HTML + event log export + verify report, all in the output dir |

**The headline gap**: steps 3–4 are autonomous *mechanisms* wrapping human-authored
*content*. The single missing piece between "library of validated schemas" and
"agent that designs experiments" is **LLM-facing guidance**: a system prompt that
teaches the schema-authoring workflow, and tool descriptions that document v2.
Everything else — validation feedback loops, stalled guards, rendering, verification —
already exists and is frozen. **No new frameworks, schemas, agents, or tools are
needed.**

Secondary gaps (real but lower priority than the headline):
- Real-LLM path untested (PA-14): the loop is FakeLLM-proven only; first real run may
  surface protocol/latency issues. M3-A's definition of done includes one real run.
- The demo CLI produces the v1 classic layout; a v2-explore demo would showcase the
  full experience, but that's presentation, not capability.
- Post-session reconciliation (M2-E) — needed for *data collection*, not for *game
  generation*; correctly out of scope here.

## Part 2 — M3-A milestone definition

**One sentence**: a researcher types one natural-language prompt; the agent
autonomously produces a verified, playable browser game plus the experiment bundle,
GameSpec, and verification report — and the demonstration runs on a second, non-Manor
experiment to prove generality.

### Boundaries

**Research boundaries (what M3-A claims and does not):**
- CLAIM: autonomous translation of a researcher prompt into schema-valid, verified,
  playable game artifacts, with deterministic reproduction and structural
  traceability of controlled variables.
- DOES NOT CLAIM: experimental validity of the generated design (factor structure,
  counterbalancing adequacy, stimulus quality are the LLM's authoring choices —
  schema validity ≠ scientific validity; a human researcher must review the design);
  research-grade timing (unchanged browser disclaimer); participant data collection
  (M2-E).
- DOES NOT CLAIM: generality across all cognitive paradigms. Two demonstrated
  paradigms (Manor-adjacent category judgement + a second, different structure) is
  evidence of *mechanism* generality, not *coverage*.

**Engineering boundaries (reuse-first):**
- Extend ONLY: `src/pipeline.py` (a prompt-template constant + optional orchestration
  convenience), tool *descriptions* in `experiment_tools.py`/`game_tools.py`
  (documentation strings — the parameter-schema surface the LLM sees), and the
  examples/tests layer.
- MUST NOT touch: ExperimentSpec/GameSpec schemas, generation/validation semantics,
  fingerprints, renderer, AgentLoop, ToolRegistry mechanics, the M1 frozen tools.
- No new tools, agents, files of framework code, or dependencies. The guidance lives
  in prompt text and tool descriptions — data, not code.
- No Manor-specific vocabulary in any shared surface (existing grep tests enforce
  this and extend naturally).

### Deliverables (judged by researcher usability, not artifact count)

1. **Agent guidance**: a system-prompt template for the experiment→game workflow
   (schema-authoring walkthrough: research intent → factors/levels/blocks →
   stimulus_spec → GameSpec v2 world/narrative/mechanics/mapping → validate-iterate
   → export → render → verify). Plus v2 documentation in the two tools' descriptions
   (the `validate_game` description currently says "schema_version(=1)" — stale and
   LLM-misleading; this is the one concrete bug-level fix).
2. **Second experiment demonstration**: a researcher-prompt→game run on a
   non-Manor paradigm — proposed: **a working-memory load manipulation with a
   starfield/space-station theme** (2-back-style letter load factor × response
   modality, explore layout with a space-station world). Different theme, different
   task structure (memory load vs perceptual salience), same pipeline. Real-LLM if a
   key is provided; FakeLLM-scripted as the deterministic fallback that still proves
   the workflow shape.
3. **One-command researcher entry**: `cognitive-agent run "..."` already exists via
   `run_task`; M3-A makes it *usable* by supplying the guidance above, and documents
   the researcher-facing flow (prompt → artifacts → how to check the game).
4. **Acceptance = the demo, not documents**: the milestone is done when the second
   experiment's game opens in a browser, validates green (G-rules + V-rules), and
   `cli verify` passes on its bundle — produced from the researcher prompt through
   the agent path, with no hand-written spec files.

### Explicitly deferred

Stage 2b/2c polish (narrative systems, condition-dependent presentation), M2-E event
reconciliation, multi-paradigm coverage testing, participant-facing data export,
any performance work.

### Risks (stated before implementation)

1. **LLM authoring quality**: v2 specs are demanding (slot grammar, invariants,
   block coverage). Mitigation: validation feedback loops already exist and are the
   designed iteration mechanism; the stalled guard bounds thrashing; the guidance
   prompt encodes the known authoring pitfalls (from every G8 error we have written
   tests for).
2. **Real-LLM protocol issues** (PA-14): first real run may fail. Mitigation: this is
   in-scope to fix (bug-fix level), and the FakeLLM demonstration stands
   independently.
3. **Guidance-bloat in tool descriptions**: the 700-char description budget test
   exists for a reason; v2 docs may need the input-model field-description pattern
   already used by experiment_tools (established, tested approach).

---

## Part 3 — Why this is the highest-value next step

- It attacks the **only** missing capability (LLM-facing guidance) while every other
  layer is built, frozen, and regression-tested — 331 tests are the safety net.
- It is small: prompt text + two tool-description updates + one example + tests.
- It converts the project's existing strength (verified determinism and structural
  traceability) into the thing the vision actually promises: an *agent* that designs,
  not a library that renders.
- Success is measured by the user's own criterion: *a researcher can actually use the
  Agent to create a new playable cognitive experiment.*
