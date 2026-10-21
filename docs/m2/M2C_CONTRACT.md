# M2-C — GameSpec v2 + Research–Game Mapping Layer: Contract Design

- **Status**: contract design only. Nothing implemented; no files modified; nothing committed or pushed.
- **Upstream verified facts** (M2-B audit at `7e9978c`, run today): materialized `trial.stimulus = {"lines": [str, ...]}` (the only key), `trial.derived = {name: int}`, `spec.measures = [{name, source, notes}]`, all covered by `trials_fingerprint` / `verify_bundle`. GameSpec v1 is fully `extra="forbid"` (G1–G7, 9 error codes); the v1 renderer displays `trial.factors` pairs and never reads `trial.stimulus`.
- **Non-negotiables honored**: M1 + M2-B APIs and artifact bytes unchanged; no detective concepts in shared schemas; generation engine untouched (zero imports added to `src/experiment/{generation,schemas,stimulus}.py`); single-agent; zero dependencies; no M2-C/D implementation; no existing-file modification; no commit/push.

---

## Part 1 — M2-B audit summary (what this contract builds on)

| Aspect | Verified state at `7e9978c` |
|---|---|
| Materialized stimuli | `{"lines": [...]}` only key; length-matched levels; seed-derived content; byte-reproducible |
| Derived values | int-only, whitelisted ops, per-trial |
| Measures | metadata only; no collection claim |
| Fingerprints | v2 fields in `config_fingerprint` when set; stimulus/derived in `trials_fingerprint`; `verify_bundle` accepts v2 bundles; v1 bytes unchanged (externally cross-checked) |
| **Gap this contract addresses** | the renderer has no way to *present* materialized stimuli, no place to describe *game content* (scenes/objects/narrative), and no *mapping* declaring how player actions become measurement trials |

## Part 2 — GameSpec v2: paradigm-independent extensions

Design principle (unchanged from v1): **the GameSpec describes presentation only; it can never express experiment semantics**. v2 adds four optional sections — all `extra="forbid"`, all bounded, none referencing any genre. A v1 GameSpec remains valid, byte-for-byte (same projection discipline as M2-B: absent/new sections are `None`-defaulted and excluded from `game_config_fingerprint` when unset).

```
GameSpec v2 (additions only; v1 keys: game / experiment_ref / scene / input / feedback / flow / gamification)
├── world:        WorldSpec | None          # scene graph + interactive objects
├── narrative:    NarrativeSpec | None      # static text surfaces
├── mechanics:    MechanicsSpec | None      # which registered interaction patterns are enabled
└── mapping:      MappingSpec | None        # research–game mapping (Part 3)
```

### 2.1 `world` — scene graph + interactive objects

```
WorldSpec:
  rooms: dict[roomId, RoomSpec]           # ≤ 8 rooms; roomId slug [a-z0-9-]{1,24}
  start_room: roomId                      # must exist
RoomSpec:
  title: str (≤ 60)
  description: str (≤ 400)                # static flavour text
  exits: dict[roomId, str]                # ≤ 4; target must exist; value = label (≤ 24)
  objects: list[ObjectSpec]               # ≤ 6 per room
ObjectSpec:
  object_id: str (slug, unique across world)
  label: str (≤ 40)
  inspect_text: str (≤ 400)               # flavour: shown on inspection, no measurement
  role: Literal["flavour", "encounter"]   # encounter = pulls the next bundle trial (see mapping)
```

- **Paradigm independence**: a room is a *named context with exits*; an object is a *labeled inspectable with a role*. Nothing about detectives, clues, suspects, patients, or maps. The Manor Case's "library" is a room titled "Library"; its "wine ledger" is an object with `role: "encounter"`.
- Text-only (v1 `scene.assets` remains UI decoration only); bounds keep single-file size and validation surface small.

### 2.2 `narrative` — static text surfaces

```
NarrativeSpec:
  intro: str (≤ 800)
  block_briefings: dict[blockName, str]   # ≤ 800 each; key must be a declared block name
  ending_bands: list[EndingBand] | None   # ≤ 3, non-overlapping
EndingBand:
  min_accuracy: float (0..1)              # band lower edge; bands sorted ascending, no overlap
  text: str (≤ 400)                       # rendered post-session (cannot contaminate measurement)
```

