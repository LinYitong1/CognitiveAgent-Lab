# M2-A — M2 Implementation Roadmap

- **Status**: plan only. Nothing implemented; no M1/Phase A/B code modified; no dependencies added.
- **Discipline carried forward**: milestone-by-milestone user approval (no auto-advance); Architect → Backend → QA per milestone; FakeLLM as the acceptance gate (PA-14 real-LLM work stays deferred); byte-reproducibility tests at every step; frozen v1 behavior verified by regression at every step.
- **Compatibility invariant for every milestone below**: v1-shaped inputs (ExperimentSpec without v2 fields; GameSpec v1) must keep producing identical fingerprints and byte-identical HTML. This is a hard acceptance item in each milestone.

---

## 1. Milestones

### M2-B — Research Layer v2 (engine extensions)
**Scope**: `schema_version: 2` (additive optional fields): R1 `stimulus_spec` + deterministic stimulus materialization into `trial.stimulus`; R2 `BlockSpec.timing` override + `TimingSpec.response_window_ms` (miss → `no_response` error trial); R3 derived materialization; R4 `measures` metadata. Engine + `validate_experiment` rules only — **no renderer changes yet**.
**Dependencies**: none (self-contained engine work).
**Acceptance**: AC-1/2/3 from PROTOTYPE_SPEC; v1 golden fixtures byte-identical under v2; new unit tests for materialization determinism (PYTHONHASHSEED-independent), window-miss semantics, per-block timing override; full suite green; pyright 0.
**Estimated size**: medium (engine + validation + tests; no runtime surface).

### M2-C — GameSpec v2 + Mapping Layer (design-time)
**Scope**: optional `world` / `narrative` / `mechanics` / `mapping` sections (all `extra="forbid"`, bounded); `validate_game` v2 rules G8_* (mapping consistency, encounters ≥ trials, experiment-semantics keys rejected everywhere); v1 specs remain valid.
**Dependencies**: M2-B (mapping references materialized stimulus semantics).
**Acceptance**: AC-5; one negative test per forbidden key family; every v1 GameSpec fixture still validates identically; FakeLLM iteration test shows a mapping error being surfaced and repaired through the two-tier error contract.

### M2-D — Runtime v2 (exploration + two-class event log)
**Scope**: renderer template extension — `explore-and-encounter` layout (room graph navigation, object inspection, encounter→next-bundle-trial pull), two-class event log (`measurement`/`game`), log header with bundle fingerprints, narrative surfaces (intro/briefing/banded ending), self-check page extensions. `render_game` unchanged in contract (new GameSpec sections flow through validation).
**Dependencies**: M2-B (materialized stimuli), M2-C (world/mapping validated).
**Acceptance**: AC-6 (scripted full-playthrough fixture reconciles 30/30), AC-7 file://+zero-deps verified, AC-8 keyboard-completeness via checklist + self-check, AC-9 log schema; byte-identity golden tests for the prototype bundle+gamespec; size budget < 1 MB confirmed; existing BR tests untouched-green.
**Estimated size**: the largest milestone (template JS + fixtures + golden files).

### M2-E — Verification + Agent workflow + prototype delivery
**Scope**: new tool `verify_game_events` (generator-free reconciliation, negative-tested on tampered logs); `design_game` intake tool (LLM-facing, R2-ASCII description pattern); stage/gate conventions + researcher checkpoint presentation (artifacts + report + checklist link; explicit human approval step — formal pending→approved artifact states listed as extension); the full "Manor Case" example (ExperimentSpec v2 + GameSpec v2 + FakeLLM E2E script + CLI demo path); README/Skill updates; browser playtest session with the checklist.
**Dependencies**: M2-B/C/D.
**Acceptance**: AC-4 (tampered log rejected), AC-10 (suite ~300 green), AC-11 (FakeLLM five-stage run, fault-injection), AC-12 (checkpoint semantics); independent QA report; user approval before any "released example" label.

### Follow-ups (post-M2-E, each requires its own approval)
- M2-F: `pressure`/deadline condition study example (if deferred from the minimal core, see PROTOTYPE_SPEC §7); formal pending→approved artifact states; Playwright smoke tier (D2 revisit); auto-download of logs; audio/pointer modalities; vendored-Phaser layout evaluation (explicit dependency waiver required); research-validity layer (the three-tier framework from the external review: engineering / methodological / theoretical validity — user-directed to the M2+ roadmap, not implemented in M2-A..E).

