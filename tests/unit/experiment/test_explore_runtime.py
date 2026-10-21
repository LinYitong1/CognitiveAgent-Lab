"""M2-D Phase 1 runtime tests: drive the shipped explore engine under node with a DOM stub.

What these tests DO cover (real runtime behavior, extracted from the rendered HTML):
room navigation, flavour inspection without trial consumption, encounter activation,
verbatim stimulus rendering, response binding resolution, the monotonic trial cursor,
return-to-exploration, session conclusion with the runtime self-check.

Browser-automation limitation (recorded in docs/m2/M2D_PHASE1_REPORT.md): node executes
the engine's JS against a minimal DOM stub — layout, styling, real keyboard events,
focus handling and setTimeout fidelity are NOT verified here. Visual verification is a
manual step (the report's checklist). Tests are skipped when no node runtime exists.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import cast

import pytest

from src.experiment.export import build_bundle
from src.experiment.game_render import render_game_html
from src.experiment.game_schemas import validate_game
from src.experiment.schemas import ExperimentSpec

PROJECT_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures" / "manor-case"
SANDBOX_DIR = PROJECT_ROOT / "data" / ".test-sandbox" / "explore-runtime"

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


# ---------------------------------------------------------------------------
# Node harness: DOM stub + script extraction + driver protocol
# ---------------------------------------------------------------------------

_HARNESS_JS = """\
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
    tagName: String(tag || "div").toUpperCase(),
    children: [], style: {}, _cls: {},
    className: "", textContent: "", value: "", readOnly: false, type: "",
    classList: null,
    appendChild: function (c) { el.children.push(c); return c; },
    removeChild: function (c) { var i = el.children.indexOf(c); if (i >= 0) { el.children.splice(i, 1); } return c; },
    addEventListener: function () {}, focus: function () {}, click: function () {}
  };
  el.classList = {
    add: function (c) { el._cls[c] = true; },
    remove: function (c) { delete el._cls[c]; },
    contains: function (c) { return !!el._cls[c]; }
  };
  Object.defineProperty(el, "firstChild", { get: function () { return el.children[0] || null; } });
  return el;
}
var keydownHandlers = [];
var elements = {};
globalThis.document = {
  getElementById: function (id) { if (!elements[id]) { elements[id] = makeEl("div"); } return elements[id]; },
  createElement: function (tag) { return makeEl(tag); },
  addEventListener: function (name, fn) { if (name === "keydown") { keydownHandlers.push(fn); } },
  activeElement: null,
  body: makeEl("body")
};

vm.runInThisContext(dataJs, { filename: "data.js" });
vm.runInThisContext(engineJs, { filename: "engine.js" });

var D = globalThis.__CA_DEBUG__;
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
  var deadline = Date.now() + (timeoutMs || 10000);
  while (Date.now() < deadline) {
    var s = D.snapshot();
    if (fn(s)) { return s; }
    await sleep(10);
  }
  throw new Error("waitFor timeout: " + fn.toString());
}
globalThis.press = press;
globalThis.waitFor = waitFor;
globalThis.textOf = textOf;
globalThis.sleep = sleep;

