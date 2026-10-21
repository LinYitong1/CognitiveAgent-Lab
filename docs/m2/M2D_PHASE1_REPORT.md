# M2-D Phase 1 — Minimal Playable Vertical Slice (Implementation Report)

- **Status**: complete, **not committed, not pushed** (awaiting review).
- **Scope held**: exploration runtime only (data + renderer + tests). No M2-E event-log
  schema, no M2-F, no scene-transition engine beyond room moves, no dependencies added.
- **Gates**: 325/325 tests (303 pre-existing behavior-identical + 22 new: 17 renderer +
  5 node-driven runtime) · pyright 0 errors · coverage ≥ 85% · all six CI gates PASS.

## 1. What was built

The Manor Case fixture is now a genuinely interactive, single-file browser game:

| # | Required experience | How it is realized |
|---|---|---|
| 1 | Navigate ≥ 2 connected rooms | 5-room world; exits are numbered items (`[4] a creaking passage`); G8 reachability guarantees no dead ends |
| 2 | Inspect non-experimental objects without consuming a trial | Flavour objects show `inspect_text` (mode `inspect`); logs `game: object_inspect`; cursor untouched (tested) |
| 3 | Encounter object initiates a controlled trial | Fresh encounter object → `game: encounter_trigger` → briefing (new block) → fixation → trial |
| 4 | Exact materialized `trial.stimulus.lines` | The plan carries bundle `stimulus.lines` verbatim; the engine renders them with no override surface; runtime test asserts every line byte-exact in the DOM |
| 5 | Response via approved bindings | Key → option resolution strictly from `mapping.response_bindings`; correctness computed from bundle `correct_from` factors |
| 6 | Return to exploration | After feedback/ISI the engine re-renders the room (same room, object marked `(examined)`) |
| 7 | Next encounter = next bundle trial, in order | Monotonic cursor (`TRIALS[cursor++]`); no selection surface; runtime test drives 4 encounters across 2 rooms in mixed object order → trial indices `[0,1,2,3]`; re-examined objects never re-fire |
| 8 | Clear exploration/experiment distinction | Distinct screen layouts + `#stage.mode-experiment` (bordered/tinted centered panel) + a "controlled trial — your response is recorded" banner |

## 2. Architecture

- **`src/experiment/explore_render.py` (new)** — the v2 layout renderer:
  `build_explore_plan()` (pure plan builder: world/narrative projections, verbatim
  trials, mapping bindings — strict, no silent fallbacks) + `render_explore_html()`
  (same embedding/security/integrity discipline as the classic renderer: `_js_string`
  escaping, split-interleaved template, embedded SHA-256 startup verification,
  textContent/createElement-only engine JS).
- **`src/experiment/game_render.py` (one guarded addition)** — a **v2 layout registry**
  (`register_v2_layout`). `render_game_html` dispatches to a registered renderer only
  for `schema_version == 2` + `mechanics.layout == "explore-and-encounter"`; every
  other spec (all v1, v2-sequential) takes the **unchanged classic path** — the golden
  HTML byte-identity suite re-runs green untouched.
- **`examples/run_manor_prototype.py` (new)** — renders the fixture into
  `data/m2d-prototype/manor-case.html` (single file, `file://`, no network).
- **Untouched**: ExperimentBundle, generation engine, stimulus materialization,
  GameSpec schemas and G1–G8 validation semantics, tools, AgentLoop.

Invariants preserved: game content cannot overwrite stimuli or response semantics
(structurally — the GameSpec has no such fields); no genre/Manor vocabulary in the
shared runtime (grep-enforced); no research-grade timing or persistence claims
(footer + end-screen disclaimers; the event log must be exported manually).

Event log (provisional, channel-tagged; final schema is M2-E):
`measurement` = trial_start / block_start / response / game_end (the data body);
`game` = game_start / room_enter / object_inspect / encounter_trigger (flow only).

## 3. Tests (22 new)

`tests/unit/experiment/test_explore_render.py` (17) — plan invariants (reachability,
encounter/mapping parity, verbatim trials, mapping-surface bindings, renderer guards:
non-choice responses / missing bindings / unmaterialized stimulus / missing sections),
HTML structure + mode-distinction CSS, embedded-plan losslessness, integrity anchors,
malicious-text escaping, determinism (+ PYTHONHASHSEED independence), genre-vocabulary
ban, dispatch: v1 golden byte-identity, explore routing, v2-sequential classic path.

`tests/unit/experiment/test_explore_runtime.py` (5, node-driven) — the shipped engine
JS is extracted from the rendered HTML and executed under node against a minimal DOM
stub: navigation + `room_enter` logging; flavour inspection consumes nothing;
encounter activation with verbatim stimulus + binding resolution (`b` → `"b"`,
correctness vs bundle) + return to exploration; monotonic cursor across rooms and
arbitrary object order + re-examination inertness; and a **synthetic non-Manor
two-room game** (distinct keys j/k → options x/y) driven to conclusion with the
runtime self-check, ending band and channel discipline asserted — proving the runtime
is generic, not Manor-specific.

### Browser-automation limitations (recorded)

No real browser is driven. The node harness verifies the state machine, event log and
data integrity against a DOM stub; it does **not** verify visual layout, CSS, focus
handling, real keyboard event semantics or `setTimeout` fidelity (real timers are used,
but scheduling precision is node's, not a browser's). Visual/UX verification is manual
(§5). Runtime tests are skipped gracefully when node is unavailable (same policy as
the existing BR-8 integrity tests).

## 4. Known limitations (Phase 1)

- Choice responses only; a non-choice response fails loudly at plan build
  (`ValueError` → tool `ok=False` via the registry's exception handling).
- Concluding the session requires all trials consumed (`[x]` appears then); no early
  quit/export mid-session.
- Encounter objects beyond the trial count become inspect-only with an on-screen note.
- Exit key order is alphabetical (deterministic embedding, `sort_keys`), not the
  GameSpec declaration order — presentation-only, documented.
- The event vocabulary is provisional; reconciliation (`verify_game_events`) is M2-E.
- The renderer consumes `trial.timing` (fixation/stimulus deadline/ISI) as the classic
  engine does; browser timing remains approximate.

## 5. Manual test instructions

```bash
.venv/bin/python examples/run_manor_prototype.py
open data/m2d-prototype/manor-case.html   # macOS; or drag the file into a browser
```

Checklist (10–15 minutes):
1. Intro screen → press any key → you are in the Entrance Hall.
2. Press `1` (dusty clock) → inspect text, no trial counted (header `trials 0/26`).
3. Press `2` (calling card) → section briefing → fixation `+` → the four stimulus
   lines appear in the bordered "controlled trial" panel (visually distinct from the
   room view).
4. Press `b` → no feedback → after ~0.5 s you are back in the hall; the calling card
   is now marked `(examined)`; header `trials 1/26`.
5. Press `3` (torn invitation) → the **next** trial (no briefing, same block).
6. Press `4` → you move to the Library; press `5` → the Study; explore freely —
   every room is reachable.
7. Play through all 26 encounters (any order) → `[x] conclude the session` appears →
   press `x` → summary, ending band, `Self-check OK`, event-log textarea.
8. "Download event log (JSON)" exports the channel-tagged log.

## 6. Rollback

Three new files + one guarded dispatch block in `game_render.py` (additive; the
classic path is byte-identical). Single revert restores the pre-M2-D state.

**Stopped. Awaiting review. No commit or push has been made.**
