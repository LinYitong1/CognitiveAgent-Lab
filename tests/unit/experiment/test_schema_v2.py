"""M2-B Phase 2 tests: v2 schema, semantic validation, materialization, fingerprints.

Covers the D-M2-1 contract (docs/m2/M2B_CONTRACT.md):
- schema acceptance (v2 fields, extra=forbid) and V2_VERSION_MISMATCH;
- every V2_* error code has >= 1 negative test (contract Part 3 matrix);
- deterministic materialization (isolated stream, PYTHONHASHSEED-independence,
  pinned draw order);
- fingerprint coverage: materialized stimulus/derived are inside
  trials_fingerprint; v2 config fields are inside config_fingerprint; explicit
  null == absent (no v2 keys in the dump);
- stimulus.py import surface (game/tool/agent independence).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from src.experiment.export import build_bundle
from src.experiment.schemas import (
    DerivedOpSpec,
    ExperimentSpec,
    MeasureSpec,
    StimulusSpec,
    spec_dump,
)
from src.experiment.stimulus import DERIVED_OP_WHITELIST, materialize_trials
from src.experiment.validation import ErrorCode, validate_spec

REPO_ROOT = Path(__file__).resolve().parents[3]


def _v2_config(**overrides: object) -> dict[str, object]:
    config: dict[str, object] = {
        "schema_version": 2,
        "name": "v2-test",
        "version": "0.1.0",
        "seed": 42,
        "factors": [
            {"name": "salience", "levels": [{"name": "salient"}, {"name": "embedded"}]},
        ],
        "blocks": [{"name": "main", "trial_count": 8}],
        "constraints": {"balance": True},
        "responses": [
            {"name": "answer", "kind": "choice", "options": ["a", "b"], "correct_from": None}
        ],
        "timing": {"fixation_ms": 300, "stimulus_ms": None, "isi_ms": 500},
    }
    config.update(overrides)
    return config


# length-UNmatched variant with match_line_count=true (triggers the mismatch)
_STIMULUS_SPEC: dict[str, object] = {
    "factors": {
        "salience": {
            "levels": {
                "salient": [["Clue: the trail leads {salience}."]],
                "embedded": [
                    [
                        "A dusty shelf holds unrelated ledgers.",
                        "Clue: the trail leads {salience}.",
                        "Nothing else of note here.",
                        "{pool:decoys}",
                    ]
                ],
            },
            "match_line_count": True,
        },
    },
    "pools": {"decoys": ["A clock ticks.", "A portrait watches.", "A rug lies flat."]},
}

# length-matched variant for the confound-control path
_STIMULUS_SPEC_MATCHED: dict[str, object] = {
    "factors": {
        "salience": {
            "levels": {
                "salient": [
                    ["Clue: the trail leads {salience}.", "A clock ticks.", "Nothing else of note here.", "A portrait watches."]
                ],
                "embedded": [
                    [
                        "A dusty shelf holds unrelated ledgers.",
                        "Clue: the trail leads {salience}.",
                        "Nothing else of note here.",
                        "{pool:decoys}",
                    ]
                ],
            },
            "match_line_count": True,
        },
    },
    "pools": {"decoys": ["A clock ticks.", "A portrait watches.", "A rug lies flat."]},
}


def _codes(result: object) -> list[str]:
    return [issue.error_code for issue in result.errors]  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Schema acceptance / version guard
# ---------------------------------------------------------------------------

def test_v2_fields_accepted_and_valid() -> None:
    config = _v2_config(
        stimulus_spec=_STIMULUS_SPEC_MATCHED,
        derived_spec=[{"name": "n", "op": "trial_number"}],
        measures=[{"name": "rt", "source": "response.rt_ms"}],
    )
    result = validate_spec(config)
    assert result.valid, [ (e.error_code, e.path, e.message) for e in result.errors ]
    assert result.spec is not None
    assert result.spec.schema_version == 2


def test_v2_version_mismatch_on_v1() -> None:
    config = _v2_config(schema_version=1, measures=[{"name": "rt", "source": "response.rt_ms"}])
    result = validate_spec(config)
    assert not result.valid
    assert ErrorCode.V2_VERSION_MISMATCH in _codes(result)


def test_v2_explicit_null_equals_absent() -> None:
    config = _v2_config(stimulus_spec=None, derived_spec=None, measures=None)
    result = validate_spec(config)
    assert result.valid, _codes(result)
    dump = spec_dump(result.spec)  # type: ignore[arg-type]
    for key in ("stimulus_spec", "derived_spec", "measures"):
        assert key not in dump


def test_v2_extra_keys_rejected() -> None:
    config = _v2_config(stimulus_spec={"factors": {}, "pools": {}, "smuggled": True})
    result = validate_spec(config)
    assert not result.valid
    assert ErrorCode.SCHEMA_INVALID in _codes(result)


def test_v2_with_no_v2_fields_is_legal() -> None:
    result = validate_spec(_v2_config())
    assert result.valid, _codes(result)


# ---------------------------------------------------------------------------
# Stimulus semantic validation (one test per error code family)
# ---------------------------------------------------------------------------

def _with_stim(spec: object) -> dict[str, object]:
    return _v2_config(stimulus_spec=spec)


def test_stim_empty_factors() -> None:
    result = validate_spec(_with_stim({"factors": {}}))
    assert ErrorCode.V2_STIM_EMPTY in _codes(result)


def test_stim_unknown_factor() -> None:
    bad = {"factors": {"nonexistent": {"levels": {"salient": [["x"]]}}}}
    result = validate_spec(_with_stim(bad))
    assert ErrorCode.V2_STIM_UNKNOWN_FACTOR in _codes(result)


def test_stim_unknown_level() -> None:
    bad = {"factors": {"salience": {"levels": {"salient": [["x"]], "typo-level": [["y"]]}}}}
    result = validate_spec(_with_stim(bad))
    assert ErrorCode.V2_STIM_UNKNOWN_LEVEL in _codes(result)


def test_stim_level_coverage_partial() -> None:
    bad = {"factors": {"salience": {"levels": {"salient": [["x"]]}}}}  # embedded missing
    result = validate_spec(_with_stim(bad))
    assert ErrorCode.V2_STIM_LEVEL_COVERAGE in _codes(result)


def test_stim_template_bounds() -> None:
    bad = {"factors": {"salience": {"levels": {
        "salient": [["x"]] * 5, "embedded": [["y"]] * 5}}}}
    result = validate_spec(_with_stim(bad))
    assert ErrorCode.V2_STIM_TEMPLATE_BOUNDS in _codes(result)


def test_stim_line_bounds() -> None:
    bad = {"factors": {"salience": {"levels": {
        "salient": [["x"] * 7], "embedded": [["y"] * 7]}}}}
    result = validate_spec(_with_stim(bad))
    assert ErrorCode.V2_STIM_LINE_BOUNDS in _codes(result)
    long_line = "x" * 201
    bad2 = {"factors": {"salience": {"levels": {
        "salient": [[long_line]], "embedded": [[long_line]]}}}}
    assert ErrorCode.V2_STIM_LINE_BOUNDS in _codes(validate_spec(_with_stim(bad2)))


def test_stim_line_count_mismatch() -> None:
    # match_line_count=true but salient=1 line vs embedded=4 lines
    result = validate_spec(_with_stim(_STIMULUS_SPEC))
    assert ErrorCode.V2_STIM_LINE_COUNT_MISMATCH in _codes(result)
    # the matched variant must pass
    assert validate_spec(_with_stim(_STIMULUS_SPEC_MATCHED)).valid


def test_stim_slot_syntax() -> None:
    bad = {"factors": {"salience": {"levels": {
        "salient": [["ok {salience}"]], "embedded": [["bad {salience"]]},
        "match_line_count": False}}}
    result = validate_spec(_with_stim(bad))
    assert ErrorCode.V2_STIM_SLOT_SYNTAX in _codes(result)


def test_stim_unresolved_pool_slot() -> None:
    bad = {"factors": {"salience": {"levels": {
        "salient": [["{pool:missing}"]], "embedded": [["{pool:missing}"]]},
        "match_line_count": False}}}
    result = validate_spec(_with_stim(bad))
    assert ErrorCode.V2_STIM_UNRESOLVED_SLOT in _codes(result)


def test_stim_response_name_slot_rejected() -> None:
    # {answer} is a response name, not a factor — must be rejected, not coerced
    bad = {"factors": {"salience": {"levels": {
        "salient": [["slot {answer}"]], "embedded": [["slot {answer}"]]},
        "match_line_count": False}}}
    result = validate_spec(_with_stim(bad))
    assert ErrorCode.V2_STIM_UNRESOLVED_SLOT in _codes(result)


def test_stim_pool_bounds() -> None:
    bad = {"factors": {"salience": {"levels": {
        "salient": [["x"]], "embedded": [["y"]]}, "match_line_count": False}},
        "pools": {"p": []}}
    result = validate_spec(_with_stim(bad))
    assert ErrorCode.V2_STIM_POOL_BOUNDS in _codes(result)


# ---------------------------------------------------------------------------
# Derived spec validation
# ---------------------------------------------------------------------------

def test_derived_unknown_op() -> None:
    result = validate_spec(_v2_config(derived_spec=[{"name": "x", "op": "magic"}]))
    assert ErrorCode.V2_DERIVED_UNKNOWN_OP in _codes(result)


def test_derived_duplicate_name() -> None:
    result = validate_spec(_v2_config(derived_spec=[
        {"name": "x", "op": "trial_number"}, {"name": "x", "op": "block_progress"}]))
    assert ErrorCode.V2_DERIVED_DUPLICATE_NAME in _codes(result)


def test_derived_bad_args_unknown_factor() -> None:
    result = validate_spec(_v2_config(derived_spec=[
        {"name": "x", "op": "count_factor_level", "args": {"factor": "nope", "level": "salient"}}]))
    assert ErrorCode.V2_DERIVED_BAD_ARGS in _codes(result)


def test_derived_bad_args_extra() -> None:
    result = validate_spec(_v2_config(derived_spec=[
        {"name": "x", "op": "trial_number", "args": {"junk": "1"}}]))
    assert ErrorCode.V2_DERIVED_BAD_ARGS in _codes(result)


# ---------------------------------------------------------------------------
# Measures validation
# ---------------------------------------------------------------------------

def test_measure_bad_source() -> None:
    result = validate_spec(_v2_config(measures=[{"name": "rt", "source": "Not A Path"}]))
    assert ErrorCode.V2_MEASURE_BAD_SOURCE in _codes(result)


def test_measure_duplicate_name() -> None:
    result = validate_spec(_v2_config(measures=[
        {"name": "rt", "source": "response.rt_ms"}, {"name": "rt", "source": "response.value"}]))
    assert ErrorCode.V2_MEASURE_DUPLICATE_NAME in _codes(result)


# ---------------------------------------------------------------------------
# Materialization determinism + fingerprint coverage
# ---------------------------------------------------------------------------

_V2_FULL: dict[str, object] = _v2_config(
    stimulus_spec=_STIMULUS_SPEC_MATCHED,
    derived_spec=[
        {"name": "trial_number", "op": "trial_number"},
        {"name": "block_progress", "op": "block_progress"},
        {"name": "salient_count", "op": "count_factor_level",
         "args": {"factor": "salience", "level": "salient"}},
    ],
)


def test_materialization_deterministic_in_process() -> None:
    spec1 = ExperimentSpec.model_validate(dict(_V2_FULL))
    spec2 = ExperimentSpec.model_validate(dict(_V2_FULL))
    b1 = build_bundle(spec1, generated_at="2000-01-01T00:00:00Z")
    b2 = build_bundle(spec2, generated_at="2000-01-01T00:00:00Z")
    assert b1["bundle_sha256"] == b2["bundle_sha256"]
    # stimulus content present and non-trivial
    trials = b1["trials"]
    assert isinstance(trials, list) and trials
    for trial in trials:
        lines = trial["stimulus"]["lines"]  # type: ignore[index]
        assert isinstance(lines, list) and lines
        assert set(trial["stimulus"].keys()) == {"lines"}  # type: ignore[index]
        assert isinstance(trial["derived"]["trial_number"], int)  # type: ignore[index]
        assert isinstance(trial["derived"]["salient_count"], int)  # type: ignore[index]


def test_materialization_covers_line_count_and_slots() -> None:
    spec = ExperimentSpec.model_validate(dict(_V2_FULL))
    bundle = build_bundle(spec, generated_at="2000-01-01T00:00:00Z")
    for trial in bundle["trials"]:  # type: ignore[index]
        lines = trial["stimulus"]["lines"]  # type: ignore[index]
        assert len(lines) == 4  # both levels length-matched at 4 lines
        # no unresolved slots survive materialization
        assert all("{" not in line and "}" not in line for line in lines)


def test_materialization_independent_of_pythonhashseed() -> None:
    code = (
        "from src.experiment.export import build_bundle\n"
        "from src.experiment.canonical import canonical_json\n"
        "from src.experiment.schemas import ExperimentSpec\n"
        f"spec = ExperimentSpec.model_validate({repr(_V2_FULL)})\n"
        "bundle = build_bundle(spec, generated_at='2000-01-01T00:00:00Z')\n"
        "print(canonical_json(bundle))\n"
    )
    outputs = []
    for hashseed in ("1", "2"):
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
            env={"PYTHONHASHSEED": hashseed, "PATH": "", "CALC_AGENT_ENV_FILE": "/dev/null"},
            timeout=120,
        )
        assert proc.returncode == 0, proc.stderr
        outputs.append(proc.stdout.strip())
    assert outputs[0] == outputs[1]


def test_v2_fingerprint_changes_with_stimulus_content() -> None:
    """Materialized stimulus is inside trials_fingerprint: editing a template must change it."""
    altered = dict(_V2_FULL)
    stim = _deep_copy_stim()
    stim["factors"]["salience"]["levels"]["salient"][0][0] = "DIFFERENT clue text."
    altered["stimulus_spec"] = stim
    b_base = build_bundle(ExperimentSpec.model_validate(dict(_V2_FULL)), generated_at="2000-01-01T00:00:00Z")
    b_alt = build_bundle(ExperimentSpec.model_validate(altered), generated_at="2000-01-01T00:00:00Z")
    assert b_base["reproducibility"]["trials_fingerprint"] != b_alt["reproducibility"]["trials_fingerprint"]  # type: ignore[index]
    assert b_base["reproducibility"]["config_fingerprint"] != b_alt["reproducibility"]["config_fingerprint"]  # type: ignore[index]


def _deep_copy_stim() -> dict[str, object]:
    import copy
    return copy.deepcopy(_STIMULUS_SPEC_MATCHED)  # type: ignore[arg-type]


def test_v2_config_fields_in_config_fingerprint() -> None:
    """Setting measures (config-level field) changes config_fingerprint but not trials."""
    base = build_bundle(ExperimentSpec.model_validate(_v2_config()), generated_at="2000-01-01T00:00:00Z")
    with_m = build_bundle(
        ExperimentSpec.model_validate(_v2_config(measures=[{"name": "rt", "source": "response.rt_ms"}])),
        generated_at="2000-01-01T00:00:00Z",
    )
    assert base["reproducibility"]["config_fingerprint"] != with_m["reproducibility"]["config_fingerprint"]  # type: ignore[index]
    assert base["reproducibility"]["trials_fingerprint"] == with_m["reproducibility"]["trials_fingerprint"]  # type: ignore[index]


def test_v2_bundle_verify_bundle_ok() -> None:
    from src.experiment.verify import verify_bundle

    bundle = build_bundle(ExperimentSpec.model_validate(dict(_V2_FULL)), generated_at="2000-01-01T00:00:00Z")
    sandbox = Path("data/.test-sandbox/v2")
    sandbox.mkdir(parents=True, exist_ok=True)
    path = sandbox / "bundle.json"
    from src.experiment.canonical import canonical_json
    path.write_text(canonical_json(bundle), encoding="utf-8")
    try:
        report = verify_bundle(path)
        assert report.ok, report.detail
    finally:
        path.unlink(missing_ok=True)  # keep the shared sandbox directory


def test_derived_ops_whitelist_frozen() -> None:
    assert DERIVED_OP_WHITELIST == ("trial_number", "block_progress", "count_factor_level")


# ---------------------------------------------------------------------------
# Import-surface independence (game/tool/agent freedom)
# ---------------------------------------------------------------------------

def test_stimulus_module_import_surface() -> None:
    """stimulus.py must not import from tools/, agent/, api/, or any game module."""
    import src.experiment.stimulus as stim_module

    forbidden = ("src.tools", "src.agent", "src.api", "src.experiment.game_schemas",
                 "src.experiment.game_render")
    source = Path(stim_module.__file__).read_text(encoding="utf-8")
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")):
            for prefix in forbidden:
                assert prefix not in stripped, f"forbidden import: {stripped}"
