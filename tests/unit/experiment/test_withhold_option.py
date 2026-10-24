"""Expressiveness Stage 1 tests: withhold-as-answer semantics (responses[].withhold_option).

Design (docs/experiment-expressiveness/04 §P2, revised): the event log records
BEHAVIOR — a deadline expiry keeps value: null — and only the SCORING rule
treats null as an answer. null is correct exactly when the response declares
withhold_option and the expected key equals that value. Every runtime addition
(the withheld:true event marker, the feedback branch, the scoring clause) is
gated on the response declaring withhold_option, with EXPLICIT undefined
checks (a bare undefined === undefined comparison must never score a miss as
correct — the review's compatibility risk).

Coverage: schema/validation (collision, kind, v1 gating, rule options may be
the withhold value), spec_dump projection (no bytes when unset), run-plan
projection, both engines' four Go/No-Go cells (hit / omission / commission /
correct rejection), the missing-answer-key edge (correct: null, never a
crash), and the old-spec regression (no withhold -> historical behavior,
marker absent).
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
from src.experiment.schemas import ExperimentSpec, spec_dump
from src.experiment.validation import ErrorCode, WarningCode, validate_spec

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXED_GENERATED_AT = "2000-01-01T00:00:00Z"
SANDBOX_DIR = REPO_ROOT / "data" / ".test-sandbox" / "withhold-runtime"

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


def _codes(result: object) -> list[str]:
    return [issue.error_code for issue in result.errors]  # type: ignore[attr-defined]


def _warning_codes(result: object) -> list[str]:
    return [issue.error_code for issue in result.warnings]  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _classic_gonogo_spec(*, correct_rule: bool = True) -> dict[str, object]:
    """A go/no-go design (correct_rule path: the key is content-derived from the
    trial_type factor; withholding is correct on no_go trials)."""
    response: dict[str, object] = {
        "name": "press",
        "kind": "choice",
        "options": ["go"],
        "withhold_option": "withhold",
    }
    if correct_rule:
        response["correct_rule"] = {
            "op": "eq",
            "left": {"factor": "trial_type"},
            "right": {"literal": "no_go"},
            "true_option": "withhold",
            "false_option": "go",
        }
    else:
        response.pop("withhold_option")
    return {
        "schema_version": 2,
        "name": "gonogo-withhold",
        "version": "0.1.0",
        "seed": 77,
        "factors": [{"name": "trial_type", "levels": [{"name": "go"}, {"name": "no_go"}]}],
        "blocks": [{"name": "main", "trial_count": 4, "shuffle_within": False}],
        "constraints": {"balance": True},
        "responses": [response],
        "timing": {"fixation_ms": 0, "stimulus_ms": 250, "isi_ms": 40},
        # correct_rule requires a stimulus_spec (validation + materialization path)
        "stimulus_spec": {
            "factors": {
                "trial_type": {
                    "levels": {"go": [["Signal: press"]], "no_go": [["Signal: hold"]]},
                    "match_line_count": True,
                }
            },
            "pools": {},
        },
    }


def _explore_gonogo_spec() -> dict[str, object]:
    """The correct_from path: the no_go level name EQUALS the withhold value,
    so a withheld no_go trial scores correct without any rule."""
    config = _classic_gonogo_spec(correct_rule=False)
    responses = cast(list[dict[str, object]], config["responses"])
    responses[0]["withhold_option"] = "no_go"
    responses[0]["correct_from"] = "trial_type"
    config["name"] = "gonogo-withhold-explore"
    config["stimulus_spec"] = {
        "factors": {
            "trial_type": {
                "levels": {"go": [["Signal: press"]], "no_go": [["Signal: hold"]]},
                "match_line_count": True,
            }
        },
        "pools": {},
    }
    return config


def _bundle(config: dict[str, object]) -> dict[str, object]:
    return build_bundle(
        ExperimentSpec.model_validate(config), generated_at=FIXED_GENERATED_AT
    )


def _classic_gamespec(bundle: dict[str, object], name: str) -> dict[str, object]:
    repro = cast(dict[str, object], bundle["reproducibility"])
    spec = cast(dict[str, object], bundle["spec"])
    return {
        "schema_version": 1,
        "game": {"name": name, "version": "0.1.0"},
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
    gamespec = _classic_gamespec(bundle, "gonogo-explore")
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
# Validation
# ---------------------------------------------------------------------------


def test_withhold_spec_valid() -> None:
    result = validate_spec(_classic_gonogo_spec())
    assert result.valid, [(e.error_code, e.path, e.message) for e in result.errors]


def test_withhold_collision_rejected() -> None:
    config = _classic_gonogo_spec()
    cast(list[dict[str, object]], config["responses"])[0]["withhold_option"] = "go"
    assert ErrorCode.V2_WITHHOLD_COLLISION in _codes(validate_spec(config))


def test_withhold_non_choice_rejected() -> None:
    config = _classic_gonogo_spec()
    response = cast(list[dict[str, object]], config["responses"])[0]
    response["kind"] = "text"
    response["options"] = []
    response.pop("correct_rule")
    response["withhold_option"] = "withhold"
    assert ErrorCode.V2_WITHHOLD_KIND in _codes(validate_spec(config))


def test_withhold_on_v1_rejected() -> None:
    config = _classic_gonogo_spec()
    config["schema_version"] = 1
    assert ErrorCode.V2_VERSION_MISMATCH in _codes(validate_spec(config))


def test_rule_option_may_be_the_withhold_value() -> None:
    """correct_rule true/false_option may be the withhold_option value (04 §P2.2)."""
    result = validate_spec(_classic_gonogo_spec())
    assert result.valid
    assert ErrorCode.V2_RULE_OPTION_UNKNOWN not in _codes(result)


def test_correct_from_withhold_value_is_legal() -> None:
    """correct_from + withhold: when the no-press level NAME equals the withhold
    value, a withheld trial scores correct (documented interplay, not an error)."""
    result = validate_spec(_explore_gonogo_spec())
    assert result.valid, _codes(result)


def test_spec_dump_strips_unset_withhold() -> None:
    """An unset withhold_option contributes no bytes (fingerprint preservation)."""
    v1_config: dict[str, object] = {
        "schema_version": 1,
        "name": "gonogo-v1",
        "version": "0.1.0",
        "seed": 5,
        "factors": [{"name": "trial_type", "levels": [{"name": "go"}, {"name": "no_go"}]}],
        "blocks": [{"name": "main", "trial_count": 4}],
        "constraints": {"balance": True},
        "responses": [
            {"name": "press", "kind": "choice", "options": ["go"], "correct_from": "trial_type"}
        ],
        "timing": {"fixation_ms": 0, "stimulus_ms": 250, "isi_ms": 40},
    }
    result = validate_spec(v1_config)
    assert result.valid and result.spec is not None
    dump = spec_dump(result.spec)
    for response in cast(list[dict[str, object]], dump["responses"]):
        assert "withhold_option" not in response
        assert "correct_rule" not in response
    for block in cast(list[dict[str, object]], dump["blocks"]):
        assert "timing" not in block


# ---------------------------------------------------------------------------
# Materialization + run plans
# ---------------------------------------------------------------------------


def test_content_key_carries_withhold_value() -> None:
    trials = cast(list[dict[str, object]], _bundle(_classic_gonogo_spec())["trials"])
    keys = [cast(dict[str, str], t["correct"])["press"] for t in trials]
    assert set(keys) == {"go", "withhold"}
    for trial, key in zip(trials, keys):
        factors = cast(dict[str, str], trial["factors"])
        assert key == ("withhold" if factors["trial_type"] == "no_go" else "go")


def test_classic_plan_projects_withhold_only_when_declared() -> None:
    bundle = _bundle(_classic_gonogo_spec())
    plan = build_run_plan(bundle, GameSpec.model_validate(_classic_gamespec(bundle, "gonogo")))
    responses = cast(list[dict[str, object]], cast(dict[str, object], plan["meta"])["responses"])
    assert responses[0]["withhold_option"] == "withhold"

    config = _classic_gonogo_spec(correct_rule=False)
    config["schema_version"] = 1
    bundle_old = _bundle(config)
    plan_old = build_run_plan(
        bundle_old, GameSpec.model_validate(_classic_gamespec(bundle_old, "gonogo-old"))
    )
    responses_old = cast(
        list[dict[str, object]], cast(dict[str, object], plan_old["meta"])["responses"]
    )
    assert "withhold_option" not in responses_old[0]


def test_explore_plan_projects_withhold() -> None:
    from src.experiment.explore_render import build_explore_plan

    bundle = _bundle(_explore_gonogo_spec())
    gamespec = _explore_gamespec(bundle)
    result = validate_game(gamespec, bundle)
    assert result.valid, [(e.error_code, e.path) for e in result.errors]
    plan = build_explore_plan(bundle, result.game_spec)  # type: ignore[arg-type]
    responses = cast(list[dict[str, object]], cast(dict[str, object], plan["meta"])["responses"])
    assert responses[0]["withhold_option"] == "no_go"


def test_withhold_html_contains_patch_and_old_spec_html_does_not() -> None:
    bundle = _bundle(_classic_gonogo_spec())
    withhold_html = render_game_html(
        bundle, GameSpec.model_validate(_classic_gamespec(bundle, "gonogo"))
    )
    assert "withheld" in withhold_html
    assert "withhold_option !== undefined" in withhold_html

    config = _classic_gonogo_spec(correct_rule=False)
    config["schema_version"] = 1
    bundle_old = _bundle(config)
    old_html = render_game_html(
        bundle_old, GameSpec.model_validate(_classic_gamespec(bundle_old, "gonogo-old"))
    )
    assert "withheld" not in old_html
    assert "withhold_option" not in old_html


# ---------------------------------------------------------------------------
# Runtime (node): the four cells, both engines
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


def _cell_assertions(result: dict[str, object]) -> None:
    """The four Go/No-Go cells from the event log alone: (conditions, value, correct)."""
    responses = cast(list[dict[str, object]], result["responses"])
    assert len(responses) == 4
    by_cell: dict[tuple[object, object, object], int] = {}
    for ev in responses:
        conditions = cast(dict[str, object], ev["conditions"])
        cell = (conditions["trial_type"], ev["value"], ev["correct"])
        by_cell[cell] = by_cell.get(cell, 0) + 1
    assert by_cell.get(("go", "go", True)) == 1, by_cell      # hit
    assert by_cell.get(("go", None, False)) == 1, by_cell     # omission
    assert by_cell.get(("no_go", "go", False)) == 1, by_cell  # commission
    assert by_cell.get(("no_go", None, True)) == 1, by_cell   # correct rejection
    # every null-value event carries the gated withheld marker
    for ev in responses:
        if ev["value"] is None:
            assert ev.get("withheld") is True, ev
        else:
            assert "withheld" not in ev, ev


@pytest.mark.skipif(_node_bin() is None, reason="node runtime not available")
def test_runtime_classic_four_cells() -> None:
    node = _node_bin()
    assert node is not None
    SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
    bundle = _bundle(_classic_gonogo_spec())
    html = render_game_html(bundle, GameSpec.model_validate(_classic_gamespec(bundle, "gonogo")))
    html_path = SANDBOX_DIR / "gonogo-classic.html"
    html_path.write_text(html, encoding="utf-8")
    harness_path = SANDBOX_DIR / "classic-harness.js"
    if not harness_path.exists() or harness_path.read_text(encoding="utf-8") != _CLASSIC_HARNESS_JS:
        harness_path.write_text(_CLASSIC_HARNESS_JS, encoding="utf-8")
    # deterministic order (shuffle_within=false): trials 0,1 = go; 2,3 = no_go.
    # press trial 0 (hit), withhold trial 1 (omission), press trial 2
    # (commission), withhold trial 3 (correct rejection). Edge detection on the
    # response prompt: one decision per prompt appearance (a no-press window
    # stays visible until the deadline).
    driver = (
        "globalThis.__DONE__ = (async function () {\n"
        "  await waitFor(function () { return textOf('screen').indexOf('Press any key') >= 0; });\n"
        "  press(' ');\n"
        "  await waitFor(function () { return textOf('screen').indexOf('Press any key') < 0; });\n"
        "  var plan = [true, false, true, false];\n"
        "  var current = 0;\n"
        "  var lastPrompt = false;\n"
        "  var ticks = 0;\n"
        "  while (ticks < 20000) {\n"
        "    ticks += 1;\n"
        "    if (elById('eventlog') && elById('eventlog').value) { break; }\n"
        "    var hasPrompt = textOf('screen').indexOf('[g] go') >= 0;\n"
        "    if (hasPrompt && !lastPrompt && current < 4) {\n"
        "      if (plan[current]) { press('g'); }\n"
        "      current += 1;\n"
        "    }\n"
        "    lastPrompt = hasPrompt;\n"
        "    await sleep(5);\n"
        "  }\n"
        "  await waitFor(function () { return elById('eventlog') && elById('eventlog').value; }, 30000);\n"
        "  var events = JSON.parse(elById('eventlog').value);\n"
        "  var responses = events.filter(function (e) { return e.event === 'response'; });\n"
        "  return { responses: responses };\n"
        "})();\n"
    )
    driver_path = SANDBOX_DIR / "driver-gonogo-classic.js"
    driver_path.write_text(driver, encoding="utf-8")
    proc = subprocess.run(
        [node, str(harness_path), str(html_path), str(driver_path)],
        capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, proc.stderr
    result_line = next(ln for ln in proc.stdout.splitlines() if ln.startswith("__RESULT__"))
    _cell_assertions(json.loads(result_line[len("__RESULT__"):]))
    # summary counters: 2 correct of 4 applicable
    events = json.loads(result_line[len("__RESULT__"):])["responses"]
    assert sum(1 for e in events if e["correct"] is True) == 2


@pytest.mark.skipif(_node_bin() is None, reason="node runtime not available")
def test_runtime_explore_four_cells() -> None:
    node = _node_bin()
    assert node is not None
    from tests.unit.experiment.test_explore_runtime import _HARNESS_JS as EXPLORE_HARNESS

    SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
    bundle = _bundle(_explore_gonogo_spec())
    gamespec = _explore_gamespec(bundle)
    result_validated = validate_game(gamespec, bundle)
    assert result_validated.valid, result_validated.errors
    html = render_game_html(bundle, result_validated.game_spec)
    html_path = SANDBOX_DIR / "gonogo-explore.html"
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
        "  var lastPrompt = false;\n"
        "  var ticks = 0;\n"
        "  while (ticks < 30000) {\n"
        "    ticks += 1;\n"
        "    var s = D.snapshot();\n"
        "    if (s.mode === 'encounter') {\n"
        "      var hasPrompt = textOf('screen').indexOf('[g] go') >= 0;\n"
        "      if (hasPrompt && !lastPrompt) {\n"
        "        var idx = s.cursor - 1;\n"
        "        if (idx >= 0 && idx < 4 && plan[idx]) { press('g'); }\n"
        "      }\n"
        "      lastPrompt = hasPrompt;\n"
        "    } else {\n"
        "      lastPrompt = false;\n"
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
    driver_path = SANDBOX_DIR / "driver-gonogo-explore.js"
    driver_path.write_text(driver, encoding="utf-8")
    proc = subprocess.run(
        [node, str(harness_path), str(html_path), str(driver_path)],
        capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, proc.stderr
    result_line = next(ln for ln in proc.stdout.splitlines() if ln.startswith("__RESULT__"))
    result = json.loads(result_line[len("__RESULT__"):])["result"]
    _cell_assertions(result)


@pytest.mark.skipif(_node_bin() is None, reason="node runtime not available")
def test_runtime_missing_answer_key_edge() -> None:
    """A withhold response WITHOUT any answer key on the trials: a no-press
    records value null with correct null (not scored, never a crash) — the
    answer-key presence check runs BEFORE the withhold clause."""
    node = _node_bin()
    assert node is not None
    config = _classic_gonogo_spec(correct_rule=False)
    cast(list[dict[str, object]], config["responses"])[0]["withhold_option"] = "withhold"
    bundle = _bundle(config)
    html = render_game_html(bundle, GameSpec.model_validate(_classic_gamespec(bundle, "gonogo-nokey")))
    SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
    html_path = SANDBOX_DIR / "gonogo-nokey.html"
    html_path.write_text(html, encoding="utf-8")
    harness_path = SANDBOX_DIR / "classic-harness.js"
    if not harness_path.exists() or harness_path.read_text(encoding="utf-8") != _CLASSIC_HARNESS_JS:
        harness_path.write_text(_CLASSIC_HARNESS_JS, encoding="utf-8")
    driver = (
        "globalThis.__DONE__ = (async function () {\n"
        "  await waitFor(function () { return textOf('screen').indexOf('Press any key') >= 0; });\n"
        "  press(' ');\n"
        "  var ticks = 0;\n"
        "  while (ticks < 20000) {\n"
        "    ticks += 1;\n"
        "    if (elById('eventlog') && elById('eventlog').value) { break; }\n"
        "    await sleep(5);\n"  # never press: every trial times out with no answer key
        "  }\n"
        "  await waitFor(function () { return elById('eventlog') && elById('eventlog').value; }, 30000);\n"
        "  var events = JSON.parse(elById('eventlog').value);\n"
        "  var responses = events.filter(function (e) { return e.event === 'response'; });\n"
        "  return { responses: responses };\n"
        "})();\n"
    )
    driver_path = SANDBOX_DIR / "driver-gonogo-nokey.js"
    driver_path.write_text(driver, encoding="utf-8")
    proc = subprocess.run(
        [node, str(harness_path), str(html_path), str(driver_path)],
        capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, proc.stderr
    result_line = next(ln for ln in proc.stdout.splitlines() if ln.startswith("__RESULT__"))
    responses = cast(list[dict[str, object]], json.loads(result_line[len("__RESULT__"):])["responses"])
    assert len(responses) == 4
    for ev in responses:
        assert ev["value"] is None
        assert ev["correct"] is None  # no answer key: unscored, not false
        assert ev.get("withheld") is True  # marker still flags the deliberate no-press


@pytest.mark.skipif(_node_bin() is None, reason="node runtime not available")
def test_runtime_old_spec_timeout_regression() -> None:
    """A spec WITHOUT withhold_option: a timeout keeps the historical behavior —
    correct: false, no withheld marker, 'missed' feedback path."""
    node = _node_bin()
    assert node is not None
    config = _classic_gonogo_spec(correct_rule=False)
    config["schema_version"] = 1
    cast(list[dict[str, object]], config["responses"])[0]["correct_from"] = "trial_type"
    bundle = _bundle(config)
    html = render_game_html(bundle, GameSpec.model_validate(_classic_gamespec(bundle, "gonogo-old")))
    SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
    html_path = SANDBOX_DIR / "gonogo-old.html"
    html_path.write_text(html, encoding="utf-8")
    harness_path = SANDBOX_DIR / "classic-harness.js"
    if not harness_path.exists() or harness_path.read_text(encoding="utf-8") != _CLASSIC_HARNESS_JS:
        harness_path.write_text(_CLASSIC_HARNESS_JS, encoding="utf-8")
    driver = (
        "globalThis.__DONE__ = (async function () {\n"
        "  await waitFor(function () { return textOf('screen').indexOf('Press any key') >= 0; });\n"
        "  press(' ');\n"
        "  var ticks = 0;\n"
        "  while (ticks < 20000) {\n"
        "    ticks += 1;\n"
        "    if (elById('eventlog') && elById('eventlog').value) { break; }\n"
        "    await sleep(5);\n"  # never press: every trial times out
        "  }\n"
        "  await waitFor(function () { return elById('eventlog') && elById('eventlog').value; }, 30000);\n"
        "  var events = JSON.parse(elById('eventlog').value);\n"
        "  var responses = events.filter(function (e) { return e.event === 'response'; });\n"
        "  return { responses: responses };\n"
        "})();\n"
    )
    driver_path = SANDBOX_DIR / "driver-gonogo-old.js"
    driver_path.write_text(driver, encoding="utf-8")
    proc = subprocess.run(
        [node, str(harness_path), str(html_path), str(driver_path)],
        capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, proc.stderr
    result_line = next(ln for ln in proc.stdout.splitlines() if ln.startswith("__RESULT__"))
    responses = cast(list[dict[str, object]], json.loads(result_line[len("__RESULT__"):])["responses"])
    assert len(responses) == 4
    for ev in responses:
        assert ev["value"] is None
        assert ev["correct"] is False  # historical null -> false, unconditionally
        assert "withheld" not in ev  # no marker without a declared withhold_option


def test_withhold_bundle_reproducible() -> None:
    bundle = _bundle(_classic_gonogo_spec())
    assert canonical_json(bundle) == canonical_json(_bundle(_classic_gonogo_spec()))
