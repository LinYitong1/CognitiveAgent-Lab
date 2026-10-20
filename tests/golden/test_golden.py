"""PA-13 黄金文件测试（契约 §7.1 冻结 spec；-k golden / pytest tests/golden 命中）。

逐字节比对（含 bundle_sha256）；generated_at 固定 "2026-01-01T00:00:00Z"（测试注入）。
更新流程：UPDATE_GOLDEN=1 python -m pytest tests/golden → 人工 review diff → PR 说明
（engine_spec_version 同步递增）。
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

# 契约 §7.1 冻结 spec（任何范式无关）
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
    """build_bundle(spec, generated_at=固定值) → 落盘字节与 golden 逐字节一致（含 bundle_sha256）。"""
    spec = ExperimentSpec.model_validate(GOLDEN_SPEC)
    bundle = build_bundle(spec, generated_at=FIXED_TIMESTAMP)
    text = canonical_json(bundle)

    if os.environ.get("UPDATE_GOLDEN") == "1":
        GOLDEN_PATH.write_text(text, encoding="utf-8")
        pytest.skip("golden 文件已重写——请人工 review diff 后提交（engine_spec_version 须同步递增）")

    golden = GOLDEN_PATH.read_text(encoding="utf-8")
    assert text == golden, "黄金文件逐字节 diff 不为空：生成结果相对基线发生变更"

    # 黄金文件自洽性（契约 §7.1）：48 试次、每组合 12（2+10）、每水平 24/24
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
