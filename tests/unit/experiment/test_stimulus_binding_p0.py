"""M3-A P0 tests: intra-trial variables, content reference, content-driven correctness.

Scope (no P1/P2): variables bound inside a trial, references to already-bound
content, and an answer key computed from that content. The fixture is composed
only from the generic primitives (factors / pools / counts / references /
closed relations) — the engine contains no paradigm vocabulary, which
test_engine_has_no_paradigm_vocabulary enforces.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import cast

import pytest

from src.experiment.canonical import canonical_json
from src.experiment.export import build_bundle
from src.experiment.game_render import build_run_plan
from src.experiment.schemas import ExperimentSpec
from src.experiment.validation import ErrorCode, validate_spec
from src.experiment.verify import verify_bundle

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXED_GENERATED_AT = "2000-01-01T00:00:00Z"

TOKENS = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta"]


def _spec(**overrides: object) -> dict[str, object]:
    """A generic composition: one factor sets how many elements a variable binds
    (real content difference), one factor selects how a second variable is bound
    (reuse vs. disjoint draw), and a closed relation scores it."""
    config: dict[str, object] = {
        "schema_version": 2,
        "name": "p0-binding",
        "version": "0.1.0",
        "seed": 20261022,
        "factors": [
            {"name": "size", "levels": [{"name": "few"}, {"name": "many"}]},
            {"name": "relation", "levels": [{"name": "repeat"}, {"name": "novel"}]},
        ],
        "blocks": [{"name": "main", "trial_count": 12}],
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
        "timing": {"fixation_ms": 300, "stimulus_ms": None, "isi_ms": 500},
        "stimulus_spec": {
            "factors": {
                "size": {
                    "levels": {
                        "few": [["Items: {var:items}", "Probe: {var:probe}"]],
                        "many": [["Items: {var:items}", "Probe: {var:probe}"]],
                    },
                    "match_line_count": True,
                }
            },
            "pools": {"tokens": list(TOKENS)},
            "variables": [
                {
                    "name": "items",
                    "pool": "tokens",
                    "count": {"factor": "size", "levels": {"few": 2, "many": 5}},
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
        },
    }
    config.update(overrides)
    return config


def _bundle(config: dict[str, object]) -> dict[str, object]:
    return build_bundle(
        ExperimentSpec.model_validate(config), generated_at=FIXED_GENERATED_AT
    )


def _lines(trial: dict[str, object]) -> tuple[list[str], str]:
    """(items, probe) re-parsed from the rendered stimulus text."""
    stimulus = cast(dict[str, object], trial["stimulus"])
    rendered = cast(list[str], stimulus["lines"])
    return rendered[0].removeprefix("Items: ").split(), rendered[1].removeprefix("Probe: ")


def _codes(result: object) -> list[str]:
    return [issue.error_code for issue in result.errors]  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# 1. Variables: a factor level produces different materialized content
# ---------------------------------------------------------------------------

def test_valid_and_balanced() -> None:
    result = validate_spec(_spec())
    assert result.valid, [(e.error_code, e.path, e.message) for e in result.errors]
    bundle = _bundle(_spec())
    combos = Counter(
        (cast(dict[str, str], t["factors"])["size"], cast(dict[str, str], t["factors"])["relation"])
        for t in cast(list[object], bundle["trials"])
    )
    assert len(combos) == 4 and set(combos.values()) == {3}


def test_count_map_makes_levels_differ_in_content() -> None:
    """few/many is not a label: the rendered item list has a different length."""
    trials = cast(list[dict[str, object]], _bundle(_spec())["trials"])
    lengths: dict[str, set[int]] = {}
    for trial in trials:
        factors = cast(dict[str, str], trial["factors"])
        items, _ = _lines(trial)
        lengths.setdefault(factors["size"], set()).add(len(items))
    assert lengths == {"few": {2}, "many": {5}}, lengths
    assert len(lengths["few"] | lengths["many"]) == 2  # conditions are not content-identical


def test_pool_draw_without_count_binds_one_element() -> None:
    config = _spec(
        stimulus_spec={
            "factors": {
                "size": {
                    "levels": {
                        "few": [["Item: {var:one}"]],
                        "many": [["Item: {var:one}"]],
                    },
                    "match_line_count": True,
                }
            },
            "pools": {"tokens": list(TOKENS)},
            "variables": [{"name": "one", "pool": "tokens"}],
        },
        responses=[
            {"name": "judge", "kind": "choice", "options": ["repeat", "novel"], "correct_from": None}
        ],
    )
    result = validate_spec(config)
    assert result.valid, _codes(result)
    trial = cast(list[dict[str, object]], _bundle(config)["trials"])[0]
    rendered = cast(list[str], cast(dict[str, object], trial["stimulus"])["lines"])
    assert rendered[0].removeprefix("Item: ") in TOKENS


# ---------------------------------------------------------------------------
# 2. Reference: later content reuses earlier content (no re-draw)
# ---------------------------------------------------------------------------

def test_reference_reuses_bound_content() -> None:
    trials = cast(list[dict[str, object]], _bundle(_spec())["trials"])
    repeat_seen = novel_seen = 0
    for trial in trials:
        factors = cast(dict[str, str], trial["factors"])
        items, probe = _lines(trial)
        if factors["relation"] == "repeat":
            assert probe in items, trial  # reuse: the probe is one of the bound elements
            repeat_seen += 1
        else:
            assert probe not in items, trial  # constrained draw: disjoint by construction
            novel_seen += 1
    assert repeat_seen == 6 and novel_seen == 6


def test_positional_reference_is_exact() -> None:
    """copy_from with an integer index reuses that exact element (no draw at all)."""
    config = _spec()
    stimulus = cast(dict[str, object], config["stimulus_spec"])
    stimulus["variables"] = [
        {"name": "items", "pool": "tokens", "count": 3},
        {"name": "third", "copy_from": {"var": "items", "index": 2}},
    ]
    cast(dict[str, object], stimulus["factors"])["size"] = {
        "levels": {
            "few": [["Items: {var:items}", "Probe: {var:third}"]],
            "many": [["Items: {var:items}", "Probe: {var:third}"]],
        },
        "match_line_count": True,
    }
    config["responses"] = [
        {"name": "judge", "kind": "choice", "options": ["repeat", "novel"], "correct_from": None}
    ]
    result = validate_spec(config)
    assert result.valid, _codes(result)
    for trial in cast(list[dict[str, object]], _bundle(config)["trials"]):
        items, probe = _lines(trial)
        assert probe == items[2]


# ---------------------------------------------------------------------------
# 3. Content-driven correctness
# ---------------------------------------------------------------------------

def test_answer_key_follows_materialized_content() -> None:
    """Recompute the expected option from the RENDERED text: it must equal trial.correct."""
    trials = cast(list[dict[str, object]], _bundle(_spec())["trials"])
    assert trials
    for trial in trials:
        items, probe = _lines(trial)
        expected = "repeat" if probe in items else "novel"
        assert cast(dict[str, str], trial["correct"])["judge"] == expected, trial


def test_answer_key_flips_when_the_binding_flips() -> None:
    """Swapping which binding each level uses flips the derived answer key."""
    base = _bundle(_spec())
    flipped = _spec()
    variables = cast(list[dict[str, object]], cast(dict[str, object], flipped["stimulus_spec"])["variables"])
    variables[1]["when"] = {"relation": "novel"}
    variables[2]["when"] = {"relation": "repeat"}
    other = _bundle(flipped)
    base_keys = [cast(dict[str, str], t["correct"])["judge"] for t in cast(list[object], base["trials"])]
    other_keys = [cast(dict[str, str], t["correct"])["judge"] for t in cast(list[object], other["trials"])]
    assert len(base_keys) == len(other_keys)
    assert set(base_keys) == {"repeat", "novel"}, "the answer key is constant — not content-driven"
    # every trial swaps its binding, so every answer key must follow
    assert all(a != b for a, b in zip(base_keys, other_keys)), "the answer key ignored the binding"


def test_correct_rule_on_v1_spec_is_version_mismatch() -> None:
    config = _spec(schema_version=1)
    result = validate_spec(config)
    assert not result.valid
    assert ErrorCode.V2_VERSION_MISMATCH in _codes(result)


def test_correct_from_still_supported_and_rule_conflict_detected() -> None:
    """correct_from (label-derived) remains legal; declaring both sources is rejected."""
    label_only = _spec(
        responses=[
            {"name": "judge", "kind": "choice", "options": ["few", "many"], "correct_from": "size"}
        ]
    )
    assert validate_spec(label_only).valid, _codes(validate_spec(label_only))
    both = _spec(
        responses=[
            {
                "name": "judge",
                "kind": "choice",
                "options": ["repeat", "novel"],
                "correct_from": "size",
                "correct_rule": {
                    "op": "in",
                    "left": {"var": "probe"},
                    "right": {"var": "items"},
                    "true_option": "repeat",
                    "false_option": "novel",
                },
            }
        ]
    )
    assert ErrorCode.V2_RULE_CONFLICT in _codes(validate_spec(both))


# ---------------------------------------------------------------------------
# 4. Determinism / integrity / renderers
# ---------------------------------------------------------------------------

def test_bundle_reproducible_and_verifiable() -> None:
    bundle = _bundle(_spec())
    assert canonical_json(bundle) == canonical_json(_bundle(_spec()))
    path = Path("data/.test-sandbox/p0") / "bundle.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(bundle), encoding="utf-8")
    try:
        report = verify_bundle(path)
        assert report.ok, report.detail
    finally:
        path.unlink(missing_ok=True)


def test_materialization_is_hashseed_independent() -> None:
    code = (
        "import json,sys;sys.path.insert(0,'.');"
        "from src.experiment.export import build_bundle;"
        "from src.experiment.schemas import ExperimentSpec;"
        "from src.experiment.canonical import canonical_json;"
        "print(canonical_json(build_bundle(ExperimentSpec.model_validate("
        "json.load(open(sys.argv[1]))),generated_at='2000-01-01T00:00:00Z')))"
    )
    path = Path("data/.test-sandbox/p0") / "spec.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_spec()), encoding="utf-8")
    outputs = set()
    try:
        for seed in ("0", "1", "12345"):
            proc = subprocess.run(
                [sys.executable, "-c", code, str(path)],
                capture_output=True, text=True, cwd=str(REPO_ROOT),
                env={"PATH": "/usr/bin:/bin", "PYTHONHASHSEED": seed},
                timeout=120,
            )
            assert proc.returncode == 0, proc.stderr
            outputs.add(proc.stdout.strip())
    finally:
        path.unlink(missing_ok=True)
    assert len(outputs) == 1, "materialized content depends on PYTHONHASHSEED"


def test_classic_run_plan_uses_the_content_answer_key() -> None:
    """The renderer consumes trial.correct (it must not recompute from labels)."""
    bundle = _bundle(_spec())
    from src.experiment.game_schemas import GameSpec

    repro = cast(dict[str, object], bundle["reproducibility"])
    spec_part = cast(dict[str, object], bundle["spec"])
    game = {
        "schema_version": 1,
        "game": {"name": "p0-demo", "version": "0.1.0"},
        "experiment_ref": {
            "name": spec_part["name"],
            "version": spec_part["version"],
            "seed": spec_part["seed"],
            "config_fingerprint": repro["config_fingerprint"],
            "trials_fingerprint": repro["trials_fingerprint"],
            "bundle_sha256": bundle["bundle_sha256"],
        },
        "scene": {"title": "t", "instructions": "i"},
        "input": {
            "modalities": ["keyboard"],
            "bindings": [{"response_name": "judge", "keys": {"r": "repeat", "n": "novel"}}],
        },
        "feedback": {"on_response": "correctness-flash", "duration_ms": 400},
        "flow": {"ready_screen": True, "block_breaks": False, "end_screen": "summary"},
        "gamification": {"score": True, "progress_bar": True, "streak_bonus": False},
    }
    plan = build_run_plan(bundle, GameSpec.model_validate(game))
    steps = [s for s in cast(list[dict[str, object]], plan["steps"]) if s.get("type") == "trial"]
    trials = cast(list[dict[str, object]], bundle["trials"])
    assert len(steps) == len(trials)
    for step, trial in zip(steps, trials):
        assert cast(dict[str, object], step["correct"]) == cast(dict[str, object], trial["correct"])


def test_explore_plan_uses_the_content_answer_key() -> None:
    """The v2 explore renderer consumes the same content-derived answer key."""
    from src.experiment.explore_render import build_explore_plan
    from src.experiment.game_schemas import GameSpec

    gamespec = json.loads(
        (REPO_ROOT / "tests" / "fixtures" / "manor-case" / "gamespec.json").read_text(encoding="utf-8")
    )
    keys = {"r": "repeat", "n": "novel"}
    gamespec["input"]["bindings"] = [{"response_name": "judge", "keys": keys}]
    gamespec["mapping"]["response_bindings"] = [{"response_name": "judge", "keys": keys}]
    bundle = _bundle(_spec())
    plan = build_explore_plan(bundle, GameSpec.model_validate(gamespec))
    plan_trials = cast(list[dict[str, object]], plan["trials"])
    trials = cast(list[dict[str, object]], bundle["trials"])
    assert len(plan_trials) == len(trials)
    for step, trial in zip(plan_trials, trials):
        assert cast(dict[str, object], step["correct"]) == cast(dict[str, object], trial["correct"])


# ---------------------------------------------------------------------------
# 5. Negative cases (validation before generation; no artifact is written)
# ---------------------------------------------------------------------------

def _with_variables(variables: list[object], pools: dict[str, list[str]] | None = None) -> dict[str, object]:
    config = _spec()
    stimulus = cast(dict[str, object], config["stimulus_spec"])
    stimulus["variables"] = variables
    if pools is not None:
        stimulus["pools"] = pools
    return config


def test_slot_referencing_undeclared_variable() -> None:
    config = _spec()
    stimulus = cast(dict[str, object], config["stimulus_spec"])
    cast(dict[str, object], stimulus["factors"])["size"] = {
        "levels": {"few": [["Items: {var:missing}"]], "many": [["Items: {var:missing}"]]},
        "match_line_count": True,
    }
    assert ErrorCode.V2_VAR_REF_UNKNOWN in _codes(validate_spec(config))


def test_rule_referencing_undeclared_variable() -> None:
    config = _spec(
        responses=[
            {
                "name": "judge",
                "kind": "choice",
                "options": ["repeat", "novel"],
                "correct_rule": {
                    "op": "in",
                    "left": {"var": "nope"},
                    "right": {"var": "items"},
                    "true_option": "repeat",
                    "false_option": "novel",
                },
            }
        ]
    )
    assert ErrorCode.V2_RULE_REF_UNKNOWN in _codes(validate_spec(config))


def test_forward_reference_rejected() -> None:
    variables = [
        {"name": "probe", "copy_from": {"var": "items"}},  # items declared later
        {"name": "items", "pool": "tokens", "count": 2},
    ]
    assert ErrorCode.V2_VAR_REF_UNKNOWN in _codes(validate_spec(_with_variables(variables)))


def test_source_conflict_rejected() -> None:
    variables = [
        {"name": "items", "pool": "tokens", "count": 2},
        {"name": "probe", "pool": "tokens", "count": 1, "copy_from": {"var": "items"}},
    ]
    assert ErrorCode.V2_VAR_SOURCE_CONFLICT in _codes(validate_spec(_with_variables(variables)))


def test_impossible_exclusion_rejected() -> None:
    """The pool cannot supply count + excluded values -> rejected before generation."""
    variables = [
        {"name": "items", "pool": "tokens", "count": 4},
        {"name": "probe", "pool": "tokens", "count": 1, "exclude": ["items"]},
    ]
    assert ErrorCode.V2_VAR_POOL_EXHAUSTED in _codes(
        validate_spec(_with_variables(variables, pools={"tokens": ["a", "b", "c", "d"]}))
    )


def test_when_coverage_must_be_complete() -> None:
    variables = [
        {"name": "items", "pool": "tokens", "count": 2},
        {"name": "probe", "when": {"relation": "repeat"}, "copy_from": {"var": "items", "index": "any"}},
    ]  # no binding for relation=novel
    assert ErrorCode.V2_VAR_WHEN_COVERAGE in _codes(validate_spec(_with_variables(variables)))


def test_index_out_of_bounds_rejected() -> None:
    variables = [
        {"name": "items", "pool": "tokens", "count": 2},
        {"name": "probe", "copy_from": {"var": "items", "index": 5}},
    ]
    assert ErrorCode.V2_VAR_INDEX_BOUNDS in _codes(validate_spec(_with_variables(variables)))


def test_rule_option_must_be_declared() -> None:
    config = _spec(
        responses=[
            {
                "name": "judge",
                "kind": "choice",
                "options": ["repeat", "novel"],
                "correct_rule": {
                    "op": "in",
                    "left": {"var": "probe"},
                    "right": {"var": "items"},
                    "true_option": "yes",
                    "false_option": "novel",
                },
            }
        ]
    )
    assert ErrorCode.V2_RULE_OPTION_UNKNOWN in _codes(validate_spec(config))


def test_unknown_rule_op_rejected() -> None:
    config = _spec(
        responses=[
            {
                "name": "judge",
                "kind": "choice",
                "options": ["repeat", "novel"],
                "correct_rule": {
                    "op": "matches_lag_two",
                    "left": {"var": "probe"},
                    "right": {"var": "items"},
                    "true_option": "repeat",
                    "false_option": "novel",
                },
            }
        ]
    )
    assert ErrorCode.V2_RULE_UNKNOWN_OP in _codes(validate_spec(config))


def test_extra_key_in_rule_rejected() -> None:
    config = _spec(
        responses=[
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
                    "lag": 2,
                },
            }
        ]
    )
    assert ErrorCode.SCHEMA_INVALID in _codes(validate_spec(config))


# ---------------------------------------------------------------------------
# 6. Task-agnostic guard
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "term",
    ["n-back", "nback", "working memory", "dmts", "serial recall", "sternberg"],
)
def test_engine_has_no_paradigm_vocabulary(term: str) -> None:
    """The engine must stay composed of primitives: no paradigm name in src/experiment."""
    hits = [
        path.name
        for path in sorted((REPO_ROOT / "src" / "experiment").glob("*.py"))
        if term in path.read_text(encoding="utf-8").lower()
    ]
    assert hits == [], f"paradigm vocabulary {term!r} found in {hits}"
