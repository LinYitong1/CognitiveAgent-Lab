"""M2-D Phase 1: the explore-and-encounter v2 layout renderer.

Registered into game_render's v2 layout registry (game_render.register_v2_layout);
the classic v1 pipeline is NOT registry-based and stays the default path for every
spec without a registered v2 layout (all v1 specs and v2 sequential specs).

Design rules (M2-D Phase 1 contract):
- same determinism discipline as the classic renderer: render_explore_html is a pure
  function, same Bundle + GameSpec -> byte-identical HTML;
- the ExperimentBundle is the sole source of trials/stimuli/correct answers/timing
  (defense D-2, unchanged): the world/narrative sections supply presentation only;
  there is no field that can alter, filter or reorder trial.stimulus.lines — the
  encounter renders them VERBATIM — and response bindings cannot be overridden by
  game content;
- exploration is free (rooms, flavour objects); measurement is cursor-driven:
  examining a fresh encounter object pulls the NEXT unconsumed bundle trial in
  index order (monotonic cursor — no skip, no reorder; the mapping schema has no
  selection surface at all, M2-C);
- events are channel-tagged: "measurement" (trial_start/block_start/response — the
  data body, to be reconciled by M2-E verify_game_events) vs "game" (room_enter/
  object_inspect/encounter_trigger — presentation flow, logged but not reconciled).
  The final event schema is owned by M2-E; the channel tag is provisional;
- runtime is single-file zero-dependency JS using textContent/createElement only
  (same security contract as the classic engine: no innerHTML/eval/document.write)
  and verifies the embedded BUNDLE_CANONICAL/TRIALS_CANONICAL fingerprints at
  startup (defense D-3, unchanged);
- no research-grade claims: browser timing is approximate (stated in the footer and
  the end screen); nothing is persisted — the event log is exported manually.

Phase 1 limitations (docs/m2/M2D_PHASE1_REPORT.md): choice responses only;
the session can be concluded once all trials are consumed; encounter objects beyond
the trial count become inspect-only; a "sequential" trial_trigger never reaches this
renderer (it renders through the classic pipeline).
"""

from __future__ import annotations

import html
from typing import Callable, cast

from src.experiment.canonical import canonical_json
from src.experiment.game_render import (
    _INTEGRITY_JS,
    _SHA256_JS,
    _compact_json,
    _js_string,
    _split_once,
)
from src.experiment.game_schemas import GameSpec

LAYOUT_NAME = "explore-and-encounter"

# ---------------------------------------------------------------------------
# Explore plan (pure function; the testable carrier of the explore state machine)
# ---------------------------------------------------------------------------


