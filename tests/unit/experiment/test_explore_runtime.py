"""M2-D runtime tests (Phase 1 + Stage 2a): drive the shipped explore engine under node
with a DOM stub.

Covered (real runtime behavior, extracted from the rendered HTML):
room navigation, flavour inspection without trial consumption, encounter activation,
verbatim stimulus rendering, response binding resolution, the monotonic trial cursor,
return-to-exploration, session conclusion with the runtime self-check — and, since
Stage 2a, the click path: clicking an object/exit performs the same action as its
keyboard equivalent, the inline inspect panel, and examined visual states.

Browser-automation limitation (docs/m2/M2D_STAGE2A_REPORT.md): node executes the
engine's JS against a minimal DOM stub — layout, styling, real pointer/keyboard
events, focus handling and setTimeout fidelity are NOT verified here. Visual
verification is a manual step (the report's checklist). Tests are skipped when no
node runtime exists. The stub reflects the two browser behaviors the engine relies
on: element.id property assignment and setAttribute("class") → classList.

Sandbox discipline: each test writes its own driver-{name}.js (never a shared
driver.js), so parallel pytest runs cannot cross-contaminate.
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
# Node harness: DOM stub (id/class reflection, click handlers) + driver protocol
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
    children: [], style: {}, _cls: {}, attrs: {}, handlers: {},
    className: "", textContent: "", value: "", readOnly: false, type: "",
    classList: null,
    appendChild: function (c) { el.children.push(c); return c; },
    removeChild: function (c) { var i = el.children.indexOf(c); if (i >= 0) { el.children.splice(i, 1); } return c; },
    addEventListener: function (name, fn) { (el.handlers[name] = el.handlers[name] || []).push(fn); },
    setAttribute: function (k, v) {
      el.attrs[k] = String(v);
      if (k === "id") { elementsById[v] = el; }
      if (k === "class") {
        el._cls = {};
        String(v).split(/\\s+/).forEach(function (c) { if (c) { el._cls[c] = true; } });
      }
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
  createElementNS: function (ns, tag) { return makeEl(tag); },
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
function clickEl(el) {
  (el.handlers.click || []).forEach(function (fn) { fn({ preventDefault: function () {} }); });
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
globalThis.clickEl = clickEl;
globalThis.waitFor = waitFor;
globalThis.textOf = textOf;
globalThis.sleep = sleep;
globalThis.elById = function (id) { return globalThis.document.getElementById(id); };

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


def _run_driver(name: str, html_path: Path, driver_code: str) -> dict[str, object]:
    """Run the engine from the rendered HTML under node; return {result, events, snapshot}.

    Each test gets its own driver-<name>.js (parallel-run safe).
    """
    node = _node_bin()
    assert node is not None
    SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
    harness_path = SANDBOX_DIR / "harness.js"
    if not harness_path.exists() or harness_path.read_text(encoding="utf-8") != _HARNESS_JS:
        harness_path.write_text(_HARNESS_JS, encoding="utf-8")
    driver_path = SANDBOX_DIR / f"driver-{name}.js"
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
# Keyboard path (Phase 1 behavior, keys now follow DECLARATION order:
# hall = 3 objects (1-3) + exits study(4), library(5); study = 6 objects (1-6)
# + exits hall(7), parlour(8))
# ---------------------------------------------------------------------------

@pytest.mark.skipif(_node_bin() is None, reason="node runtime not available")
def test_runtime_navigation_between_rooms() -> None:
    """The player moves hall -> study -> hall -> library; every move logs room_enter."""
    html, _ = _manor_html()
    path = _write_html("manor.html", html)
    driver = (
        "globalThis.__DONE__ = (async function () {\n"
        "  await waitFor(function (s) { return s.mode === 'intro'; });\n"
        "  press(' ');\n"
        "  await waitFor(function (s) { return s.mode === 'explore' && s.room === 'hall'; });\n"
        "  press('4');  // exit: study (declaration order: study=4, library=5)\n"
        "  await waitFor(function (s) { return s.room === 'study'; });\n"
        "  press('7');  // exit: back to hall (study: 6 objects, exits hall=7)\n"
        "  await waitFor(function (s) { return s.room === 'hall'; });\n"
        "  press('5');  // exit: library\n"
        "  await waitFor(function (s) { return s.room === 'library'; });\n"
        "  return true;\n"
        "})();\n"
    )
    report = _run_driver("nav-keys", path, driver)
    snapshot = cast(dict[str, object], report["snapshot"])
    assert snapshot["room"] == "library"
    moves = _of_channel(_events(report), "game", "room_enter")
    assert [m["room"] for m in moves] == ["study", "hall", "library"]
    assert _of_channel(_events(report), "measurement", "trial_start") == []
    assert snapshot["cursor"] == 0


@pytest.mark.skipif(_node_bin() is None, reason="node runtime not available")
def test_runtime_flavour_inspect_consumes_nothing() -> None:
    """Inspecting a flavour object shows the inline panel and consumes no trial."""
    html, _ = _manor_html()
    path = _write_html("manor.html", html)
    driver = (
        "globalThis.__DONE__ = (async function () {\n"
        "  await waitFor(function (s) { return s.mode === 'intro'; });\n"
        "  press(' ');\n"
        "  await waitFor(function (s) { return s.mode === 'explore'; });\n"
        "  press('1');  // dusty clock (flavour)\n"
        "  await waitFor(function (s) { return s.mode === 'inspect'; });\n"
        "  var seen = textOf('inspect-panel');\n"
        "  var roomStillVisible = textOf('screen').indexOf('Entrance Hall') >= 0;\n"
        "  press(' ');  // any key dismisses the inline panel\n"
        "  await waitFor(function (s) { return s.mode === 'explore'; });\n"
        "  return { seen: seen, roomStillVisible: roomStillVisible };\n"
        "})();\n"
    )
    report = _run_driver("flavour-key", path, driver)
    result = cast(dict[str, object], report["result"])
    assert "It stopped at 3:14." in cast(str, result["seen"])  # inspect_text displayed
    assert result["roomStillVisible"] is True  # inline panel: the room stays on screen
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
    report = _run_driver("encounter-key", path, driver)
    result = cast(dict[str, object], report["result"])
    assert result["missing"] == []  # every stimulus line rendered verbatim
    assert result["stageMode"] is True  # exploration/experiment visual distinction active

    events = _events(report)
    triggers = _of_channel(events, "game", "encounter_trigger")
    assert len(triggers) == 1
    assert triggers[0]["object_id"] == "calling-card"
    assert triggers[0]["trial_index"] == 0
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

    driver = (
        "globalThis.__DONE__ = (async function () {\n"
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
        "  await waitFor(function (s) { return s.mode === 'intro'; });\n"
        "  press(' ');\n"
        "  await waitFor(function (s) { return s.mode === 'explore'; });\n"
        "  await encounter('2', 'b');  // hall: calling-card      -> trial 0\n"
        "  await encounter('3', 'a');  // hall: torn-invitation   -> trial 1\n"
        "  press('4');                 // hall -> study (declaration: study=4)\n"
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
    report = _run_driver("cursor-key", path, driver)
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
# Click path (Stage 2a): clicking performs the same action as the keyboard key
# ---------------------------------------------------------------------------

@pytest.mark.skipif(_node_bin() is None, reason="node runtime not available")
def test_runtime_click_flavour_inspect_equivalent_to_key() -> None:
    """Clicking the flavour object opens the same inline panel as key 1; closing via
    the close button returns to exploration; no trial is consumed."""
    html, _ = _manor_html()
    path = _write_html("manor.html", html)
    driver = (
        "globalThis.__DONE__ = (async function () {\n"
        "  await waitFor(function (s) { return s.mode === 'intro'; });\n"
        "  press(' ');\n"
        "  await waitFor(function (s) { return s.mode === 'explore'; });\n"
        "  clickEl(elById('obj-dusty-clock'));\n"
        "  await waitFor(function (s) { return s.mode === 'inspect'; });\n"
        "  var seen = textOf('inspect-panel');\n"
        "  var roomStillVisible = textOf('screen').indexOf('Entrance Hall') >= 0;\n"
        "  clickEl(elById('inspect-close'));\n"
        "  await waitFor(function (s) { return s.mode === 'explore'; });\n"
        "  var flavourExamined = elById('obj-dusty-clock').classList.contains('examined');\n"
        "  return { seen: seen, roomStillVisible: roomStillVisible, flavourExamined: flavourExamined };\n"
        "})();\n"
    )
    report = _run_driver("flavour-click", path, driver)
    result = cast(dict[str, object], report["result"])
    assert "It stopped at 3:14." in cast(str, result["seen"])
    assert result["roomStillVisible"] is True
    assert result["flavourExamined"] is True  # inspected visual state (flavour side)
    inspects = _of_channel(_events(report), "game", "object_inspect")
    assert len(inspects) == 1 and inspects[0]["object_id"] == "dusty-clock"
    assert _of_channel(_events(report), "measurement", "trial_start") == []
    snapshot = cast(dict[str, object], report["snapshot"])
    assert snapshot["cursor"] == 0 and snapshot["done_trials"] == 0


@pytest.mark.skipif(_node_bin() is None, reason="node runtime not available")
def test_runtime_click_encounter_exactly_one_trial_and_examined_state() -> None:
    """Clicking an encounter object triggers exactly ONE trial; after the response the
    room view returns with the node in the examined visual state; clicking it again
    opens the inline inspect panel (no second trial)."""
    html, _ = _manor_html()
    path = _write_html("manor.html", html)
    driver = (
        "globalThis.__DONE__ = (async function () {\n"
        "  await waitFor(function (s) { return s.mode === 'intro'; });\n"
        "  press(' ');\n"
        "  await waitFor(function (s) { return s.mode === 'explore'; });\n"
        "  var beforeExamined = elById('obj-calling-card').classList.contains('examined');\n"
        "  clickEl(elById('obj-calling-card'));\n"
        "  await waitFor(function (s) { return s.mode === 'briefing'; });\n"
        "  press(' ');\n"
        "  await waitFor(function (s) { return s.mode === 'encounter' && s.phase === 'response'; });\n"
        "  press('a');\n"
        "  await waitFor(function (s) { return s.mode === 'explore'; });\n"
        "  var afterExamined = elById('obj-calling-card').classList.contains('examined');\n"
        "  var roomPreserved = globalThis.__CA_DEBUG__.snapshot().room === 'hall';\n"
        "  clickEl(elById('obj-calling-card'));\n"  # click AGAIN
        "  await waitFor(function (s) { return s.mode === 'inspect'; });\n"
        "  press(' ');\n"
        "  await waitFor(function (s) { return s.mode === 'explore'; });\n"
        "  return { before: beforeExamined, after: afterExamined, roomPreserved: roomPreserved };\n"
        "})();\n"
    )
    report = _run_driver("encounter-click", path, driver)
    result = cast(dict[str, object], report["result"])
    assert result["before"] is False  # unexamined before the trial
    assert result["after"] is True  # examined visual state after
    assert result["roomPreserved"] is True  # room state preserved on return
    events = _events(report)
    starts = _of_channel(events, "measurement", "trial_start")
    assert len(starts) == 1 and starts[0]["trial_index"] == 0  # EXACTLY one trial
    responses = _of_channel(events, "measurement", "response")
    assert len(responses) == 1
    # the second click was an inspect, not a trial
    inspects = _of_channel(events, "game", "object_inspect")
    assert [i["object_id"] for i in inspects] == ["calling-card"]
    snapshot = cast(dict[str, object], report["snapshot"])
    assert snapshot["cursor"] == 1 and snapshot["done_trials"] == 1


@pytest.mark.skipif(_node_bin() is None, reason="node runtime not available")
def test_runtime_click_navigation_and_click_conclusion() -> None:
    """Clicking an exit doorway navigates; after consuming every trial the conclude
    button appears and clicking it ends the session with a passing self-check."""
    html, _ = _manor_html()
    path = _write_html("manor.html", html)
    # consume all 26 trials via the keyboard helper (click path already proven), then
    # navigate and conclude by mouse only
    driver = (
        "globalThis.__DONE__ = (async function () {\n"
        "  async function encounter(key, answer) {\n"
        "    press(key);\n"
        "    var s = await waitFor(function (s) { return s.mode === 'encounter' || s.mode === 'briefing'; });\n"
        "    if (s.mode === 'briefing') { press(' '); }\n"
        "    await waitFor(function (s) { return s.mode === 'encounter' && s.phase === 'response'; });\n"
        "    press(answer);\n"
        "    await waitFor(function (s) { return s.mode === 'explore'; });\n"
        "  }\n"
        "  await waitFor(function (s) { return s.mode === 'intro'; });\n"
        "  press(' ');\n"
        "  await waitFor(function (s) { return s.mode === 'explore'; });\n"
        "  for (var i = 0; i < 2; i++) { await encounter(String(i + 2), 'a'); }  // hall encounters\n"
        "  clickEl(elById('exit-study'));\n"
        "  await waitFor(function (s) { return s.room === 'study' && s.mode === 'explore'; });\n"
        "  for (var j = 0; j < 6; j++) { await encounter(String(j + 1), 'b'); }   // study encounters\n"
        "  clickEl(elById('exit-hall'));\n"
        "  await waitFor(function (s) { return s.room === 'hall' && s.mode === 'explore'; });\n"
        "  clickEl(elById('exit-library'));\n"
        "  await waitFor(function (s) { return s.room === 'library' && s.mode === 'explore'; });\n"
        "  for (var k = 0; k < 6; k++) { await encounter(String(k + 1), 'c'); }   // library\n"
        "  clickEl(elById('exit-parlour'));\n"
        "  await waitFor(function (s) { return s.room === 'parlour' && s.mode === 'explore'; });\n"
        "  for (var p = 0; p < 6; p++) { await encounter(String(p + 1), 'a'); }   // parlour\n"
        "  clickEl(elById('exit-cellar'));\n"
        "  await waitFor(function (s) { return s.room === 'cellar' && s.mode === 'explore'; });\n"
        "  for (var q = 0; q < 6; q++) { await encounter(String(q + 1), 'b'); }   // cellar\n"
        "  var concludeVisible = !!elById('conclude-btn');\n"
        "  clickEl(elById('conclude-btn'));\n"
        "  await waitFor(function (s) { return s.mode === 'end'; });\n"
        "  return { concludeVisible: concludeVisible, endText: textOf('screen') };\n"
        "})();\n"
    )
    report = _run_driver("click-nav-conclude", path, driver)
    result = cast(dict[str, object], report["result"])
    assert result["concludeVisible"] is True
    end_text = cast(str, result["endText"])
    assert "Self-check OK" in end_text
    events = _events(report)
    starts = _of_channel(events, "measurement", "trial_start")
    assert [s["trial_index"] for s in starts] == list(range(26))  # all 26, cursor order
    moves = _of_channel(events, "game", "room_enter")
    assert [m["room"] for m in moves] == ["study", "hall", "library", "parlour", "cellar"]
    snapshot = cast(dict[str, object], report["snapshot"])
    assert snapshot["mode"] == "end" and snapshot["cursor"] == 26


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
        "  press('x');  // conclude (all trials consumed)\n"
        "  await waitFor(function (s) { return s.mode === 'end'; });\n"
        "  return { stimOk: stimOk, endText: textOf('screen') };\n"
        "})();\n"
    )
    report = _run_driver("probe-session", path, driver)
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
