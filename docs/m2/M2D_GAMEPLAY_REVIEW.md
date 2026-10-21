# M2-D Phase 1 — Critical Game Experience Review

Scope: the Manor Case prototype as experienced by a player, judged against the five
criteria of the project vision ("engaging, interactive games", not "trials in a
decorative wrapper"). **No engagement claims are made here** — there is no participant
data; every judgement below is an architectural/deficiency analysis. Recruiting even
3–5 playtesters is a prerequisite before any "engaging" claim in future documents.

The verdict up front: the reviewer's criticism is correct. Phase 1 proves the *plumbing*
(trials fire from world interactions, cursor is monotonic, stimuli are verbatim,
events are channel-tagged) but the *experience* is a text questionnaire with a room
metaphor. The gap to close is presentation and agency, not measurement.

## 1. Meaningful player agency — **deficient**

What the player actually decides:

- **Which encounter to examine next.** This selects *when* the next locked sequence
  item fires — never *which* trial, *what* it contains, or *how* it is scored. It is
  pacing control, not agency.
- **The a/b/c judgement inside a trial.** This is the experimental response — the
  thing the design must *not* gamify — so it cannot count as gameplay agency either.

Deficiencies:

- No decision has consequences outside the measurement channel: examining the wine
  ledger before or after the tea cup changes nothing the player can perceive.
- The single flavour object (dusty clock) demonstrates the inspect mechanic but
  yields no information, no state change, no path through the game — it is a dead-end
  easter egg.
- There is no resource, no risk, no objective structure that makes "where do I go
  next / what do I look at" a *choice* rather than a *click*.
- The `[x] conclude` action only exists after all 26 trials — the player cannot make
  the meaningful meta-decision "I have seen enough" (which a real investigator, and a
  real game, would allow).

## 2. Narrative progression — **deficient (static)**

- The story is three fixed texts (intro, two block briefings) plus one of three
  ending lines keyed on accuracy alone. Nothing between minute 0 and minute ~10 of
  play changes based on what the player does or learns.
- Exploration has no narrative consequence: entering the cellar "cold, exact, honest"
  reads identically whether it is the player's first room or their last.
- No mid-session narrative beats (discoveries, notes, reactions) — the GameSpec v2
  `narrative` section structurally supports only static surfaces; the contract has
  no expression for state-dependent text (by design in M2-C — narrative progression
  semantics were deferred).
- The ending bands cannot reference the player's path (rooms visited, evidence
  examined), so the story cannot "close" what the player actually did.

## 3. Interactive environment — **deficient (text menu)**

- Rooms are rendered as numbered lists; objects and exits share the same interaction
  grammar (press a number). There is no space, no layout, no object permanence — the
  "hall" is five lines of text, not a hall.
- Inspect is a full-screen page turn that discards the room context; returning
  requires a keypress that does nothing else. The environment has no memory of
  attention (no "you already looked here" affordance beyond the `(examined)` suffix).
- Keyboard-only input with no pointer support: no hovering, no clicking, no spatial
  affordances. This is the single largest reason the prototype reads as a
  questionnaire.
- One concrete symptom: the required experience #8 (explore vs experiment
  distinction) is met by a CSS border — because there is so little environmental
  texture that a border is the only contrast available.

## 4. Cognitive integration — **deficient (juxtaposed, not embedded)**

- The cognitive task (salience × suspect judgement) is *inserted into* exploration as
  a modal interruption, not *expressed by* it. Mechanically: walk → press number →
  read four lines → press a/b/c. The four lines are the whole stimulus; the room,
  the object, and the walk contributed nothing to the cognitive load manipulation.
- The salience manipulation is realized only inside stimulus text (clean record vs
  cluttered description) — the obvious environmental mapping (a clue sitting plainly
  on a tidy desk vs buried among clutter) is unused. The GameSpec *could* carry this
  (object/world presentation is a freedom), but Phase 1 renders encounters as a
  uniform text panel.
- Nothing in exploration engages a cognitive process: no working-memory demand
  (remembering which rooms hold unexamined evidence is the only one, and it is
  incidental), no attention deployment, no inference the game recognizes.
- The encounter "wrapper" (you are examining: X) is one line — the object's identity,
  position, and history do not modulate the trial in any way the player experiences.

## 5. Engagement (reasons to continue) — **deficient, honestly stated**

- After trial 26 there is *no reason to remain*: encounters degrade to inspect-only
  with an explicit on-screen note saying nothing further is recorded; the single
  flavour object was likely seen in minute one; the ending text has already shown.
- During play, motivational scaffolding is absent by configuration (feedback `none`,
  score off, progress bar showing only `n/26`). The progress counter is the only
  loop-closure signal, and it counts *the experiment's* progress, not the
  *investigation's*.
- No completion structure the player cares about: no case board, no "evidence
  collected" view, no rooms-cleared state, no curiosity gaps opened by narrative.
- **Evidence status**: zero participants have played this build. The deficiencies
  above are structural predictions, not measured outcomes; conversely, no one should
  infer from this document that the prototype is *un*engaging — that, too, requires
  participant data.

## Summary table

| Criterion | Status | Root cause (one line) |
|---|---|---|
| Meaningful agency | ✗ | Choices affect pacing only; no consequence-bearing decisions exist |
| Narrative progression | ✗ | All narrative surfaces are static; GameSpec v2 has no state-dependent text |
| Interactive environment | ✗ | Numbered text menu; no space, no pointer, no object permanence |
| Cognitive integration | ✗ | Task is a modal interruption; environmental mapping of the manipulation unused |
| Engagement | ✗ (unmeasured) | No post-completion or mid-session reason to continue; no motivational structure |

The constructive side of this critique — how to close each gap without touching the
measurement plane — is the subject of `M2D_PHASE2_PROPOSAL.md`, with the
scientific-validity boundaries drawn explicitly in its Part-4 section.