def build_explore_plan(bundle: dict[str, object], game_spec: GameSpec) -> dict[str, object]:
    """Build the explore run plan from Bundle + GameSpec (pure function).

    Determinism: dict iteration comes from declaration order (pydantic preserves it)
    and the embedded JSON is produced by _compact_json (sorted keys) — hash-seed
    independent, byte-identical for the same inputs.
    """
    spec = cast(dict[str, object], bundle["spec"])
    trials = cast(list[object], bundle["trials"])
    repro = cast(dict[str, object], bundle["reproducibility"])

    mapping = game_spec.mapping
    world = game_spec.world
    if mapping is None or world is None:
        raise ValueError(
            "the explore-and-encounter layout requires the world and mapping sections"
        )
    if mapping.trial_trigger != "explore-encounter":
        raise ValueError(
            "the explore-and-encounter layout requires trial_trigger='explore-encounter'"
        )

    # responses: Phase 1 supports choice responses only (documented limitation)
    responses: list[dict[str, object]] = []
    for raw in cast(list[object], spec["responses"]):
        item = cast(dict[str, object], raw)
        if item.get("kind") != "choice":
            raise ValueError(
                f"explore layout supports choice responses only (Phase 1); "
                f"response {item.get('name')!r} has kind {item.get('kind')!r}"
            )
        responses.append(
            {
                "name": item["name"],
                "kind": "choice",
                "options": item.get("options"),
                "correct_from": item.get("correct_from"),
            }
        )

    # bindings: the mapping surface is the encounter-trial surface (G8 requires
    # response_bindings for the explore-encounter trigger; the builder is strict —
    # no silent fallback, a missing binding is a render-time error)
    bindings: dict[str, dict[str, str]] = {}
    for b in mapping.response_bindings:
        bindings[b.response_name] = dict(b.keys)
    for resp in responses:
        name = cast(str, resp["name"])
        if not bindings.get(name):
            raise ValueError(
                f"response {name!r} has no key binding on the mapping or input surface"
            )

    # world projection (plain dicts; G8 already validated structure/reachability)
    rooms: dict[str, dict[str, object]] = {}
    for room_id, room in world.rooms.items():
        rooms[room_id] = {
            "title": room.title,
            "description": room.description,
            "exits": dict(room.exits),
            "objects": [
                {
                    "object_id": o.object_id,
                    "label": o.label,
                    "inspect_text": o.inspect_text,
                    "role": o.role,
                }
                for o in room.objects
            ],
        }
    for room_id, room in rooms.items():
        for target in cast(dict[str, str], room["exits"]):
            if target not in rooms:
                raise ValueError(
                    f"exit target {target!r} of room {room_id!r} does not exist"
                )

    # trials projection: lines VERBATIM from the bundle (no override surface)
    trial_steps: list[dict[str, object]] = []
    for raw in trials:
        trial = cast(dict[str, object], raw)
        factors = cast(dict[str, object], trial["factors"])
        stimulus = trial.get("stimulus")
        lines = (
            cast(list[object], stimulus.get("lines"))
            if isinstance(stimulus, dict)
            else None
        )
        if not isinstance(lines, list) or not all(isinstance(x, str) for x in lines):
            raise ValueError(
                f"trial {trial.get('index')} has no materialized stimulus.lines — "
                "the explore layout requires a v2 bundle (G8_STIMULUS_SEMANTICS)"
            )
        correct: dict[str, object] = {}
        for resp in responses:
            correct_from = resp["correct_from"]
            if isinstance(correct_from, str) and correct_from in factors:
                correct[cast(str, resp["name"])] = factors[correct_from]
        trial_steps.append(
            {
                "index": trial["index"],
                "block": trial["block"],
                "conditions": dict(factors),
                "lines": list(lines),
                "correct": correct,
                "timing": trial.get("timing"),
            }
        )

    narrative = game_spec.narrative
    intro = narrative.intro if narrative else ""
    briefings = dict(narrative.block_briefings) if narrative else {}
    bands = (
        [{"min_accuracy": b.min_accuracy, "text": b.text} for b in narrative.ending_bands]
        if narrative
        else []
    )

    meta: dict[str, object] = {
        "game_name": game_spec.game.name,
        "title": game_spec.scene.title or game_spec.game.name,
        "instructions": game_spec.scene.instructions,
        "theme": game_spec.scene.theme,
        "mode": LAYOUT_NAME,
        "inspect_objects": (
            game_spec.mechanics.inspect_objects if game_spec.mechanics else True
        ),
        "responses": responses,
        "bindings": bindings,
        "total_trials": len(trials),
        "blocks": [
            cast(str, cast(dict[str, object], b)["name"]) for b in cast(list[object], spec["blocks"])
        ],
        "feedback": {
            "on_response": game_spec.feedback.on_response,
            "duration_ms": game_spec.feedback.duration_ms,
        },
        "gamification": {
            "score": game_spec.gamification.score,
            "progress_bar": game_spec.gamification.progress_bar,
            "streak_bonus": game_spec.gamification.streak_bonus,
        },
        "integrity": {
            "bundle_sha256": bundle["bundle_sha256"],
            "trials_fingerprint": repro["trials_fingerprint"],
            "config_fingerprint": repro["config_fingerprint"],
        },
    }
    return {
        "meta": meta,
        "world": {"start_room": world.start_room, "rooms": rooms},
        "narrative": {"intro": intro, "block_briefings": briefings, "ending_bands": bands},
        "encounters": list(mapping.encounter_objects or []),
        "trials": trial_steps,
    }


