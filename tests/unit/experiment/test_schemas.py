"""PA-1 schema unit tests (contract §7; matched by -k "spec_").

Legal cases: the proposal §4.2 generic example (cueing-generic), the demo spec (contract §9.2), the default-omitted shape.
Illegal cases: each returns SCHEMA_INVALID carrying the corresponding path.
"""

from __future__ import annotations

from src.experiment.validation import ErrorCode, validate_spec

# proposal §4.2 generic example (only a schema-expressiveness case; implies no paradigm support)
CUEING_GENERIC_SPEC: dict[str, object] = {
    "schema_version": 1,
    "name": "cueing-generic",
    "version": "0.1.0",
    "seed": 11,
    "paradigm": None,
    "factors": [
        {"name": "cue_type", "levels": [{"name": "valid"}, {"name": "invalid"}]},
        {"name": "target_side", "levels": [{"name": "left"}, {"name": "right"}]},
    ],
    "blocks": [
        {"name": "practice", "trial_count": 8, "factor_filter": {}, "shuffle_within": True},
        {"name": "main", "trial_count": 80, "factor_filter": {}, "shuffle_within": True},
    ],
    "constraints": {"balance": True},
    "responses": [
        {"name": "locate_target", "kind": "choice", "options": ["left", "right"], "correct_from": "target_side"}
    ],
    "timing": {"fixation_ms": 400, "stimulus_ms": None, "isi_ms": 800},
}

# contract §9.2 demo spec (104 trials: practice 8 + main 96; 26 per combo, 52/52 per level)
DEMO_SPEC: dict[str, object] = {
    "schema_version": 1,
    "name": "generic-demo",
    "version": "0.1.0",
    "seed": 42,
    "factors": [
        {"name": "difficulty", "levels": [{"name": "easy"}, {"name": "hard"}]},
        {"name": "modality", "levels": [{"name": "visual"}, {"name": "audio"}]},
    ],
    "blocks": [
        {"name": "practice", "trial_count": 8},
        {"name": "main", "trial_count": 96},
    ],
    "constraints": {"balance": True},
    "responses": [
        {"name": "respond", "kind": "choice", "options": ["easy", "hard"], "correct_from": "difficulty"}
    ],
    "timing": {"fixation_ms": 500, "stimulus_ms": None, "isi_ms": 1000},
}

# default-omitted shape (the golden spec, contract §7.1)
GOLDEN_SPEC: dict[str, object] = {
    "schema_version": 1,
    "name": "generic-2x2",
    "version": "0.1.0",
    "seed": 7,
    "paradigm": None,
    "factors": [
        {"name": "difficulty", "levels": [{"name": "easy"}, {"name": "hard"}]},
        {"name": "modality", "levels": [{"name": "visual"}, {"name": "audio"}]},
    ],
    "blocks": [
        {"name": "practice", "trial_count": 8},
        {"name": "main", "trial_count": 40},
    ],
    "constraints": {"balance": True},
    "responses": [
        {"name": "judge_difficulty", "kind": "choice", "options": ["easy", "hard"], "correct_from": "difficulty"}
    ],
    "timing": {"fixation_ms": 500, "stimulus_ms": None, "isi_ms": 1000},
}


def _assert_schema_invalid(config: dict[str, object], path_fragment: str) -> None:
    """Assert: rejected at the schema layer and the SCHEMA_INVALID issue's path contains the locating fragment."""
    result = validate_spec(config)
    assert not result.valid
    assert result.spec is None
    schema_issues = [e for e in result.errors if e.error_code == ErrorCode.SCHEMA_INVALID]
    assert schema_issues, f"expected SCHEMA_INVALID, actual errors: {[e.error_code for e in result.errors]}"
    assert any(path_fragment in e.path for e in schema_issues), (
        f"path should contain {path_fragment!r}, actual {[e.path for e in schema_issues]}"
    )


def test_spec_accepts_proposal_generic_example() -> None:
    result = validate_spec(CUEING_GENERIC_SPEC)
    assert result.valid, [f"{e.error_code}:{e.path}" for e in result.errors]
    assert result.spec is not None
    assert result.stats == {"trial_count": 88, "factor_count": 2, "blocks": 2, "combinations": 4, "plugin": None}


def test_spec_accepts_demo_spec() -> None:
    result = validate_spec(DEMO_SPEC)
    assert result.valid, [f"{e.error_code}:{e.path}" for e in result.errors]
    assert result.stats == {"trial_count": 104, "factor_count": 2, "blocks": 2, "combinations": 4, "plugin": None}


def test_spec_accepts_default_omission() -> None:
    # paradigm/paradigm_params/constraints/responses' correct_from/timing etc. defaulted (omitted)
    minimal: dict[str, object] = {
        "schema_version": 1,
        "name": "minimal",
        "seed": 0,
        "factors": [{"name": "f", "levels": [{"name": "a"}, {"name": "b"}]}],
        "blocks": [{"name": "main", "trial_count": 4}],
        "responses": [{"name": "r", "kind": "text"}],
    }
    result = validate_spec(minimal)
    assert result.valid, [f"{e.error_code}:{e.path}" for e in result.errors]
    assert result.spec is not None
    assert result.spec.paradigm is None
    assert result.spec.paradigm_params == {}
    assert result.spec.constraints.balance is False
    assert result.spec.timing.fixation_ms == 500


def test_spec_rejects_missing_seed() -> None:
    config = {k: v for k, v in GOLDEN_SPEC.items() if k != "seed"}
    _assert_schema_invalid(config, "seed")


