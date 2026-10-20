"""PA-3 constraints and frequencies + PA-6 UNSAT/SEARCH_EXHAUSTED semantics tests (contract §7).

PA-3 selector: -k "c1 or c2 or c3 or ratio or remainder or mismatch or mutex or
filter_empty or correct_from or paradigm or unsupported"
PA-6 selector: -k "unsat or search_exhausted"
All frequency assertions are exact integers (OUT-6: no chi-square-style statistical strengthening).
"""

from __future__ import annotations

import inspect

from src.config import Settings
from src.experiment.generation import (
    ENGINE_SPEC_VERSION,
    block_allocation,
    effective_weights,
    filter_mutex,
    generate_trials,
    largest_remainder_counts,
    mutex_pairs,
)
from src.experiment.schemas import ExperimentSpec
from src.experiment.validation import (
    UNSAT_ERROR_CODES,
    ErrorCode,
    WarningCode,
    validate_spec,
)

BASE_SPEC: dict[str, object] = {
    "schema_version": 1,
    "name": "test-spec",
    "version": "0.1.0",
    "seed": 42,
    "factors": [
        {"name": "difficulty", "levels": [{"name": "easy"}, {"name": "hard"}]},
        {"name": "modality", "levels": [{"name": "visual"}, {"name": "audio"}]},
    ],
    "blocks": [{"name": "main", "trial_count": 96}],
    "constraints": {"balance": True},
    "responses": [
        {"name": "respond", "kind": "choice", "options": ["easy", "hard"], "correct_from": "difficulty"}
    ],
    "timing": {"fixation_ms": 500, "stimulus_ms": None, "isi_ms": 1000},
}

DEMO_SPEC: dict[str, object] = {
    **BASE_SPEC,
    "blocks": [{"name": "practice", "trial_count": 8}, {"name": "main", "trial_count": 96}],
}


def _spec(config: dict[str, object]) -> ExperimentSpec:
    return ExperimentSpec.model_validate(config)


def _error_codes(config: dict[str, object]) -> list[str]:
    return [e.error_code for e in validate_spec(config).errors]


def _warning_codes(config: dict[str, object]) -> list[str]:
    return [w.error_code for w in validate_spec(config).warnings]


def test_c1_conflict() -> None:
    config = dict(BASE_SPEC)
    config["constraints"] = {
        "balance": True,
        "ratios": [{"factor": "difficulty", "ratios": {"easy": 0.5, "hard": 0.5}}],
    }
    result = validate_spec(config)
    assert not result.valid
    issue = next(e for e in result.errors if e.error_code == ErrorCode.CONSTRAINT_CONFLICT)
    assert issue.path == "constraints"
    assert issue.message and issue.suggestion


def test_c2_weight_ignored_both_cases() -> None:
    # case ①: balance=true with an explicit weight ≠ 1.0
    config = dict(BASE_SPEC)
    config["factors"] = [
        {"name": "difficulty", "levels": [{"name": "easy", "weight": 2.0}, {"name": "hard"}]},
        {"name": "modality", "levels": [{"name": "visual"}, {"name": "audio"}]},
    ]
    result = validate_spec(config)
    assert result.valid  # warnings do not affect the valid decision
    assert WarningCode.WEIGHT_IGNORED in _warning_codes(config)

    # case ②: balance=false with an explicit weight ≠ 1.0 on a ratios-declared factor
    config = dict(BASE_SPEC)
    config["factors"] = [
        {"name": "difficulty", "levels": [{"name": "easy", "weight": 3.0}, {"name": "hard", "weight": 1.0}]},
        {"name": "modality", "levels": [{"name": "visual"}, {"name": "audio"}]},
    ]
    config["constraints"] = {
        "balance": False,
        "ratios": [{"factor": "difficulty", "ratios": {"easy": 0.5, "hard": 0.5}}],
    }
    result = validate_spec(config)
    assert result.valid
    assert WarningCode.WEIGHT_IGNORED in _warning_codes(config)


def test_c3_ratio_priority() -> None:
    """ratios override Level.weight: weights 3:1 overridden by ratios 0.5:0.5 → 48/48."""
    config = dict(BASE_SPEC)
    config["factors"] = [
        {"name": "difficulty", "levels": [{"name": "easy", "weight": 3.0}, {"name": "hard", "weight": 1.0}]},
        {"name": "modality", "levels": [{"name": "visual"}, {"name": "audio"}]},
    ]
    config["constraints"] = {
        "balance": False,
        "ratios": [{"factor": "difficulty", "ratios": {"easy": 0.5, "hard": 0.5}}],
    }
    result = validate_spec(config)
    assert result.valid, [e.error_code for e in result.errors]
    gen = generate_trials(_spec(config))
    frequency: dict[str, dict[str, int]] = {}
    for trial in gen.trials:
        for factor, level in trial.factors.items():
            frequency.setdefault(factor, {}).setdefault(level, 0)
            frequency[factor][level] += 1
    assert frequency["difficulty"] == {"easy": 48, "hard": 48}


