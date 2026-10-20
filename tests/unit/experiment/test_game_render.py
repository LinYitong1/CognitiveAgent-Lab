"""Phase B B2 acceptance tests: the deterministic HTML renderer (contract §11.10 BR-1~BR-5, BR-7, BR-8, BR-10).

Fixture genericity (BR-10): the demo GameSpec is derived dynamically from the golden bundle; key
bindings are generated programmatically from the first letters of the response options — no hand-written fingerprints, no paradigm-specific data.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import cast

import pytest

from src.experiment.canonical import sha256_hex
from src.experiment.game_render import build_run_plan, render_game_html
from src.experiment.game_schemas import validate_game

PROJECT_ROOT = Path(__file__).resolve().parents[3]
GOLDEN_BUNDLE_PATH = PROJECT_ROOT / "tests" / "golden" / "generic-2x2-seed7.json"
GOLDEN_HTML_PATH = PROJECT_ROOT / "tests" / "golden" / "game-generic-demo.html"

# the number of script tags inherent to the template (one pair for the data block and one for the engine block)
_TEMPLATE_SCRIPT_TAGS = 2


def _load_bundle() -> dict[str, object]:
    return json.loads(GOLDEN_BUNDLE_PATH.read_text(encoding="utf-8"))


def demo_game_spec(bundle: dict[str, object]) -> dict[str, object]:
    """Demo GameSpec (the single source of the golden rendered file; keys = option first letters, generated programmatically)."""
    spec_part = cast(dict[str, object], bundle["spec"])
    repro = cast(dict[str, object], bundle["reproducibility"])
    responses = cast(list[object], spec_part["responses"])
    choice = cast(dict[str, object], next(r for r in responses if cast(dict[str, object], r)["kind"] == "choice"))
    options = cast(list[str], choice["options"])
    keys = {option[:1]: option for option in options}
    return {
        "schema_version": 1,
        "game": {"name": "generic-demo", "version": "0.1.0"},
        "experiment_ref": {
            "name": spec_part["name"],
            "version": spec_part["version"],
            "seed": spec_part["seed"],
            "config_fingerprint": repro["config_fingerprint"],
            "trials_fingerprint": repro["trials_fingerprint"],
            "bundle_sha256": bundle["bundle_sha256"],
        },
        "scene": {
            "title": "Condition Judgement Demo",
            "instructions": "Watch each trial and press the key matching your answer.",
        },
        "input": {
            "modalities": ["keyboard"],
            "bindings": [{"response_name": choice["name"], "keys": keys}],
        },
        "feedback": {"on_response": "outcome-text", "duration_ms": 400},
    }


def _validated_spec(bundle: dict[str, object]):
    result = validate_game(demo_game_spec(bundle), bundle)
    assert result.valid is True, result.errors
    assert result.game_spec is not None
    return result.game_spec


def _render(bundle: dict[str, object]) -> str:
    return render_game_html(bundle, _validated_spec(bundle))


# ---------- extraction helpers (extract embedded data back from the final HTML; intermediate artifacts are not trusted) ----------

def _extract_string_literal(html: str, pattern: str) -> str:
    """Extract the JS string literal body (escaped form) and json.loads it back to the original text."""
    m = re.search(pattern, html)
    assert m is not None, f"pattern not found: {pattern}"
    return cast(str, json.loads('"' + m.group(1) + '"'))


def _extract_plan(html: str) -> dict[str, object]:
    text = _extract_string_literal(html, r'const PLAN = JSON\.parse\("(.*?)(?<!\\)"\);')
    return cast(dict[str, object], json.loads(text))


def _extract_trials_canonical(html: str) -> str:
    return _extract_string_literal(html, r'const TRIALS_CANONICAL = "(.*?)(?<!\\)";')


def _extract_bundle_canonical(html: str) -> str:
    return _extract_string_literal(html, r'const BUNDLE_CANONICAL = "(.*?)(?<!\\)";')


# ---------- BR-1: determinism + golden file ----------

def test_br1_render_is_deterministic() -> None:
    bundle = _load_bundle()
    assert _render(bundle) == _render(bundle)


def test_br1_matches_committed_golden_html() -> None:
    bundle = _load_bundle()
    assert _render(bundle) == GOLDEN_HTML_PATH.read_text(encoding="utf-8")


def test_br1_golden_html_shape() -> None:
    html = GOLDEN_HTML_PATH.read_text(encoding="utf-8")
    assert html.startswith("<!DOCTYPE html>")
    assert html.count("<script>") == _TEMPLATE_SCRIPT_TAGS
    assert html.count("</script>") == _TEMPLATE_SCRIPT_TAGS


# ---------- BR-2: run-plan data integrity (the D-4 logic core, browser-free) ----------

def test_br2_trial_steps_mirror_bundle_trials_exactly() -> None:
    bundle = _load_bundle()
    plan = build_run_plan(bundle, _validated_spec(bundle))
    steps = cast(list[object], plan["steps"])
    trial_steps = [s for s in steps if cast(dict[str, object], s)["type"] == "trial"]
    trials = cast(list[object], bundle["trials"])

# one-to-one correspondence with consistent ordering
    assert [cast(dict[str, object], s)["index"] for s in trial_steps] == [
        cast(dict[str, object], t)["index"] for t in trials
    ]
    spec_part = cast(dict[str, object], bundle["spec"])
    responses = cast(list[object], spec_part["responses"])

    for step_raw, trial_raw in zip(trial_steps, trials):
        step = cast(dict[str, object], step_raw)
        trial = cast(dict[str, object], trial_raw)
        assert step["block"] == trial["block"]
        assert step["timing"] == trial["timing"]
        # display covers all factors (plus stimulus if non-empty)
        factors = cast(dict[str, object], trial["factors"])
        display = {k: v for k, v in cast(list[list[object]], step["display"])}
        for fname, fval in factors.items():
            assert display[fname] == fval
        # correct answer = the bundle's factor value (the authoritative source for correct_from)
        correct = cast(dict[str, object], step["correct"])
        for r_raw in responses:
            r = cast(dict[str, object], r_raw)
            cf = r.get("correct_from")
            if isinstance(cf, str):
                assert correct[cast(str, r["name"])] == factors[cf]
            else:
                assert cast(str, r["name"]) not in correct


def test_br2_extracted_plan_matches_builder() -> None:
    """The PLAN embedded in the HTML is value-equal to build_run_plan's output (lossless embedding)."""
    bundle = _load_bundle()
    html = _render(bundle)
    assert _extract_plan(html) == build_run_plan(bundle, _validated_spec(bundle))


