# M2-A — Focused Design Review (pre-M2-B gate)

- **Status**: design review only. No files modified besides this one; no code, schema, API or test changes; nothing committed or pushed.
- **Inputs reviewed**: the five M2-A documents (`docs/m2/*.md`), the frozen M1/Phase A/B sources, and the four reference-repository analyses.
- **Reviewer stance**: adversarial — each section names the weakest point of the M2-A proposal before answering, because a review that only restates the proposal is worthless.

---

## 1. Meaningful gameplay — how The Manor Case avoids being "a trial list with wallpaper"

**The honest weakness first**: the measurement trials of the Manor Case are structurally *conventional* — a three-alternative forced choice with (optionally) a deadline. If encounters auto-trigger on a timer, the rooms are wallpaper and the game is a 3AFC task with room-change animations. Everything below exists to prevent exactly that.

**What makes it a game rather than decoration — four agency loci, all deliberate:**

1. **Self-initiated measurement (the core mechanic).** The player decides *when*, *where* and *in what order* trials happen. Encounters are pulled **only** when the player examines a clue object; nothing auto-triggers. This is a real information-foraging structure: the experiment does not advance without player action. Contrast: a conventional experiment owns the pace; here the player does — which is both the engagement mechanism *and* itself a measurable variable (see §2).
2. **Route and search agency.** The room graph is traversed freely (5 rooms, no forced order); objects are skippable and re-examinable (flavour objects re-show text; consumed clue encounters are marked). The player can adopt strategies: systematic sweep vs. targeted re-visits vs. cramming clue encounters before exploring context. The *strategy choice* is theirs, and its trace is logged.
3. **Context-gathering as a meaningful (but non-scored) choice.** Flavour objects and room descriptions carry no points, but attentive players can use them to build a mental model of the case narrative. This creates a genuine exploration-vs-exploitation tension with no payoff structure forcing one behaviour — precisely what we want to log rather than prescribe.
4. **Motivated judgement frame.** The 3AFC is not "select the matching attribute" (as in the v1 demo); it is "which suspect does this clue support?" — a judgement embedded in a task the player has been exploring on their own terms. The decision is *contextually motivated* even though its *scoring* is purely experimental.

**What we are NOT claiming**: we do not claim the measured decisions themselves become "meaningful choices" in the game-design sense — they stay experimentally controlled, and that is the design. Meaningful *player* agency lives in the unmeasured game class (routes, pacing, search); *measured* choices stay standardized. The mapping layer (§3) exists to keep these two cleanly separable while binding them into one experience.

**Minimal-core honesty note**: in the single-factor minimal core (PROTOTYPE_SPEC §7), agency loci 1–3 are all present; only the deadline pressure mechanic is deferred. If playtesting (§7, engagement criteria) shows players treat exploration as a chore to reach trials, the design fails its own bar and must be revised before M2-E — that is an explicit gate, not an assumption of success.

## 2. Experimental validity — mechanic → process → variables → confounds → controls

