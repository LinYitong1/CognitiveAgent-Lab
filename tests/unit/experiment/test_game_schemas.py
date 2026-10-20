"""Phase B B0 acceptance tests: the GameSpec schema and validate_game (contract §6 GB-1~GB-10).

Fixture genericity (GB-10): all references use the golden bundle tests/golden/generic-2x2-seed7.json,
reading its real six fingerprints dynamically to build a legal GameSpec — no hand-written fingerprints, no paradigm-specific data.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.experiment.game_schemas import (
    ExperimentRef,
    GameSpec,
    game_config_fingerprint,
    validate_game,
)

GOLDEN_BUNDLE_PATH = Path(__file__).resolve().parents[2] / "golden" / "generic-2x2-seed7.json"

# experiment-layer ownership fields (the forbidden-name set of contract §1 D-1; the GB-8 introspection exempts the ExperimentRef subtree)
FORBIDDEN_FIELD_NAMES = frozenset(
    {"trials", "factors", "blocks", "constraints", "correct", "correct_from", "timing", "responses"}
)


def _load_bundle() -> dict[str, object]:
    return json.loads(GOLDEN_BUNDLE_PATH.read_text(encoding="utf-8"))


def _ref_from_bundle(bundle: dict[str, object]) -> dict[str, object]:
    spec_part = bundle["spec"]  # type: ignore[index]
    repro = bundle["reproducibility"]  # type: ignore[index]
    return {
        "name": spec_part["name"],  # type: ignore[index]
        "version": spec_part["version"],  # type: ignore[index]
        "seed": spec_part["seed"],  # type: ignore[index]
        "config_fingerprint": repro["config_fingerprint"],  # type: ignore[index]
        "trials_fingerprint": repro["trials_fingerprint"],  # type: ignore[index]
        "bundle_sha256": bundle["bundle_sha256"],
    }


def _valid_game_spec(bundle: dict[str, object]) -> dict[str, object]:
    """Minimal legal GameSpec: references the golden bundle + binds all options for the first choice response."""
    responses = bundle["spec"]["responses"]  # type: ignore[index]
    choice = next(r for r in responses if r["kind"] == "choice")  # type: ignore[union-attr]
    keys = {chr(ord("a") + i): option for i, option in enumerate(choice["options"])}  # type: ignore[call-overload]
    return {
        "schema_version": 1,
        "game": {"name": "generic-demo", "version": "0.1.0"},
        "experiment_ref": _ref_from_bundle(bundle),
        "scene": {"title": "Demo", "instructions": "Respond as fast as possible"},
        "input": {"modalities": ["keyboard"], "bindings": [{"response_name": choice["name"], "keys": keys}]},  # type: ignore[union-attr]
        "feedback": {"on_response": "none"},
        "flow": {"ready_screen": True, "block_breaks": True, "end_screen": "summary"},
        "gamification": {"score": False, "progress_bar": True, "streak_bonus": False},
    }


# ---------- GB-1: the minimal legal GameSpec passes G1+G2 ----------


def test_gb1_minimal_valid_game_spec_passes() -> None:
    bundle = _load_bundle()
    result = validate_game(_valid_game_spec(bundle), bundle)
    assert result.valid is True
    assert result.errors == []
    assert result.game_spec is not None
    assert result.game_config_fingerprint is not None


# ---------- GB-2: undeclared fields rejected per model (defense D-1) ----------


@pytest.mark.parametrize(
    "inject_path",
    [
        ["rogue_field"],  # top level
        ["game", "rogue_field"],
        ["experiment_ref", "rogue_field"],
        ["scene", "rogue_field"],
        ["input", "rogue_field"],
        ["input", "bindings", 0, "rogue_field"],
        ["feedback", "rogue_field"],
        ["flow", "rogue_field"],
        ["gamification", "rogue_field"],
        ["trials"],  # attempted smuggling of experiment semantics (trials)
        ["correct_from"],  # attempted smuggling of correctness determination
        ["constraints"],  # attempted smuggling of experiment constraints
    ],
)
def test_gb2_unknown_fields_rejected(inject_path: list[object]) -> None:
    bundle = _load_bundle()
    spec = _valid_game_spec(bundle)

    node: object = spec
    for key in inject_path[:-1]:
        node = node[key]  # type: ignore[index]
    node[inject_path[-1]] = {"evil": True}  # type: ignore[index]

    result = validate_game(spec, bundle)
    assert result.valid is False
    assert any(e.error_code == "SCHEMA_INVALID" for e in result.errors)


# ---------- GB-3: fingerprint format + the six references mutated one by one ----------


def test_gb3_fingerprint_format_enforced() -> None:
    bundle = _load_bundle()
    spec = _valid_game_spec(bundle)
    spec["experiment_ref"]["config_fingerprint"] = "not-a-hex-fingerprint"  # type: ignore[index]
    result = validate_game(spec, bundle)
    assert result.valid is False
    assert any(e.error_code == "SCHEMA_INVALID" for e in result.errors)


@pytest.mark.parametrize(
    "field,value",
    [
        ("name", "other-experiment"),
        ("version", "9.9.9"),
        ("seed", 123),
        ("config_fingerprint", "0" * 64),
        ("trials_fingerprint", "0" * 64),
        ("bundle_sha256", "0" * 64),
    ],
)
def test_gb3_reference_mismatch_detected(field: str, value: object) -> None:
    bundle = _load_bundle()
    spec = _valid_game_spec(bundle)
    spec["experiment_ref"][field] = value  # type: ignore[index]
    result = validate_game(spec, bundle)
    assert result.valid is False
    mismatches = [e for e in result.errors if e.error_code == "REF_MISMATCH"]
    assert mismatches, f"expected REF_MISMATCH for {field}"
    assert mismatches[0].path == f"experiment_ref.{field}"


def test_gb3_tampered_bundle_detected() -> None:
    """Whole-bundle integrity: hand-editing any bundle content → recomputed fingerprint mismatch → REF_MISMATCH."""
    bundle = _load_bundle()
    tampered = copy.deepcopy(bundle)
    tampered["trials"][0]["factors"] = {"difficulty": "easy"}  # type: ignore[index]
    result = validate_game(_valid_game_spec(bundle), tampered)
    assert result.valid is False
    assert any(
        e.error_code == "REF_MISMATCH" and "integrity" in e.message for e in result.errors
    )


# ---------- GB-4: binding-rule error codes, full positive and negative cases ----------


def test_gb4_unknown_response() -> None:
    bundle = _load_bundle()
    spec = _valid_game_spec(bundle)
    spec["input"]["bindings"][0]["response_name"] = "nonexistent_response"  # type: ignore[index]
    result = validate_game(spec, bundle)
    assert any(e.error_code == "UNKNOWN_RESPONSE" for e in result.errors)


def test_gb4_invalid_binding_target_text_response() -> None:
    """Binding to a non-choice response → INVALID_BINDING_TARGET (builds a legal spec variant containing a text response)."""
    bundle = _load_bundle()
    spec = _valid_game_spec(bundle)
    # append a text response on the spec side of a bundle copy (deep-copying the bundle and recomputing
    # fingerprints is unnecessary — instead, point the binding at a construction that does not exist
    # among the golden bundle's choices: the golden bundle has exactly one choice response, so a local bundle copy is built)
    local_bundle = copy.deepcopy(bundle)
    local_bundle["spec"]["responses"].append(  # type: ignore[index]
        {"name": "notes", "kind": "text", "options": [], "scale": None, "correct_from": None}
    )
    spec["input"]["bindings"].append(  # type: ignore[index]
        {"response_name": "notes", "keys": {"t": "anything"}}
    )
    result = validate_game(spec, local_bundle)
    assert any(e.error_code == "INVALID_BINDING_TARGET" for e in result.errors)


def test_gb4_option_out_of_domain() -> None:
    bundle = _load_bundle()
    spec = _valid_game_spec(bundle)
    first_key = next(iter(spec["input"]["bindings"][0]["keys"]))  # type: ignore[index]
    spec["input"]["bindings"][0]["keys"][first_key] = "not-an-option"  # type: ignore[index]
    result = validate_game(spec, bundle)
    assert any(e.error_code == "OPTION_OUT_OF_DOMAIN" for e in result.errors)


def test_gb4_duplicate_key_across_bindings() -> None:
    bundle = _load_bundle()
    spec = _valid_game_spec(bundle)
    responses = bundle["spec"]["responses"]  # type: ignore[index]
    choice = next(r for r in responses if r["kind"] == "choice")  # type: ignore[union-attr]
    spec["input"]["bindings"].append(  # type: ignore[index]
        {"response_name": choice["name"], "keys": {next(iter(spec["input"]["bindings"][0]["keys"])): choice["options"][0]}}  # type: ignore[index,union-attr]
    )
    result = validate_game(spec, bundle)
    assert any(e.error_code == "DUPLICATE_KEY" for e in result.errors)


def test_gb4_missing_binding_for_choice_response() -> None:
    bundle = _load_bundle()
    spec = _valid_game_spec(bundle)
    spec["input"]["bindings"] = []  # type: ignore[index]
    result = validate_game(spec, bundle)
    assert any(e.error_code == "MISSING_BINDING" for e in result.errors)


@pytest.mark.parametrize("bad_key", ["A", "ab", "F1", "ctrl", "", "SPACE"])
def test_gb4_invalid_key_format(bad_key: str) -> None:
    bundle = _load_bundle()
    spec = _valid_game_spec(bundle)
    spec["input"]["bindings"][0]["keys"] = {bad_key: "easy"}  # type: ignore[index]
    result = validate_game(spec, bundle)
    assert any(e.error_code == "INVALID_KEY" for e in result.errors)


# ---------- GB-5: complete error-report structure ----------


def test_gb5_error_report_structure() -> None:
    bundle = _load_bundle()
    spec = _valid_game_spec(bundle)
    spec["input"]["bindings"][0]["response_name"] = "nope"  # type: ignore[index]
    result = validate_game(spec, bundle)
    assert result.valid is False
    for issue in result.errors:
        assert issue.error_code
        assert issue.path
        assert issue.message
        assert issue.suggestion


# ---------- GB-6: legal but with a warning (partial option coverage) ----------


def test_gb6_partial_option_coverage_warns() -> None:
    bundle = _load_bundle()
    spec = _valid_game_spec(bundle)
    responses = bundle["spec"]["responses"]  # type: ignore[index]
    choice = next(r for r in responses if r["kind"] == "choice")  # type: ignore[union-attr]
    options = choice["options"]  # type: ignore[union-attr]
    # bind only the first option → the other option is unreachable → warning but legal
    spec["input"]["bindings"][0]["keys"] = {"a": options[0]}  # type: ignore[index]
    result = validate_game(spec, bundle)
    assert result.valid is True
    assert result.errors == []
    assert any(w.error_code == "PARTIAL_OPTION_COVERAGE" for w in result.warnings)


# ---------- GB-7: fingerprint determinism ----------


def test_gb7_fingerprint_key_order_and_whitespace_insensitive() -> None:
    bundle = _load_bundle()
    spec = _valid_game_spec(bundle)
    reference = game_config_fingerprint(GameSpec.model_validate(spec))

    # key order shuffled + whitespace added (re-serialized, then re-parsed)
    shuffled = json.loads(json.dumps(spec, indent=4, sort_keys=False))
    reordered = {k: shuffled[k] for k in reversed(list(shuffled))}
    assert game_config_fingerprint(GameSpec.model_validate(reordered)) == reference


def test_gb7_fingerprint_changes_on_any_field_change() -> None:
    bundle = _load_bundle()
    spec = _valid_game_spec(bundle)
    reference = game_config_fingerprint(GameSpec.model_validate(spec))

    variant = copy.deepcopy(spec)
    variant["feedback"]["duration_ms"] = 300
    assert game_config_fingerprint(GameSpec.model_validate(variant)) != reference


# ---------- GB-8: introspection assertion — field tree ∩ forbidden-name set = ∅ (ExperimentRef exempt) ----------


def _collect_field_names(model: type[object], _seen: set[type[object]] | None = None) -> set[str]:
    """Recursively collect model field names (the ExperimentRef subtree is exempt — its fields are read-only reference copies)."""
    seen: set[type[object]] = _seen or set()
    if model in seen or model is ExperimentRef:
        return set()
    seen.add(model)
    fields: set[str] = set()
    field_types: dict[str, object] = getattr(model, "model_fields", {})
    for name, field_info in field_types.items():
        fields.add(name)
        annotation = getattr(field_info, "annotation", None)
        if annotation is not None:
            fields |= _collect_field_names(annotation, seen)  # type: ignore[arg-type]
    return fields


def test_gb8_no_experiment_logic_fields_in_game_spec() -> None:
    names = _collect_field_names(GameSpec)
    assert names, "introspection found no fields"
    overlap = names & FORBIDDEN_FIELD_NAMES
    assert not overlap, f"GameSpec field tree contains experiment-owned names: {overlap}"


# ---------- GB-9: the size guard ----------


def test_gb9_size_guard_rejects_oversized_spec() -> None:
    bundle = _load_bundle()
    spec = _valid_game_spec(bundle)
    spec["scene"]["assets"] = {"pad": "x" * (300 * 1024)}  # type: ignore[index]
    result = validate_game(spec, bundle)
    assert result.valid is False
    assert any(e.error_code == "GAME_SPEC_TOO_LARGE" for e in result.errors)


def test_gb9_size_guard_passes_normal_spec() -> None:
    bundle = _load_bundle()
    result = validate_game(_valid_game_spec(bundle), bundle)
    assert result.valid is True


# ---------- GB-10: genericity — no paradigm names hardcoded in product source ----------


def test_gb10_no_paradigm_hardcoding_in_product_source() -> None:
    source = Path("src/experiment/game_schemas.py").read_text(encoding="utf-8").lower()
    for token in ("stroop", "nback", "n-back", "flanker", "go/no-go"):
        assert token not in source, f"paradigm name {token!r} hardcoded in game_schemas.py"


def test_gb10_fixtures_derive_from_golden_bundle() -> None:
    """All six references of the legal fixture come from the golden bundle's actual values (no hand-written fingerprints)."""
    bundle = _load_bundle()
    spec = _valid_game_spec(bundle)
    result = validate_game(spec, bundle)
    assert result.valid is True  # with hand-written fingerprints, G2 would necessarily mismatch


# ---------- supplement: non-dict input / direct Pydantic use ----------


def test_non_dict_input_rejected() -> None:
    bundle = _load_bundle()
    result = validate_game(["not", "a", "dict"], bundle)
    assert result.valid is False
    assert result.game_spec is None
    assert result.game_config_fingerprint is None


def test_gamespec_pydantic_direct_validation() -> None:
    bundle = _load_bundle()
    spec = GameSpec.model_validate(_valid_game_spec(bundle))
    assert spec.game.name == "generic-demo"
    assert spec.experiment_ref.seed == bundle["spec"]["seed"]  # type: ignore[index]
    with pytest.raises(ValidationError):
        GameSpec.model_validate({"schema_version": 2})  # type: ignore[arg-type,dict-item]