# ---------------------------------------------------------------------------
# Rendering (same embedding/security discipline as the classic renderer)
# ---------------------------------------------------------------------------


def render_explore_html(bundle: dict[str, object], game_spec: GameSpec) -> str:
    """Render the single-file playable explore HTML (pure function, byte-identical output)."""
    plan = build_explore_plan(bundle, game_spec)
    plan_text = _compact_json(plan)

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
    body_class = f"theme-{game_spec.scene.theme} layout-{LAYOUT_NAME}"
    return _assemble(html.escape(title, quote=True), body_class, data_script)


def register_into(
    register: Callable[[str, Callable[[dict[str, object], GameSpec], str]], None],
) -> None:
    """Register this layout into game_render's v2 layout registry (M2-D)."""
    register(LAYOUT_NAME, render_explore_html)


def _assemble(title: str, body_class: str, data_script: str) -> str:
    head, rest = _split_once(_TEMPLATE, "__TITLE__")
    mid, tail = _split_once(rest, "__BODY_CLASS__")
    pre_data, post_data = _split_once(tail, "__DATA__")
    return head + title + mid + body_class + pre_data + data_script + post_data


# ---------------------------------------------------------------------------
# Embedded JS: the explore engine (textContent/createElement only; zero dependencies)
# ---------------------------------------------------------------------------

