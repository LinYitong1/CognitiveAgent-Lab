"""E1 scorer regression tests: pin the offline validation matrix.

These tests use ONLY in-code reference fixtures (no dependency on the
gitignored historical artifacts under data/.test-sandbox/). The scorer's
behavior on the REAL historical T5/T2R artifacts is additionally demonstrated
by `python -m scripts.e1_scorer --selfcheck` (results captured in
docs/agent-evaluation/04-offline-validation.md).

The core acceptance property (the E1-A gate): the T2R nominal-manipulation
signature MUST be caught (D4 FAIL) while schema validity passes — schema
validity is not scientific validity.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, cast

import pytest

from scripts.e1_scorer import (
    FAIL,
    INCONCLUSIVE,
    NOT_APPLICABLE,
    PASS,
    _flanker_reference,
    _taskswitch_reference,
    _t2r_nominal_reference,
    _wm_reference,
    check_answer_recomputation,
    check_real_manipulation,
    check_run_record,
    score_artifacts,
)
from src.experiment.export import build_bundle
from src.experiment.schemas import ExperimentSpec

REPO_ROOT = Path(__file__).resolve().parents[3]
SANDBOX = REPO_ROOT / "data" / ".test-sandbox" / "e1-scorer-tests"


def _bundle(config: dict[str, Any]) -> dict[str, Any]:
    return build_bundle(
        ExperimentSpec.model_validate(config), generated_at="2000-01-01T00:00:00Z"
    )


def _score(bundle: dict[str, Any], task: str) -> tuple[str, str, str]:
    d4 = check_real_manipulation(bundle, task)
    d5 = check_answer_recomputation(bundle, task)
    return cast(str, d4["verdict"]), cast(str, d5["verdict"]), cast(str, d4["detail"])


def test_flanker_reference_passes() -> None:
    d4, d5, detail = _score(_bundle(_flanker_reference()), "e1_flanker")
    assert d4 == PASS, detail
    assert d5 == PASS


def test_wm_reference_passes() -> None:
    d4, d5, detail = _score(_bundle(_wm_reference()), "e1_wm")
    assert d4 == PASS, detail
    assert d5 == PASS


def test_taskswitch_reference_passes() -> None:
    d4, d5, detail = _score(_bundle(_taskswitch_reference()), "e1_taskswitch")
    assert d4 == PASS, detail
    assert d5 == PASS


def test_t2r_nominal_signature_must_fail() -> None:
    """THE E1-A gate: the T2R nominal-manipulation pattern fails D4 even
    though the bundle is schema-valid and verify_bundle-clean."""
    bundle = _bundle(_t2r_nominal_reference())
    d4, d5, detail = _score(bundle, "e1_t2r_regression")
    assert d4 == FAIL, detail
    assert "nominal manipulation" in detail
    # the nominal design's answer key is still (trivially) consistent — D5
    # passes there and CANNOT be the T2R detector; D4 is
    assert d5 == PASS


def test_inverted_keys_fail_d5() -> None:
    bundle = _bundle(_wm_reference())
    for trial in cast(list[dict[str, Any]], bundle["trials"]):
        if trial.get("correct"):
            trial["correct"]["judge"] = (
                "novel" if trial["correct"]["judge"] == "repeat" else "repeat"
            )
    d4, d5, _ = _score(bundle, "e1_wm")
    assert d4 == PASS  # content is untouched
    assert d5 == FAIL  # direction contradicts the declared correct_rule


def test_ambiguous_content_fails_d5() -> None:
    """Identical displayed content with different keys = answer not derivable."""
    config: dict[str, Any] = {
        "schema_version": 2,
        "name": "ambiguous-content",
        "version": "0.1.0",
        "seed": 1,
        "factors": [{"name": "cue", "levels": [{"name": "a"}, {"name": "b"}]}],
        "blocks": [{"name": "main", "trial_count": 4}],
        "constraints": {"balance": True},
        "responses": [
            {"name": "answer", "kind": "choice", "options": ["a", "b"], "correct_from": "cue"}
        ],
        "timing": {"fixation_ms": 100, "stimulus_ms": None, "isi_ms": 100},
        "stimulus_spec": {
            "factors": {
                "cue": {
                    # BOTH levels render the identical line: content cannot
                    # determine the key (and the manipulation is nominal)
                    "levels": {"a": [["X X X"]], "b": [["X X X"]]},
                    "match_line_count": True,
                }
            },
            "pools": {},
        },
    }
    bundle = _bundle(config)
    d4, d5, _ = _score(bundle, "e1_flanker")
    assert d4 == FAIL  # identical masked content -> nominal manipulation
    assert d5 == FAIL  # identical content maps to different keys ("a" and "b")


def test_run_record_d1_separation() -> None:
    """T5-style completed run -> D1 PASS; T2R-style budget-stop -> D1 FAIL."""
    t5_report = {
        "scenarios": [{
            "loop_status": "completed",
            "n_tool_calls": 6,
            "tool_calls": [
                {"tool": "validate_experiment", "ok": True},
                {"tool": "validate_game", "ok": True},
                {"tool": "validate_game", "ok": True},
                {"tool": "validate_game", "ok": True},
                {"tool": "render_game", "ok": True},
            ],
            "detail": "prompt -> bundle -> playable HTML",
            "llm_calls": 7,
            "wall_s": 95.1,
            "tokens_total": 32001,
            "tokens_in": 27996,
            "tokens_out": 2332,
            "cost_estimate_usd": 0.036,
        }]
    }
    dims = check_run_record("e1_t5_retest", t5_report)
    assert dims["D1_task_completion"]["verdict"] == PASS
    assert dims["D2_tool_calls"]["verdict"] == PASS
    assert dims["D7_self_repair"]["verdict"] == PASS
    assert dims["D8_efficiency"]["verdict"] == PASS

    t2r_report = {
        "scenarios": [{
            "loop_status": "failed",
            "n_tool_calls": 10,
            "tool_calls": [{"tool": "validate_experiment", "ok": True}],
            "detail": "budget-stop",
            "llm_calls": 10,
            "wall_s": 139.5,
            "tokens_total": 99768,
            "tokens_in": 89953,
            "tokens_out": 6135,
            "cost_estimate_usd": 0.1043,
        }]
    }
    dims = check_run_record("e1_t2r_regression", t2r_report)
    assert dims["D1_task_completion"]["verdict"] == FAIL  # no render_game, loop failed
    assert dims["D7_self_repair"]["verdict"] == FAIL  # adapted but never completed


def test_d8_not_applicable_without_usage() -> None:
    report = {"scenarios": [{
        "loop_status": "completed", "n_tool_calls": 1,
        "tool_calls": [{"tool": "render_game", "ok": True}],
        "detail": "d",
    }]}
    dims = check_run_record("e1_t5_retest", report)
    assert dims["D8_efficiency"]["verdict"] == NOT_APPLICABLE


def test_unknown_task_rejected() -> None:
    with pytest.raises(SystemExit):
        score_artifacts("nope", Path("/dev/null"), None)


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
def test_d6_generic_html_driver_on_reference_game() -> None:
    from src.experiment.game_render import render_game_html
    from src.experiment.game_schemas import validate_game

    SANDBOX.mkdir(parents=True, exist_ok=True)
    bundle = _bundle(_flanker_reference())
    spec = cast(dict[str, Any], bundle["spec"])
    repro = cast(dict[str, Any], bundle["reproducibility"])
    gamespec = {
        "schema_version": 1,
        "game": {"name": "flanker-ref", "version": "0.1.0"},
        "experiment_ref": {
            "name": spec["name"], "version": spec["version"], "seed": spec["seed"],
            "config_fingerprint": repro["config_fingerprint"],
            "trials_fingerprint": repro["trials_fingerprint"],
            "bundle_sha256": bundle["bundle_sha256"],
        },
        "scene": {"title": "t", "instructions": "i"},
        "input": {"modalities": ["keyboard"],
                  "bindings": [{"response_name": "answer", "keys": {"l": "left", "r": "right"}}]},
        "feedback": {"on_response": "outcome-text", "duration_ms": 20},
    }
    result = validate_game(gamespec, bundle)
    assert result.valid and result.game_spec is not None
    html = render_game_html(bundle, result.game_spec)
    html_path = SANDBOX / "flanker-ref.html"
    html_path.write_text(html, encoding="utf-8")
    bundle_path = SANDBOX / "flanker-ref.json"
    bundle_path.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    scored = score_artifacts("e1_flanker", bundle_path, html_path)
    d6 = scored["D6_html_interaction"]
    assert d6["verdict"] == PASS, d6
    assert "8 trials" in str(d6["detail"])


# ---------------------------------------------------------------------------
# E1-B preflight: task-level acceptance invariants + adversarial samples
# ---------------------------------------------------------------------------

from scripts.e1_scorer import (  # noqa: E402
    _flanker_congruency_not_in_flanks_bad,
    _flanker_four_arrows_bad,
    _flanker_key_from_congruency_bad,
    _t2r_good_reference,
    _t2r_two_rooms_game_bad,
    _t5_identical_content_bad,
    _t5_reference,
    _t5_unbalanced_bad,
    _taskswitch_flipped_bad,
    _wm_probe_shows_set_bad,
    _wm_three_words_bad,
    check_task_invariants,
)
from src.experiment.game_schemas import validate_game  # noqa: E402
from src.experiment.explore_render import render_explore_html  # noqa: E402


def _inv(bundle: dict[str, Any], task: str) -> dict[str, Any]:
    return check_task_invariants(bundle, task)


def test_task_invariants_pass_on_references() -> None:
    """The five good references satisfy their own task-level requirements."""
    for task, config in (
        ("e1_t5_retest", _t5_reference()),
        ("e1_flanker", _flanker_reference()),
        ("e1_wm", _wm_reference()),
        ("e1_taskswitch", _taskswitch_reference()),
        ("e1_t2r_regression", _t2r_good_reference()),
    ):
        inv = _inv(_bundle(config), task)
        assert not inv["d4_problems"], (task, inv["d4_problems"])
        assert not inv["d5_problems"], (task, inv["d5_problems"])
        assert inv["notes"], task  # each task produced affirmative evidence


def test_flanker_four_arrows_flagged() -> None:
    inv = _inv(_bundle(_flanker_four_arrows_bad()), "e1_flanker")
    assert any("arrow characters" in p for p in inv["d4_problems"])


def test_flanker_center_key_flagged() -> None:
    inv = _inv(_bundle(_flanker_key_from_congruency_bad()), "e1_flanker")
    assert any("middle arrow" in p for p in inv["d5_problems"])
    assert not inv["d4_problems"]  # content manipulation itself is real


def test_flanker_congruency_not_in_flanks_flagged() -> None:
    inv = _inv(_bundle(_flanker_congruency_not_in_flanks_bad()), "e1_flanker")
    assert any("never varies" in p for p in inv["d4_problems"])
    assert any("not analyzable" in p for p in inv["d4_problems"])


def test_wm_three_words_flagged() -> None:
    inv = _inv(_bundle(_wm_three_words_bad()), "e1_wm")
    assert any("memorized words" in p for p in inv["d4_problems"])


def test_wm_probe_shows_set_flagged() -> None:
    inv = _inv(_bundle(_wm_probe_shows_set_bad()), "e1_wm")
    assert any("probe phase shows" in p for p in inv["d4_problems"])


def test_taskswitch_flipped_direction_flagged() -> None:
    """Mappings consistent, inverted, balanced — but the literal direction is
    flipped: only the brief-level check catches it."""
    inv = _inv(_bundle(_taskswitch_flipped_bad()), "e1_taskswitch")
    assert any("literal direction" in p for p in inv["d5_problems"])
    assert not inv["d4_problems"]


def test_t5_unbalanced_flagged() -> None:
    inv = _inv(_bundle(_t5_unbalanced_bad()), "e1_t5_retest")
    assert any("not balanced" in p for p in inv["d4_problems"])


def test_t5_identical_content_flagged() -> None:
    inv = _inv(_bundle(_t5_identical_content_bad()), "e1_t5_retest")
    assert any("identical content" in p for p in inv["d4_problems"])


def _write_t2r_artifacts(game_config: dict[str, Any], tag: str) -> tuple[Path, Path]:
    bundle = _bundle(_t2r_good_reference())
    result = validate_game(game_config, bundle)
    assert result.valid and result.game_spec is not None, [str(e) for e in result.errors]
    html = render_explore_html(bundle, result.game_spec)
    bundle_path = SANDBOX / f"{tag}-bundle.json"
    html_path = SANDBOX / f"{tag}.html"
    bundle_path.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    html_path.write_text(html, encoding="utf-8")
    return bundle_path, html_path


def test_t2r_two_rooms_flagged_via_html() -> None:
    """A schema-valid explore game with only 2 rooms must FAIL the brief's
    >= 3 rooms requirement (checked from the rendered HTML's PLAN)."""
    bundle_path, html_path = _write_t2r_artifacts(_t2r_two_rooms_game_bad(), "t2r-two-rooms")
    scored = score_artifacts("e1_t2r_regression", bundle_path, html_path)
    d4 = scored["D4_real_manipulation"]
    assert d4["verdict"] == FAIL, d4
    assert "explorable room" in d4["detail"]
    # the good-side checks (load, membership, balance) still hold on this bundle
    assert "matches the computed encoding sizes" in d4["detail"]


def test_t2r_good_reference_html_passes() -> None:
    """A 3-room brief-compliant explore game passes D4 with an explicit
    INCONCLUSIVE marker for runtime exploration-order invariance (manual)."""
    game = _t2r_two_rooms_game_bad()  # reuse the builder, then widen to 3 rooms
    game["game"]["name"] = "t2r-good"
    rooms = cast(dict[str, Any], game["world"]["rooms"])
    encs = cast(list[dict[str, Any]], game["mapping"]["encounter_objects"])
    half = len(encs) // 2
    rooms["hall"]["objects"] = [
        {"object_id": oid, "label": oid, "inspect_text": "A panel.", "role": "encounter"}
        for oid in encs[:half]
    ]
    rooms["lab"]["objects"] = [
        {"object_id": "dust", "label": "dust", "inspect_text": "Dust.", "role": "flavour"}
    ]
    rooms["bridge"] = {
        "title": "Bridge", "description": "Connector.",
        "exits": {"hall": "back to the hall"},
        "objects": [
            {"object_id": oid, "label": oid, "inspect_text": "A panel.", "role": "encounter"}
            for oid in encs[half:]
        ],
    }
    rooms["hall"]["exits"]["bridge"] = "to the bridge"
    bundle_path, html_path = _write_t2r_artifacts(game, "t2r-good")
    scored = score_artifacts("e1_t2r_regression", bundle_path, html_path)
    d4 = scored["D4_real_manipulation"]
    assert d4["verdict"] == PASS, d4
    assert "3 explorable rooms" in d4["detail"]
    assert any("MANUAL ACCEPTANCE" in i for i in scored["task_invariants"]["inconclusive"])


def test_scorer_version_pinned() -> None:
    from scripts.e1_scorer import SCORER_VERSION
    assert SCORER_VERSION == "e1-scorer-v2"
