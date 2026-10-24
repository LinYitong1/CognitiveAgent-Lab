"""Expressiveness Stage 1 closeout: phased trials + withhold semantics, both engines.

Covers the U-2 interaction left NEEDS-TEST in the Stage 1 report: a phased
spec (cue phase, then a response-window probe phase with a deadline) whose
response declares withhold_option. Verified under node with DOM stubs on BOTH
engines:

- response-window expiry with no keypress on a withhold-correct trial logs
  value: null, correct: true, withheld: true (correct rejection);
- a keypress OUTSIDE the response window (during the closed cue phase) is
  never recorded (exactly one response event per trial);
- the four Go/No-Go cells hold with phases, and the engine bytes carry BOTH
  the phased addon and the gated withhold patch (they compose).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import cast

import pytest

from src.experiment.canonical import canonical_json
from src.experiment.export import build_bundle
from src.experiment.game_render import build_run_plan, render_game_html
from src.experiment.game_schemas import GameSpec, validate_game
from src.experiment.schemas import ExperimentSpec
from src.experiment.validation import validate_spec

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXED_GENERATED_AT = "2000-01-01T00:00:00Z"
SANDBOX_DIR = REPO_ROOT / "data" / ".test-sandbox" / "withhold-phased-runtime"

_NODE_CANDIDATES = [
    shutil.which("node"),
    str(Path.home() / ".workbuddy/binaries/node/versions/22.22.2-6/bin/node"),
    "/opt/homebrew/bin/node",
]


def _node_bin() -> str | None:
    for cand in _NODE_CANDIDATES:
        if cand and Path(cand).is_file():
            return cand
    return None


def _phased_gonogo_spec() -> dict[str, object]:
    """Phased go/no-go: cue phase (closed window), probe phase (response
    window with a 300 ms deadline); withholding is correct on no_go trials."""
    return {
        "schema_version": 2,
        "name": "phased-gonogo",
        "version": "0.1.0",
        "seed": 88,
        "factors": [{"name": "trial_type", "levels": [{"name": "go"}, {"name": "no_go"}]}],
        "blocks": [{"name": "main", "trial_count": 4, "shuffle_within": False}],
        "constraints": {"balance": True},
        "responses": [
            {
                "name": "press",
                "kind": "choice",
                "options": ["go"],
                "withhold_option": "withhold",
                "correct_rule": {
                    "op": "eq",
                    "left": {"factor": "trial_type"},
                    "right": {"literal": "no_go"},
                    "true_option": "withhold",
                    "false_option": "go",
                },
            }
        ],
        "timing": {"fixation_ms": 0, "stimulus_ms": 500, "isi_ms": 40},
        "stimulus_spec": {
            "pools": {},
            "phases": [
                {
                    "name": "cue",
                    "lines": ["Get ready"],
                    "duration_ms": 120,
                    "advance": "auto",
                    "response_window": False,
                },
                {
                    "name": "probe",
                    "lines": ["Signal: {trial_type}"],
                    "duration_ms": 300,
                    "advance": "auto",
                    "response_window": True,
                },
            ],
        },
    }


def _bundle() -> dict[str, object]:
    return build_bundle(
        ExperimentSpec.model_validate(_phased_gonogo_spec()), generated_at=FIXED_GENERATED_AT
    )


def _classic_gamespec(bundle: dict[str, object]) -> dict[str, object]:
    repro = cast(dict[str, object], bundle["reproducibility"])
    spec = cast(dict[str, object], bundle["spec"])
    return {
        "schema_version": 1,
        "game": {"name": "phased-gonogo", "version": "0.1.0"},
        "experiment_ref": {
            "name": spec["name"],
            "version": spec["version"],
            "seed": spec["seed"],
            "config_fingerprint": repro["config_fingerprint"],
            "trials_fingerprint": repro["trials_fingerprint"],
            "bundle_sha256": bundle["bundle_sha256"],
        },
        "scene": {"title": "t", "instructions": "i"},
        "input": {
            "modalities": ["keyboard"],
            "bindings": [{"response_name": "press", "keys": {"g": "go"}}],
        },
        "feedback": {"on_response": "outcome-text", "duration_ms": 30},
        "flow": {"ready_screen": True, "block_breaks": False, "end_screen": "summary"},
        "gamification": {"score": False, "progress_bar": True, "streak_bonus": False},
    }


def _explore_gamespec(bundle: dict[str, object]) -> dict[str, object]:
    gamespec = _classic_gamespec(bundle)
    gamespec["schema_version"] = 2
    keys = {"g": "go"}
    gamespec["world"] = {
        "start_room": "hall",
        "rooms": {
            "hall": {
                "title": "Hall",
                "description": "Four marked crates.",
                "exits": {},
                "objects": [
                    {
                        "object_id": f"crate-{i}",
                        "label": f"crate {i}",
                        "inspect_text": "A marked crate.",
                        "role": "encounter",
                    }
                    for i in range(1, 5)
                ],
            }
        },
    }
    gamespec["narrative"] = {
        "intro": "Open every marked crate.",
        "block_briefings": {"main": "Controlled section."},
        "ending_bands": [{"min_accuracy": 0.0, "text": "Done."}],
    }
    gamespec["mechanics"] = {
        "layout": "explore-and-encounter",
        "inspect_objects": True,
        "trial_trigger": "explore-encounter",
    }
    gamespec["mapping"] = {
        "trial_trigger": "explore-encounter",
        "encounter_objects": [f"crate-{i}" for i in range(1, 5)],
        "response_bindings": [{"response_name": "press", "keys": keys}],
        "creative_freedom": ["theme", "room_labels", "object_labels", "narrative_text", "feedback_style"],
        "controlled_invariants": ["trial_order", "conditions", "stimulus_content", "correct_answers", "timing"],
    }
    return gamespec


# ---------------------------------------------------------------------------
# Static: composition of the phased addon and the withhold patch
# ---------------------------------------------------------------------------


def test_phased_withhold_spec_valid() -> None:
    result = validate_spec(_phased_gonogo_spec())
    assert result.valid, [(e.error_code, e.path, e.message) for e in result.errors]


def test_phased_withhold_bundle_reproducible_and_plan_composition() -> None:
    bundle = _bundle()
    assert canonical_json(bundle) == canonical_json(_bundle())
    plan = build_run_plan(bundle, GameSpec.model_validate(_classic_gamespec(bundle)))
    responses = cast(list[dict[str, object]], cast(dict[str, object], plan["meta"])["responses"])
    assert responses[0]["withhold_option"] == "withhold"
    trial_steps = [
        cast(dict[str, object], s)
        for s in cast(list[object], plan["steps"])
        if cast(dict[str, object], s).get("type") == "trial"
    ]
    assert all("phases" in step for step in trial_steps)
    # the rendered classic HTML carries BOTH patches (disjoint anchor regions)
    html = render_game_html(bundle, GameSpec.model_validate(_classic_gamespec(bundle)))
    assert "playPhases" in html and "runPhasedTrial" in html
    assert "withhold_option !== undefined" in html and "ev.withheld = true" in html


# ---------------------------------------------------------------------------
# Runtime (node)
# ---------------------------------------------------------------------------


_CLASSIC_HARNESS_JS = """\
"use strict";
var fs = require("fs");
var vm = require("vm");
var html = fs.readFileSync(process.argv[2], "utf8");
var driverPath = process.argv[3];
var parts = html.split("<script>");
if (parts.length !== 3) { console.error("unexpected script count: " + parts.length); process.exit(2); }
var dataJs = parts[1].split("</script>")[0];
var engineJs = parts[2].split("</script>")[0];

