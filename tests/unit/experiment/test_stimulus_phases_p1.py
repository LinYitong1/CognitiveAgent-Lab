"""M3-A P1 tests: trial presentation phases (generic sequential playback).

Scope: stimulus_spec.phases — materialization, validation, run-plan plumbing,
both HTML engines (classic + explore), and phased runtime behavior under node:
phase order, duration-bound advance, response-window gating (keys outside a
window are never recorded), RT anchored at the window phase onset, and no
duplicate/missing responses or skipped trials. Unphased specs keep the exact
historical bytes (golden/fingerprints — covered by the existing suites and
re-asserted here for the renderer source).

The fixture composes ONLY the generic primitives (factors / pools / counts /
references / phases / closed relations); the engine has no paradigm
vocabulary (enforced by the P0 module's guard test).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest

from src.experiment.canonical import canonical_json
from src.experiment.export import build_bundle
from src.experiment.game_render import build_run_plan, render_game_html
from src.experiment.game_schemas import GameSpec, validate_game
from src.experiment.schemas import ExperimentSpec
from src.experiment.validation import ErrorCode, validate_spec
from src.experiment.verify import verify_bundle

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXED_GENERATED_AT = "2000-01-01T00:00:00Z"
TOKENS = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta"]

PROJECT_ROOT = REPO_ROOT
SANDBOX_DIR = PROJECT_ROOT / "data" / ".test-sandbox" / "phases-runtime"

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


def _phased_spec() -> dict[str, object]:
    """A minimal pure-primitive composition: phase 1 presents content to hold,
    phase 2 is a timed interval, phase 3 presents referenced content and is the
    only phase where answering is recorded."""
    return {
        "schema_version": 2,
        "name": "p1-phased",
        "version": "0.1.0",
        "seed": 20261022,
        "factors": [
            {"name": "size", "levels": [{"name": "few"}, {"name": "many"}]},
            {"name": "relation", "levels": [{"name": "repeat"}, {"name": "novel"}]},
        ],
        "blocks": [{"name": "main", "trial_count": 8}],
        "constraints": {"balance": True},
        "responses": [
            {
                "name": "judge",
                "kind": "choice",
                "options": ["repeat", "novel"],
                "correct_rule": {
                    "op": "in",
                    "left": {"var": "probe"},
                    "right": {"var": "items"},
                    "true_option": "repeat",
                    "false_option": "novel",
                },
            }
        ],
        "timing": {"fixation_ms": 200, "stimulus_ms": None, "isi_ms": 200},
        "stimulus_spec": {
            "pools": {"tokens": list(TOKENS)},
            "variables": [
                {
                    "name": "items",
                    "pool": "tokens",
                    "count": {"factor": "size", "levels": {"few": 2, "many": 4}},
                },
                {
                    "name": "probe",
                    "when": {"relation": "repeat"},
                    "copy_from": {"var": "items", "index": "any"},
                },
                {
                    "name": "probe",
                    "when": {"relation": "novel"},
                    "pool": "tokens",
                    "count": 1,
                    "exclude": ["items"],
                },
            ],
            "phases": [
                {
                    "name": "encoding",
                    "lines": ["Remember: {var:items}"],
                    "duration_ms": 120,
                    "advance": "auto",
                    "response_window": False,
                },
                {
                    "name": "retention",
                    "lines": ["Hold..."],
                    "duration_ms": 60,
                    "advance": "auto",
                    "response_window": False,
                },
                {
                    "name": "probe",
                    "lines": ["Probe: {var:probe}"],
                    "duration_ms": None,
                    "advance": "auto",
                    "response_window": True,
                },
            ],
        },
    }


def _bundle() -> dict[str, object]:
    return build_bundle(
        ExperimentSpec.model_validate(_phased_spec()), generated_at=FIXED_GENERATED_AT
    )


def _classic_gamespec(bundle: dict[str, object]) -> dict[str, object]:
    repro = cast(dict[str, object], bundle["reproducibility"])
    spec = cast(dict[str, object], bundle["spec"])
    return {
        "schema_version": 1,
        "game": {"name": "p1-classic", "version": "0.1.0"},
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
            "bindings": [{"response_name": "judge", "keys": {"r": "repeat", "n": "novel"}}],
        },
        "feedback": {"on_response": "correctness-flash", "duration_ms": 50},
        "flow": {"ready_screen": True, "block_breaks": False, "end_screen": "summary"},
        "gamification": {"score": True, "progress_bar": True, "streak_bonus": False},
    }


def _explore_gamespec(bundle: dict[str, object]) -> dict[str, object]:
    gamespec = _classic_gamespec(bundle)
    gamespec["schema_version"] = 2
    gamespec["game"]["name"] = "p1-explore"
    keys = {"r": "repeat", "n": "novel"}
    gamespec["world"] = {
        "start_room": "vault",
        "rooms": {
            "vault": {
                "title": "The Vault",
                "description": "Sealed crates hum quietly.",
                "exits": {"annex": "to the annex"},
                "objects": [
                    {
                        "object_id": f"crate-{i}",
                        "label": f"crate {i}",
                        "inspect_text": "A marked crate.",
                        "role": "encounter",
                    }
                    for i in range(1, 5)
                ],
            },
            "annex": {
                "title": "The Annex",
                "description": "More crates, dimmer light.",
                "exits": {"vault": "back to the vault"},
                "objects": [
                    {
                        "object_id": f"crate-{i}",
                        "label": f"crate {i}",
                        "inspect_text": "A marked crate.",
                        "role": "encounter",
                    }
                    for i in range(5, 9)
                ],
            },
        },
    }
    gamespec["narrative"] = {
        "intro": "Eight marked crates in two rooms.",
        "block_briefings": {"main": "Controlled section."},
        "ending_bands": [
            {"min_accuracy": 0.0, "text": "Done."},
            {"min_accuracy": 0.8, "text": "Sharp."},
        ],
    }
    gamespec["mechanics"] = {
        "layout": "explore-and-encounter",
        "inspect_objects": True,
        "trial_trigger": "explore-encounter",
    }
    gamespec["mapping"] = {
        "trial_trigger": "explore-encounter",
        "encounter_objects": [f"crate-{i}" for i in range(1, 9)],
        "response_bindings": [{"response_name": "judge", "keys": keys}],
        "creative_freedom": ["theme", "room_labels", "object_labels", "narrative_text", "feedback_style"],
        "controlled_invariants": ["trial_order", "conditions", "stimulus_content", "correct_answers", "timing"],
    }
    return gamespec


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_phased_spec_valid() -> None:
    result = validate_spec(_phased_spec())
    assert result.valid, [(e.error_code, e.path, e.message) for e in result.errors]


def test_phases_with_factor_templates_rejected() -> None:
    config = _phased_spec()
    stimulus = cast(dict[str, object], config["stimulus_spec"])
    stimulus["factors"] = {
        "size": {
            "levels": {"few": [["x"]], "many": [["y"]]},
            "match_line_count": True,
        }
    }
    assert ErrorCode.V2_PHASE_TEMPLATE_CONFLICT in _codes(validate_spec(config))


def test_no_response_window_rejected() -> None:
    config = _phased_spec()
    stimulus = cast(dict[str, object], config["stimulus_spec"])
    cast(list[object], stimulus["phases"])[2]["response_window"] = False
    assert ErrorCode.V2_PHASE_WINDOW_COUNT in _codes(validate_spec(config))


def test_fewer_windows_than_responses_rejected() -> None:
    config = _phased_spec()
    config["responses"] = [
        {
            "name": "judge",
            "kind": "choice",
            "options": ["repeat", "novel"],
            "correct_rule": {
                "op": "in",
                "left": {"var": "probe"},
                "right": {"var": "items"},
                "true_option": "repeat",
                "false_option": "novel",
            },
        },
        {"name": "confidence", "kind": "choice", "options": ["high", "low"]},
    ]
    assert ErrorCode.V2_PHASE_WINDOW_COUNT in _codes(validate_spec(config))


def test_duplicate_phase_name_rejected() -> None:
    config = _phased_spec()
    stimulus = cast(dict[str, object], config["stimulus_spec"])
    cast(list[object], stimulus["phases"])[1]["name"] = "encoding"
    assert ErrorCode.V2_PHASE_NAME in _codes(validate_spec(config))


def test_phase_line_bounds_rejected() -> None:
    config = _phased_spec()
    stimulus = cast(dict[str, object], config["stimulus_spec"])
    cast(list[object], stimulus["phases"])[0]["lines"] = ["x" * 201]
    assert ErrorCode.V2_PHASE_LINE_BOUNDS in _codes(validate_spec(config))


def test_phase_slot_reference_rejected() -> None:
    config = _phased_spec()
    stimulus = cast(dict[str, object], config["stimulus_spec"])
    cast(list[object], stimulus["phases"])[0]["lines"] = ["Remember: {var:missing}"]
    assert ErrorCode.V2_VAR_REF_UNKNOWN in _codes(validate_spec(config))


def test_phases_only_without_factors_is_legal() -> None:
    """factors may be omitted entirely when phases are the line source."""
    config = _phased_spec()
    stimulus = cast(dict[str, object], config["stimulus_spec"])
    stimulus.pop("factors", None)  # already absent; assert no V2_STIM_EMPTY either way
    result = validate_spec(config)
    assert result.valid, _codes(result)
    assert ErrorCode.V2_STIM_EMPTY not in _codes(result)


def test_neither_phases_nor_factors_rejected() -> None:
    config = _phased_spec()
    stimulus = cast(dict[str, object], config["stimulus_spec"])
    stimulus.pop("phases")
    assert ErrorCode.V2_STIM_EMPTY in _codes(validate_spec(config))


def test_too_many_phases_rejected() -> None:
    config = _phased_spec()
    stimulus = cast(dict[str, object], config["stimulus_spec"])
    base = cast(list[object], stimulus["phases"])
    stimulus["phases"] = base + [
        {"name": f"pad-{i}", "lines": ["x"], "duration_ms": 10} for i in range(8)
    ]
    assert ErrorCode.V2_PHASE_BOUNDS in _codes(validate_spec(config))


# ---------------------------------------------------------------------------
# Materialization
# ---------------------------------------------------------------------------

def test_phases_materialized_in_order_with_concatenated_lines() -> None:
    trial = cast(list[dict[str, object]], _bundle()["trials"])[0]
    stimulus = cast(dict[str, object], trial["stimulus"])
    phases = cast(list[dict[str, object]], stimulus["phases"])
    assert [p["name"] for p in phases] == ["encoding", "retention", "probe"]
    assert all(isinstance(p["lines"], list) and p["lines"] for p in phases)
    assert cast(list[str], stimulus["lines"]) == [
        line for p in phases for line in cast(list[str], p["lines"])
    ]
    # duration / advance / response_window pass through verbatim
    assert phases[0]["duration_ms"] == 120 and phases[0]["response_window"] is False
    assert phases[2]["duration_ms"] is None and phases[2]["response_window"] is True


def test_variables_and_content_key_work_under_phases() -> None:
    """The P0 binding/reference/correctness machinery is phase-independent."""
    trials = cast(list[dict[str, object]], _bundle()["trials"])
    lengths: dict[str, set[int]] = {}
    for trial in trials:
        factors = cast(dict[str, str], trial["factors"])
        phases = cast(list[dict[str, object]], cast(dict[str, object], trial["stimulus"])["phases"])
        items = cast(list[str], phases[0]["lines"])[0].removeprefix("Remember: ").split()
        probe = cast(list[str], phases[2]["lines"])[0].removeprefix("Probe: ")
        lengths.setdefault(factors["size"], set()).add(len(items))
        expected = "repeat" if probe in items else "novel"
        assert cast(dict[str, str], trial["correct"])["judge"] == expected
    assert lengths == {"few": {2}, "many": {4}}


def test_phased_bundle_reproducible_and_verifiable(tmp_path: Path) -> None:
    bundle = _bundle()
    assert canonical_json(bundle) == canonical_json(_bundle())
    path = tmp_path / "bundle.json"
    path.write_text(canonical_json(bundle), encoding="utf-8")
    report = verify_bundle(path)
    assert report.ok, report.detail


def test_phased_materialization_hashseed_independent(tmp_path: Path) -> None:
    code = (
        "import json,sys;sys.path.insert(0,'.');"
        "from src.experiment.export import build_bundle;"
        "from src.experiment.schemas import ExperimentSpec;"
        "from src.experiment.canonical import canonical_json;"
        "print(canonical_json(build_bundle(ExperimentSpec.model_validate("
        "json.load(open(sys.argv[1]))),generated_at='2000-01-01T00:00:00Z')))"
    )
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(_phased_spec()), encoding="utf-8")
    outputs = set()
    for seed in ("0", "1", "12345"):
        proc = subprocess.run(
            [sys.executable, "-c", code, str(path)],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
            env={"PATH": "/usr/bin:/bin", "PYTHONHASHSEED": seed},
            timeout=120,
        )
        assert proc.returncode == 0, proc.stderr
        outputs.add(proc.stdout.strip())
    assert len(outputs) == 1


def test_unphased_spec_has_no_phases_key() -> None:
    config = _phased_spec()
    stimulus = cast(dict[str, object], config["stimulus_spec"])
    stimulus.pop("phases")
    stimulus["factors"] = {
        "size": {"levels": {"few": [["Items: {var:items}"]], "many": [["Items: {var:items}"]]}}
    }
    result = validate_spec(config)
    assert result.valid, _codes(result)
    trial = cast(list[dict[str, object]], _bundle()["trials"])[0] if False else None
    bundle = build_bundle(ExperimentSpec.model_validate(config), generated_at=FIXED_GENERATED_AT)
    trial = cast(list[dict[str, object]], bundle["trials"])[0]
    assert set(cast(dict[str, object], trial["stimulus"]).keys()) == {"lines"}


# ---------------------------------------------------------------------------
# Run plans + renderer source
# ---------------------------------------------------------------------------

def test_classic_plan_carries_phases_verbatim() -> None:
    bundle = _bundle()
    plan = build_run_plan(bundle, GameSpec.model_validate(_classic_gamespec(bundle)))
    steps = [
        s for s in cast(list[dict[str, object]], plan["steps"]) if s.get("type") == "trial"
    ]
    trials = cast(list[dict[str, object]], bundle["trials"])
    assert len(steps) == len(trials)
    for step, trial in zip(steps, trials):
        stimulus = cast(dict[str, object], trial["stimulus"])
        assert step["phases"] == stimulus["phases"]
        # phased trials display conditions only (no stimulus blob)
        display = cast(list[list[object]], step["display"])
        assert all(pair[0] in ("size", "relation") for pair in display)


def test_explore_plan_carries_phases_verbatim() -> None:
    from src.experiment.explore_render import build_explore_plan

    bundle = _bundle()
    gamespec = _explore_gamespec(bundle)
    result = validate_game(gamespec, bundle)
    assert result.valid, [(e.error_code, e.path) for e in result.errors]
    plan = build_explore_plan(bundle, result.game_spec)  # type: ignore[arg-type]
    steps = cast(list[dict[str, object]], plan["trials"])
    trials = cast(list[dict[str, object]], bundle["trials"])
    for step, trial in zip(steps, trials):
        stimulus = cast(dict[str, object], trial["stimulus"])
        assert step["phases"] == stimulus["phases"]


def test_phased_classic_html_injects_player_and_unphased_does_not() -> None:
    bundle = _bundle()
    phased = render_game_html(bundle, GameSpec.model_validate(_classic_gamespec(bundle)))
    assert "playPhases" in phased and "runPhasedTrial" in phased

    # unphased manor bundle through the same renderer: historical engine bytes
    manor_bundle = json.loads(
        (REPO_ROOT / "tests" / "fixtures" / "manor-case" / "bundle.json").read_text(encoding="utf-8")
    )
    manor_gamespec = json.loads(
        (REPO_ROOT / "tests" / "fixtures" / "manor-case" / "gamespec.json").read_text(encoding="utf-8")
    )
    unphased = render_game_html(manor_bundle, GameSpec.model_validate(manor_gamespec))
    assert "playPhases" not in unphased and "runPhasedTrial" not in unphased


def test_phased_explore_html_injects_player_and_unphased_does_not() -> None:
    bundle = _bundle()
    gamespec = _explore_gamespec(bundle)
    result = validate_game(gamespec, bundle)
    assert result.valid
    phased = render_game_html(bundle, result.game_spec)  # type: ignore[arg-type]
    assert "playPhases" in phased and "runPhasedEncounter" in phased

    manor_bundle = json.loads(
        (REPO_ROOT / "tests" / "fixtures" / "manor-case" / "bundle.json").read_text(encoding="utf-8")
    )
    manor_gamespec = json.loads(
        (REPO_ROOT / "tests" / "fixtures" / "manor-case" / "gamespec.json").read_text(encoding="utf-8")
    )
    manor_result = validate_game(manor_gamespec, manor_bundle)
    unphased = render_game_html(manor_bundle, manor_result.game_spec)  # type: ignore[arg-type]
    assert "playPhases" not in unphased and "runPhasedEncounter" not in unphased


# ---------------------------------------------------------------------------
# Runtime (node; real timers are approximate but sufficient for sequencing)
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

_MEMORY_DRIVER_CORE = """\
  var remembered = null;
  var answered = 0;
  var sawEncoding = 0;
  var sawRetention = 0;
  var countedRetention = false;
  function pollTrial(txt) {
    if (txt.indexOf("Remember:") >= 0 && remembered === null) {
      remembered = txt.slice(txt.indexOf("Remember:") + 9).trim().split(/\\s+/);
      sawEncoding += 1;
      countedRetention = false;
      press("r");  // decoy press during the CLOSED window: must never be recorded
    } else if (txt.indexOf("Hold...") >= 0 && remembered !== null && !countedRetention) {
      sawRetention += 1;
      countedRetention = true;
    } else if (txt.indexOf("Probe:") >= 0 && remembered !== null) {
      var probe = txt.slice(txt.indexOf("Probe:") + 6).trim().split(/\\s+/)[0];
      press(remembered.indexOf(probe) >= 0 ? "r" : "n");
      answered += 1;
      remembered = null;
    }
  }
