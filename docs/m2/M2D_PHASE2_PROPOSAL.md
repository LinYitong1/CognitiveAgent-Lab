# M2-D Phase 2 — Proposed Design & Implementation Roadmap

Status: **proposal only — nothing implemented**. Depends on Phase 1 acceptance
(includes the commit approval). All designs below preserve the frozen measurement
plane; the validity boundaries are drawn in §5 before any gameplay design is trusted.

## 1. Design target

A visually interactive Manor Case where the *investigation is the game* and the
*cognitive trials are the evidence examination* — the player walks a rendered space,
examines visual objects, accumulates a case, and every examination IS a controlled
trial whose stimulus, order, scoring and timing come — unchanged — from the
ExperimentBundle.

## 2. Option comparison: enhance the dependency-free renderer (A) vs a 2D framework (B)

| Dimension | A. Enhanced HTML/CSS/SVG/JS renderer | B. Lightweight 2D framework (Phaser/PixiJS + asset pipeline) |
|---|---|---|
| **Dev complexity** | Moderate. Room views are absolutely-positioned clickable SVG/CSS nodes; no new tooling; the Phase 1 state machine is reused as-is | High. Asset pipeline (sprites/tilesets/atlas), a build step to embed the framework (~1–3 MB into the single file) or a bundler, and a second runtime to debug |
| **Agent generation flexibility** | **High — the decisive factor.** The agent already generates declarative GameSpec; world/objects are data, presentation is generic CSS/SVG shapes + labels. No art skill required to produce a valid, decent-looking game | Low–medium. The agent would have to select/parameterize pre-made art assets; without an artist in the loop, framework output looks *worse* than styled SVG. Asset descriptions become a second, softer contract to validate |
| **Reproducibility** | Preserved end-to-end: pure function → byte-identical HTML (sha256-anchored), zero external fetches, `file://` direct-open | HTML bytes can still be deterministic (framework JS embedded), but the *rendered result* depends on the framework's raster pipeline; the integrity story (self-check SHA-256) must be re-verified against a much larger attack/complexity surface |
| **Scientific control** | DOM events = measurement events; timing still browser-approximate (unchanged, disclaimed); presentation fully derived from spec data | Canvas abstracts DOM events away; input-latency and frame-pacing details move into the framework (harder to reason about, e.g. input polling vs event dispatch); stimulus rendering path is framework-owned |
| **Maintainability** | One ~700-line module + template, no upgrades, no CVE tracking, no version churn | Framework version upgrades, breaking changes, security patches; a dependency the repo currently has **zero** of (a standing acceptance criterion) |
| **Accessibility** | DOM = keyboard/AT-friendly by construction (Phase 1 keyboard path survives) | Canvas is invisible to assistive tech unless duplicated in DOM |

**Recommendation: Option A.** A framework buys physics, particles and sprite tooling —
none of which the scientific contract can use freely — at the cost of the properties
the project is built on (zero deps, byte-reproducible output, spec-driven generation,
DOM-measurable events). If Phase 3 ever needs what only a framework provides (e.g.
continuous-space navigation), that is a new contract negotiation, not an upgrade.

## 3. Phase 2 design (Option A)

### 3.1 2D room-based environment with clickable objects
Each room renders as a stylized SVG floor panel (walls, 2–4 exit arches positioned on
edges). Objects are clickable nodes with a generated glyph (CSS/SVG shape by role:
flavour vs encounter) placed at deterministic layout slots; hover shows the label;
click = the current number-key action (both input modes active, keyboard retained).
Slot assignment is a pure function of declaration order (deterministic, no runtime
layout jitter).

### 3.2 Visual inspection
Inspect opens an **inset panel** (side/bottom) instead of a full-screen page turn —
the room stays visible, preserving spatial context. Objects get visual state rings:
unseen (accent), examined (dimmed), exhausted encounter (grey + check). Inspect text
gets a small "evidence card" styling.