function makeEl(tag) {
  var el = {
    tagName: String(tag || "div").toUpperCase(), children: [], style: {}, _cls: {}, attrs: {},
    handlers: {}, className: "", textContent: "", value: "", readOnly: false, type: "", classList: null,
    appendChild: function (c) { el.children.push(c); return c; },
    removeChild: function (c) { var i = el.children.indexOf(c); if (i >= 0) { el.children.splice(i, 1); } return c; },
    addEventListener: function (name, fn) { (el.handlers[name] = el.handlers[name] || []).push(fn); },
    setAttribute: function (k, v) {
      el.attrs[k] = String(v);
      if (k === "id") { elementsById[v] = el; }
      if (k === "class") { el._cls = {}; String(v).split(/\\s+/).forEach(function (c) { if (c) { el._cls[c] = true; } }); }
    },
    getAttribute: function (k) { return el.attrs[k]; },
    focus: function () {}, click: function () {}
  };
  el.classList = {
    add: function (c) { el._cls[c] = true; },
    remove: function (c) { delete el._cls[c]; },
    contains: function (c) { return !!el._cls[c]; }
  };
  Object.defineProperty(el, "firstChild", { get: function () { return el.children[0] || null; } });
  Object.defineProperty(el, "id", {
    get: function () { return el.attrs.id || ""; },
    set: function (v) { el.attrs.id = String(v); elementsById[String(v)] = el; }
  });
  return el;
}
var keydownHandlers = [];
var elementsById = {};
var elements = {};
globalThis.document = {
  getElementById: function (id) {
    if (elementsById[id]) { return elementsById[id]; }
    if (!elements[id]) { elements[id] = makeEl("div"); elementsById[id] = elements[id]; }
    return elements[id];
  },
  createElement: function (tag) { return makeEl(tag); },
  addEventListener: function (name, fn) { if (name === "keydown") { keydownHandlers.push(fn); } },
  activeElement: null,
  body: makeEl("body")
};
globalThis.performance = { now: function () { return Date.now(); } };