# ---------- BR-3: state-machine flow switches ----------

def _spec_with_overrides(bundle: dict[str, object], **flow: object) -> dict[str, object]:
    spec = demo_game_spec(bundle)
    flow_spec = cast(dict[str, object], spec.setdefault("flow", {}))
    flow_spec.update(flow)
    return spec


def test_br3_flow_flags_shape_steps() -> None:
    bundle = _load_bundle()
    gs = _validated_spec(bundle)
    plan = build_run_plan(bundle, gs)
    steps = [cast(dict[str, object], s) for s in cast(list[object], plan["steps"])]
    types = [s["type"] for s in steps]

    # default flow: ready opening, exactly one break between blocks, end closing
    assert types[0] == "ready"
    assert types[-1] == "end"
    breaks = [s for s in steps if s["type"] == "block_break"]
    assert len(breaks) == 1
    assert breaks[0]["completed_block"] == "practice"
    assert breaks[0]["next_block"] == "main"
    assert breaks[0]["done_trials"] == 8
    assert breaks[0]["total_trials"] == 48
    # the break sits after the 8th trial (practice has 8 trials)
    first_break_idx = types.index("block_break")
    trial_positions = [i for i, t in enumerate(types) if t == "trial"]
    assert first_break_idx == trial_positions[7] + 1

    # ready_screen=False → no ready step
    result = validate_game(_spec_with_overrides(bundle, ready_screen=False), bundle)
    assert result.valid and result.game_spec
    steps2 = [cast(dict[str, object], s) for s in cast(list[object], build_run_plan(bundle, result.game_spec)["steps"])]
    assert steps2[0]["type"] == "trial"

    # block_breaks=False → no break step
    result = validate_game(_spec_with_overrides(bundle, block_breaks=False), bundle)
    assert result.valid and result.game_spec
    steps3 = [cast(dict[str, object], s) for s in cast(list[object], build_run_plan(bundle, result.game_spec)["steps"])]
    assert all(s["type"] != "block_break" for s in steps3)

    # end_screen="none" → the end step still exists (the event log must stay exportable) but summary=False
    result = validate_game(_spec_with_overrides(bundle, end_screen="none"), bundle)
    assert result.valid and result.game_spec
    steps4 = [cast(dict[str, object], s) for s in cast(list[object], build_run_plan(bundle, result.game_spec)["steps"])]
    assert steps4[-1]["type"] == "end"
    assert steps4[-1]["summary"] is False


