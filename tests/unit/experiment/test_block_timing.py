"""Expressiveness Stage 1 tests: per-block timing override (blocks[].timing).

Scope (docs/experiment-expressiveness/04 §P3): BLOCK-LEVEL whole-object
replacement only — this primitive does not solve condition-level timing
variation. When a block declares timing, every trial of that block carries the
block timing; when absent, the spec-level timing (historical behavior).
Zero-byte-drift obligations: spec_dump strips blocks[].timing when None, so
every existing config_fingerprint / trials_fingerprint / golden HTML is
unchanged for specs that do not opt in.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from src.experiment.canonical import canonical_json
from src.experiment.export import build_bundle
from src.experiment.game_render import build_run_plan, render_game_html
from src.experiment.game_schemas import GameSpec, validate_game
from src.experiment.schemas import ExperimentSpec, spec_dump
from src.experiment.validation import ErrorCode, WarningCode, validate_spec

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXED_GENERATED_AT = "2000-01-01T00:00:00Z"


def _codes(result: object) -> list[str]:
    return [issue.error_code for issue in result.errors]  # type: ignore[attr-defined]


def _warning_codes(result: object) -> list[str]:
    return [issue.error_code for issue in result.warnings]  # type: ignore[attr-defined]


def _block_timing_spec() -> dict[str, object]:
    """Practice block with a short deadline; main block on the spec-level timing."""
    return {
        "schema_version": 2,
        "name": "block-timing-demo",
        "version": "0.1.0",
        "seed": 21,
        "factors": [{"name": "item", "levels": [{"name": "red"}, {"name": "blue"}]}],
        "blocks": [
            {
                "name": "practice",
                "trial_count": 2,
                "timing": {"fixation_ms": 10, "stimulus_ms": 150, "isi_ms": 20},
            },
            {"name": "main", "trial_count": 4},
        ],
        "constraints": {"balance": True},
        "responses": [
            {"name": "pick", "kind": "choice", "options": ["red", "blue"], "correct_from": "item"}
        ],
        "timing": {"fixation_ms": 100, "stimulus_ms": 900, "isi_ms": 50},
    }


def _bundle() -> dict[str, object]:
    return build_bundle(
        ExperimentSpec.model_validate(_block_timing_spec()), generated_at=FIXED_GENERATED_AT
    )


def _gamespec(bundle: dict[str, object]) -> dict[str, object]:
    repro = cast(dict[str, object], bundle["reproducibility"])
    spec = cast(dict[str, object], bundle["spec"])
    return {
        "schema_version": 1,
        "game": {"name": "block-timing-demo", "version": "0.1.0"},
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
            "bindings": [{"response_name": "pick", "keys": {"r": "red", "b": "blue"}}],
        },
        "feedback": {"on_response": "correctness-flash", "duration_ms": 20},
    }


# ---------------------------------------------------------------------------
# Validation + projection
# ---------------------------------------------------------------------------


def test_block_timing_spec_valid_with_override_warning() -> None:
    result = validate_spec(_block_timing_spec())
    assert result.valid, [(e.error_code, e.path, e.message) for e in result.errors]
    # whole-object replacement semantics: informational warning on every override
    assert WarningCode.BLOCK_TIMING_OVERRIDE in _warning_codes(result)


def test_block_timing_on_v1_rejected() -> None:
    config = _block_timing_spec()
    config["schema_version"] = 1
    assert ErrorCode.V2_VERSION_MISMATCH in _codes(validate_spec(config))


def test_block_timing_explicit_null_equals_absent() -> None:
    config = _block_timing_spec()
    cast(list[dict[str, object]], config["blocks"])[0]["timing"] = None
    result = validate_spec(config)
    assert result.valid, _codes(result)
    assert WarningCode.BLOCK_TIMING_OVERRIDE not in _warning_codes(result)


def test_block_timing_materialized_per_trial() -> None:
    trials = cast(list[dict[str, object]], _bundle()["trials"])
    assert len(trials) == 6
    for trial in trials:
        timing = cast(dict[str, object], trial["timing"])
        if trial["block"] == "practice":
            assert timing == {"fixation_ms": 10, "stimulus_ms": 150, "isi_ms": 20}
        else:
            assert timing == {"fixation_ms": 100, "stimulus_ms": 900, "isi_ms": 50}


def test_run_plan_carries_block_timing() -> None:
    """The plan embeds per-trial timing from the bundle — the runtime consumes
    it unchanged (no engine modification was needed for this primitive)."""
    bundle = _bundle()
    plan = build_run_plan(bundle, GameSpec.model_validate(_gamespec(bundle)))
    steps = [
        cast(dict[str, object], s)
        for s in cast(list[object], plan["steps"])
        if cast(dict[str, object], s).get("type") == "trial"
    ]
    assert len(steps) == 6
    for step, trial in zip(steps, cast(list[dict[str, object]], bundle["trials"])):
        assert step["timing"] == trial["timing"]


def test_spec_dump_strips_unset_block_timing() -> None:
    result = validate_spec(_block_timing_spec())
    assert result.valid and result.spec is not None
    dump = spec_dump(result.spec)
    blocks = cast(list[dict[str, object]], dump["blocks"])
    # declared override survives the projection...
    assert blocks[0]["timing"] == {"fixation_ms": 10, "stimulus_ms": 150, "isi_ms": 20}
    # ...and an unset override contributes no bytes
    assert "timing" not in blocks[1]


def test_block_timing_bundle_reproducible() -> None:
    bundle = _bundle()
    assert canonical_json(bundle) == canonical_json(_bundle())


def test_golden_bundle_and_html_unchanged_without_override() -> None:
    """Zero-byte-drift gate: the committed golden bundle (v1, no block timing)
    and the golden HTML regenerate byte-identically — the strip rule keeps the
    historical serialization for every spec that does not opt in."""
    golden_bundle_path = REPO_ROOT / "tests" / "golden" / "generic-2x2-seed7.json"
    golden_html_path = REPO_ROOT / "tests" / "golden" / "game-generic-demo.html"
    bundle = json.loads(golden_bundle_path.read_text(encoding="utf-8"))
    spec = ExperimentSpec.model_validate(cast(dict[str, object], bundle["spec"]))
    rebuilt = build_bundle(spec, generated_at=str(bundle["generated_at"]))
    assert canonical_json(rebuilt) == canonical_json(bundle)
    dump = spec_dump(spec)
    for block in cast(list[dict[str, object]], dump["blocks"]):
        assert "timing" not in block

    result = validate_game(
        _golden_demo_gamespec(bundle), bundle
    )
    assert result.valid and result.game_spec is not None
    assert render_game_html(bundle, result.game_spec) == golden_html_path.read_text(encoding="utf-8")


def _golden_demo_gamespec(bundle: dict[str, object]) -> dict[str, object]:
    spec_part = cast(dict[str, object], bundle["spec"])
    repro = cast(dict[str, object], bundle["reproducibility"])
    responses = cast(list[object], spec_part["responses"])
    choice = cast(dict[str, object], next(r for r in responses if cast(dict[str, object], r)["kind"] == "choice"))
    options = cast(list[str], choice["options"])
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
            "bindings": [{"response_name": choice["name"], "keys": {o[:1]: o for o in options}}],
        },
        "feedback": {"on_response": "outcome-text", "duration_ms": 400},
    }