### 3.3 Meaningful story progression
- First entry into each room triggers a one-line **detective note** (from a new
  `narrative.room_notes` map — static text per room, but *state-gated*: fires once,
  logged as a `game` event). This gives exploration narrative payoff without touching
  measurement.
- Mid-session beat: when half the encounters are consumed, an interstitial notebook
  page summarizes (in fixed prose) that the re-examination is half done — pacing
  acknowledgment, content purely from static narrative fields.
- Ending selection stays accuracy-keyed (a controlled surface); **new**: a separate
  exploration epilogue line (rooms visited / evidence examined) appended *after* the
  band text, clearly framed as investigator's notes, not a score.

### 3.4 Lightweight dialogue and narrative choices
Flavour objects upgrade to a 1–2 beat **ask/answer** interaction (fixed Q&A pairs in
the object's inspect data — schema addition on the presentation side, e.g.
`WorldObjectSpec.dialogue`): the player picks one of two questions; each yields a
flavour answer. Pure `game` channel; zero measurement events; answers carry no
`true_suspect` information (enforced by review rule, §5.3).

### 3.5 Coherent investigation objective
A **case board** overlay (key `c`): a grid of the world's encounters as evidence
cards — collected (with the object's label and room) vs uncollected silhouettes —
plus rooms-visited pins on a miniature map. It visualizes *investigation* progress
(distinct from the `trials n/26` measurement counter), giving the player a
completion structure that is about the fiction, not the experiment. After all trials,
the board invites the concluding action.

### 3.6 Mechanics naturally connected to the cognitive task
The salience manipulation gains an **environmental presentation mapping** (the
highest-risk item — see §5.1): the encounter panel's backdrop density (clutter
pattern) is derived from the trial's `salience` condition. Crucially this is a
*presentation rule bound to a spec-declared condition*, rendered identically for all
trials sharing the condition — proposed as a GameSpec `world.condition_themes`
mapping so the agent declares it, it is fingerprinted, and it never lives in renderer
code. The stimulus **lines remain verbatim text**; the environment frames them.

## 4. Implementation roadmap (3 stages, each user-approved separately)

| Stage | Contents | New schema surface | Tests |
|---|---|---|---|
| **2a — Spatial room view** | SVG room panel, clickable objects/exits, visual state rings, inspect inset panel, keyboard retained | none (pure presentation) | plan-projection shape, determinism, node-driven click routing ≡ key routing, golden compat |
| **2b — Investigation structure** | case board overlay, room notes + mid-session beat + exploration epilogue, flavour dialogue | `narrative.room_notes`, `WorldObjectSpec.dialogue` (both presentation-only, extra=forbid, optional) | G8 additive rules (room_notes keys must name existing rooms), dialogue smuggle-tests (no correctness/factor info), runtime: board reflects cursor, notes fire once |
| **2c — Condition presentation mapping** | `condition_themes` backdrop mapping, hover affordances, ending epilogue polish | `world.condition_themes: dict[factor, dict[level, theme]]` (closed theme vocabulary) | mapping validity (factors/levels must exist), determinism, confound review sign-off (§5.1) as an explicit gate |

Each stage keeps: byte-reproducible HTML, zero dependencies, v1 classic path
untouched, six gates green, and a stop-for-review.

## 5. Part 4 — Preserving scientific validity

### 5.1 Three content classes, explicitly

**Class E — Experimental (frozen, fingerprint-anchored, never touched by gameplay):**
trial.stimulus.lines (verbatim), trial order (bundle-index cursor), condition
assignment, correct answers (`correct_from` from bundle factors), timing parameters
(fixation/stimulus deadline/ISI), response binding semantics (key→option mapping).
Anything in this class is already structurally protected: the GameSpec has no field
that can express an override (M2-C smuggling tests).

**Class N — Non-experimental (free, creative-freedom surfaces):** room/object naming
and text, intro/briefings/ending bands, theme/colors/layout, flavour interactions,
dialogue, case board framing, exploration epilogue. All presentation; logged at most
as `game`-channel events; may never enter the measurement channel.