# ---------- BR-4: presentation-layer isolation (GameSpec presentation fields must not affect experiment data) ----------

def test_br4_presentation_changes_do_not_touch_trial_steps() -> None:
    bundle = _load_bundle()
    base_plan = build_run_plan(bundle, _validated_spec(bundle))

    varied = demo_game_spec(bundle)
    scene = cast(dict[str, object], varied["scene"])
    scene["theme"] = "dark"
    scene["layout"] = "rows"
    scene["title"] = "A Different Presentation"
    varied["feedback"] = {"on_response": "correctness-flash", "duration_ms": 120}
    result = validate_game(varied, bundle)
    assert result.valid and result.game_spec

    varied_plan = build_run_plan(bundle, result.game_spec)
    base_steps = [s for s in cast(list[object], base_plan["steps"]) if cast(dict[str, object], s)["type"] == "trial"]
    varied_steps = [s for s in cast(list[object], varied_plan["steps"]) if cast(dict[str, object], s)["type"] == "trial"]
    assert base_steps == varied_steps


# ---------- BR-5: output security (escaping + engine static constraints) ----------

def _malicious_spec(bundle: dict[str, object]) -> dict[str, object]:
    spec = demo_game_spec(bundle)
    scene = cast(dict[str, object], spec["scene"])
    scene["title"] = "</script><script>alert(1)</script>"
    scene["instructions"] = '<img src=x onerror="alert(2)"> "quotes" \\ backslash'
    return spec


def test_br5_malicious_text_never_breaks_out() -> None:
    bundle = _load_bundle()
    result = validate_game(_malicious_spec(bundle), bundle)
    assert result.valid is True, result.errors  # legal at the schema layer (no content constraints on presentation text)
    assert result.game_spec is not None
    html = render_game_html(bundle, result.game_spec)

    # the template's inherent </script> count is not broken by data
    assert html.count("</script>") == _TEMPLATE_SCRIPT_TAGS
    assert "<script>alert" not in html
    # malicious text in <title> appears only in html.escape form
    assert "&lt;/script&gt;" in html
    # malicious text embedded in PLAN round-trips fully after JSON escaping (not executed, not distorted)
    plan = _extract_plan(html)
    meta = cast(dict[str, object], plan["meta"])
    assert meta["title"] == "</script><script>alert(1)</script>"
    assert cast(str, meta["instructions"]).startswith("<img src=x onerror=")
    # engine security constraints: no dangerous DOM APIs / eval
    for banned in ("innerHTML", "insertAdjacentHTML", "document.write", "eval("):
        assert banned not in html, f"banned API {banned!r} present in rendered HTML"