def test_ratio_sum() -> None:
    config = dict(BASE_SPEC)
    config["constraints"] = {
        "balance": False,
        "ratios": [{"factor": "difficulty", "ratios": {"easy": 0.6, "hard": 0.3}}],
    }
    result = validate_spec(config)
    assert not result.valid
    issue = next(e for e in result.errors if e.error_code == ErrorCode.RATIO_SUM)
    assert issue.path == "constraints.ratios[0].ratios"
    assert "0.9" in issue.message
    assert issue.suggestion


def test_ratio_rounded_warning() -> None:
    """10 trials / 4 combos → 3/3/2/2 + the RATIO_ROUNDED warning present."""
    config = dict(BASE_SPEC)
    config["blocks"] = [{"name": "main", "trial_count": 10}]
    result = validate_spec(config)
    assert result.valid  # a warning is not an error, let alone UNSAT
    assert WarningCode.RATIO_ROUNDED in _warning_codes(config)

    gen = generate_trials(_spec(config))
    combo_counts: dict[str, int] = {}
    for trial in gen.trials:
        key = f"{trial.factors['difficulty']}|{trial.factors['modality']}"
        combo_counts[key] = combo_counts.get(key, 0) + 1
    # declaration order: easy|visual, easy|audio, hard|visual, hard|audio → the remainder goes to the first 2 in declaration order
    assert combo_counts == {"easy|visual": 3, "easy|audio": 3, "hard|visual": 2, "hard|audio": 2}


def test_largest_remainder_math() -> None:
    """Frequency sum == trial_count; each combo count ∈ {floor, floor+1}; remainders allocated by fractional descending / declaration order."""
    # exact integer vectors: 100 trials, weights [0.5, 0.3, 0.2] → [50, 30, 20]
    assert largest_remainder_counts(100, [0.5, 0.3, 0.2]) == [50, 30, 20]
    # ties broken by declaration order: 10 trials / 4 equal weights → the first 2 combos get +1
    assert largest_remainder_counts(10, [0.25, 0.25, 0.25, 0.25]) == [3, 3, 2, 2]
    # end-to-end frequencies for several fixed seeds (balance, 2x2)
    for seed in (0, 1, 7, 42, 2**63 - 1):
        config = dict(DEMO_SPEC, seed=seed)
        gen = generate_trials(_spec(config))
        assert len(gen.trials) == 104
        frequency: dict[str, dict[str, int]] = {}
        for trial in gen.trials:
            for factor, level in trial.factors.items():
                frequency.setdefault(factor, {}).setdefault(level, 0)
                frequency[factor][level] += 1
    # demo-spec self-consistency: 26 per combo (2+24), 52/52 per level
        assert frequency["difficulty"] == {"easy": 52, "hard": 52}
        assert frequency["modality"] == {"visual": 52, "audio": 52}
        per_block: dict[str, dict[str, int]] = {}
        for trial in gen.trials:
            key = f"{trial.block}:{trial.factors['difficulty']}|{trial.factors['modality']}"
            per_block.setdefault(trial.block, {}).setdefault(key, 0)
            per_block[trial.block][key] += 1
        assert set(per_block["practice"].values()) == {2}
        assert set(per_block["main"].values()) == {24}


def test_trial_count_mismatch() -> None:
    """ratios set to 0 + filter scoping: the block is left with only weight-0 combos."""
    config = dict(BASE_SPEC)
    config["constraints"] = {
        "balance": False,
        "ratios": [{"factor": "difficulty", "ratios": {"easy": 0.0, "hard": 1.0}}],
    }
    config["blocks"] = [{"name": "main", "trial_count": 20, "factor_filter": {"difficulty": ["easy"]}}]
    result = validate_spec(config)
    assert not result.valid
    issue = next(e for e in result.errors if e.error_code == ErrorCode.TRIAL_COUNT_MISMATCH)
    assert issue.path == "blocks[0]"
    assert issue.suggestion


def test_mutex_violation_empty() -> None:
    """Mutex declarations empty the available combination space (all 4 pairs of a 2x2 mutually exclusive)."""
    config = dict(BASE_SPEC)
    config["constraints"] = {
        "balance": True,
        "mutually_exclusive": [
            ["easy", "visual"], ["easy", "audio"], ["hard", "visual"], ["hard", "audio"]
        ],
    }
    result = validate_spec(config)
    assert not result.valid
    issue = next(e for e in result.errors if e.error_code == ErrorCode.MUTEX_VIOLATION)
    assert issue.path == "constraints.mutually_exclusive"


def test_mutex_violation_same_factor() -> None:
    config = dict(BASE_SPEC)
    config["constraints"] = {"balance": True, "mutually_exclusive": [["easy", "hard"]]}
    result = validate_spec(config)
    assert not result.valid
    issue = next(e for e in result.errors if e.error_code == ErrorCode.MUTEX_VIOLATION)
    assert issue.path == "constraints.mutually_exclusive[0]"


