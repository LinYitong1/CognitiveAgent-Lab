# Manor Case fixture (M2-C)

Minimal-core prototype data (PROTOTYPE_SPEC §7): single-factor load manipulation
(`salience`: salient vs embedded clue lines), ground truth `true_suspect` (a/b/c),
6 practice + 20 investigation trials, seed 20261021. All files are deterministic
(fixed `generated_at`); `generate.py` reproduces them byte-identically.

## Research-game mapping walkthrough (one interaction)

1. Player moves hall → library: `game: room_enter` (logged, NOT reconciled).
2. Player inspects the dusty clock (flavour): `game: object_inspect` (no trial).
3. Player examines the **wine ledger** (role=encounter): `game: encounter_trigger`;
   the runtime pulls the NEXT unconsumed bundle trial in index order (monotonic
   cursor — no skip, no reorder; 26 encounter objects ≥ 26 trials).
4. The encounter renders `trial.stimulus["lines"]` VERBATIM (M2-B materialization;
   the GameSpec has no field that can alter, filter or reorder lines).
   Event: `measurement: trial_start` (index, block, conditions).
5. Player presses `b` → mapping binding resolves to value "b"; the renderer
   computes `correct = (trial.factors["true_suspect"] == "b")` FROM THE BUNDLE.
   Event: `measurement: response` (value, correct, rt_ms).
6. No feedback (investigation, `feedback.on_response=none`); return to exploration.
7. Post-session (M2-E, not yet implemented): `verify_game_events` reconciles every
   measurement event against the bundle — order, conditions, correctness.

Controlled invariants (architectural, validated by G8 + schema absence):
trial_order, conditions, stimulus_content, correct_answers, timing.
Creative freedom surfaces: theme, room_labels, object_labels, narrative_text,
feedback_style.