vm.runInThisContext(dataJs, { filename: "data.js" });
vm.runInThisContext(engineJs, { filename: "engine.js" });

function press(key) {
  keydownHandlers.forEach(function (fn) { fn({ key: key, preventDefault: function () {} }); });
}
function textOf(id) {
  var el = globalThis.document.getElementById(id);
  function walk(n) {
    var t = String(n.textContent || "");
    for (var i = 0; i < n.children.length; i++) { t += " " + walk(n.children[i]); }
    return t;
  }
  return walk(el);
}
function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
async function waitFor(fn, timeoutMs) {
  var deadline = Date.now() + (timeoutMs || 20000);
  while (Date.now() < deadline) {
    if (fn()) { return true; }
    await sleep(10);
  }
  throw new Error("waitFor timeout: " + fn.toString());
}
globalThis.press = press;
globalThis.waitFor = waitFor;
globalThis.textOf = textOf;
globalThis.sleep = sleep;
globalThis.elById = function (id) { return globalThis.document.getElementById(id); };

vm.runInThisContext(fs.readFileSync(driverPath, "utf8"), { filename: "driver.js" });
globalThis.__DONE__.then(function (r) {
  console.log("__RESULT__" + JSON.stringify(r));
  process.exit(0);
}, function (err) {
  console.error("driver failed: " + ((err && err.stack) || err));
  process.exit(1);
});
"""


def _assert_four_cells(responses: list[dict[str, object]]) -> None:
    """Four cells from the event log alone + no out-of-window keypress recorded."""
    assert len(responses) == 4
    by_cell: dict[tuple[object, object, object], int] = {}
    per_trial: dict[int, int] = {}
    for ev in responses:
        conditions = cast(dict[str, object], ev["conditions"])
        cell = (conditions["trial_type"], ev["value"], ev["correct"])
        by_cell[cell] = by_cell.get(cell, 0) + 1
        idx = int(cast(int, ev["trial_index"]))
        per_trial[idx] = per_trial.get(idx, 0) + 1
    assert by_cell.get(("go", "go", True)) == 1, by_cell      # hit
    assert by_cell.get(("go", None, False)) == 1, by_cell     # omission (window expiry)
    assert by_cell.get(("no_go", "go", False)) == 1, by_cell  # commission
    assert by_cell.get(("no_go", None, True)) == 1, by_cell   # correct rejection
    # the cue-phase decoy keypress was outside the window: never recorded
    assert all(count == 1 for count in per_trial.values()), per_trial
    for ev in responses:
        if ev["value"] is None:
            assert ev.get("withheld") is True, ev
        else:
            assert "withheld" not in ev, ev
        assert isinstance(ev.get("rt_ms"), int) and cast(int, ev["rt_ms"]) >= 0, ev


@pytest.mark.skipif(_node_bin() is None, reason="node runtime not available")
def test_runtime_classic_phased_withhold() -> None:
    """Classic phased engine: cue phase decoy keypress ignored; window expiry
    on a withhold-correct trial scores correct with value null + withheld."""
    node = _node_bin()
    assert node is not None
    SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
    bundle = _bundle()
    html = render_game_html(bundle, GameSpec.model_validate(_classic_gamespec(bundle)))
    html_path = SANDBOX_DIR / "phased-gonogo-classic.html"
    html_path.write_text(html, encoding="utf-8")
    harness_path = SANDBOX_DIR / "classic-harness.js"
    if not harness_path.exists() or harness_path.read_text(encoding="utf-8") != _CLASSIC_HARNESS_JS:
        harness_path.write_text(_CLASSIC_HARNESS_JS, encoding="utf-8")
    # deterministic order: trials 0,1 = go; 2,3 = no_go. press / withhold /
    # press(commission) / withhold(correct rejection). Edge-driven: one decoy
    # keypress per cue phase (outside the window), one decision per probe.
    driver = (
        "globalThis.__DONE__ = (async function () {\n"
        "  await waitFor(function () { return textOf('screen').indexOf('Press any key') >= 0; });\n"
        "  press(' ');\n"
        "  await waitFor(function () { return textOf('screen').indexOf('Press any key') < 0; });\n"
        "  var plan = [true, false, true, false];\n"
        "  var trial = -1;\n"
        "  var sawCue = false, sawProbe = false;\n"
        "  var ticks = 0;\n"
        "  while (ticks < 20000) {\n"
        "    ticks += 1;\n"
        "    if (elById('eventlog') && elById('eventlog').value) { break; }\n"
        "    var txt = textOf('screen');\n"
        "    var inCue = txt.indexOf('Get ready') >= 0;\n"
        "    var inProbe = txt.indexOf('Signal:') >= 0;\n"
        "    if (!inCue && !inProbe) {\n"
        "      sawCue = false; sawProbe = false;\n"  # feedback/isi: re-arm edge detection
        "    } else if (inCue && !sawCue) {\n"
        "      sawCue = true; sawProbe = false;\n"
        "      trial += 1;\n"
        "      press('g');\n"  # decoy: OUTSIDE the response window (cue phase)
        "    } else if (inProbe && !sawProbe) {\n"
        "      sawProbe = true;\n"
        "      if (plan[trial]) { press('g'); }\n"
        "    }\n"
        "    await sleep(5);\n"
        "  }\n"
        "  await waitFor(function () { return elById('eventlog') && elById('eventlog').value; }, 30000);\n"
        "  var events = JSON.parse(elById('eventlog').value);\n"
        "  return { responses: events.filter(function (e) { return e.event === 'response'; }) };\n"
        "})();\n"
    )
    driver_path = SANDBOX_DIR / "driver-phased-gonogo-classic.js"
    driver_path.write_text(driver, encoding="utf-8")
    proc = subprocess.run(
        [node, str(harness_path), str(html_path), str(driver_path)],
        capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, proc.stderr
    result_line = next(ln for ln in proc.stdout.splitlines() if ln.startswith("__RESULT__"))
    _assert_four_cells(
        cast(list[dict[str, object]], json.loads(result_line[len("__RESULT__"):])["responses"])
    )


@pytest.mark.skipif(_node_bin() is None, reason="node runtime not available")
def test_runtime_explore_phased_withhold() -> None:
    """Explore phased engine: same four cells; the cue-phase decoy keypress is
    ignored; one measurement response per encounter."""
    node = _node_bin()
    assert node is not None
    from tests.unit.experiment.test_explore_runtime import _HARNESS_JS as EXPLORE_HARNESS

    SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
    bundle = _bundle()
    gamespec = _explore_gamespec(bundle)
    result_validated = validate_game(gamespec, bundle)
    assert result_validated.valid, result_validated.errors
    html = render_game_html(bundle, result_validated.game_spec)
    html_path = SANDBOX_DIR / "phased-gonogo-explore.html"
    html_path.write_text(html, encoding="utf-8")
    harness_path = SANDBOX_DIR / "explore-harness.js"
    if not harness_path.exists() or harness_path.read_text(encoding="utf-8") != EXPLORE_HARNESS:
        harness_path.write_text(EXPLORE_HARNESS, encoding="utf-8")
    driver = (
        "globalThis.__DONE__ = (async function () {\n"
        "  var D = globalThis.__CA_DEBUG__;\n"
        "  await waitFor(function (s) { return s.mode === 'intro'; });\n"
        "  press(' ');\n"
        "  await waitFor(function (s) { return s.mode === 'explore' && s.room === 'hall'; });\n"
        "  var plan = [true, false, true, false];\n"
        "  var sawCue = false, sawProbe = false;\n"
        "  var ticks = 0;\n"
        "  while (ticks < 30000) {\n"
        "    ticks += 1;\n"
        "    var s = D.snapshot();\n"
        "    if (s.mode === 'encounter') {\n"
        "      var txt = textOf('screen');\n"
        "      if (txt.indexOf('Get ready') >= 0 && !sawCue) {\n"
        "        sawCue = true; sawProbe = false;\n"
        "        press('g');\n"  # decoy: OUTSIDE the response window (cue phase)
        "      } else if (txt.indexOf('Signal:') >= 0 && !sawProbe) {\n"
        "        sawProbe = true;\n"
        "        if (plan[s.cursor - 1]) { press('g'); }\n"
        "      }\n"
        "    } else {\n"
        "      sawCue = false; sawProbe = false;\n"
        "      if (s.mode === 'explore') {\n"
        "        if (s.cursor >= 4) { press('x'); }\n"
        "        else { press(String(1 + (s.cursor % 4))); }\n"
        "      } else if (s.mode === 'briefing' || s.mode === 'inspect') { press(' '); }\n"
        "      else if (s.mode === 'end') { break; }\n"
        "    }\n"
        "    await sleep(5);\n"
        "  }\n"
        "  await waitFor(function (s) { return s.mode === 'end'; }, 30000);\n"
        "  var evs = D.events;\n"
        "  var meas = evs.filter(function (e) { return e.channel === 'measurement'; });\n"
        "  var responses = meas.filter(function (e) { return e.event === 'response'; });\n"
        "  return { responses: responses };\n"
        "})();\n"
    )
    driver_path = SANDBOX_DIR / "driver-phased-gonogo-explore.js"
    driver_path.write_text(driver, encoding="utf-8")
    proc = subprocess.run(
        [node, str(harness_path), str(html_path), str(driver_path)],
        capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, proc.stderr
    result_line = next(ln for ln in proc.stdout.splitlines() if ln.startswith("__RESULT__"))
    result = json.loads(result_line[len("__RESULT__"):])["result"]
    _assert_four_cells(cast(list[dict[str, object]], result["responses"]))