def test_br5_placeholder_injection_is_inert() -> None:
    """User text containing template placeholder literals must not inject into template assembly (split interleaving blocks injection)."""
    bundle = _load_bundle()
    spec = demo_game_spec(bundle)
    scene = cast(dict[str, object], spec["scene"])
    scene["title"] = "__TITLE__ __BODY_CLASS__ __DATA__"
    result = validate_game(spec, bundle)
    assert result.valid and result.game_spec
    html = render_game_html(bundle, result.game_spec)
    plan = _extract_plan(html)
    assert cast(dict[str, object], plan["meta"])["title"] == "__TITLE__ __BODY_CLASS__ __DATA__"
    # the template structure is not broken: placeholders appear only inside data strings (escaped); the HTML still has two script tag pairs
    assert html.count("<script>") == _TEMPLATE_SCRIPT_TAGS


# ---------- BR-7: embedded integrity anchors (build-time defense) ----------

def test_br7_embedded_canonical_anchors_match_fingerprints() -> None:
    bundle = _load_bundle()
    html = _render(bundle)
    repro = cast(dict[str, object], bundle["reproducibility"])

    trials_text = _extract_trials_canonical(html)
    assert sha256_hex(trials_text) == repro["trials_fingerprint"]
    assert json.loads(trials_text) == bundle["trials"]

    bundle_text = _extract_bundle_canonical(html)
    assert sha256_hex(bundle_text) == bundle["bundle_sha256"]
    # stripping rule: bundle_canonical excludes bundle_sha256 / generated_at
    parsed = cast(dict[str, object], json.loads(bundle_text))
    assert "bundle_sha256" not in parsed
    assert "generated_at" not in parsed


# ---------- BR-8: runtime integrity decision (run under node when available, skip otherwise) ----------

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


@pytest.mark.skipif(_node_bin() is None, reason="node runtime not available")
def test_br8_runtime_integrity_check_passes_in_node() -> None:
    node = _node_bin()
    assert node is not None
    bundle = _load_bundle()
    html = _render(bundle)
    script1 = html.split("<script>")[1].split("</script>")[0]
    assert "document" not in script1  # the data block has no DOM dependency (the premise for node to run it standalone)

    probe = script1 + '\nconsole.log(JSON.stringify(integrity));\n'
    proc = subprocess.run([node, "-e", probe], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout.strip().splitlines()[-1])
    assert report == {"ok": True, "bundle_ok": True, "trials_ok": True}


@pytest.mark.skipif(_node_bin() is None, reason="node runtime not available")
def test_br8_integrity_check_detects_tampering_in_node() -> None:
    node = _node_bin()
    assert node is not None
    bundle = _load_bundle()
    html = _render(bundle)
    script1 = html.split("<script>")[1].split("</script>")[0]
    probe = (
        script1
        + '\nvar tampered = sha256Hex(TRIALS_CANONICAL + "x") !== EXPECTED.trials_fingerprint'
        + " && sha256Hex(BUNDLE_CANONICAL + \"x\") !== EXPECTED.bundle_sha256;\n"
        + "console.log(JSON.stringify({tampered: tampered}));\n"
    )
    proc = subprocess.run([node, "-e", probe], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout.strip().splitlines()[-1]) == {"tampered": True}


# ---------- BR-10: genericity ----------

def test_br10_no_paradigm_hardcoding_in_render_source() -> None:
    for rel in ("src/experiment/game_render.py", "src/tools/game_tools.py"):
        source = (PROJECT_ROOT / rel).read_text(encoding="utf-8").lower()
        for token in ("stroop", "nback", "n-back", "flanker", "go/no-go"):
            assert token not in source, f"paradigm name {token!r} hardcoded in {rel}"


def test_br10_golden_html_derives_from_golden_bundle() -> None:
    """The golden HTML is rendered from the golden bundle + the derived GameSpec (proven by the BR-1 golden match)."""
    bundle = _load_bundle()
    assert sha256_hex(_render(bundle)) == sha256_hex(GOLDEN_HTML_PATH.read_text(encoding="utf-8"))