def test_block_filter_empty() -> None:
    config = dict(BASE_SPEC)
    config["blocks"] = [{"name": "main", "trial_count": 20, "factor_filter": {"difficulty": []}}]
    result = validate_spec(config)
    assert not result.valid
    issue = next(e for e in result.errors if e.error_code == ErrorCode.BLOCK_FILTER_EMPTY)
    assert issue.path == "blocks[0].factor_filter"


def test_correct_from_unknown() -> None:
    config = dict(BASE_SPEC)
    config["responses"] = [
        {"name": "respond", "kind": "choice", "options": ["easy", "hard"], "correct_from": "no_such_factor"}
    ]
    result = validate_spec(config)
    assert not result.valid
    issue = next(e for e in result.errors if e.error_code == ErrorCode.CORRECT_FROM_UNKNOWN)
    assert issue.path == "responses[0].correct_from"


def test_unknown_paradigm() -> None:
    config = dict(BASE_SPEC, paradigm="stroop")
    result = validate_spec(config)
    assert not result.valid
    issue = next(e for e in result.errors if e.error_code == ErrorCode.UNKNOWN_PARADIGM)
    assert "Phase A has no plugin system" in issue.message
    assert issue.suggestion


def test_unsupported_constraint_max_repeat() -> None:
    config = dict(BASE_SPEC)
    config["constraints"] = {"balance": True, "max_repeat": 3}
    result = validate_spec(config)
    assert not result.valid
    issue = next(e for e in result.errors if e.error_code == ErrorCode.UNSUPPORTED_CONSTRAINT)
    assert "Phase B" in issue.message
    assert issue.suggestion


def test_unsat_error_code_mapping() -> None:
    """Per-code trigger assertions for the UNSAT class of the §4.4 table (excluding SEARCH_EXHAUSTED — not triggerable in Phase A)."""
    fixtures: dict[str, dict[str, object]] = {
        ErrorCode.CONSTRAINT_CONFLICT: {
            "constraints": {
                "balance": True,
                "ratios": [{"factor": "difficulty", "ratios": {"easy": 0.5, "hard": 0.5}}],
            }
        },
        ErrorCode.RATIO_SUM: {
            "constraints": {
                "balance": False,
                "ratios": [{"factor": "difficulty", "ratios": {"easy": 0.6, "hard": 0.3}}],
            }
        },
        ErrorCode.BLOCK_FILTER_EMPTY: {
            "blocks": [{"name": "main", "trial_count": 20, "factor_filter": {"difficulty": []}}]
        },
        ErrorCode.TRIAL_COUNT_MISMATCH: {
            "constraints": {
                "balance": False,
                "ratios": [{"factor": "difficulty", "ratios": {"easy": 0.0, "hard": 1.0}}],
            },
            "blocks": [{"name": "main", "trial_count": 20, "factor_filter": {"difficulty": ["easy"]}}],
        },
        ErrorCode.MUTEX_VIOLATION: {
            "constraints": {"balance": True, "mutually_exclusive": [["easy", "hard"]]}
        },
    }
    assert set(fixtures) == set(UNSAT_ERROR_CODES)
    for expected_code, overrides in fixtures.items():
        config = dict(BASE_SPEC)
        for key, value in overrides.items():
            config[key] = value
        result = validate_spec(config)
        assert not result.valid, expected_code
        issue = next(e for e in result.errors if e.error_code == expected_code)
        assert issue.message, expected_code  # message contains actual values and is non-empty
        assert issue.suggestion, expected_code


def test_search_exhausted_framework_capability() -> None:
    """Declarative weak assertion (contract PA-6 honestly notes the limitation):

    the Phase A constraint set has no search path, so SEARCH_EXHAUSTED is not triggerable; this test only asserts the
    framework capability is present (error-code enum, Settings field, generate_trials signature); a real trigger test
    arrives with Phase B's max_repeat sequence constraints.
    """
    assert ErrorCode.SEARCH_EXHAUSTED == "SEARCH_EXHAUSTED"
    settings = Settings()
    assert settings.experiment_max_search_attempts == 100
    signature = inspect.signature(generate_trials)
    assert "max_attempts" in signature.parameters
    assert signature.parameters["max_attempts"].default == 100
    assert ENGINE_SPEC_VERSION == "1.0"


def test_mutex_static_filter_and_allocation_helpers() -> None:
    """CR-4 static combination filtering + the allocation per-block basis (supplementary assertions for QA investigation)."""
    config = dict(BASE_SPEC)
    config["constraints"] = {"balance": True, "mutually_exclusive": [["easy", "visual"]]}
    spec = _spec(config)
    full = spec.expanded_combinations()
    assert len(full) == 4
    filtered = filter_mutex(full, mutex_pairs(spec))
    assert len(filtered) == 3  # easy|visual is removed
    weights = effective_weights(spec)
    alloc = block_allocation(spec, spec.blocks[0], filtered, weights)
    assert {"|".join(k): v for k, v in alloc} == {"easy|audio": 32, "hard|visual": 32, "hard|audio": 32}