### 2.3 `mechanics` — registered interaction patterns

```
MechanicsSpec:
  layout: Literal["canvas-center", "rows", "explore-and-encounter"]   # new enum member
  inspect_objects: bool = True            # objects inspectable in explore mode
  trial_trigger: Literal["sequential", "explore-encounter"] = "sequential"
```

`explore-and-encounter` is a **new registered layout** in the (future M2-D) renderer's layout registry — the v1 registry philosophy (`canvas-center|rows`): new gameplay = new layout template + tests, core untouched. `trial_trigger` duplicates the mapping's trigger for convenience but **must agree with `mapping.trial_trigger`** when both are set (G8 check).

### 2.4 Alternatives & trade-offs (Part 2)

| Decision | Chosen | Rejected alternative & why |
|---|---|---|
| World as room graph vs. free-form "scenes list" | Room graph with bounded exits | Free-form scenes have no traversal model → runtime would invent semantics; a bounded graph is validatable (reachability, no orphan rooms) and renderer-implementable |
| Objects embedded in rooms vs. global object table | Embedded | Global table requires cross-referencing rooms↔objects (a second source of truth); embedding makes "objects in this room" structural |
| Narrative as branching tree vs. static surfaces | Static only | Branching engines multiply state and validation surface; MVP needs motivation text, not interactive fiction (PROTOTYPE_SPEC §6 non-goal) |
| New layout enum member vs. new top-level "mode" flag | Enum member | Layout already is the v1 mechanism for "how trials are presented"; a parallel mode flag would create two knobs for one concern |

## Part 3 — Research–Game Mapping contract

### 3.1 `MappingSpec` shape

```
MappingSpec:
  trial_trigger: Literal["sequential", "explore-encounter"]
  encounter_objects: list[object_id] | None    # required iff trial_trigger=explore-encounter
  response_bindings: list[ResponseBinding]     # ≥1; reuses v1 binding semantics
  creative_freedom: list[Literal[
      "theme", "room_labels", "object_labels", "narrative_text", "feedback_style"]]
  controlled_invariants: list[Literal[
      "trial_order", "conditions", "stimulus_content", "correct_answers", "timing"]]
ResponseBinding:
  response_name: str        # must be a declared response variable in the bundle spec
  keys: dict[str, str]      # key -> option value (same shape as v1 InputBinding)
```

### 3.2 Semantics (the load-bearing rules)

1. **Trigger rule**: with `explore-encounter`, examining an object in `encounter_objects` (and only such an object) pulls the **next unconsumed trial in bundle index order**. The runtime holds a consumption cursor; it can neither skip nor reorder (cursor = 0..N-1 monotonic). Encounter objects may exceed the trial count (extra encounters after the last trial simply show a "session complete" state); **encounter objects < total trials → invalid** (G8).
2. **Stimulus rule**: the encounter renders **`trial.stimulus["lines"]` verbatim** (M2-B materialization). The game layer cannot alter, filter, or re-order lines — there is no field for it. When a trial's stimulus is empty (v1-shaped spec), the encounter renders the v1-style factor display (v1 compatibility path).
3. **Response rule**: `response_bindings` map keys to option values for each declared response, exactly v1 `input.bindings` semantics — value correctness is computed by the renderer from the bundle (`correct_from`), never by game content.
4. **Declaration of the fence**: `creative_freedom` / `controlled_invariants` are *declarative documentation of the architecture*, machine-checked for exactly two things: (a) `controlled_invariants` must contain all five invariant literals (the fence is not optional — omitting one is a G8 error, preventing silent erosion); (b) `creative_freedom` entries must be from the closed literal list (no invented freedoms). This makes the iron rule *stated in the artifact and validated*, per DESIGN_REVIEW.
5. **Per-block feedback requirement** (DESIGN_REVIEW §2 control): `narrative.block_briefings` keys must cover **every declared block** (G8); feedback during measured trials stays governed by v1 `feedback` (global). *Note*: per-block feedback *values* remain a v2 addition candidate for M2-D scope discussion — flagged in Part 9 blocking decisions, not silently assumed.

