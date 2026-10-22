"""Deterministic HTML game renderer (Phase B contract §11, frozen in B2).

Core responsibilities (contract §11.1):
- render_game_html(bundle, game_spec) is a pure function — same input → byte-identical HTML (§11.7);
- trials/conditions/stimuli/correct answers come only from the Bundle (defense D-2: the renderer is the sole consumer of trials);
- GameSpec only supplies presentation parameters: any presentation change leaves trial steps untouched (BR-4).

Security (contract §11.3):
- dynamic text is always embedded as json.dumps(ensure_ascii=True) + '<'→'\\u003c' inside JS strings (blocks </script> escape);
- <title> goes through html.escape; template assembly uses split interleaving (chained replace is forbidden — blocks placeholder injection via user text);
- the engine JS uses textContent/createElement only; no innerHTML/eval/document.write (BR-5 grep assertion).

Startup integrity (contract §11.4, defense D-3): the HTML embeds a pure-JS SHA-256 implementation (zero dependencies);
at startup it verifies the BUNDLE_CANONICAL / TRIALS_CANONICAL fingerprints and refuses to start on any mismatch.

Timing precision (contract §11.9): browser setTimeout scheduling is approximate — stated verbatim in both
the footer and the end screen; no millisecond precision is claimed; not for formal data collection.
"""

from __future__ import annotations

import html
import json
from typing import Callable, cast

from src.experiment.canonical import canonical_json
from src.experiment.game_schemas import GameSpec
from src.experiment.phase_player import PHASE_PLAYER_JS, plan_phases

MAX_RENDERED_HTML_BYTES = 1_048_576  # rendered-output guard (§11.8, same order as export)

# ---------------------------------------------------------------------------
# v2 layout registry (M2-D Phase 1): separately registered layout renderers.
#
# The classic pipeline below is NOT registry-based: it stays the default path for
# every spec without a registered v2 layout (all v1 specs and v2 sequential specs),
# byte-identical to the pre-M2-D behavior. A schema_version 2 GameSpec whose
# mechanics.layout matches a registered renderer is dispatched to it instead.
# ---------------------------------------------------------------------------

_V2_LAYOUT_RENDERERS: dict[str, Callable[[dict[str, object], GameSpec], str]] = {}


def register_v2_layout(
    name: str, renderer: Callable[[dict[str, object], GameSpec], str]
) -> None:
    """Register a schema_version 2 layout renderer (M2-D; idempotent overwrite)."""
    _V2_LAYOUT_RENDERERS[name] = renderer


def _load_v2_layouts() -> None:
    """Import the v2 layout module once and register its layout (lazy: the v1 import graph is unchanged)."""
    if "explore-and-encounter" not in _V2_LAYOUT_RENDERERS:
        from src.experiment import explore_render

        explore_render.register_into(register_v2_layout)


# ---------------------------------------------------------------------------
# Embedding escapes (§11.3)
# ---------------------------------------------------------------------------

def _js_string(text: str) -> str:
    """Text → JS string literal: full ensure_ascii escaping + '<'→'\\u003c' (blocks </script> escape)."""
    return json.dumps(text, ensure_ascii=True).replace("<", "\\u003c")