vm.runInThisContext(fs.readFileSync(driverPath, "utf8"), { filename: "driver.js" });
globalThis.__DONE__.then(function (r) {
  console.log("__RESULT__" + JSON.stringify({
    result: r, events: D.events, snapshot: D.snapshot()
  }));
  process.exit(0);
}, function (err) {
  console.error("driver failed: " + ((err && err.stack) || err));
  process.exit(1);
});
"""


def _run_driver(html_path: Path, driver_code: str) -> dict[str, object]:
    """Run the engine from the rendered HTML under node; return {result, events, snapshot}."""
    node = _node_bin()
    assert node is not None
    SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
    harness_path = SANDBOX_DIR / "harness.js"
    harness_path.write_text(_HARNESS_JS, encoding="utf-8")
    driver_path = SANDBOX_DIR / "driver.js"
    driver_path.write_text(driver_code, encoding="utf-8")
    proc = subprocess.run(
        [node, str(harness_path), str(html_path), str(driver_path)],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    result_lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("__RESULT__")]
    assert result_lines, f"no result marker in stdout: {proc.stdout[-500:]}"
    return cast(dict[str, object], json.loads(result_lines[-1][len("__RESULT__") :]))


def _events(report: dict[str, object]) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], report["events"])


def _of_channel(events: list[dict[str, object]], channel: str, name: str) -> list[dict[str, object]]:
    return [
        e
        for e in events
        if e.get("channel") == channel and e.get("event") == name
    ]


# ---------------------------------------------------------------------------
# Fixtures: the rendered Manor Case HTML
# ---------------------------------------------------------------------------

def _manor_html() -> tuple[str, dict[str, object]]:
    bundle = json.loads((FIXTURE_DIR / "bundle.json").read_text(encoding="utf-8"))
    gamespec = json.loads((FIXTURE_DIR / "gamespec.json").read_text(encoding="utf-8"))
    result = validate_game(gamespec, bundle)
    assert result.valid is True and result.game_spec is not None
    return render_game_html(bundle, result.game_spec), bundle


def _write_html(name: str, html: str) -> Path:
    SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
    path = SANDBOX_DIR / name
    path.write_text(html, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Manor Case: navigation, flavour, encounter, cursor
# ---------------------------------------------------------------------------

@pytest.mark.skipif(_node_bin() is None, reason="node runtime not available")
def test_runtime_navigation_between_rooms() -> None:
    """The player moves hall -> study -> hall -> library; every move logs room_enter.

    Exit key order is deterministic: the embedded plan JSON sorts keys, so a room's
    exits are listed alphabetically (hall: library=4, study=5; study: hall=7, parlour=8).
    """
    html, _ = _manor_html()
    path = _write_html("manor.html", html)
    driver = (
        "globalThis.__DONE__ = (async function () {\n"
        "  await waitFor(function (s) { return s.mode === 'intro'; });\n"
        "  press(' ');\n"
        "  await waitFor(function (s) { return s.mode === 'explore' && s.room === 'hall'; });\n"
        "  press('5');  // exit: study (hall exits sorted: library=4, study=5)\n"
        "  await waitFor(function (s) { return s.room === 'study'; });\n"
        "  press('7');  // exit: back to hall (study: 6 objects keys 1-6, exits hall=7)\n"
        "  await waitFor(function (s) { return s.room === 'hall'; });\n"
        "  press('4');  // exit: library\n"
        "  await waitFor(function (s) { return s.room === 'library'; });\n"
        "  return true;\n"
        "})();\n"
    )
    report = _run_driver(path, driver)
    snapshot = cast(dict[str, object], report["snapshot"])
    assert snapshot["room"] == "library"
    moves = _of_channel(_events(report), "game", "room_enter")
    assert [m["room"] for m in moves] == ["study", "hall", "library"]
    # pure navigation never starts a trial
    assert _of_channel(_events(report), "measurement", "trial_start") == []
    assert snapshot["cursor"] == 0


@pytest.mark.skipif(_node_bin() is None, reason="node runtime not available")
def test_runtime_flavour_inspect_consumes_nothing() -> None:
    """Inspecting a flavour object shows its text and consumes no trial."""
    html, _ = _manor_html()
    path = _write_html("manor.html", html)
    driver = (
        "globalThis.__DONE__ = (async function () {\n"
        "  await waitFor(function (s) { return s.mode === 'intro'; });\n"
        "  press(' ');\n"
        "  await waitFor(function (s) { return s.mode === 'explore'; });\n"
        "  press('1');  // dusty clock (flavour)\n"
        "  await waitFor(function (s) { return s.mode === 'inspect'; });\n"
        "  var seen = textOf('screen');\n"
        "  press(' ');\n"
        "  await waitFor(function (s) { return s.mode === 'explore'; });\n"
        "  return { seen: seen };\n"
        "})();\n"
    )
    report = _run_driver(path, driver)
    result = cast(dict[str, object], report["result"])
    assert "It stopped at 3:14." in cast(str, result["seen"])  # inspect_text displayed
    inspects = _of_channel(_events(report), "game", "object_inspect")
    assert len(inspects) == 1
    assert inspects[0]["object_id"] == "dusty-clock"
    assert inspects[0]["role"] == "flavour"
    assert _of_channel(_events(report), "measurement", "trial_start") == []
    snapshot = cast(dict[str, object], report["snapshot"])
    assert snapshot["cursor"] == 0 and snapshot["done_trials"] == 0


@pytest.mark.skipif(_node_bin() is None, reason="node runtime not available")
def test_runtime_encounter_verbatim_stimulus_binding_and_return() -> None:
    """An encounter renders trial.stimulus.lines verbatim, resolves the pressed key
    through the mapping binding, computes correctness from the bundle, and returns
    to exploration in the same room."""
    html, bundle = _manor_html()
    path = _write_html("manor.html", html)
    driver = (
        "globalThis.__DONE__ = (async function () {\n"
        "  await waitFor(function (s) { return s.mode === 'intro'; });\n"
        "  press(' ');\n"
        "  await waitFor(function (s) { return s.mode === 'explore'; });\n"
        "  press('2');  // calling card (encounter, hall)\n"
        "  await waitFor(function (s) { return s.mode === 'briefing'; });\n"
        "  press(' ');\n"
        "  await waitFor(function (s) { return s.mode === 'encounter' && s.phase === 'response'; });\n"
        "  var lines = PLAN.trials[0].lines;\n"
        "  var text = textOf('screen');\n"
        "  var missing = [];\n"
        "  for (var i = 0; i < lines.length; i++) {\n"
        "    if (text.indexOf(lines[i]) < 0) { missing.push(lines[i]); }\n"
        "  }\n"
        "  var stageMode = globalThis.document.getElementById('stage')\n"
        "    .classList.contains('mode-experiment');\n"
        "  press('b');\n"
        "  await waitFor(function (s) { return s.mode === 'explore'; });\n"
        "  return { missing: missing, stageMode: stageMode };\n"
        "})();\n"
    )
    report = _run_driver(path, driver)
    result = cast(dict[str, object], report["result"])
    assert result["missing"] == []  # every stimulus line rendered verbatim
    assert result["stageMode"] is True  # exploration/experiment visual distinction active

    events = _events(report)
    triggers = _of_channel(events, "game", "encounter_trigger")
    assert triggers == [
        {"event": "encounter_trigger", "object_id": "calling-card", "trial_index": 0,
         "channel": "game", "t_epoch_ms": triggers[0]["t_epoch_ms"] if triggers else 0}
    ] or (
        len(triggers) == 1
        and triggers[0]["object_id"] == "calling-card"
        and triggers[0]["trial_index"] == 0
    )
    starts = _of_channel(events, "measurement", "trial_start")
    assert len(starts) == 1 and starts[0]["trial_index"] == 0

    bundle_trial = cast(dict[str, object], cast(list[object], bundle["trials"])[0])
    assert starts[0]["conditions"] == bundle_trial["factors"]
    assert starts[0]["block"] == bundle_trial["block"]

    responses = _of_channel(events, "measurement", "response")
    assert len(responses) == 1
    resp = responses[0]
    assert resp["value"] == "b"  # key 'b' resolved through the mapping binding
    assert resp["response_name"] == "accuse"
    assert resp["correct"] is (cast(dict[str, object], bundle_trial["factors"])["true_suspect"] == "b")
    assert cast(int, resp["rt_ms"]) >= 0

    snapshot = cast(dict[str, object], report["snapshot"])
    assert snapshot["mode"] == "explore"  # returned to exploration...
    assert snapshot["room"] == "hall"  # ...in the same room
    assert snapshot["cursor"] == 1 and snapshot["done_trials"] == 1


@pytest.mark.skipif(_node_bin() is None, reason="node runtime not available")
def test_runtime_monotonic_cursor_regardless_of_object_order() -> None:
    """Trials are consumed strictly in bundle index order no matter which encounter
    object (or room) the player examines; a re-examined object never re-fires."""
    html, _ = _manor_html()
    path = _write_html("manor.html", html)

    async_drive = (
        "  async function encounter(key, answer) {\n"
        "    press(key);\n"
        "    var s = await waitFor(function (s) { return s.mode === 'encounter' || s.mode === 'briefing'; });\n"
        "    if (s.mode === 'briefing') {\n"
        "      press(' ');\n"
        "    }\n"
        "    // always wait for the response phase: keys pressed during fixation are dropped\n"
        "    await waitFor(function (s) { return s.mode === 'encounter' && s.phase === 'response'; });\n"
        "    press(answer);\n"
        "    await waitFor(function (s) { return s.mode === 'explore'; });\n"
        "  }\n"
    )
    driver = (
        "globalThis.__DONE__ = (async function () {\n"
        "  await waitFor(function (s) { return s.mode === 'intro'; });\n"
        "  press(' ');\n"
        "  await waitFor(function (s) { return s.mode === 'explore'; });\n"
        + async_drive +
        "  await encounter('2', 'b');  // hall: calling-card      -> trial 0\n"
        "  await encounter('3', 'a');  // hall: torn-invitation   -> trial 1\n"
        "  press('5');                 // hall -> study (exits sorted: library=4, study=5)\n"
        "  await waitFor(function (s) { return s.room === 'study' && s.mode === 'explore'; });\n"
        "  await encounter('1', 'c');  // study: desk-ledger      -> trial 2\n"
        "  await encounter('2', 'b');  // study: hearth-ash       -> trial 3\n"
        "  press('7');                 // study -> hall\n"
        "  await waitFor(function (s) { return s.room === 'hall' && s.mode === 'explore'; });\n"
        "  press('2');                 // calling-card AGAIN (already fired)\n"
        "  await waitFor(function (s) { return s.mode === 'inspect'; });\n"
        "  press(' ');\n"
        "  await waitFor(function (s) { return s.mode === 'explore'; });\n"
        "  return true;\n"
        "})();\n"
    )
    report = _run_driver(path, driver)
    events = _events(report)
    starts = _of_channel(events, "measurement", "trial_start")
    assert [s["trial_index"] for s in starts] == [0, 1, 2, 3]  # bundle order, no skip/reorder
    triggers = _of_channel(events, "game", "encounter_trigger")
    assert [t["trial_index"] for t in triggers] == [0, 1, 2, 3]
    # the re-examined object is an inspect, not a new trial
    inspects = _of_channel(events, "game", "object_inspect")
    assert [i["object_id"] for i in inspects] == ["calling-card"]
    assert cast(dict[str, object], inspects[0])["role"] == "encounter"
    snapshot = cast(dict[str, object], report["snapshot"])
    assert snapshot["cursor"] == 4 and snapshot["done_trials"] == 4


# ---------------------------------------------------------------------------
# Synthetic two-room game: genericity + full session to conclusion
# ---------------------------------------------------------------------------

_PROBE_SPEC: dict[str, object] = {
    "schema_version": 2,
    "name": "probe-game",
    "version": "0.1.0",
    "seed": 42,
    "factors": [{"name": "f", "levels": [{"name": "x"}, {"name": "y"}]}],
    "blocks": [{"name": "main", "trial_count": 2}],
    "constraints": {"balance": True},
    "responses": [
        {"name": "pick", "kind": "choice", "options": ["x", "y"], "correct_from": "f"}
    ],
    "timing": {"fixation_ms": 0, "stimulus_ms": None, "isi_ms": 0},
    "stimulus_spec": {
        "factors": {
            "f": {
                "levels": {
                    "x": [["The marker points to side {f}."]],
                    "y": [["The marker points to side {f}."]],
                }
            }
        },
        "pools": {},
    },
}


def _probe_gamespec(bundle: dict[str, object]) -> dict[str, object]:
    spec_part = cast(dict[str, object], bundle["spec"])
    repro = cast(dict[str, object], bundle["reproducibility"])
    return {
        "schema_version": 2,
        "game": {"name": "probe-game", "version": "0.1.0"},
        "experiment_ref": {
            "name": spec_part["name"],
            "version": spec_part["version"],
            "seed": spec_part["seed"],
            "config_fingerprint": repro["config_fingerprint"],
            "trials_fingerprint": repro["trials_fingerprint"],
            "bundle_sha256": bundle["bundle_sha256"],
        },
        "scene": {"title": "Probe Game", "instructions": "Two rooms, two encounters."},
        "input": {
            "modalities": ["keyboard"],
            "bindings": [{"response_name": "pick", "keys": {"j": "x", "k": "y"}}],
        },
        "feedback": {"on_response": "none", "duration_ms": 0},
        "world": {
            "rooms": {
                "alpha": {
                    "title": "Alpha Room",
                    "description": "The first room.",
                    "exits": {"beta": "east door"},
                    "objects": [
                        {
                            "object_id": "plain-prop",
                            "label": "plain prop",
                            "inspect_text": "Just scenery.",
                            "role": "flavour",
                        },
                        {
                            "object_id": "node-one",
                            "label": "marked node",
                            "inspect_text": "It hums quietly.",
                            "role": "encounter",
                        },
                    ],
                },
                "beta": {
                    "title": "Beta Room",
                    "description": "The second room.",
                    "exits": {"alpha": "west door"},
                    "objects": [
                        {
                            "object_id": "node-two",
                            "label": "other marked node",
                            "inspect_text": "It hums differently.",
                            "role": "encounter",
                        }
                    ],
                },
            },
            "start_room": "alpha",
        },
        "narrative": {
            "intro": "A two-room probe session.",
            "block_briefings": {"main": "Two controlled trials."},
            "ending_bands": [
                {"min_accuracy": 0.0, "text": "band-low"},
                {"min_accuracy": 0.99, "text": "band-high"},
            ],
        },
        "mechanics": {
            "layout": "explore-and-encounter",
            "inspect_objects": True,
            "trial_trigger": "explore-encounter",
        },
        "mapping": {
            "trial_trigger": "explore-encounter",
            "encounter_objects": ["node-one", "node-two"],
            "response_bindings": [{"response_name": "pick", "keys": {"j": "x", "k": "y"}}],
            "creative_freedom": [
                "theme", "room_labels", "object_labels", "narrative_text", "feedback_style",
            ],
            "controlled_invariants": [
                "trial_order", "conditions", "stimulus_content", "correct_answers", "timing",
            ],
        },
    }


@pytest.mark.skipif(_node_bin() is None, reason="node runtime not available")
def test_runtime_full_session_generic_game_to_conclusion() -> None:
    """A synthetic non-Manor world plays end-to-end: distinct binding keys (j/k),
    both trials in cursor order, conclusion, runtime self-check and the ending band.

    Proves the shared runtime logic is not Manor-specific.
    """
    bundle = build_bundle(
        ExperimentSpec.model_validate(_PROBE_SPEC), generated_at="2000-01-01T00:00:00Z"
    )
    result = validate_game(_probe_gamespec(bundle), bundle)
    assert result.valid is True, result.errors
    assert result.game_spec is not None
    html = render_game_html(bundle, result.game_spec)
    path = _write_html("probe.html", html)

    driver = (
        "globalThis.__DONE__ = (async function () {\n"
        "  await waitFor(function (s) { return s.mode === 'intro'; });\n"
        "  press(' ');\n"
        "  await waitFor(function (s) { return s.mode === 'explore' && s.room === 'alpha'; });\n"
        "  press('1');  // plain prop (flavour)\n"
        "  await waitFor(function (s) { return s.mode === 'inspect'; });\n"
        "  press(' ');\n"
        "  await waitFor(function (s) { return s.mode === 'explore'; });\n"
        "  press('2');  // node-one (encounter)\n"
        "  await waitFor(function (s) { return s.mode === 'briefing'; });\n"
        "  press(' ');\n"
        "  await waitFor(function (s) { return s.mode === 'encounter' && s.phase === 'response'; });\n"
        "  var t0 = PLAN.trials[0];\n"
        "  var expectedLine = 'The marker points to side ' + t0.conditions.f + '.';\n"
        "  var stimOk = textOf('screen').indexOf(expectedLine) >= 0;\n"
        "  press('j');  // binding j -> value 'x'\n"
        "  await waitFor(function (s) { return s.mode === 'explore'; });\n"
        "  press('3');  // exit: alpha -> beta\n"
        "  await waitFor(function (s) { return s.room === 'beta' && s.mode === 'explore'; });\n"
        "  press('1');  // node-two (encounter)\n"
        "  await waitFor(function (s) { return s.mode === 'encounter' && s.phase === 'response'; });\n"
        "  press('k');  // binding k -> value 'y'\n"
        "  await waitFor(function (s) { return s.mode === 'explore'; });\n"
        "  await waitFor(function (s) { return s.mode === 'explore'; });\n"
        "  press('x');  // conclude (all trials consumed)\n"
        "  await waitFor(function (s) { return s.mode === 'end'; });\n"
        "  return { stimOk: stimOk, endText: textOf('screen') };\n"
        "})();\n"
    )
    report = _run_driver(path, driver)
    result_payload = cast(dict[str, object], report["result"])
    assert result_payload["stimOk"] is True  # materialized line rendered verbatim

    events = _events(report)
    starts = _of_channel(events, "measurement", "trial_start")
    assert [s["trial_index"] for s in starts] == [0, 1]
    responses = _of_channel(events, "measurement", "response")
    assert [r["value"] for r in responses] == ["x", "y"]  # j->x, k->y binding resolution

    # correctness computed from the bundle factors
    trials = cast(list[object], bundle["trials"])
    for resp, trial_raw in zip(responses, trials):
        trial = cast(dict[str, object], trial_raw)
        factors = cast(dict[str, object], trial["factors"])
        assert resp["correct"] is (factors["f"] == resp["value"])

    # channel discipline
    assert _of_channel(events, "measurement", "block_start") != []
    assert _of_channel(events, "measurement", "game_end") != []
    assert _of_channel(events, "game", "game_start") != []
    assert _of_channel(events, "game", "encounter_trigger") != []

    end_text = cast(str, result_payload["endText"])
    assert "Self-check OK" in end_text
    # ending band matches the achieved accuracy
    n_correct = sum(1 for r in responses if r["correct"] is True)
    expected_band = "band-high" if n_correct == 2 else "band-low"
    assert expected_band in end_text
    assert cast(dict[str, object], report["snapshot"])["mode"] == "end"