### 3.3 Alternatives & trade-offs (Part 3)

| Decision | Chosen | Rejected & why |
|---|---|---|
| Mapping inside GameSpec vs. separate artifact | Inside GameSpec (optional section) | A separate file splits one validated artifact into two, doubles fingerprint chaining and the LLM's authoring surface; one GameSpec = one validated object is the v1 lesson |
| Encounter → trial binding by explicit `trial_index` vs. consumption cursor | Cursor (bundle order) | Explicit indices let the game layer *choose* trial order — exactly the control we must not give away; cursor order is forced by the bundle |
| Room-based trigger vs. time-based trigger vs. any-object trigger | Designated objects | Time-based re-introduces fixed-pace trials (kills self-pacing agency, DESIGN_REVIEW §2); any-object makes every inspection measured (kills flavour exploration) |
| Freedom/invariants as documentation only vs. machine-checked literals | Machine-checked closed lists | Documentation-only erodes; closed literals + mandatory invariants list make the fence part of validation |

## Part 4 — Event model: exploration vs. measurement

Two classes (adopting the WebGameTemplate split, per DESIGN_REVIEW):

| Class | Events (M2-D runtime will emit) | Integrity verification |
|---|---|---|
| `measurement` | `trial_start` (index, block, conditions), `response` (index, response_name, value, correct, rt_ms), `no_response`, `block_start/end`, `session_end` | **Required**: every measurement event must reconcile against the bundle (order, conditions, correctness) — the M2-E `verify_game_events` tool (out of M2-C scope; the *schema vocabulary* is fixed here so M2-C validation can already reason about response bindings) |
| `game` | `room_enter`, `object_inspect`, `encounter_trigger`, `exploration_resume` | **Not reconciled** (no bundle counterpart); logged with timestamps as engagement/behaviour traces; counted (encounter_trigger count must equal consumed trials — checked at reconciliation time, M2-E) |

**Why measurement events need verification and game events do not**: measurement events *are the data*; a dropped, reordered, or fabricated response silently corrupts the dataset. Game events describe presentation flow; their absence indicates reduced engagement evidence but cannot corrupt the experiment. The boundary is exactly the research/game layer boundary (D-M2-3, provisional).

## Part 5 — Creative variation without touching locked content

The four creative surfaces (machine-closed `creative_freedom` list) can vary freely **at GameSpec-authoring time** (different GameSpecs = different games over the *same* bundle — the differentiator vs. reference projects):

- `theme` / `feedback_style`: v1 presentation enums.
- `room_labels` / `object_labels` / `narrative_text`: all bounded strings in `world`/`narrative`.

What can never vary (the five invariants, all validated by construction — no field exists to express them):
1. **trial_order** — cursor consumption, G8-validated encounter count;
2. **conditions** — rendered from `trial.factors` at encounter time;
3. **stimulus_content** — rendered verbatim from `trial.stimulus["lines"]`; GameSpec has no stimulus field;
4. **correct_answers** — computed by the renderer from bundle `correct_from`; correctness never appears in GameSpec;
5. **timing** — from `trial.timing` (bundle); GameSpec has no timing field.

Runtime variation (post-authoring, e.g. randomized flavour object order per session) is **out of M2-C scope** and must be seeded + logged if ever introduced (M2-D decision); the contract requires nothing here.

## Part 6 — Manor Case walkthrough (one interaction, end to end)

Setup (all generic primitives; the *example* supplies the detective vocabulary):

```
Bundle (schema_version 2, seed 20261021): factors salience{salient,embedded}, true_suspect{a,b,c};
  block practice(6) + block investigation(20); response accuse(choice, options[a,b,c], correct_from=true_suspect);
  stimulus_spec materializes e.g. trial #7 (embedded): lines = ["The gardener...", "Payments traced to suspect b.", "A torn glove...", "Frost on the pane."]
GameSpec v2: world.rooms = {hall(start), study, library, parlour, cellar};
  library.objects includes {object_id:"wine-ledger", label:"wine ledger", role:"encounter", inspect_text:"A heavy ledger..."};
  mapping = {trial_trigger:"explore-encounter", encounter_objects:["wine-ledger", ...30 total ≥ 26 trials],
             response_bindings:[{response_name:"accuse", keys:{"1":"a","2":"b","3":"c"}}],
             creative_freedom:[theme,room_labels,object_labels,narrative_text,feedback_style],
             controlled_invariants:[trial_order,conditions,stimulus_content,correct_answers,timing]}
```

