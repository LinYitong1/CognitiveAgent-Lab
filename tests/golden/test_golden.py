"""PA-13 golden-file tests (contract §7.1 frozen spec; matched by -k golden / pytest tests/golden).

Byte-for-byte comparison (incl. bundle_sha256); generated_at fixed to "2026-01-01T00:00:00Z" (test injection).
Update flow: UPDATE_GOLDEN=1 python -m pytest tests/golden → human review of the diff → PR notes
(engine_spec_version must be bumped in sync).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.experiment.canonical import canonical_json
from src.experiment.export import build_bundle
from src.experiment.schemas import ExperimentSpec

GOLDEN_PATH = Path(__file__).resolve().parent / "generic-2x2-seed7.json"
FIXED_TIMESTAMP = "2026-01-01T00:00:00Z"

# contract §7.1 frozen spec (paradigm-agnostic)
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


def test_golden_export_unchanged() -> None:
    """build_bundle(spec, generated_at=fixed) → the on-disk bytes are byte-identical to golden (incl. bundle_sha256)."""
    spec = ExperimentSpec.model_validate(GOLDEN_SPEC)
    bundle = build_bundle(spec, generated_at=FIXED_TIMESTAMP)
    text = canonical_json(bundle)

    if os.environ.get("UPDATE_GOLDEN") == "1":
        GOLDEN_PATH.write_text(text, encoding="utf-8")
        pytest.skip("golden file rewritten — human review of the diff is required before commit (engine_spec_version must be bumped in sync)")

    golden = GOLDEN_PATH.read_text(encoding="utf-8")
    assert text == golden, "golden-file byte diff is non-empty: the generated result changed relative to the baseline"

# golden-file self-consistency (contract §7.1): 48 trials, 12 per combo (2+10), 24/24 per level
    import json

    data = json.loads(golden)
    assert data["generated_at"] == FIXED_TIMESTAMP
    assert data["summary"]["trial_count"] == 48
    assert data["summary"]["frequency"] == {
        "difficulty": {"easy": 24, "hard": 24},
        "modality": {"visual": 24, "audio": 24},
    }
    assert data["reproducibility"]["allocation"] == {
        "practice": {"easy|visual": 2, "easy|audio": 2, "hard|visual": 2, "hard|audio": 2},
        "main": {"easy|visual": 10, "easy|audio": 10, "hard|visual": 10, "hard|audio": 10},
    }
    assert data["reproducibility"]["engine_spec_version"] == "1.0"
    assert data["reproducibility"]["plugin_used"] is None