_ENGINE_JS = """\
"use strict";
(function () {
  var M = PLAN.meta;
  var WORLD = PLAN.world;
  var NARR = PLAN.narrative;
  var TRIALS = PLAN.trials;

  function $(id) { return document.getElementById(id); }
  var screenEl = $("screen");
  var stageEl = $("stage");

  // ---------- event log: channel-tagged ----------
  // "measurement" = the data body (trial_start/block_start/response; reconciled by M2-E);
  // "game" = presentation flow (room_enter/object_inspect/encounter_trigger; logged, not reconciled).
  var events = [];
  function logGame(ev) { ev.channel = "game"; ev.t_epoch_ms = Date.now(); events.push(ev); }
  function logMeasurement(ev) { ev.channel = "measurement"; ev.t_epoch_ms = Date.now(); events.push(ev); }

  // ---------- state ----------
  var state = {
    mode: "boot",        // intro | explore | inspect | briefing | encounter | end
    phase: null,         // encounter sub-phase: fixation | stimulus | response | feedback | isi
    room: WORLD.start_room,
    cursor: 0,           // monotonic trial cursor — the ONLY trial-selection mechanism
    examined: {},        // object_id -> true (an encounter object fires at most one trial)
    lastBlock: null,
    doneTrials: 0,
    score: 0, streak: 0, bestStreak: 0, correctCount: 0, correctApplicable: 0
  };
  function snapshot() {
    return { mode: state.mode, phase: state.phase, room: state.room, cursor: state.cursor,
             done_trials: state.doneTrials, total_trials: M.total_trials };
  }

  // ---------- DOM helpers: textContent only (security contract) ----------
  function clearEl(el) { while (el.firstChild) { el.removeChild(el.firstChild); } }
  function addDiv(parent, cls, text) {
    var d = document.createElement("div");
    if (cls) { d.className = cls; }
    if (text !== undefined && text !== null) { d.textContent = String(text); }
    parent.appendChild(d);
    return d;
  }

  // ---------- keyboard (same waitKey protocol as the classic engine) ----------
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
  function updateHeader() {
    $("hdr-title").textContent = M.title;
    var right = "";
    if (M.gamification.score) { right += "score " + state.score + "  "; }
    right += "trials " + state.doneTrials + "/" + M.total_trials;
    $("hdr-right").textContent = right;
    if (M.gamification.progress_bar) {
      var pct = M.total_trials > 0 ? Math.round((state.doneTrials / M.total_trials) * 100) : 100;
      $("progress-inner").style.width = pct + "%";
    } else {
      $("progress-outer").style.display = "none";
    }
  }

  function keyHintText() {
    var lines = [];
    for (var i = 0; i < M.responses.length; i++) {
      var r = M.responses[i];
      var binding = M.bindings[r.name] || {};
      var parts = [];
      var keys = Object.keys(binding);
      for (var j = 0; j < keys.length; j++) { parts.push("[" + keys[j] + "] " + binding[keys[j]]); }
      lines.push(r.name + ": " + (parts.length ? parts.join("  ") : "(no binding)"));
    }
    return lines.join(" | ");
  }

  // ---------- integrity (defense D-3, same as the classic engine) ----------
  function showIntegrityError() {
    clearEl(screenEl);
    addDiv(screenEl, "title", "Integrity check failed");
    addDiv(screenEl, "error", "This game file was modified after generation and refuses to start.");
    addDiv(screenEl, "hint", "bundle ok: " + integrity.bundle_ok + " / trials ok: " + integrity.trials_ok);
  }

  // ---------- exploration ----------
  function keyForIndex(i) { return i < 9 ? String(i + 1) : "0"; }

  function visibleObjects(room) {
    var out = [];
    for (var i = 0; i < room.objects.length; i++) {
      var o = room.objects[i];
      if (o.role === "flavour" && M.inspect_objects === false) { continue; }
      out.push(o);
    }
    return out;
  }

  function renderRoom() {
    state.mode = "explore";
    state.phase = null;
    stageEl.classList.remove("mode-experiment");
    clearEl(screenEl);
    var room = WORLD.rooms[state.room];
    addDiv(screenEl, "room-title", room.title);
    if (room.description) { addDiv(screenEl, "room-desc", room.description); }
    var objects = visibleObjects(room);
    if (objects.length > 0) {
      addDiv(screenEl, "room-section", "You notice:");
      for (var i = 0; i < objects.length; i++) {
        var o = objects[i];
        var suffix = "";
        if (o.role === "encounter" && state.examined[o.object_id]) { suffix = " (examined)"; }
        addDiv(screenEl, "room-item", "[" + keyForIndex(i) + "] " + o.label + suffix);
      }
    }
    var exitIds = Object.keys(room.exits);
    if (exitIds.length > 0) {
      addDiv(screenEl, "room-section", "Ways on:");
      for (var e = 0; e < exitIds.length; e++) {
        addDiv(screenEl, "room-item", "[" + keyForIndex(objects.length + e) + "] " + room.exits[exitIds[e]]);
      }
    }
    if (state.cursor >= M.total_trials) {
      addDiv(screenEl, "room-conclude", "[x] conclude the session");
    }
    addDiv(screenEl, "hint", "Numbers inspect objects or move between rooms; encounters run a controlled trial.");
  }

  function roomActions() {
    var room = WORLD.rooms[state.room];
    var actions = {};
    var objects = visibleObjects(room);
    for (var i = 0; i < objects.length; i++) {
      actions[keyForIndex(i)] = { kind: "object", obj: objects[i] };
    }
    var exitIds = Object.keys(room.exits);
    for (var e = 0; e < exitIds.length; e++) {
      actions[keyForIndex(objects.length + e)] = { kind: "exit", target: exitIds[e] };
    }
    if (state.cursor >= M.total_trials) { actions["x"] = { kind: "conclude" }; }
    return actions;
  }

  function exploreLoop() {
    renderRoom();
    updateHeader();
    var actions = roomActions();
    return waitKey(function (k) {
      return Object.prototype.hasOwnProperty.call(actions, k);
    }, null).then(function (k) {
      var act = actions[k];
      if (act.kind === "exit") {
        state.room = act.target;
        logGame({ event: "room_enter", room: act.target });
        return exploreLoop();
      }
      if (act.kind === "conclude") { return endGame(); }
      var obj = act.obj;
      var canFire = obj.role === "encounter" && !state.examined[obj.object_id]
        && state.cursor < M.total_trials;
      if (canFire) {
        state.examined[obj.object_id] = true;
        logGame({ event: "encounter_trigger", object_id: obj.object_id, trial_index: state.cursor });
        return runEncounter(obj).then(function () { return exploreLoop(); });
      }
      var note = null;
      if (obj.role === "encounter" && !state.examined[obj.object_id]
          && state.cursor >= M.total_trials) {
        note = "All trials are complete; nothing further is recorded here.";
      }
      logGame({ event: "object_inspect", object_id: obj.object_id, role: obj.role });
      return showInspect(obj, note).then(function () { return exploreLoop(); });
    });
  }

  function showInspect(obj, note) {
    state.mode = "inspect";
    clearEl(screenEl);
    addDiv(screenEl, "title", obj.label);
    addDiv(screenEl, "inspect-text", obj.inspect_text);
    if (note) { addDiv(screenEl, "hint", note); }
    addDiv(screenEl, "hint", "Press any key to continue");
    return waitKey(null, null);
  }

  function showBriefing(block) {
    state.mode = "briefing";
    clearEl(screenEl);
    addDiv(screenEl, "title", "Section: " + block);
    var text = (NARR.block_briefings && NARR.block_briefings[block]) || "";
    if (text) { addDiv(screenEl, "instructions", text); }
    addDiv(screenEl, "hint", "Press any key to continue");
    return waitKey(null, null);
  }

  // ---------- controlled trial (encounter) ----------
  function collectChoice(respName, deadlineMs) {
    var binding = M.bindings[respName] || {};
    return waitKey(function (key) {
      return Object.prototype.hasOwnProperty.call(binding, key);
    }, deadlineMs).then(function (k) {
      if (k === null) { return null; }
      return binding[k];
    });
  }

  function computeCorrect(trial, respName, value) {
    if (!Object.prototype.hasOwnProperty.call(trial.correct, respName)) { return null; }
    if (value === null) { return false; }
    return value === trial.correct[respName];
  }

  function applyOutcome(correct) {
    if (correct === true) {
      state.correctCount += 1; state.streak += 1; state.correctApplicable += 1;
      if (state.streak > state.bestStreak) { state.bestStreak = state.streak; }
      if (M.gamification.score) {
        state.score += 1;
        if (M.gamification.streak_bonus && state.streak > 1) { state.score += 1; }
      }
    } else if (correct === false) {
      state.streak = 0; state.correctApplicable += 1;
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

  function runEncounter(obj) {
    state.mode = "encounter";
    // pull the NEXT unconsumed trial in index order (monotonic cursor; no skip, no reorder)
    var trial = TRIALS[state.cursor];
    state.cursor += 1;
    var timing = trial.timing || {};
    var onset = 0;
    var p = Promise.resolve();
    if (trial.block !== state.lastBlock) {
      state.lastBlock = trial.block;
      p = p.then(function () {
        logMeasurement({ event: "block_start", block: trial.block });
        return showBriefing(trial.block);
      });
    }
    p = p.then(function () {
      state.mode = "encounter";
      stageEl.classList.add("mode-experiment");
      state.phase = "fixation";
    });
    if (timing.fixation_ms > 0) {
      p = p.then(function () {
        clearEl(screenEl);
        addDiv(screenEl, "trial-banner", "controlled trial — your response is recorded");
        addDiv(screenEl, "fixation", "+");
        return sleep(timing.fixation_ms);
      });
    }
    p = p.then(function () {
      state.phase = "stimulus";
      clearEl(screenEl);
      addDiv(screenEl, "trial-banner", "controlled trial — your response is recorded");
      addDiv(screenEl, "encounter-object", "you are examining: " + obj.label);
      var stim = addDiv(screenEl, "stimulus");
      for (var i = 0; i < trial.lines.length; i++) { addDiv(stim, "stim-line", trial.lines[i]); }
      addDiv(screenEl, "response-prompt", keyHintText());
      logMeasurement({ event: "trial_start", trial_index: trial.index, block: trial.block,
                       conditions: trial.conditions });
      onset = performance.now();
    });
    for (var j = 0; j < M.responses.length; j++) {
      (function (resp) {
        p = p.then(function () {
          state.phase = "response";
          var deadline = (timing.stimulus_ms === null || timing.stimulus_ms === undefined)
            ? null : timing.stimulus_ms;
          return collectChoice(resp.name, deadline);
        }).then(function (value) {
          var correct = computeCorrect(trial, resp.name, value);
          logMeasurement({ event: "response", trial_index: trial.index, block: trial.block,
                           conditions: trial.conditions, response_name: resp.name,
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
        state.phase = "isi";
        clearEl(screenEl);
        return sleep(timing.isi_ms);
      }
    }).then(function () {
      state.doneTrials += 1;
      updateHeader();
    });
    return p;
  }

  // ---------- end ----------
  function selfCheck() {
    var problems = [];
    var starts = [];
    var responses = [];
    for (var i = 0; i < events.length; i++) {
      var ev = events[i];
      if (ev.event === "trial_start") { starts.push(ev.trial_index); }
      if (ev.event === "response") { responses.push(ev.trial_index); }
    }
    if (starts.length !== M.total_trials) {
      problems.push("expected " + M.total_trials + " trial_start events, got " + starts.length);
    }
    for (var s = 0; s < starts.length; s++) {
      if (starts[s] !== s) {
        problems.push("trial_start sequence is not cursor-ordered: " + JSON.stringify(starts));
        break;
      }
    }
    var expectedResponses = [];
    for (var t = 0; t < M.total_trials; t++) {
      for (var r = 0; r < M.responses.length; r++) { expectedResponses.push(t); }
    }
    if (JSON.stringify(responses) !== JSON.stringify(expectedResponses)) {
      problems.push("response events do not cover every trial exactly once, in cursor order");
    }
    return problems;
  }

  function pickEndingBand() {
    var acc = state.correctApplicable > 0 ? state.correctCount / state.correctApplicable : 0;
    var chosen = null;
    for (var i = 0; i < NARR.ending_bands.length; i++) {
      if (NARR.ending_bands[i].min_accuracy <= acc) { chosen = NARR.ending_bands[i]; }
    }
    return chosen;
  }

  function endGame() {
    state.mode = "end";
    state.phase = null;
    stageEl.classList.remove("mode-experiment");
    logMeasurement({ event: "game_end", total_trials: M.total_trials,
                     correct: state.correctCount, applicable: state.correctApplicable });
    clearEl(screenEl);
    addDiv(screenEl, "title", "Session complete");
    addDiv(screenEl, "stat", "Trials: " + M.total_trials);
    var acc = state.correctApplicable > 0
      ? Math.round((state.correctCount / state.correctApplicable) * 100) + "%" : "n/a";
    addDiv(screenEl, "stat", "Correct: " + state.correctCount + "/" + state.correctApplicable + " (" + acc + ")");
    if (M.gamification.score) {
      addDiv(screenEl, "stat", "Score: " + state.score + " (best streak " + state.bestStreak + ")");
    }
    var band = pickEndingBand();
    if (band) { addDiv(screenEl, "ending", band.text); }
    var problems = selfCheck();
    addDiv(screenEl, problems.length === 0 ? "hint" : "warn",
      problems.length === 0
        ? "Self-check OK: " + M.total_trials + " trial(s) consumed in cursor order, all responses present"
        : "Self-check FAILED: " + problems.join("; "));
    addDiv(screenEl, "disclaimer",
      "Timing in this browser prototype is approximate and not suitable for formal data collection. " +
      "Nothing is persisted: export the event log below to keep your data.");
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

  function showIntro() {
    state.mode = "intro";
    clearEl(screenEl);
    addDiv(screenEl, "title", M.title);
    if (NARR.intro) { addDiv(screenEl, "instructions", NARR.intro); }
    if (M.instructions) { addDiv(screenEl, "instructions", M.instructions); }
    addDiv(screenEl, "hint", keyHintText());
    addDiv(screenEl, "hint", "Press any key to begin");
    return waitKey(null, null);
  }

  function main() {
    updateHeader();
    if (!integrity.ok) { showIntegrityError(); return; }
    logGame({ event: "game_start", game_name: M.game_name, mode: M.mode,
              total_trials: M.total_trials });
    showIntro().then(function () { return exploreLoop(); })
      .catch(function (err) {
        clearEl(screenEl);
        addDiv(screenEl, "error", "Engine error: " + String(err));
      });
  }
  main();

  // debug handle: a console affordance in the browser and the seam for
  // runtime tests executed under node with a DOM stub (M2-D Phase 1).
  if (typeof globalThis !== "undefined") {
    globalThis.__CA_DEBUG__ = { events: events, snapshot: snapshot };
  }
})();
"""