## 2. MVP vs later extensions

| In MVP (M2-B..E) | Later extensions |
|---|---|
| Text-only stimulus materialization (R1) | Image/audio assets; generated media |
| Explore-encounter layout, 5-room prototype | Additional layouts; vendored Phaser layout |
| Response deadline (R2) — *separable; may slide to M2-F per PROTOTYPE_SPEC §7* | Formal timing validation studies |
| Two-class event log + manual download + provenance header | Auto-persist; server-side collection; participant management |
| `verify_game_events` reconciliation | Playwright automation tier; CI browser gates |
| Checkpoint presentation + explicit human approval | Formal pending→approved artifact states; approval audit trail |
| FakeLLM five-stage E2E | Real-LLM E2E (PA-14, deferred; interface stays swappable) |
| Mystery prototype as repo example | Example library (other genres/paradigms) |

## 3. Dependency graph

```
M2-B (engine v2)
   └── M2-C (gamespec v2 + mapping) ── depends on B
          └── M2-D (runtime v2)     ── depends on B+C
                 └── M2-E (verification + workflow + example) ── depends on B+C+D
                        └── M2-F+  (follow-ups, individually approved)
```

## 4. Decisions requiring researcher approval (blocking, before the respective milestone)

| # | Decision | Needed by | Default if unaddressed |
|---|---|---|---|
| D-M2-1 | Approve `schema_version: 2` policy: optional additive fields; v1 byte-compatibility as hard gate | M2-B start | — (blocks M2-B) |
| D-M2-2 | `no_response` semantics: a deadline miss counts as an error trial (accuracy denominator includes misses) — confirm this is the intended scoring | M2-B start | Misses = errors (standard) |
| D-M2-3 | Exploration events (`room_enter`/`object_inspect`) are logged as behavioural data but excluded from bundle reconciliation — confirm they may count as "recorded meaningful behaviour" | M2-D start | Two-class split as specified |
| D-M2-4 | Prototype scope: full 2×2 (+deadline, R2 in M2-B) vs. minimal single-factor core first (R2 slides to M2-F) | M2-B start | Minimal core first (PROTOTYPE_SPEC §7) |
| D-M2-5 | End-screen accuracy-band narrative content (three bands) — review text before M2-E example ships | M2-E start | Neutral band texts drafted by Architect |
| D-M2-6 | Whether the mystery example ships publicly on first delivery or stays in-repo until a playtest cycle completes | M2-E end | Stays in-repo, ships after playtest + approval |

## 5. Risks (top five)

| Risk | Level | Mitigation |
|---|---|---|
| Runtime v2 template complexity undermines byte-identity discipline | Medium | Keep pure template assembly; golden tests from first runnable build; logic-core-first development (reconciliation fixture before visuals) |
| Exploration mode lengthens the path to a wrong-but-green build (game feels broken though tests pass) | Medium | Self-check page grows with mechanics; human playtest is a per-milestone gate (AC-7/8) |
| Spec v2 scope creep (fields accrete before validated) | Medium | Each proposed field must name its prototype consumer or it is cut to follow-ups |
| qwen2.5:7b cannot author GameSpec v2 even with examples (PA-14 same-type risk) | Known | FakeLLM gate + few-shot examples in tool descriptions + staged generation; real-LLM remains deferred, interface swappable |
| Single-file size growth from world/narrative data | Low | Bounded schema (≤8 rooms/≤24 objects); size budget asserted in M2-D |

---

## Final report summary (for the user)

The recommended smallest scientifically meaningful M2 prototype is the **"Manor Case" minimal core** (PROTOTYPE_SPEC §7): deterministic text-clue materialization (R1) + explore-and-encounter runtime + play-time event reconciliation, with a single-factor load manipulation (20 main trials), fully buildable in four milestones (M2-B→C→D→E) under approach **A** (extend the deterministic renderer). The full 2×2 design and response-deadline mechanics are cleanly separable follow-ups. Six named decisions (D-M2-1..6) require your approval before implementation begins; nothing has been implemented, committed, or pushed.

**This phase stops here. Implementation of any M2 milestone awaits explicit approval.**