**Class C — Confound-risk (allowed only with an explicit, reviewed rule):**
1. *Presentation–manipulation covariance* (Stage 2c): the salience→clutter mapping
   makes a manipulated variable visible in the environment. Acceptable only because
   it is a **uniform, spec-declared, deterministic function of the condition** — the
   same environment for every trial in a condition, which is precisely how
   task-irrelevant context is allowed to vary in standard experimental practice. The
   rule must be declared in the GameSpec (fingerprinted), never hardcoded; and it
   must be reported in the experiment's methods description.
2. *Self-paced trial spacing*: explore-triggered trials have player-controlled
   inter-trial intervals (vs fixed ISI). Already a recorded M2-C/M2-D design
   decision; Stage 2a–c does not widen it (the ISI inside a trial remains
   bundle-controlled).
3. *Speed–accuracy incentives*: any reward, streak or time-pressure framing that
   shifts the SATO tradeoff is Class C. Phase 2 keeps score/streak **off** in the
   Manor default and any gamification flag change must be justified per-experiment.
4. *Information leakage*: dialogue/notes/board must not encode `true_suspect`
   information. Enforcement: a static review rule (grep-style test over generated
   GameSpec text vs factor level names) + the smuggling-test discipline for schema.

### 5.2 The governing principle

**Gameplay may only enter through declared presentation surfaces.** Every Phase 2
feature is either Class N (free) or a new Class C rule that (a) lives in the
GameSpec, (b) is deterministic, (c) is uniform within a condition, and (d) is
documented for the methods section. The renderer stays a pure function of
Bundle + GameSpec; the bundle stays the sole measurement authority. Nothing about
the cognitive task changes silently because *nothing can* — the fingerprint
contract fails loudly on any drift.

## 6. Deliverable 4 — Smallest changes, prioritized (impact ÷ effort)

Ordered: each row is independently shippable and reversible; P0 items alone move the
prototype from "questionnaire" toward "place".

| # | Change | Class | Why it matters (ties to §review) | Effort |
|---|---|---|---|---|
| 1 | **Clickable objects & exits** (SVG nodes, click ≡ number key) | N | Environment vs menu — the single largest perceived-interactivity gain | S |
| 2 | **Inset inspect panel** (room stays visible) | N | Context preservation; inspection stops being a page turn | S |
| 3 | **Object visual states** (unseen/examined/exhausted) | N | Object permanence; the room remembers attention | S |
| 4 | **Case board overlay** (`c` key: evidence cards + visited rooms) | N | Completion structure the player cares about; investigation framing | M |
| 5 | **Room-entry detective notes** (state-gated one-liners) | N(+schema) | First narrative consequence of exploration | M |
| 6 | **Exploration epilogue** (post-ending path summary) | N | Post-trial reason to have explored; closes the fiction | S |
| 7 | **Flavour dialogue** (2-question ask/answer) | N(+schema) | Agency practice ground with zero measurement cost | M |
| 8 | **Condition backdrop mapping** (salience→clutter) | **C** | Cognitive integration — the manipulation becomes environmental | M + review |
| 9 | Hover affordances, focus ring, aria labels | N | Accessibility + polish | S |

Rows 1–3 = Stage 2a; 4–7 = Stage 2b; 8–9 = Stage 2c. Rows 1–3 are recommended as the
first Phase 2 approval unit: smallest diff, largest experience delta, zero schema
change, zero confound review needed.

## 7. What Phase 2 explicitly does NOT do

No real-time/continuous gameplay (no physics, no timers racing the player), no
multiplayer, no audio dependencies, no asset binaries in the repo, no Phaser, no
changes to ExperimentBundle/generation/G8 semantics, no M2-E/F scope creep (event-log
reconciliation and post-session verification remain M2-E), and no engagement claims
without participant data (playtest protocol proposed for Phase 2 acceptance:
3–5 testers, think-aloud, task-completion + SUS-lite, results reported as evidence,
not marketing).