| Gameplay mechanic | Cognitive process targeted | Variables it may influence | Principal confounds & controls |
|---|---|---|---|
| Clue judgement (3AFC, `correct_from=true_suspect`) | Evidence-based perceptual/category decision; recognition of which attribute the clue encodes | DV: accuracy, RT, (miss rate under deadline) | **Key-position bias** (suspects fixed to keys 1/2/3): controlled by balancing `true_suspect` across levels (the seed guarantees balance) so position bias averages out; residual per-trial bias is a known, reportable limitation. **Reading-speed differences between participants**: bounded by schema-constrained stimulus templates (fixed line counts, bounded strings — R1 bounds). |
| `clue_salience` (salient vs. embedded with decoy lines) | Cognitive load of evidence extraction; selective attention | IV (manipulated); DV: accuracy/RT cost of embedding | **Text-length confound**: materialization templates must be *length-matched* between levels (same total lines; embedded = clue line + decoys, salient = clue line + filler of equal count) — an engine-template requirement, testable deterministically (AC-3 extension). |
| `pressure` (free vs. `response_window_ms` deadline; deferred to M2-F in minimal core) | Speed–accuracy tradeoff under speed stress | IV; DV: miss rate, RT distribution shift, accuracy | **Deadline interacts with load** (embedded clues consume reading time inside the window) — this is an *interaction of interest*, not a confound, but must be pre-declared in the measures doc (R4) to avoid post-hoc flexibility. **Anticipatory responding**: window runs from stimulus onset (same onset for all trials), logged RTs allow exclusion screens. |
| Self-initiated encounters (player-paced trial onset) | Engagement; self-regulated foraging; preparation state | DV: inter-trial interval (exploration time), encounter pacing pattern; possible IV side-effect: rest/fatigue distribution differs from fixed-ITI designs | **Unbounded rest between trials** changes the effective preparation state vs. classic designs: (a) acknowledged openly in the R4 measures doc; (b) exploration time is logged per trial so analyses can condition on it; (c) the practice block uses v1-style flow so participants learn the judgement before free pacing. This is a *design property to study*, not something to hide. |
| Room exploration & object inspection | Spatial/exploratory behaviour; curiosity-driven information seeking | Logged DVs: rooms visited, objects inspected, re-inspections, time per room | **Not an experimental IV** — declared as behavioural trace (D-M2-3). Confound risk is *misinterpreting* it as controlled: the review's position is that exploration metrics are descriptive/engagement evidence, and any causal claim about them requires a designed comparison (out of MVP scope). |
| Detective score (gamification `score`) | Motivation / feedback | Could shift strategy across trials | **Feedback-learning confound**: main-block feedback is set to `none` (only the practice block shows outcome feedback) — a **newly specified control** this review adds to the prototype spec (v1 `feedback.on_response` is global; the prototype therefore runs practice with feedback via the practice block's own flow and main with `none` — feasibility to be confirmed against the v1 renderer's global-feedback assumption in M2-C; if not expressible in v1 semantics, this becomes an explicit M2-C requirement, not a silent behavior change). |
| Banded ending text | Closure; performance framing | None — post-hoc, presented only after the last trial | Cannot contaminate measurement (retrospective only). Band thresholds declared in the GameSpec so they are part of the validated artifact. |

**Global validity statement**: the prototype measures classic, well-replicated effects (load costs on accuracy/RT; under deadline, SAT) inside a game frame. The game layer's scientific role is **engagement + self-paced foraging**, not the production of exotic new measures. Claims beyond that (e.g., "gamification improves data quality") are explicitly *not* supported by this MVP and would require a between-condition comparison study (post-M2, user-directed research-validity layer).

## 3. Research–Game mapping — one concrete trial, end to end

**Artifact chain (design-time, all verified by validation):**

```
ExperimentSpec v2 (seed 20261021, balance=true)
  factors: clue_salience{salient,embedded}, pressure{free,deadline}, true_suspect{a,b,c}
  stimulus_spec: R1 templates — salient = "Ledger entry: payments traced to suspect {true_suspect}" (1 line + 0 decoys)
                 embedded = same clue line + 3 length-matched decoy lines (seeded slot fill)
  → engine materializes trial #7 (index 6): block=investigation,
    factors={clue_salience:embedded, pressure:free, true_suspect:b},
    stimulus={lines:[3 decoy lines, clue line]}, timing={fixation_ms:300, stimulus_ms:null}
  → ExperimentBundle (trials + config/trials fingerprints + bundle_sha256)

GameSpec v2 mapping:  trial_trigger="explore-and-encounter"
  world.rooms: study(start), library, parlour, hallway, cellar
  world.objects: [library:"wine ledger"→encounter, library:"dusty clock"→flavour, ...]
  input.bindings: accuse → keys {1:suspect_a, 2:suspect_b, 3:suspect_c}
  controlled_invariants: {trial_order, conditions, stimulus_content, correct_answers, timing}
```

**Play chain (runtime, per event class):**