# ---------------------------------------------------------------------------
# HTML template (static skeleton; same placeholder/split-interleaving discipline)
# ---------------------------------------------------------------------------

_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root { --fg:#222; --bg:#f6f6f4; --muted:#777; --ok:#2e7d32; --bad:#c62828; --accent:#5b8def; }
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
#progress-inner { height:100%; width:0%; background:var(--accent); border-radius:3px; }
#stage { min-height:300px; padding:4px 0; }
#stage.mode-experiment { display:flex; align-items:center; justify-content:center; text-align:center;
  border:2px solid var(--accent); border-radius:10px; padding:22px 10px;
  background:rgba(91,141,239,0.06); }
body.theme-dark #stage.mode-experiment { background:rgba(91,141,239,0.10); }
#screen { width:100%; }
.room-title { font-size:1.35rem; font-weight:700; margin-bottom:0.3rem; }
.room-desc { color:var(--muted); margin-bottom:0.8rem; }
.room-section { font-size:0.75rem; text-transform:uppercase; letter-spacing:0.09em;
  color:var(--muted); margin-top:0.9rem; }
.room-item { margin:0.25rem 0; font-size:1.05rem; }
.room-conclude { margin-top:1.1rem; font-weight:600; color:var(--accent); }
.inspect-text { font-size:1.15rem; margin:0.6rem 0; font-style:italic; }
.trial-banner { font-size:0.72rem; text-transform:uppercase; letter-spacing:0.13em;
  color:var(--accent); margin-bottom:0.9rem; font-weight:700; }
.encounter-object { color:var(--muted); font-size:0.95rem; margin-bottom:0.7rem; }
.stim-line { font-size:1.4rem; margin:0.35rem 0; font-weight:600; }
.fixation { font-size:3rem; }
.response-prompt { margin-top:1.2rem; color:var(--muted); font-size:0.95rem; }
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
.ending { margin-top:1rem; font-style:italic; font-size:1.1rem; }
.hint { color:var(--muted); font-size:0.95rem; margin:0.3rem 0; }
.warn { color:#b8860b; font-size:0.9rem; }
footer { margin-top:24px; color:var(--muted); font-size:0.75rem; text-align:center; }
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
  <footer>Prototype build: browser timing is approximate; not suitable for formal data collection. Nothing is persisted — export the event log at the end of the session.</footer>
</div>
<script>
__DATA__
</script>
<script>
""" + _ENGINE_JS + """</script>
</body>
</html>
"""
