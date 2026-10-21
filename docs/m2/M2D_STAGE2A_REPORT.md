# M2-D Stage 2a — Spatial Interaction (Implementation Report)

- **Status**: complete, **not committed, not pushed** (awaiting approval).
- **Goal met**: the exploration screen is now a visually interactive SVG room interface;
  **experimental behavior is unchanged** (same plan semantics, same cursor, same events,
  same stimuli — see §3).
- **Gates**: 331/331 tests (325 Phase 1 behavior-identical + 6 new) · pyright 0 errors ·
  coverage 90.38% ≥ 85% · all six CI gates PASS (sequential run; the parallel-run
  sandbox contamination from Phase 1 is fixed by per-test driver files).

## 1. What changed

| # | Requirement | Implementation |
|---|---|---|
| 1 | Deterministic, spec-driven SVG room view | `build_explore_plan` now emits a per-room `layout` (object slots + exit doorways) computed as a pure function of **declaration order** (fixed slot tables in Python: 2×3 object grid, 4 edge positions for exits). The engine renders an SVG floor panel (`viewBox 0 0 640 410`, scales responsively) — no runtime layout jitter, no content-dependent positioning |
| 2 | Clickable objects + exits, keyboard equivalents | A **unified action path**: `submitAction()` resolves the explore loop's action waiter; SVG node click handlers and the number keys route through the exact same `runAction()` (click ≡ key by construction, asserted in tests). Keys follow declaration order (hall: objects 1–3, exits study=4, library=5) |
| 3 | Inline inspection panel | `showInspect` renders an inset card **below the SVG room** (room stays visible) with a close button; dismissal = click close OR any key. No trial is ever consumed (tested via both input paths) |
| 4 | Visual states | Object nodes carry `examined` class: encounter = dimmed shape + green ✓ after its trial; flavour = dimmed after inspection. Unexamined = accent-stroked shape; hover thickens the stroke (CSS only) |
| 5 | Explore/encounter separation | unchanged from Phase 1 and now visually stronger: exploration = SVG room panel; encounter = bordered/tinted centered panel (`#stage.mode-experiment`) + "controlled trial" banner; the room view is replaced only during the trial |
| 6 | Responsive desktop layout | `svg { width:100%; max-width:640px; height:auto }` inside the existing 720px app column — works on ordinary desktop browsers; light/dark themes both styled |

**New input-routing rule** (engine): explore mode resolves through the action waiter;
inspect mode dismisses the panel; intro/briefing/encounter keep the classic `waitKey`
protocol. `createElementNS` + `textContent` only — the security contract (no
innerHTML/eval/document.write) is unchanged and re-asserted by tests.

## 2. Scientific constraints — compliance evidence

| Constraint | Evidence |
|---|---|
| No changes to stimuli/order/timing/correctness/bindings/fingerprints | plan trial projection is untouched (byte-for-byte same fields); `test_plan_trials_are_bundle_verbatim` re-runs green; v1 golden HTML byte-identity suite green; M1/M2-B/M2-C suites green |
| Spatial position / appearance / cues must not reveal condition or correct response | positions derive from **declaration order only**; `test_render_source_has_no_condition_dependent_styling` greps the renderer source for condition-styling vocabulary AND asserts no factor name appears anywhere in the plan's world section |
| No condition-dependent visual styling | Stage 2a implements none (salience→clutter mapping deliberately deferred to Stage 2c with its confound review); the only per-object visual difference is **role** (encounter vs flavour), which is declared gameplay semantics — and because trial assignment follows the player-driven consumption cursor, object identity cannot statically correlate with conditions |
| Gameplay visuals independent of measured content | the room view renders only GameSpec world/narrative data; stimulus lines render only inside the trial panel from the plan's verbatim projection |
| Monotonic cursor preserved | `runAction` keeps the Phase 1 cursor logic; `test_runtime_monotonic_cursor...` + click-path tests re-assert [0,1,2,3] ordering and re-exam inertness |

## 3. Compatibility evidence

- **v1 golden HTML**: byte-identical (`test_dispatch_v1_golden_html_unchanged`; the
  classic pipeline is untouched — no dispatch change was needed this stage).
- **Phase 1 behavior**: all 5 Phase 1 runtime scenarios still pass (keys remapped to
  declaration order — a presentation-only change documented in the tests).
- **Experiment plane**: no changes to ExperimentSpec, ExperimentBundle, GameSpec, or
  G1–G8 validation. Only `src/experiment/explore_render.py` was modified (plus tests).
- The rendered Manor HTML changed (new engine + layout data): deterministic across
  regenerations (sha256 `b8cca274…` reproduced; hashseed-independence test green).

## 4. Changed files

| File | Change |
|---|---|
| `src/experiment/explore_render.py` | layout slot tables + `_room_layout()`; plan gains per-room `layout`; engine: SVG room rendering, unified click/key action path, inline inspect panel, examined visual states, conclude button; CSS: SVG node/panel styles (light+dark), responsive rules |
| `tests/unit/experiment/test_explore_render.py` | +3 tests (layout declaration-order slots, oversized-room guard, no-condition-styling source/plan bans) = 20 total |
| `tests/unit/experiment/test_explore_runtime.py` | harness upgraded (createElementNS, click dispatch, id/class DOM reflection); per-test `driver-<name>.js` (parallel-run safe); keys remapped to declaration order; +3 new click tests (flavour click ≡ key, encounter click = exactly one trial + examined state + room preserved, click navigation + click conclusion through all 26 trials) = 8 total |
| `docs/m2/M2D_STAGE2A_REPORT.md` | this report |