def _compact_json(obj: object) -> str:
    """Deterministic compact JSON text (sorted keys; pure text to be embedded, not a security boundary)."""
    return json.dumps(obj, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


# ---------------------------------------------------------------------------
# Run plan (§11.2)
# ---------------------------------------------------------------------------

def build_run_plan(bundle: dict[str, object], game_spec: GameSpec) -> dict[str, object]:
    """Build the run plan from Bundle + GameSpec (pure function; the testable carrier of the state machine and data integrity).

    Determinism: every dict iteration comes from list order (spec declaration order / trials order) or sorted
    keys (lexicographic stimulus keys) — independent of the hash seed.
    """
    spec = cast(dict[str, object], bundle["spec"])
    trials = cast(list[object], bundle["trials"])
    responses_raw = cast(list[object], spec["responses"])
    factors_raw = cast(list[object], spec["factors"])
    blocks_raw = cast(list[object], spec["blocks"])
    repro = cast(dict[str, object], bundle["reproducibility"])

    responses: list[dict[str, object]] = []
    for raw in responses_raw:
        item = cast(dict[str, object], raw)
        responses.append(
            {
                "name": item["name"],
                "kind": item["kind"],
                "options": item.get("options"),
                "scale": item.get("scale"),
                "correct_from": item.get("correct_from"),
            }
        )
    factor_order = [cast(str, cast(dict[str, object], f)["name"]) for f in factors_raw]

    steps: list[dict[str, object]] = []
    if game_spec.flow.ready_screen:
        steps.append({"type": "ready"})

    total = len(trials)
    prev_block: str | None = None
    for i, raw in enumerate(trials):
        trial = cast(dict[str, object], raw)
        factors = cast(dict[str, object], trial["factors"])
        block = cast(str, trial["block"])
        if prev_block is not None and block != prev_block and game_spec.flow.block_breaks:
            steps.append(
                {
                    "type": "block_break",
                    "completed_block": prev_block,
                    "next_block": block,
                    "done_trials": i,
                    "total_trials": total,
                }
            )
        prev_block = block
        # Presentation: factors in spec declaration order + stimulus keys in lexicographic order (deterministic)
        display: list[list[object]] = [
            [name, factors[name]] for name in factor_order if name in factors
        ]
        stimulus = trial.get("stimulus")
        phases = plan_phases(trial)
        if phases is None:
            if isinstance(stimulus, dict):
                display.extend([key, stimulus[key]] for key in sorted(stimulus))
        # Correct answers: only from the Bundle — a content-derived answer key
        # (trial.correct, M3-A P0) wins, otherwise trial.factors[correct_from] (§11.2)
        correct: dict[str, object] = {}
        materialized = trial.get("correct")
        for resp in responses:
            name = cast(str, resp["name"])
            if isinstance(materialized, dict) and name in materialized:
                correct[name] = materialized[name]
                continue
            correct_from = resp["correct_from"]
            if isinstance(correct_from, str) and correct_from in factors:
                correct[name] = factors[correct_from]
        trial_step: dict[str, object] = {
            "type": "trial",
            "index": trial["index"],
            "block": block,
            "display": display,
            "timing": trial.get("timing"),
            "correct": correct,
        }
        if phases is not None:
            trial_step["phases"] = phases
        steps.append(trial_step)

    # the end step always exists (the event log must stay exportable); the summary flag controls the stats section (§11.2)
    steps.append({"type": "end", "summary": game_spec.flow.end_screen == "summary"})

    bindings: dict[str, dict[str, str]] = {
        b.response_name: dict(b.keys) for b in game_spec.input.bindings
    }
    meta: dict[str, object] = {
        "game_name": game_spec.game.name,
        "title": game_spec.scene.title or game_spec.game.name,
        "instructions": game_spec.scene.instructions,
        "theme": game_spec.scene.theme,
        "layout": game_spec.scene.layout,
        "feedback": {
            "on_response": game_spec.feedback.on_response,
            "duration_ms": game_spec.feedback.duration_ms,
        },
        "flow": {
            "ready_screen": game_spec.flow.ready_screen,
            "block_breaks": game_spec.flow.block_breaks,
            "end_screen": game_spec.flow.end_screen,
        },
        "gamification": {
            "score": game_spec.gamification.score,
            "progress_bar": game_spec.gamification.progress_bar,
            "streak_bonus": game_spec.gamification.streak_bonus,
        },
        "responses": responses,
        "bindings": bindings,
        "total_trials": total,
        "blocks": [cast(str, cast(dict[str, object], b)["name"]) for b in blocks_raw],
        "integrity": {
            "bundle_sha256": bundle["bundle_sha256"],
            "trials_fingerprint": repro["trials_fingerprint"],
            "config_fingerprint": repro["config_fingerprint"],
        },
    }
    return {"meta": meta, "steps": steps}


# ---------------------------------------------------------------------------
# Rendering (§11.3 / §11.4 / §11.7)
# ---------------------------------------------------------------------------

def render_game_html(bundle: dict[str, object], game_spec: GameSpec) -> str:
    """Render the single-file playable HTML (pure function: same Bundle + GameSpec → byte-identical output).

    Dispatch (M2-D): a schema_version 2 GameSpec with a registered mechanics.layout renders
    through that v2 layout renderer (currently: explore-and-encounter → explore_render);
    every other spec — all v1 specs and v2 sequential specs — takes the classic pipeline
    below, which is unchanged and byte-identical to the pre-M2-D behavior.
    """
    if game_spec.schema_version == 2 and game_spec.mechanics is not None:
        _load_v2_layouts()
        renderer = _V2_LAYOUT_RENDERERS.get(game_spec.mechanics.layout)
        if renderer is not None:
            return renderer(bundle, game_spec)
    plan = build_run_plan(bundle, game_spec)
    plan_text = _compact_json(plan)

    # Integrity anchors (§11.4): byte-identical to the Phase A fingerprint computation
    trials_canonical = canonical_json(bundle["trials"])
    stripped = {
        key: value
        for key, value in bundle.items()
        if key not in ("bundle_sha256", "generated_at")
    }
    bundle_canonical = canonical_json(stripped)
    repro = cast(dict[str, object], bundle["reproducibility"])
    expected = {
        "bundle_sha256": str(bundle["bundle_sha256"]),
        "trials_fingerprint": str(repro["trials_fingerprint"]),
    }

    data_script = (
        '"use strict";\n'
        "const PLAN = JSON.parse(" + _js_string(plan_text) + ");\n"
        "const TRIALS_CANONICAL = " + _js_string(trials_canonical) + ";\n"
        "const BUNDLE_CANONICAL = " + _js_string(bundle_canonical) + ";\n"
        "const EXPECTED = JSON.parse(" + _js_string(_compact_json(expected)) + ");\n"
        + _SHA256_JS
        + "\n"
        + _INTEGRITY_JS
    )

    title = str(cast(dict[str, object], plan["meta"])["title"])
    body_class = f"theme-{game_spec.scene.theme} layout-{game_spec.scene.layout}"
    has_phases = any(
        isinstance(step, dict) and "phases" in step
        for step in cast(list[object], plan["steps"])
    )
    return _assemble(html.escape(title, quote=True), body_class, data_script, _engine_script(has_phases))


def _split_once(template: str, placeholder: str) -> tuple[str, str]:
    """Split the template at the placeholder (each must occur exactly once; content is never re-scanned — blocks injection)."""
    parts = template.split(placeholder)
    if len(parts) != 2:
        raise ValueError(f"template placeholder {placeholder!r} expected exactly once")
    return parts[0], parts[1]


# runTrial anchor for the M3-A P1 phased addon (must occur exactly once)
_RUNTRIAL_ANCHOR = "  function runTrial(step) {\n"

# Phased-trial addon (injected ONLY when the plan carries phased trials, so
# every unphased game keeps the exact historical engine bytes / golden HTML):
# shared playPhases state machine (phase_player.py) + engine glue. One response
# is collected per response_window phase (RT anchored at that phase's onset);
# keys outside a window are never recorded; responses without a window phase
# are logged as missed (value null), never skipped and never duplicated.
_PHASED_ADDON_JS = """\
  // ---------- M3-A P1: phased trial playback (present only when trials have phases) ----------
  function phaseWindowDeadline(timing, phaseDeadline) {
    var d1 = (timing.stimulus_ms === null || timing.stimulus_ms === undefined)
      ? null : timing.stimulus_ms;
    if (d1 !== null && phaseDeadline !== null) { return Math.min(d1, phaseDeadline); }
    return (d1 !== null) ? d1 : phaseDeadline;
  }
  function phasedCollectChoice(resp, deadline) {
    var binding = (M.bindings && M.bindings[resp.name]) || {};
    var prompt = addDiv(screenEl, "response-prompt");
    addDiv(prompt, "hint", hintForResponse(resp));
    return waitKey(function (key) {
      return Object.prototype.hasOwnProperty.call(binding, key);
    }, deadline).then(function (k) {
      if (k === null) { return null; }
      return binding[k];
    });
  }
  function phasedCollectInput(resp, deadline) {
    var wrap = addDiv(screenEl, "response-prompt");
    addDiv(wrap, "hint", hintForResponse(resp));
    var input = document.createElement("input");
    input.type = "text";
    input.className = "text-input";
    input.autocomplete = "off";
    wrap.appendChild(input);
    input.focus();
    return new Promise(function (resolve) {
      var settled = false;
      function finish(v) { if (!settled) { settled = true; resolve(v); } }
      input.addEventListener("keydown", function (ev) {
        ev.stopPropagation();
        if (ev.key !== "Enter") { return; }
        ev.preventDefault();
        var raw = input.value;
        if (resp.kind === "rating" && resp.scale) {
          var n = Number(raw);
          if (raw.trim() === "" || !Number.isInteger(n) || n < resp.scale[0] || n > resp.scale[1]) {
            addDiv(wrap, "warn", "enter an integer between " + resp.scale[0] + " and " + resp.scale[1]);
            return;
          }
          finish(n);
        } else {
          finish(raw);
        }
      });
      if (deadline !== null && deadline !== undefined) {
        setTimeout(function () { finish(null); }, deadline);
      }
    });
  }
  function runPhasedTrial(step) {
    var timing = step.timing || {};
    var respIdx = 0;
    var p = Promise.resolve();
    if (timing.fixation_ms > 0) {
      p = p.then(function () {
        clearEl(screenEl);
        addDiv(screenEl, "fixation", "+");
        return sleep(timing.fixation_ms);
      });
    }
    p = p.then(function () {
      logEvent({ event: "trial_start", trial_index: step.index, block: step.block,
                 conditions: conditionsOf(step) });
    });
    p = p.then(function () {
      return playPhases({
        phases: step.phases,
        show: function (ph) {
          clearEl(screenEl);
          var stim = addDiv(screenEl, "stimulus");
          for (var i = 0; i < ph.lines.length; i++) { addDiv(stim, "stim-line", ph.lines[i]); }
        },
        sleep: sleep,
        waitKey: waitKey,
        collectWindow: function (ph, phaseDeadline) {
          var resp = M.responses[respIdx];
          if (!resp) { return Promise.resolve(); }
          var deadline = phaseWindowDeadline(timing, phaseDeadline);
          var onset = performance.now();
          var collectP = (resp.kind === "choice")
            ? phasedCollectChoice(resp, deadline)
            : phasedCollectInput(resp, deadline);
          return collectP.then(function (value) {
            respIdx += 1;
            var correct = computeCorrect(resp, step, value);
            logEvent({ event: "response", trial_index: step.index, block: step.block,
                       conditions: conditionsOf(step), response_name: resp.name,
                       value: value, correct: correct,
                       rt_ms: Math.round(performance.now() - onset) });
            applyOutcome(correct);
            updateHeader();
            return showFeedback(correct, value);
          });
        }
      });
    });
    p = p.then(function () {
      // responses left without a window phase: recorded as missed, never valid answers
      function missOne() {
        if (respIdx >= M.responses.length) { return Promise.resolve(); }
        var resp = M.responses[respIdx];
        respIdx += 1;
        var correct = computeCorrect(resp, step, null);
        logEvent({ event: "response", trial_index: step.index, block: step.block,
                   conditions: conditionsOf(step), response_name: resp.name,
                   value: null, correct: correct, rt_ms: null });
        applyOutcome(correct);
        return missOne();
      }
      return missOne();
    });
    p = p.then(function () {
      if (timing.isi_ms > 0) {
        clearEl(screenEl);
        return sleep(timing.isi_ms);
      }
    }).then(function () {
      doneTrials += 1;
      updateHeader();
    });
    return p;
  }
"""


def _engine_script(phased: bool) -> str:
    """Engine JS for one rendering: the historical bytes, plus the phased addon
    (player + dispatch) ONLY when the plan carries phased trials.

    Unphased output is byte-identical to the pre-P1 engine (golden gate).
    """
    if not phased:
        return _ENGINE_JS
    if _ENGINE_JS.count(_RUNTRIAL_ANCHOR) != 1:
        raise ValueError("runTrial anchor not unique in the classic engine")
    return (
        PHASE_PLAYER_JS
        + _ENGINE_JS.replace(
            _RUNTRIAL_ANCHOR,
            _PHASED_ADDON_JS
            + _RUNTRIAL_ANCHOR
            + "    if (step.phases) { return runPhasedTrial(step); }\n",
            1,
        )
    )


def _assemble(title: str, body_class: str, data_script: str, engine_script: str) -> str:
    head, rest = _split_once(_TEMPLATE, "__TITLE__")
    mid, tail = _split_once(rest, "__BODY_CLASS__")
    pre_data, post_data = _split_once(tail, "__DATA__")
    pre_engine, post_engine = _split_once(post_data, "__ENGINE__\n")
    return (
        head + title + mid + body_class + pre_data + data_script
        + pre_engine + engine_script + post_engine
    )


# ---------------------------------------------------------------------------
# Embedded JS: SHA-256 implementation (standard algorithm, zero dependencies; independently runnable under node — BR-8)
# ---------------------------------------------------------------------------

_SHA256_JS = """\
function sha256Hex(str) {
  var K = [0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,
           0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,
           0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,
           0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
           0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,
           0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,
           0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,
           0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
           0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,
           0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,
           0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2];
  var bytes = new TextEncoder().encode(str);
  var l = bytes.length;
  var blocks = Math.ceil((l + 9) / 64);
  var m = new Uint8Array(blocks * 64);
  m.set(bytes);
  m[l] = 0x80;
  var bits = l * 8;
  var dv = new DataView(m.buffer);
  dv.setUint32(blocks * 64 - 8, Math.floor(bits / 4294967296));
  dv.setUint32(blocks * 64 - 4, (bits % 4294967296) >>> 0);
  var H = new Int32Array([0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,
                          0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19]);
  var w = new Int32Array(64);
  function rotr(x, n) { return (x >>> n) | (x << (32 - n)); }
  for (var b = 0; b < blocks; b++) {
    var off = b * 64;
    for (var i = 0; i < 16; i++) { w[i] = dv.getInt32(off + i * 4); }
    for (var i = 16; i < 64; i++) {
      var s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >>> 3);
      var s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >>> 10);
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) | 0;
    }
    var a = H[0], b2 = H[1], c = H[2], d = H[3];
    var e = H[4], f = H[5], g = H[6], h = H[7];
    for (var i = 0; i < 64; i++) {
      var S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
      var ch = (e & f) ^ (~e & g);
      var t1 = (h + S1 + ch + K[i] + w[i]) | 0;
      var S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
      var maj = (a & b2) ^ (a & c) ^ (b2 & c);
      var t2 = (S0 + maj) | 0;
      h = g; g = f; f = e; e = (d + t1) | 0;
      d = c; c = b2; b2 = a; a = (t1 + t2) | 0;
    }
    H[0] = (H[0] + a) | 0; H[1] = (H[1] + b2) | 0; H[2] = (H[2] + c) | 0;
    H[3] = (H[3] + d) | 0; H[4] = (H[4] + e) | 0; H[5] = (H[5] + f) | 0;
    H[6] = (H[6] + g) | 0; H[7] = (H[7] + h) | 0;
  }
  var out = "";
  for (var i = 0; i < 8; i++) {
    out += ("00000000" + (H[i] >>> 0).toString(16)).slice(-8);
  }
  return out;
}
"""

_INTEGRITY_JS = """\
var integrity = (function () {
  try {
    var bundle_ok = sha256Hex(BUNDLE_CANONICAL) === EXPECTED.bundle_sha256;
    var trials_ok = sha256Hex(TRIALS_CANONICAL) === EXPECTED.trials_fingerprint;
    return { ok: bundle_ok && trials_ok, bundle_ok: bundle_ok, trials_ok: trials_ok };
  } catch (err) {
    return { ok: false, bundle_ok: false, trials_ok: false, error: String(err) };
  }
})();
"""


# ---------------------------------------------------------------------------
# HTML template (static skeleton + engine JS; security contract: the engine uses textContent/createElement only)
# ---------------------------------------------------------------------------

_ENGINE_JS = """\
"use strict";
(function () {
  var M = PLAN.meta;
  var STEPS = PLAN.steps;
  function $(id) { return document.getElementById(id); }
  var screenEl = $("screen");
  var stageEl = $("stage");

  // ---------- event log (runtime data; not part of HTML determinism) ----------
  var events = [];
  function logEvent(ev) { ev.t_epoch_ms = Date.now(); events.push(ev); }

  // ---------- DOM helpers: textContent only (security contract) ----------
  function clearEl(el) { while (el.firstChild) { el.removeChild(el.firstChild); } }
  function addDiv(parent, cls, text) {
    var d = document.createElement("div");
    if (cls) { d.className = cls; }
    if (text !== undefined && text !== null) { d.textContent = String(text); }
    parent.appendChild(d);
    return d;
  }

  // ---------- keyboard ----------
  var NAMED_KEYS = { space: " ", enter: "Enter", left: "ArrowLeft",
                     right: "ArrowRight", up: "ArrowUp", down: "ArrowDown" };
  function physKey(ev) {
    if (ev.key.length === 1) { return ev.key.toLowerCase(); }
    for (var name in NAMED_KEYS) { if (NAMED_KEYS[name] === ev.key) { return name; } }
    return null;
  }
  var pendingKey = null;
  var keySeq = 0;
  function waitKey(filter, deadlineMs) {
    return new Promise(function (resolve) {
      keySeq += 1;
      var gen = keySeq;
      var entry = { resolve: resolve, filter: filter, gen: gen, timer: null };
      if (deadlineMs !== null && deadlineMs !== undefined) {
        entry.timer = setTimeout(function () {
          if (pendingKey && pendingKey.gen === gen) { pendingKey = null; }
          resolve(null);
        }, deadlineMs);
      }
      pendingKey = entry;
    });
  }
  document.addEventListener("keydown", function (ev) {
    var el = document.activeElement;
    if (el && el.tagName === "INPUT") { return; }
    if (!pendingKey) { return; }
    var k = physKey(ev);
    if (k === null) { return; }
    if (pendingKey.filter && !pendingKey.filter(k)) { return; }
    ev.preventDefault();
    var entry = pendingKey;
    pendingKey = null;
    if (entry.timer) { clearTimeout(entry.timer); }
    entry.resolve(k);
  });
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  // ---------- header ----------
  var doneTrials = 0;
  var score = 0, streak = 0, bestStreak = 0, correctCount = 0, correctApplicable = 0;
  function updateHeader() {
    $("hdr-title").textContent = M.title;
    var right = "";
    if (M.gamification.score) { right += "score " + score + "  "; }
    right += doneTrials + "/" + M.total_trials;
    $("hdr-right").textContent = right;
    if (M.gamification.progress_bar) {
      var pct = M.total_trials > 0 ? Math.round((doneTrials / M.total_trials) * 100) : 0;
      $("progress-inner").style.width = pct + "%";
    } else {
      $("progress-outer").style.display = "none";
    }
  }

  function conditionsOf(step) {
    var obj = {};
    for (var i = 0; i < step.display.length; i++) { obj[step.display[i][0]] = step.display[i][1]; }
    return obj;
  }
  function hintForResponse(r) {
    if (r.kind === "choice") {
      var binding = (M.bindings && M.bindings[r.name]) || {};
      var parts = [];
      var keys = Object.keys(binding);
      for (var j = 0; j < keys.length; j++) {
        parts.push("[" + keys[j] + "] " + binding[keys[j]]);
      }
      return r.name + ": " + (parts.length ? parts.join("  ") : "(no binding)");
    }
    if (r.kind === "rating" && r.scale) {
      return r.name + ": type a number " + r.scale[0] + "-" + r.scale[1] + " then Enter";
    }
    return r.name + ": type your answer then Enter";
  }
  function keyHintText() {
    var lines = [];
    for (var i = 0; i < M.responses.length; i++) { lines.push(hintForResponse(M.responses[i])); }
    return lines.join(" | ");
  }

  // ---------- screens ----------
  function showIntegrityError() {
    clearEl(screenEl);
    addDiv(screenEl, "title", "Integrity check failed");
    addDiv(screenEl, "error", "This game file was modified after generation and refuses to start.");
    addDiv(screenEl, "hint", "bundle ok: " + integrity.bundle_ok + " / trials ok: " + integrity.trials_ok);
  }

  function showReady() {
    clearEl(screenEl);
    addDiv(screenEl, "title", M.title);
    if (M.instructions) { addDiv(screenEl, "instructions", M.instructions); }
    addDiv(screenEl, "hint", keyHintText());
    addDiv(screenEl, "hint", "Press any key to start");
    return waitKey(null, null);
  }

  function showBlockBreak(step) {
    clearEl(screenEl);
    addDiv(screenEl, "title", "Block '" + step.completed_block + "' complete");
    addDiv(screenEl, "hint", step.done_trials + " of " + step.total_trials + " trials done");
    addDiv(screenEl, "hint", "Press any key to continue");
    return waitKey(null, null);
  }

  function collectChoice(resp, step) {
    var binding = (M.bindings && M.bindings[resp.name]) || {};
    var prompt = addDiv(screenEl, "response-prompt");
    addDiv(prompt, "hint", hintForResponse(resp));
    var t = step.timing || {};
    var deadline = (t.stimulus_ms === null || t.stimulus_ms === undefined) ? null : t.stimulus_ms;
    return waitKey(function (key) {
      return Object.prototype.hasOwnProperty.call(binding, key);
    }, deadline).then(function (k) {
      if (k === null) { return null; }
      return binding[k];
    });
  }

  function collectInput(resp, step) {
    var wrap = addDiv(screenEl, "response-prompt");
    addDiv(wrap, "hint", hintForResponse(resp));
    var input = document.createElement("input");
    input.type = "text";
    input.className = "text-input";
    input.autocomplete = "off";
    wrap.appendChild(input);
    input.focus();
    return new Promise(function (resolve) {
      var settled = false;
      function finish(v) { if (!settled) { settled = true; resolve(v); } }
      input.addEventListener("keydown", function (ev) {
        ev.stopPropagation();
        if (ev.key !== "Enter") { return; }
        ev.preventDefault();
        var raw = input.value;
        if (resp.kind === "rating" && resp.scale) {
          var n = Number(raw);
          if (raw.trim() === "" || !Number.isInteger(n) || n < resp.scale[0] || n > resp.scale[1]) {
            addDiv(wrap, "warn", "enter an integer between " + resp.scale[0] + " and " + resp.scale[1]);
            return;
          }
          finish(n);
        } else {
          finish(raw);
        }
      });
      var t = step.timing || {};
      if (t.stimulus_ms !== null && t.stimulus_ms !== undefined) {
        setTimeout(function () { finish(null); }, t.stimulus_ms);
      }
    });
  }

  function computeCorrect(resp, step, value) {
    var has = step.correct && Object.prototype.hasOwnProperty.call(step.correct, resp.name);
    if (!has) { return null; }
    var expected = step.correct[resp.name];
    if (value === null) { return false; }
    return value === expected;
  }

  function applyOutcome(correct) {
    if (correct === true) {
      correctCount += 1; streak += 1; correctApplicable += 1;
      if (streak > bestStreak) { bestStreak = streak; }
      if (M.gamification.score) {
        score += 1;
        if (M.gamification.streak_bonus && streak > 1) { score += 1; }
      }
    } else if (correct === false) {
      streak = 0; correctApplicable += 1;
    }
  }

  function showFeedback(correct, value) {
    var style = M.feedback.on_response;
    var dur = M.feedback.duration_ms;
    if (style === "none" || dur <= 0) { return Promise.resolve(); }
    var text;
    if (value === null) { text = "missed"; }
    else if (correct === null || correct === undefined) { text = "recorded"; }
    else { text = correct ? "correct" : "incorrect"; }
    if (style === "correctness-flash") {
      stageEl.classList.add(correct === false ? "flash-wrong" : "flash-correct");
      return sleep(dur).then(function () {
        stageEl.classList.remove("flash-correct");
        stageEl.classList.remove("flash-wrong");
      });
    }
    clearEl(screenEl);
    addDiv(screenEl, "feedback " + (correct === false ? "fb-wrong" : "fb-correct"), text);
    return sleep(dur);
  }

  function runTrial(step) {
    var timing = step.timing || {};
    var p = Promise.resolve();
    if (timing.fixation_ms > 0) {
      p = p.then(function () {
        clearEl(screenEl);
        addDiv(screenEl, "fixation", "+");
        return sleep(timing.fixation_ms);
      });
    }
    p = p.then(function () {
      clearEl(screenEl);
      var stim = addDiv(screenEl, "stimulus");
      for (var i = 0; i < step.display.length; i++) {
        addDiv(stim, "stim-line", step.display[i][0] + ": " + step.display[i][1]);
      }
      logEvent({ event: "trial_start", trial_index: step.index, block: step.block,
                 conditions: conditionsOf(step) });
    });
    var onset = performance.now();
    for (var j = 0; j < M.responses.length; j++) {
      (function (resp) {
        p = p.then(function () {
          if (resp.kind === "choice") { return collectChoice(resp, step); }
          return collectInput(resp, step);
        }).then(function (value) {
          var correct = computeCorrect(resp, step, value);
          logEvent({ event: "response", trial_index: step.index, block: step.block,
                     conditions: conditionsOf(step), response_name: resp.name,
                     value: value, correct: correct,
                     rt_ms: Math.round(performance.now() - onset) });
          applyOutcome(correct);
          updateHeader();
          return showFeedback(correct, value);
        });
      })(M.responses[j]);
    }
    p = p.then(function () {
      if (timing.isi_ms > 0) {
        clearEl(screenEl);
        return sleep(timing.isi_ms);
      }
    }).then(function () {
      doneTrials += 1;
      updateHeader();
    });
    return p;
  }

  function selfCheck() {
    var problems = [];
    var byTrial = {};
    for (var i = 0; i < events.length; i++) {
      var ev = events[i];
      if (ev.event !== "response") { continue; }
      if (!byTrial[ev.trial_index]) { byTrial[ev.trial_index] = []; }
      byTrial[ev.trial_index].push(ev);
    }
    var trialSteps = [];
    for (var s = 0; s < STEPS.length; s++) { if (STEPS[s].type === "trial") { trialSteps.push(STEPS[s]); } }
    for (var t = 0; t < trialSteps.length; t++) {
      var st = trialSteps[t];
      var got = byTrial[st.index] || [];
      if (got.length !== M.responses.length) {
        problems.push("trial " + st.index + ": expected " + M.responses.length +
                      " response event(s), got " + got.length);
      } else {
        for (var g = 0; g < got.length; g++) {
          if (got[g].response_name !== M.responses[g].name) {
            problems.push("trial " + st.index + ": response " + g + " name mismatch");
            break;
          }
        }
      }
    }
    for (var key in byTrial) {
      var idx = Number(key);
      var known = false;
      for (var t2 = 0; t2 < trialSteps.length; t2++) { if (trialSteps[t2].index === idx) { known = true; } }
      if (!known) { problems.push("unexpected trial index in event log: " + key); }
    }
    return problems;
  }

  function showEnd(step) {
    clearEl(screenEl);
    addDiv(screenEl, "title", "Done");
    if (step.summary) {
      addDiv(screenEl, "stat", "Trials: " + M.total_trials);
      var acc = correctApplicable > 0
        ? Math.round((correctCount / correctApplicable) * 100) + "%" : "n/a";
      addDiv(screenEl, "stat", "Correct: " + correctCount + "/" + correctApplicable + " (" + acc + ")");
      if (M.gamification.score) {
        addDiv(screenEl, "stat", "Score: " + score + " (best streak " + bestStreak + ")");
      }
    }
    var problems = selfCheck();
    addDiv(screenEl, problems.length === 0 ? "hint" : "warn",
      problems.length === 0
        ? "Self-check OK: " + M.total_trials + " trials, " +
          (M.total_trials * M.responses.length) + " response events"
        : "Self-check FAILED: " + problems.join("; "));
    addDiv(screenEl, "disclaimer",
      "Timing in this browser prototype is approximate and not suitable for formal data collection.");
    var ta = document.createElement("textarea");
    ta.id = "eventlog";
    ta.readOnly = true;
    ta.value = JSON.stringify(events, null, 1);
    screenEl.appendChild(ta);
    var btn = document.createElement("button");
    btn.textContent = "Download event log (JSON)";
    btn.addEventListener("click", function () {
      var blob = new Blob([JSON.stringify(events, null, 1)], { type: "application/json" });
      var a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = M.game_name + "-events.json";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(a.href);
    });
    screenEl.appendChild(btn);
  }

  function main() {
    updateHeader();
    if (!integrity.ok) { showIntegrityError(); return; }
    logEvent({ event: "game_start", game_name: M.game_name, total_trials: M.total_trials });
    var currentBlock = null;
    var p = Promise.resolve();
    var runStep = function (step) {
      if (step.type === "ready") { return showReady(); }
      if (step.type === "trial") {
        if (step.block !== currentBlock) {
          currentBlock = step.block;
          logEvent({ event: "block_start", block: step.block });
        }
        return runTrial(step);
      }
      if (step.type === "block_break") { return showBlockBreak(step); }
      if (step.type === "end") {
        logEvent({ event: "game_end", total_trials: M.total_trials,
                   correct: correctCount, applicable: correctApplicable });
        showEnd(step);
      }
      return Promise.resolve();
    };
    for (var i = 0; i < STEPS.length; i++) {
      (function (step) { p = p.then(function () { return runStep(step); }); })(STEPS[i]);
    }
    p.catch(function (err) {
      clearEl(screenEl);
      addDiv(screenEl, "error", "Engine error: " + String(err));
    });
  }
  main();
})();
"""

_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root { --fg:#222; --bg:#f6f6f4; --muted:#777; --ok:#2e7d32; --bad:#c62828; }
body.theme-dark { --fg:#eee; --bg:#1e1e22; --muted:#999; }
* { box-sizing: border-box; }
body { margin:0; font-family:-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
       background:var(--bg); color:var(--fg); }
#app { max-width:720px; margin:0 auto; padding:16px; }
header { display:flex; justify-content:space-between; align-items:baseline; gap:12px; }
header h1 { font-size:1.1rem; margin:0; }
#hdr-right { color:var(--muted); font-size:0.9rem; white-space:nowrap; }
#progress-outer { height:6px; background:#ccc; border-radius:3px; margin:8px 0 16px; }
body.theme-dark #progress-outer { background:#3a3a40; }
#progress-inner { height:100%; width:0%; background:#5b8def; border-radius:3px; }
#stage { min-height:300px; display:flex; align-items:center; justify-content:center; text-align:center; }
body.layout-rows #stage { display:block; text-align:left; }
#screen { width:100%; }
.fixation { font-size:3rem; }
.stim-line { font-size:1.6rem; margin:0.35rem 0; font-weight:600; }
.response-prompt { margin-top:1.2rem; }
.hint { color:var(--muted); font-size:0.95rem; margin:0.3rem 0; }
.warn { color:#b8860b; font-size:0.9rem; }
.title { font-size:1.5rem; font-weight:700; margin-bottom:0.8rem; }
.instructions { white-space:pre-wrap; margin:0.6rem auto; max-width:560px; }
.feedback { font-size:1.4rem; font-weight:700; margin:1rem 0; }
.fb-correct { color:var(--ok); }
.fb-wrong { color:var(--bad); }
#stage.flash-correct { background:#d7ffd9; }
#stage.flash-wrong { background:#ffdcdc; }
body.theme-dark #stage.flash-correct { background:#1d3a20; }
body.theme-dark #stage.flash-wrong { background:#3a1d1d; }
.error { color:var(--bad); font-weight:700; }
#eventlog { width:100%; height:180px; font-family:monospace; font-size:0.75rem; margin-top:8px; }
button { padding:6px 14px; font-size:0.9rem; cursor:pointer; margin-top:8px; }
.disclaimer { color:var(--muted); font-size:0.8rem; margin-top:1rem; font-style:italic; }
.stat { margin:0.25rem 0; font-size:1.05rem; }
footer { margin-top:24px; color:var(--muted); font-size:0.75rem; text-align:center; }
.text-input { font-size:1.1rem; padding:6px 10px; margin-top:6px; }
</style>
</head>
<body class="__BODY_CLASS__">
<div id="app">
  <header>
    <h1 id="hdr-title"></h1>
    <div id="hdr-right"></div>
  </header>
  <div id="progress-outer"><div id="progress-inner"></div></div>
  <main id="stage"><div id="screen"></div></main>
  <footer>Prototype build: browser timing is approximate; not suitable for formal data collection.</footer>
</div>
<script>
__DATA__
</script>
<script>
__ENGINE__
</script>
</body>
</html>
"""