One interaction, step by step:

1. Player (in hall) moves to library → runtime logs `game: room_enter {from:"hall", to:"library", t_epoch_ms}` — not reconciled.
2. Player inspects "dusty clock" (flavour) → `game: object_inspect {object_id:"dusty-clock", t}`; flavour text shown; **no cursor movement**.
3. Player examines the **wine ledger** → `game: encounter_trigger {object_id:"wine-ledger", t}`; runtime pulls bundle trial index 6 (cursor 0→6: the 7th encounter of the session, order forced by bundle indices 0..N-1).
4. Encounter screen renders `trial #7.stimulus.lines` **verbatim** (4 materialized lines); logs `measurement: trial_start {trial_index:6, block:"investigation", conditions:{salience:"embedded", true_suspect:"b"}}` — reconcilable.
5. Player presses `2` → binding resolves to value `"b"`; renderer computes `correct = (trial.factors["true_suspect"] == "b")` from the bundle → `true`; logs `measurement: response {trial_index:6, response_name:"accuse", value:"b", correct:true, rt_ms, t}`; cursor advances to 7.
6. No feedback (investigation block, v1 `feedback=none`); return to library → `game: exploration_resume {room:"library", t}`.
7. Post-session: M2-E `verify_game_events` asserts measurement events == bundle trials 0..25 in order, conditions match, correctness recomputed — the proof the played session matches the design.

## Part 7 — Validation, negative tests, backward compatibility

### 7.1 New validation rules (G8 family, additive; G1–G7 untouched)

| Code | Rule (each gets ≥1 negative test) |
|---|---|
| G8_MAPPING_UNKNOWN_REFERENCE | encounter_objects / response_bindings / block_briefings reference undefined object_id / response / block |
| G8_MAPPING_ENCOUNTER_SHORTFALL | encounter_objects count < total bundle trials |
| G8_MAPPING_TRIGGER_CONFLICT | mechanics.trial_trigger ≠ mapping.trial_trigger (when both set) |
| G8_MAPPING_INVARIANT_MISSING | controlled_invariants missing any of the five literals |
| G8_MAPPING_FREEDOM_UNKNOWN | creative_freedom entry outside the closed list |
| G8_WORLD_STRUCTURE | unknown exit target / orphan room (unreachable from start) / duplicate object_id / start_room missing / bounds violations |
| G8_STIMULUS_SEMANTICS | mechanics/layout = explore-and-encounter while the bundle spec is v1-shaped (no stimulus_spec) **and** no fallback declaration — see blocking decision D-M2-C-2 |
| G8_VERSION_GUARD | any v2 section on `schema_version: 1` GameSpec (GameSpec v2 = `schema_version: 2`) |

Schema-shape errors and unknown keys → existing SCHEMA_INVALID path (extra=forbid), unchanged.

### 7.2 Backward compatibility guarantees (test-enforced, M2-B discipline)