Untouched: game_render.py, game_schemas.py, generation, stimulus, tools, AgentLoop,
all golden fixtures, the Manor fixture.

## 5. Test results

- Renderer suite: 20/20. Runtime suite: 8/8 (node-driven, from the rendered HTML).
- Full suite: **331/331** (+3 renderer, +3 runtime vs Phase 1), six gates PASS,
  pyright 0 errors, coverage 90.38%.
- Sandbox discipline: every test writes its own driver file; harness.js is written
  only if content differs — no shared mutable test artifacts remain.

## 6. Known limitations

- **DOM-stub fidelity**: the harness reflects `id` property assignment and
  `setAttribute("class")` → classList (the two browser behaviors the engine relies
  on); everything else (rendering, hit-testing, hover, focus, SVG text metrics,
  real pointer events) is verified manually — see §7.
- SVG label overflow **fixed during the final acceptance audit** (see §8a): door
  width is now a deterministic function of label length with edge-aware caps; the
  longest Manor label ('down the cellar stairs', est. 133 units) fits its 174-unit
  door. Final HTML sha256 `5c694bc6…`, reproduced byte-identically.
- Keyboard focus is not trapped in the SVG; number keys are global (same as Phase 1).
- The encounter trial itself remains keyboard-only (a/b/c); on-screen response
  buttons are a Stage 2b+ consideration.

## 7. Manual playtest instructions

```bash
.venv/bin/python examples/run_manor_prototype.py
open data/m2d-prototype/manor-case.html   # any modern desktop browser
```

Checklist (~10 minutes):
1. Intro → any key → the **Entrance Hall renders as a room panel**: three clickable
   shapes (dusty clock = circle, calling card / torn invitation = squares) and two
   doorways on the edges (heavy oak door, creaking passage) with key badges [1]–[5].
2. **Click the dusty clock** → an inline card appears below the room (room stays
   visible) with the inspect text + a close button; close it → the clock node is now
   dimmed. Or press `1` — same result.
3. **Click the calling card** → section briefing → fixation → the bordered
   "controlled trial" panel replaces the room; the four stimulus lines render
   verbatim; press `b` → back in the hall, the calling-card node is dimmed with a ✓.
4. Click it again → inline inspect card (no second trial); close.
5. **Click doorways** to walk hall ↔ study ↔ library ↔ parlour ↔ cellar; try the
   number keys too — identical behavior.
6. Narrow the browser window — the room panel scales down proportionally; try dark
   theme expectations (colors switch cleanly if theme is set in the spec).
7. Play all 26 encounters (any order) → the **conclude button** appears under the
   room; click it → summary + ending band + `Self-check OK` + event-log export.
8. Hover objects/doors — the stroke thickens (click affordance).

## 8. Rollback

Single-file source revert (`explore_render.py`) + test reverts; nothing else depends
on the new layout data (v1 path and dispatch untouched).

## 8a. Final acceptance audit (2026-10-21, user-requested eight items)

**Browser automation limitation (declared, not worked around)**: no browser-control
capability is available in this session; **items 1 and 6 are NOT claimed as
browser-verified**. What was done instead:

| # | Item | Method | Result |
|---|---|---|---|
| 1 | SVG objects/exits clickable in a real browser | **not verified here** — node DOM-stub click dispatch + manual checklist §7 steps 2–5 | stub-level PASS; browser = manual |
| 2 | Mouse ≡ keyboard state transitions | node acceptance driver: key-inspect vs click-encounter through the unified action path | PASS |
| 3 | Inline inspection consumes no trial | driver: cursor/done_trials unchanged after inspect; suite re-run | PASS |
| 4 | Examined state persists across leave/return | driver: hall → study (trial) → hall; calling-card still `examined` + ✓ glyph | PASS |
| 5 | Verbatim stimuli + trial order | driver: trial 0 lines byte-present; trial_start = [0,1] cursor order; suite re-run | PASS |
| 6 | Label overflow / hover / focus / responsive | **static analysis**: hover rules + responsive CSS + light/dark styles present; no `<input>`; **found and fixed** 5 overflowing exit labels (door width now label-length-driven, deterministic, edge-capped 128/220) | PASS (static + fix); visual = manual |
| 7 | 331 tests + six gates | full `check.sh` after the fix | **331/331, all gates PASS, coverage 90.38%** |
| 8 | Golden HTML unchanged + reproducibility | golden suites + v1 fingerprint tests green; demo HTML `62740ee0…`; Stage 2a HTML regenerated twice | PASS — `5c694bc6…` byte-identical |

The audit fix changed `explore_render.py` only (engine door rendering; no plan/schema/
measurement change). Final playable artifact: `data/m2d-prototype/manor-case.html`.

**Stopped. Awaiting review. No commit or push has been made. Stage 2b/2c not started.**