| # | What happens | Event logged | Class | Reconciled? |
|---|---|---|---|---|
| 1 | Player moves study→library | `game: room_enter {from:study, to:library, t}` | game | counted, not reconciled |
| 2 | Inspects "dusty clock" | `game: object_inspect {object_id, flavour, t}` | game | no |
| 3 | Examines "wine ledger" (encounter object) | `game: encounter_trigger {object_id, t}` then runtime pulls **bundle trial index 6** (next in fixed order — the player's 7th encounter because encounters consumed 0–5 before) | game (trigger) | trigger count feeds AC-6 |
| 4 | Clue screen renders the **engine-materialized** stimulus (decoys + clue line); fixation first | `measurement: trial_start {trial_index:6, block, conditions{...}}` | measurement | **yes — must equal bundle trial 6 exactly** |
| 5 | Player presses `2` | `measurement: response {trial_index:6, response_name:accuse, value:suspect_b, correct:true, rt_ms, t}` | measurement | **yes — correctness recomputed from bundle** |
| 6 | No feedback (main block `feedback=none`); return to library view | `game: exploration_resume {room:library, t}` | game | no |
| 7 | … session end … | `measurement: session_end`; log header carries bundle fingerprints | both | header provenance |

**Post-play proof**: `verify_game_events(log, bundle)` asserts — measurement events form exactly the bundle's trial sequence (indices 0..N-1 in order, no skips/inserts/reorders), each event's `conditions` equals the bundle trial's `factors`, each `correct` equals the bundle-derived correctness; game events are counted and reported (encounters == trials consumed). A tampered log (reorder, condition edit, response injection) → named rejection. This chain is what distinguishes "we logged something" from "we can prove what was played matches the design".

## 4. Architecture flexibility — can the deterministic renderer carry real gameplay without debt?

**Honest assessment**: the renderer-extension route (A) is viable for the MVP, with a **medium, bounded** debt profile — provided three disciplines hold:

1. **Logic-core-first separation.** The template JS is sectioned into (i) a *logic core* (trial scheduling, encounter bookkeeping, event emission — pure functions over the embedded bundle/GameSpec data) and (ii) *presentation* (DOM updates). The logic core is exercised by the reconciliation fixture and self-check assertions independently of visuals. Without this split, ~1,200 lines of script-tag JS with shared mutable state is where the debt would live — this is the single biggest engineering risk of route A and it is mitigated by structure, not by hope.
2. **Data contracts are the renderer firewall.** The runtime consumes exactly three renderer-agnostic contracts: the materialized **bundle JSON**, the validated **GameSpec JSON**, and the **event-log schema** (with fingerprints). All three are defined, validated and golden-tested *outside* any renderer. Consequence: a future Phaser (or canvas/WebGL) layout is a **new registered layout consuming the same three contracts** — it is additive by construction, never a rewrite. Byte-identity is asserted **per layout** (each layout has its own golden files), so adopting Phaser later does not invalidate route-A artifacts.
3. **Budgeted size, asserted.** < 1 MB single-file for the MVP (text-only world); schema bounds (≤8 rooms, ≤24 objects, bounded strings) are the hard ceiling that keeps template complexity linear.

**Explicit trigger conditions for switching renderers** (preserved, not foreclosed): (a) validated need for sprite/audio/physics interactions after M2-E → vendored-Phaser layout proposal with an explicit dependency waiver decision; (b) template JS exceeding maintainability signals (self-check assertion count not covering new failure classes; golden diffs becoming opaque) → re-evaluate. **What would create unacceptable debt**: letting presentation code call into measurement logic or vise versa beyond the declared event schema — fenced by the same reconciliation tests (a presentation bug that drops a measurement event is caught; one that invents one is caught).

**Residual risks named**: no module system under `file://` (mitigated: IIFE sections, fixed load order, no shared globals beyond the declared store object); manual DOM manipulation verbosity (accepted: it is what keeps zero-dependency and byte-identity possible); golden-file churn during M2-D development (mitigated: golden files land only after the reconciliation fixture stabilizes).

## 5. Scientific generalizability — why M2 is not "The Manor Case framework"

**Zero mystery-specific content enters the engine** — the no-paradigm-hardcoding boundary is enforced the same way it was for Stroop/N-back (which never entered the engine either): no detective/suspect/room field exists in any schema; the Manor Case is an *example* composed entirely from generic primitives. The generic primitives M2 adds are:

- **R1 `stimulus_spec`**: factor-level → content mapping with seeded materialization. Paradigm-agnostic: any design whose stimuli vary by condition (words, shapes, numbers, described scenarios) materializes through the same mechanism.
- **R2 timing extensions** (block override + response window): classic methodology knobs, no paradigm coupling.
- **Registered interaction layouts**: `explore-and-encounter` joins `canvas-center|rows`. A layout binds *how the next bundle trial is entered and what surrounds it* — nothing about what the trials measure.
- **Mapping layer**: `trial_trigger`, response bindings, invariants/freedom lists — all described in terms of bundle/response variables, never task content.
- **Two-class event log + reconciliation**: any paradigm's measurement events reconcile the same way (order/conditions/correctness against the bundle).

**Concrete other-paradigm sketches (composability proof, no implementation implied):**

| Paradigm | How it composes from M2 primitives |
|---|---|
| Task-switching / set-shifting | Rooms = task contexts; room-enter rule selects which factor level (task cue) the next encounter's trial carries — cue is an experimental factor materialized via R1 |
| Working memory (span / N-back) | Encounters in a patrol route; R1 materializes memory-set items, responses via existing `choice`/`text`; the route structure is world data |
| Category learning | Feedback-driven learning wants feedback *on* — that is the v1 `feedback` flag (manor runs it *off*); training blocks with feedback, transfer blocks without, via block structure |
| Reward / foraging (bandit-style) | Two "prospects" as objects/rooms; choice response + `derived` reward schedule (R3) — engine computes reward deterministically, runtime only presents |
| Prospective memory | R3 materializes an intention token; the ongoing task is ordinary trials; the prospective cue appears via R1 stimulus templates on a balanced subset |

Each sketch uses only: factors/levels, R1/R2/R3, layouts, bindings, two-class logs. If any of these turned out to require engine specialization, that would be evidence the M2-A design is too narrow — the sketches are the standing falsifier.

**Honest limit**: M2 MVP supports *discrete-trial* designs wrapped in exploration. Continuous motor tasks, multiplayer, or audio-timed paradigms remain out of scope (runtime modality limits; documented, not hidden).

## 6. The six blocking decisions — alternatives, recommendation, trade-offs, M1 impact

| # | Decision (roadmap wording) | Alternatives | Recommendation | Trade-offs & M1 compatibility |
|---|---|---|---|---|
| **D-M2-1** | Approve `schema_version: 2` policy: optional additive fields; v1 byte-compatibility as hard gate | (a) additive v2 fields, v1 byte-compat hard gate · (b) parallel `ExperimentSpecV2` type, v1 untouched as separate model · (c) push everything through the existing free-form `paradigm_params` | **(a)** | (b) duplicates validation/generation code paths and forks fingerprints → rejected. (c) `paradigm_params` is unvalidated free-form — using it for structured timing/stimulus semantics would bypass the validation boundary that *is* the project's core value. (a) keeps one engine; the hard gate (v1 fixtures byte-identical under v2) preserves M1 exactly — it is an acceptance test, so M1 compatibility is enforced, not assumed. |
| **D-M2-2** | `no_response` semantics: deadline miss counts as an error trial | (a) miss = error (in accuracy denominator) · (b) miss = excluded (accuracy on answered only) · (c) miss tracked separately, denominator declared per analysis | **(a)**, with (c) as reporting practice — log keeps misses distinguishable, so (b)/(c) remain *analyzable* post hoc | (a) is the standard SAT treatment (misses are speed failures, excluding them rewards wild guessing under deadline); the log retains `no_response` as its own event type so no information is destroyed and later analyses may re-scope. Zero M1 impact (v1 has no deadline field). |
| **D-M2-3** | Exploration events logged as behavioural data but excluded from bundle reconciliation | (a) two-class split: game events logged, not reconciled · (b) everything reconciled · (c) game-event logging optional per GameSpec | **(a)** | (b) is incoherent — game events have no bundle counterpart to reconcile against; forcing it would either bloat bundles with presentation content (violates the separation fence) or fake a check. (c) loses engagement evidence by default. (a) keeps reconciliation meaningful and preserves the data. No M1 impact (v1 logs have no game class because v1 has no exploration). |
| **D-M2-4** | Prototype scope: full 2×2 (+deadline in M2-B) vs minimal single-factor core (R2 → M2-F) | (a) minimal core first (salience only, 20 main trials; R2 deferred) · (b) full 2×2 immediately | **(a)** | (b) pulls response-window semantics, deadline rendering, and SAT-relevant scoring (D-M2-2) into the first engine milestone, growing review and failure surface before the mapping/runtime chain has ever run end-to-end. (a) exercises every layer (R1, mapping, exploration runtime, reconciliation) with one manipulated factor; R2 is cleanly separable (engine timing only). M1 impact identical for both (same v2 schema policy). |
| **D-M2-5** | Ending-text bands: review before the example ships | (a) Architect drafts three neutral bands → user reviews at M2-E · (b) user supplies texts now · (c) single neutral ending, no bands | **(a)**; fallback **(c)** if review slips | Ending text is post-hoc presentation only (cannot contaminate measurement), so the decision is low-risk editorially; (c) removes a small engagement feature if the review round-trip is slow. No M1 impact. |
| **D-M2-6** | Mystery example: public on first delivery vs in-repo until playtest completes | (a) in-repo until a full playtest cycle + your approval · (b) public with the M2-E release | **(a)** | (b) risks shipping an example whose engagement claim (§1) is unevaluated — exactly the overclaiming pattern the project was criticized for and corrected. (a) costs nothing (the repo is public; "example" labelling is the gate). No M1 impact. |

**Review-added control (feeding M2-C)**: main-block feedback must be expressible as `none` while practice shows feedback. If v1's global `feedback` semantics cannot express per-block feedback, M2-C adds it as a **v2 additive field with the v1 byte-compat gate** — never a silent change to v1 behavior (§2, gamification row).

## 7. MVP scope — smallest prototype with meaningful gameplay *and* valid control

**Scope (minimal core, consistent with PROTOTYPE_SPEC §7 + D-M2-4a):**
single-factor design (`clue_salience`: salient/embedded; `true_suspect` ground truth), 6 practice + 20 main trials, 5 rooms / ~18 objects (≈10 encounters + 8 flavour), explore-and-encounter runtime, two-class event log with provenance header, `verify_game_events` reconciliation, FakeLLM five-stage workflow, researcher checkpoint. Deferred: pressure/deadline (R2 → M2-F), banded endings may degrade to single neutral ending (D-M2-5c fallback), pending→approved artifact states, Playwright.

**Engineering acceptance criteria (objective, machine-checked — each maps to a milestone):**

- E-1 Determinism: same spec+seed → identical fingerprints; same bundle+GameSpec → byte-identical HTML (golden). *(M2-D)*
- E-2 v1 compatibility: all v1 golden fixtures byte-identical under the v2 engine/renderer; all 231 existing tests green. *(every milestone)*
- E-3 Materialization: length-matched salient/embedded templates (schema-bounded), seeded, PYTHONHASHSEED-independent. *(M2-B)*
- E-4 Fences: every forbidden experiment-semantics key in world/narrative/mechanics/mapping → rejected with a distinct error code (one negative test per family). *(M2-C)*
- E-5 Reconciliation: scripted full-playthrough log → 26/26 measurement events match the bundle exactly; tamper mutations (reorder, condition edit, injected response, dropped trial) each → named rejection. *(M2-E)*
- E-6 Runtime integrity: self-check page asserts room-graph reachability, encounter count ≥ trial count, event-schema conformance; single file < 1 MB, zero external URLs, `file://` playable. *(M2-D)*
- E-7 Workflow: FakeLLM E2E drives all five stages; injected faults (missing render, tampered log) fail loudly with non-zero exit; nothing reports success without the human checkpoint step. *(M2-E)*
- E-8 Suite & statics: suite green (target ~300 incl. new), pyright 0, six CI gates pass. *(every milestone)*

**Participant-engagement evaluation criteria (separate, human-protocol — explicitly NOT engineering gates):**

Run as a structured playtest (n ≥ 6 adult volunteers, single session, checklist + short questionnaire) after E-1..E-8 hold:

- PE-1 *Engagement floor*: median session within the 5–10 min band; ≥ 80% of participants complete all 26 trials unprompted.
- PE-2 *Exploration is real, not endured*: median rooms visited ≥ 3 of 5; ≥ 50% of participants inspect ≥ 2 flavour objects (i.e., explore beyond the minimum path to encounters) — the falsifier for the "wallpaper" failure mode of §1.
- PE-3 *Comprehension*: ≥ 80% answer the post-session purpose question ("you were judging which suspect each clue supported") correctly without re-reading instructions.
- PE-4 *Load manipulation is felt*: embedded trials show measurable accuracy and/or RT cost in the expected direction at the group level (manipulation check — this is *evidence the experiment works*, reported descriptively; n is too small for inference, and the report says so).
- PE-5 *Subjective*: median enjoyment/interest rating ≥ 3/5 on a stated 5-point scale; free-text comments harvested for iteration.

**Interpretation rule (stated in advance)**: PE criteria evaluate the *example's* engagement and the manipulation's plausibility. They do **not** validate timing for formal data collection, do not constitute a normed instrument, and are not claimable as "engagement proven" in any public text without the raw playtest report being available. A failed PE-2 blocks M2-E's "shipped example" labelling and triggers a design revision — before, not after, any public framing.

---

## Review conclusion

The M2-A proposal survives adversarial review **with three concrete strengthenings adopted**: (1) length-matched stimulus templates as a hard engine requirement (confound control); (2) main-block feedback `none` with per-block feedback expressibility as an M2-C requirement (feedback-learning control); (3) the engagement falsifier PE-2 as an explicit pre-registered gate against the wallpaper failure mode. The renderer-extension route (A) is confirmed as low-to-medium bounded debt with the Phaser option preserved through renderer-agnostic data contracts. All six blocking decisions are presented with recommendations; none requires touching M1 frozen behavior.

**Recommendation**: proceed to M2-B upon your approval of D-M2-1..6 (recommendations: 1a, 2a, 3a, 4a, 5a, 6a). No implementation has started; this document is the only new file; nothing was committed or pushed.
