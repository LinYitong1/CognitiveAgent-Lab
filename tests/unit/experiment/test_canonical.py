"""PA-4 canonical JSON tests (contract §7; matched by -k canonical)."""

from __future__ import annotations

import pytest

from src.experiment.canonical import canonical_json, sha256_hex
from src.experiment.schemas import ExperimentSpec, spec_dump
from src.experiment.validation import validate_spec

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


def test_canonical_sorted_compact() -> None:
    text = canonical_json({"b": 1, "a": {"y": [1, 2], "x": "s"}})
    assert text == '{"a":{"x":"s","y":[1,2]},"b":1}'  # sorted keys, no whitespace
    assert " " not in text
    assert "\n" not in text


def test_canonical_utf8() -> None:
    text = canonical_json({"level": "中文水平"})
    assert text == '{"level":"中文水平"}'  # ensure_ascii=False: UTF-8 direct output
    assert canonical_json({"水平": "左"}) == '{"水平":"左"}'


def test_canonical_rejects_nan() -> None:
    nan = float("nan")
    infinity = float("inf")
    with pytest.raises(ValueError):
        canonical_json({"weight": nan})
    with pytest.raises(ValueError):
        canonical_json({"weight": infinity})


def test_default_omission_same_fingerprint() -> None:
    """Omitted vs. default-filled fields produce the same config_fingerprint (proposal MI-2 semantics)."""
    omitted: dict[str, object] = {
        "schema_version": 1,
        "name": "minimal",
        "seed": 3,
        "factors": [{"name": "f", "levels": [{"name": "a"}, {"name": "b"}]}],
        "blocks": [{"name": "main", "trial_count": 4}],
        "responses": [{"name": "r", "kind": "text"}],
    }
    completed = {
        **omitted,
        "version": "0.1.0",
        "paradigm": None,
        "paradigm_params": {},
        "constraints": {"balance": False, "ratios": [], "mutually_exclusive": [], "max_repeat": None},
        "timing": {"fixation_ms": 500, "stimulus_ms": None, "isi_ms": 1000},
    }
    fp_omitted = validate_spec(omitted).config_fingerprint
    fp_completed = validate_spec(completed).config_fingerprint
    assert fp_omitted is not None and fp_completed is not None
    assert fp_omitted == fp_completed
    # the fingerprint is computed over the parsed, normalized object.
    # M2-B (D-M2-1 §1.1): the reference formula is the spec_dump() projection
    # (bare model_dump() now carries the None-defaulted v2 keys, which the
    # projection removes — v1 fingerprints are unchanged by construction,
    # proven in test_v1_compatibility.py).
    assert fp_omitted == sha256_hex(canonical_json(spec_dump(ExperimentSpec.model_validate(omitted))))