def test_spec_rejects_seed_out_of_range() -> None:
    config = dict(GOLDEN_SPEC, seed=2**63)  # beyond the CR-7 upper bound
    _assert_schema_invalid(config, "seed")
    config_negative = dict(GOLDEN_SPEC, seed=-1)
    _assert_schema_invalid(config_negative, "seed")


def test_spec_rejects_duplicate_factor_names() -> None:
    config = dict(GOLDEN_SPEC)
    config["factors"] = [
        {"name": "difficulty", "levels": [{"name": "easy"}, {"name": "hard"}]},
        {"name": "difficulty", "levels": [{"name": "visual"}, {"name": "audio"}]},
    ]
    _assert_schema_invalid(config, "factors")


def test_spec_rejects_duplicate_level_names() -> None:
    config = dict(GOLDEN_SPEC)
    config["factors"] = [{"name": "difficulty", "levels": [{"name": "easy"}, {"name": "easy"}]}]
    _assert_schema_invalid(config, "factors[0].levels")


def test_spec_rejects_duplicate_block_names() -> None:
    config = dict(GOLDEN_SPEC)
    config["blocks"] = [{"name": "main", "trial_count": 8}, {"name": "main", "trial_count": 40}]
    _assert_schema_invalid(config, "blocks")


def test_spec_rejects_duplicate_response_names() -> None:
    config = dict(GOLDEN_SPEC)
    config["responses"] = [
        {"name": "respond", "kind": "choice", "options": ["easy", "hard"]},
        {"name": "respond", "kind": "text"},
    ]
    _assert_schema_invalid(config, "responses")


def test_spec_rejects_unknown_factor_references() -> None:
    # factor_filter references an undeclared factor
    config = dict(GOLDEN_SPEC)
    config["blocks"] = [{"name": "main", "trial_count": 8, "factor_filter": {"nope": ["easy"]}}]
    _assert_schema_invalid(config, "blocks")
    # ratios.factor references an undeclared factor
    config = dict(GOLDEN_SPEC)
    config["constraints"] = {"balance": False, "ratios": [{"factor": "nope", "ratios": {"easy": 1.0}}]}
    _assert_schema_invalid(config, "constraints")
    # ratios keys reference undeclared levels of that factor
    config = dict(GOLDEN_SPEC)
    config["constraints"] = {"balance": False, "ratios": [{"factor": "difficulty", "ratios": {"nope": 1.0}}]}
    _assert_schema_invalid(config, "constraints")
    # mutually_exclusive references an undeclared level
    config = dict(GOLDEN_SPEC)
    config["constraints"] = {"balance": True, "mutually_exclusive": [["easy", "nope"]]}
    _assert_schema_invalid(config, "constraints")


def test_spec_rejects_options_kind_mismatch() -> None:
    # choice missing options
    config = dict(GOLDEN_SPEC)
    config["responses"] = [{"name": "respond", "kind": "choice", "options": []}]
    _assert_schema_invalid(config, "responses")
    # non-choice carrying options
    config = dict(GOLDEN_SPEC)
    config["responses"] = [{"name": "respond", "kind": "text", "options": ["easy"]}]
    _assert_schema_invalid(config, "responses")


def test_spec_rejects_scale_mismatch() -> None:
    # rating missing scale
    config = dict(GOLDEN_SPEC)
    config["responses"] = [{"name": "respond", "kind": "rating"}]
    _assert_schema_invalid(config, "responses")
    # non-rating carrying scale (superfluous)
    config = dict(GOLDEN_SPEC)
    config["responses"] = [{"name": "respond", "kind": "text", "scale": [1, 5]}]
    _assert_schema_invalid(config, "responses")
    # rating with min >= max
    config = dict(GOLDEN_SPEC)
    config["responses"] = [{"name": "respond", "kind": "rating", "scale": [5, 1]}]
    _assert_schema_invalid(config, "responses")


def test_spec_rejects_paradigm_params_with_null_paradigm() -> None:
    config = dict(GOLDEN_SPEC, paradigm_params={"n": 2})  # V8
    _assert_schema_invalid(config, "paradigm_params")


def test_spec_rejects_combination_limit_exceeded() -> None:
    # two factors with 400 levels each → 160,000 combinations > 100,000 (CR-7 / V9)
    big_levels_a = [{"name": f"a{i}"} for i in range(400)]
    big_levels_b = [{"name": f"b{i}"} for i in range(400)]
    config = dict(GOLDEN_SPEC)
    config["factors"] = [{"name": "fa", "levels": big_levels_a}, {"name": "fb", "levels": big_levels_b}]
    config["blocks"] = [{"name": "main", "trial_count": 10}]
    _assert_schema_invalid(config, "factors")


def test_spec_rejects_trial_count_out_of_range() -> None:
    config = dict(GOLDEN_SPEC)
    config["blocks"] = [{"name": "main", "trial_count": 0}]
    _assert_schema_invalid(config, "blocks")
    config = dict(GOLDEN_SPEC)
    config["blocks"] = [{"name": "main", "trial_count": 100_001}]
    _assert_schema_invalid(config, "blocks")


def test_spec_rejects_mutex_wrong_length() -> None:
    config = dict(GOLDEN_SPEC)
    config["constraints"] = {"balance": True, "mutually_exclusive": [["easy", "hard", "visual"]]}
    _assert_schema_invalid(config, "mutually_exclusive")


def test_spec_rejects_duplicate_ratio_rules() -> None:
    # V6: two ratios rules for the same factor
    config = dict(GOLDEN_SPEC)
    config["constraints"] = {
        "balance": False,
        "ratios": [
            {"factor": "difficulty", "ratios": {"easy": 0.5, "hard": 0.5}},
            {"factor": "difficulty", "ratios": {"easy": 0.3, "hard": 0.7}},
        ],
    }
    _assert_schema_invalid(config, "ratios")