- Every v1 GameSpec fixture validates **identically** (same errors/warnings/fingerprint) — projection discipline: `game_config_fingerprint` excludes unset v2 sections, so v1 fingerprints are stable.
- v1 bundles + v1 GameSpecs → renderer output byte-identical (M2-D's gate, prepared here by keeping render-relevant additions out of v1 paths).
- `validate_game` v1 rule paths (G1–G7) untouched; G8 runs only when v2 sections are present.
- Tool surface: `validate_game`/`render_game` input models gain optional fields only (R2-ASCII description additions, budget-disciplined as in M2-B).

### 7.3 Negative-test matrix (minimum set; one test per code)

unknown encounter object; encounter count 25 < 26 trials; trigger conflict; missing `stimulus_content` invariant; invented freedom literal; exit to unknown room; orphan room; duplicate object_id; missing start_room; room with 7 objects; block briefing for undeclared block; v2 section on version-1 GameSpec; response binding referencing undeclared response; keys mapping to non-option values (v1 G3 semantics extended); explore layout + v1-shaped bundle without fallback.

## Part 8 — Acceptance criteria (objective, machine-checkable)

- AC-C1 Every v1 GameSpec fixture → identical validation result + fingerprint (compat gate).
- AC-C2 Every G8 code ≥1 negative test; all pass.
- AC-C3 Fingerprint stability: unset v2 sections → v1 fingerprint; set sections → new fingerprint (both directions tested).
- AC-C4 Pure-function validation: same inputs → identical `game_config_fingerprint`, PYTHONHASHSEED-independent (subprocess test).
- AC-C5 No detective/genre vocabulary in any shared schema (grep ban extended to `game_schemas.py` v2 additions — mirroring the existing GB-8 introspection test).
- AC-C6 Import surface: `game_schemas.py` v2 additions import nothing from tools/agent/api (layering check already enforces; explicit test mirrors stimulus.py's).
- AC-C7 Suite green (266 existing + ~35–45 new), pyright 0, six CI gates PASS.
- AC-C8 FakeLLM iteration test: a mapping error surfaced through the two-tier error contract is repairable in the next round (stalled protocol unchanged).

## Part 9 — Implementation phases + blocking decisions

### Phases (each independently testable; no runtime work)

- **M2-C-1 (schema)**: v2 models in `game_schemas.py` + version guard + G8_WORLD_STRUCTURE + compat projection for `game_config_fingerprint`. Tests: AC-C1/C3/C5.
- **M2-C-2 (mapping rules)**: G8_MAPPING_* + stimulus-semantics rule + `validate_game` wiring + tool description additions. Tests: AC-C2/C4/C8.
- **M2-C-3 (docs/tools)**: skill + README notes (GameSpec v2 authoring surface), example GameSpec v2 fixture for the Manor Case (as *test fixture*, not shipped example). Tests: AC-C6/C7.

### Blocking decisions requiring your approval before implementation

| # | Decision | Alternatives | Recommendation | Trade-off |
|---|---|---|---|---|
| D-M2-C-1 | GameSpec `schema_version` bump to 2 (same mechanism as ExperimentSpec) | (a) v2 sections allowed on version 1 via a "v2 marker" field · (b) explicit `schema_version: 2` | **(b)** | (a) makes v1 semantics ambiguous (a v1 spec with world sections is neither v1 nor v2); (b) costs one literal widening, exactly the M2-B pattern |
| D-M2-C-2 | Explore layout with a v1-shaped bundle (no materialized stimuli) | (a) reject (G8_STIMULUS_SEMANTICS) · (b) allow with factor-display fallback (v1 render path) | **(a) reject in MVP**, documented fallback available later | (b) maximizes compatibility but silently renders un-measured-looking encounters in v1 bundles — an accidental science hazard; rejecting forces explicitness; revisit post-MVP if a use case appears |
| D-M2-C-3 | Where per-block feedback lives | (a) leave to M2-D runtime discussion (narrative.block_briefings only) · (b) add optional `feedback.block_overrides` now | **(a)** | (b) is a real need (practice-with-feedback / main-without) but belongs with the runtime that consumes it; designing it blind risks a rewrite |
| D-M2-C-4 | `measures` conformance vocabulary (Part 4 event schema) | (a) fix the vocabulary in this contract only (schema lives in M2-D/E) · (b) implement the event-log schema now | **(a)** | the vocabulary is needed to design bindings correctly; the schema implementation is runtime-coupled and premature |
| D-M2-C-5 | Manor fixture location | (a) test fixture under `tests/fixtures/` (not shipped as example) · (b) `examples/` immediately | **(a)** | D-M2-6 (in-repo until playtest) governs shipping; fixture-first keeps the example pipeline honest |

**Smallest scope preparing a playable prototype without runtime**: M2-C-1 + M2-C-2 + the Manor fixture (D-M2-C-5a). M2-C-3 documentation can trail the first milestone.

---

**Stop. Implementation of M2-C begins only after approval of this contract and the five blocking decisions (recommendations: C-1b, C-2a, C-3a, C-4a, C-5a).**
