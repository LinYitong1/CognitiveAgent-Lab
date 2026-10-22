"""M3-A P1: the shared trial-phase player (one JS state machine, two renderers).

Both HTML engines (classic `game_render.py` and v2 explore `explore_render.py`)
embed PHASE_PLAYER_JS verbatim, so phased trials share ONE timing semantics:

- phases play in declaration order; `show(phase)` renders the phase's lines;
- a phase without a response window advances on its duration (advance="auto"),
  on the first keypress (duration_ms null / advance="keypress" racing the
  duration), or on a submitted response — never more than one of these;
- a phase with response_window=true hands control to the engine's
  `collectWindow(phase, deadlineMs)` for exactly ONE response (the next
  uncollected of the trial); keys outside a window are not recorded;
- when `collectWindow` resolves (response submitted or deadline missed), the
  player advances immediately — no double counting, no skipped trials;
- RT anchoring is the engine's duty: it anchors at the window phase's onset
  (the deadline handed to collectWindow starts at that same onset).

Timing limitation (documented, unchanged from the M2 engines): phase durations
use browser setTimeout and are approximate — suitable for gameplay-grade
presentation, NOT millisecond-accurate research timing.

The helper is paradigm-neutral: it knows sequences, durations and windows,
never any task.
"""

from __future__ import annotations

PHASE_PLAYER_JS = """\
// M3-A P1 shared phase player: sequential presentation, one timing semantics.
// Browser timing is approximate (setTimeout); not research-grade.
function playPhases(deps) {
  function run(i) {
    if (i >= deps.phases.length) { return Promise.resolve(); }
    var ph = deps.phases[i];
    deps.show(ph);
    var hasDuration = (ph.duration_ms !== null && ph.duration_ms !== undefined);
    if (ph.response_window) {
      // exactly one response per window phase; the engine resolves the promise
      // when that response is submitted or its deadline is missed
      return deps.collectWindow(ph, hasDuration ? ph.duration_ms : null)
        .then(function () { return run(i + 1); });
    }
    if (ph.advance === "keypress") {
      var keyP = deps.waitKey(null, null);
      if (!hasDuration) { return keyP.then(function () { return run(i + 1); }); }
      return Promise.race([keyP, deps.sleep(ph.duration_ms)])
        .then(function () { return run(i + 1); });
    }
    if (hasDuration) { return deps.sleep(ph.duration_ms).then(function () { return run(i + 1); }); }
    return deps.waitKey(null, null).then(function () { return run(i + 1); });
  }
  return run(0);
}
"""


def plan_phases(trial: dict[str, object]) -> list[dict[str, object]] | None:
    """Extract the materialized phase list from a bundle trial (None when unphased).

    The single projection both run-plan builders use: verbatim from the bundle,
    no engine-side re-derivation (the bundle is the sole source of truth).
    """
    stimulus = trial.get("stimulus")
    if not isinstance(stimulus, dict):
        return None
    phases = stimulus.get("phases")
    if not isinstance(phases, list) or not phases:
        return None
    return phases  # type: ignore[return-value]