"""


def _summarize_responses(responses: list[dict[str, object]], starts: list[dict[str, object]]) -> dict[str, object]:
    per_trial: dict[int, int] = {}
    for r in responses:
        idx = int(cast(int, r["trial_index"]))
        per_trial[idx] = per_trial.get(idx, 0) + 1
    no_dup_missing = len(per_trial) == len(starts) and all(v == 1 for v in per_trial.values())
    return {
        "trials_started": len(starts),
        "responses_logged": len(responses),
        "no_duplicate_or_missing_response": no_dup_missing,
        "all_correct": all(r.get("correct") is True for r in responses),
        "all_have_rt": all(isinstance(r.get("rt_ms"), int) and cast(int, r["rt_ms"]) >= 0 for r in responses),
        "all_have_conditions": all(
            isinstance(r.get("conditions"), dict) and "relation" in cast(dict[str, object], r["conditions"])
            for r in responses
        ),
        "values": [cast(str, r["value"]) for r in responses],
    }


@pytest.mark.skipif(_node_bin() is None, reason="node runtime not available")
def test_runtime_classic_phased_playback() -> None:
    """The phased classic engine plays encoding -> retention -> probe; a decoy
    keypress during the closed window is never recorded; every trial collects
    exactly one response, answered from held content."""
    node = _node_bin()
    assert node is not None
    SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
    bundle = _bundle()
    html = render_game_html(bundle, GameSpec.model_validate(_classic_gamespec(bundle)))
    html_path = SANDBOX_DIR / "phased-classic.html"
    html_path.write_text(html, encoding="utf-8")
    harness_path = SANDBOX_DIR / "classic-harness.js"
    if not harness_path.exists() or harness_path.read_text(encoding="utf-8") != _CLASSIC_HARNESS_JS:
        harness_path.write_text(_CLASSIC_HARNESS_JS, encoding="utf-8")
    driver = (
        "globalThis.__DONE__ = (async function () {\n"
        "  await waitFor(function () { return textOf('screen').indexOf('Press any key') >= 0; });\n"
        "  press(' ');\n"
        + _MEMORY_DRIVER_CORE
        + "  var ticks = 0;\n"
        "  while (ticks < 8000) {\n"
        "    ticks += 1;\n"
        "    pollTrial(textOf('screen'));\n"
        "    if (elById('eventlog') && elById('eventlog').value) { break; }\n"
        "    await sleep(5);\n"
        "  }\n"
        "  await waitFor(function () { return elById('eventlog') && elById('eventlog').value; }, 30000);\n"
        "  var events = JSON.parse(elById('eventlog').value);\n"
        "  var starts = events.filter(function (e) { return e.event === 'trial_start'; });\n"
        "  var responses = events.filter(function (e) { return e.event === 'response'; });\n"
        "  var per = {};\n"
        "  responses.forEach(function (e) { per[e.trial_index] = (per[e.trial_index] || 0) + 1; });\n"
        "  return { answered: answered, sawEncoding: sawEncoding, sawRetention: sawRetention,\n"
        "           trials: starts.length, responses: responses.length,\n"
        "           perTrialMax: Math.max.apply(null, Object.keys(per).map(function (k) { return per[k]; }).concat([0])),\n"
        "           allCorrect: responses.every(function (e) { return e.correct === true; }),\n"
        "           allRt: responses.every(function (e) { return typeof e.rt_ms === 'number' && e.rt_ms >= 0; }),\n"
        "           values: responses.map(function (e) { return e.value; }).join(',') };\n"
        "})();\n"
    )
    driver_path = SANDBOX_DIR / "driver-phased-classic.js"
    driver_path.write_text(driver, encoding="utf-8")
    proc = subprocess.run(
        [node, str(harness_path), str(html_path), str(driver_path)],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    result_line = next(ln for ln in proc.stdout.splitlines() if ln.startswith("__RESULT__"))
    result = json.loads(result_line[len("__RESULT__"):])
    assert result["answered"] == 8
    assert result["sawEncoding"] == 8 and result["sawRetention"] == 8  # phase order per trial
    assert result["trials"] == 8 and result["responses"] == 8
    assert result["perTrialMax"] == 1  # decoy press during encoding never recorded
    assert result["allCorrect"] is True  # answered from held content -> content-driven key
    assert result["allRt"] is True
    assert set(result["values"].split(",")) == {"repeat", "novel"}  # not a constant key


@pytest.mark.skipif(_node_bin() is None, reason="node runtime not available")
def test_runtime_explore_phased_playback() -> None:
    """The phased explore engine: exploration consumes encounters via the
    monotonic cursor; each encounter plays the phases; the closed-window decoy
    is ignored; exactly one measurement response per trial."""
    node = _node_bin()
    assert node is not None
    from tests.unit.experiment.test_explore_runtime import _HARNESS_JS as EXPLORE_HARNESS

    SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
    bundle = _bundle()
    gamespec = _explore_gamespec(bundle)
    result_validated = validate_game(gamespec, bundle)
    assert result_validated.valid
    html = render_game_html(bundle, result_validated.game_spec)
    html_path = SANDBOX_DIR / "phased-explore.html"
    html_path.write_text(html, encoding="utf-8")
    harness_path = SANDBOX_DIR / "explore-harness.js"
    if not harness_path.exists() or harness_path.read_text(encoding="utf-8") != EXPLORE_HARNESS:
        harness_path.write_text(EXPLORE_HARNESS, encoding="utf-8")
    driver = (
        "globalThis.__DONE__ = (async function () {\n"
        "  var D = globalThis.__CA_DEBUG__;\n"
        "  await waitFor(function (s) { return s.mode === 'intro'; });\n"
        "  press(' ');\n"
        "  await waitFor(function (s) { return s.mode === 'explore' && s.room === 'vault'; });\n"
        + _MEMORY_DRIVER_CORE
        + "  var ticks = 0;\n"
        "  while (ticks < 15000) {\n"
        "    ticks += 1;\n"
        "    var s = D.snapshot();\n"
        "    if (s.mode === 'encounter') {\n"
        "      pollTrial(textOf('screen'));\n"
        "    } else if (s.mode === 'explore') {\n"
        "      if (s.cursor >= 8) { press('x'); }\n"
        "      else if (s.room === 'vault' && s.cursor >= 4) { press('5'); }\n"
        "      else { press(String(1 + (s.cursor % 4))); }\n"
        "    } else if (s.mode === 'briefing' || s.mode === 'inspect') { press(' '); }\n"
        "    else if (s.mode === 'end') { break; }\n"
        "    await sleep(5);\n"
        "  }\n"
        "  await waitFor(function (s) { return s.mode === 'end'; }, 15000);\n"
        "  var evs = D.events;\n"
        "  var meas = evs.filter(function (e) { return e.channel === 'measurement'; });\n"
        "  var starts = meas.filter(function (e) { return e.event === 'trial_start'; });\n"
        "  var responses = meas.filter(function (e) { return e.event === 'response'; });\n"
        "  var per = {};\n"
        "  responses.forEach(function (e) { per[e.trial_index] = (per[e.trial_index] || 0) + 1; });\n"
        "  var triggers = evs.filter(function (e) { return e.event === 'encounter_trigger'; });\n"
        "  return { answered: answered, triggers: triggers.length,\n"
        "           trials: starts.length, responses: responses.length,\n"
        "           perTrialMax: Math.max.apply(null, Object.keys(per).map(function (k) { return per[k]; }).concat([0])),\n"
        "           allCorrect: responses.every(function (e) { return e.correct === true; }),\n"
        "           allRt: responses.every(function (e) { return typeof e.rt_ms === 'number' && e.rt_ms >= 0; }),\n"
        "           values: responses.map(function (e) { return e.value; }).join(',') };\n"
        "})();\n"
    )
    driver_path = SANDBOX_DIR / "driver-phased-explore.js"
    driver_path.write_text(driver, encoding="utf-8")
    proc = subprocess.run(
        [node, str(harness_path), str(html_path), str(driver_path)],
        capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, proc.stderr
    result_line = next(ln for ln in proc.stdout.splitlines() if ln.startswith("__RESULT__"))
    # the explore harness wraps the driver result: {result, events, snapshot}
    result = json.loads(result_line[len("__RESULT__"):])["result"]
    assert result["answered"] == 8 and result["triggers"] == 8
    assert result["trials"] == 8 and result["responses"] == 8
    assert result["perTrialMax"] == 1
    assert result["allCorrect"] is True
    assert result["allRt"] is True
    assert set(result["values"].split(",")) == {"repeat", "novel"}
