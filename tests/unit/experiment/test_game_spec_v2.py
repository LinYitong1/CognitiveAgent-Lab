"""M2-C Phase 3 tests: GameSpec v2 sections, G8 validation, compatibility, fixture.

Covers the approved M2C_CONTRACT:
- v1 GameSpec fingerprints reproduce the pre-change baselines (captured before
  any game_schemas.py edit on 2026-10-21, working tree == 7e9978c);
- every G8 code has >= 1 negative test;
- experiment-semantics smuggling rejected per invariant (static enforcement);
- fingerprint stability: unset v2 sections -> v1 fingerprint; set -> different;
  key-order independent; PYTHONHASHSEED independent;
- the Manor Case fixture validates and regenerates byte-identically.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from src.experiment.game_schemas import (
    CREATIVE_FREEDOMS,
    CONTROLLED_INVARIANTS,
    GameSpec,
    game_config_fingerprint,
    game_spec_dump,
    validate_game,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "manor-case"

# --- pre-change v1 baselines (captured 2026-10-21 before any M2-C edit) ------

V1_DEMO_FINGERPRINT = "a6327d395ee733648997dbdc1045f3b8a304fe2d5bbc76bf84dc81b6105c2a8c"
V1_HANDMADE_FINGERPRINT = "8aeac5b63f7bb1fbf2278facd3d06c88be20652017fb20fb88500a1b20c6abb7"


def _load_fixture() -> tuple[dict[str, object], dict[str, object]]:
    bundle = json.loads((FIXTURE_DIR / "bundle.json").read_text(encoding="utf-8"))
    gamespec = json.loads((FIXTURE_DIR / "gamespec.json").read_text(encoding="utf-8"))
    return gamespec, bundle


def _manor_with(**overrides: object) -> dict[str, object]:
    """Deep-copied fixture gamespec with top-level section overrides."""
    import copy

    gamespec, _ = _load_fixture()
    gamespec = copy.deepcopy(gamespec)
    gamespec.update(overrides)
    return gamespec


def _manor_mapping_with(**overrides: object) -> dict[str, object]:
    import copy

    gamespec, _ = _load_fixture()
    gamespec = copy.deepcopy(gamespec)
    mapping = gamespec["mapping"]  # type: ignore[index]
    assert isinstance(mapping, dict)
    mapping.update(overrides)
    return gamespec


def _codes(result: object) -> list[str]:
    return [issue.error_code for issue in result.errors]  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Fixture + compatibility
# ---------------------------------------------------------------------------

def test_manor_fixture_validates() -> None:
    gamespec, bundle = _load_fixture()
    result = validate_game(gamespec, bundle)
    assert result.valid, [(e.error_code, e.path, e.message) for e in result.errors]


def test_manor_fixture_regenerates_byte_identical() -> None:
    """The committed fixture files must match a fresh deterministic regeneration."""
    proc = subprocess.run(
        [sys.executable, str(FIXTURE_DIR / "generate.py")],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
        env={"PATH": "", "CALC_AGENT_ENV_FILE": "/dev/null"},
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() != ""
    # generate.py rewrote the files; git diff must show no change
    diff = subprocess.run(
        ["git", "diff", "--stat", "tests/fixtures/manor-case/"],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    assert diff.stdout.strip() == "", f"fixture regeneration is not byte-identical:\n{diff.stdout}"


def test_v1_demo_gamespec_fingerprint_unchanged() -> None:
    from src.pipeline import demo_game_config

    assert game_config_fingerprint(GameSpec.model_validate(demo_game_config())) == V1_DEMO_FINGERPRINT


def test_v1_handmade_gamespec_fingerprint_unchanged() -> None:
    from src.experiment.export import build_bundle
    from src.experiment.schemas import ExperimentSpec

    b = build_bundle(
        ExperimentSpec.model_validate(
            {
                "schema_version": 1, "name": "gs-baseline", "seed": 5,
                "factors": [{"name": "f", "levels": [{"name": "x"}, {"name": "y"}]}],
                "blocks": [{"name": "main", "trial_count": 4}], "constraints": {"balance": True},
                "responses": [{"name": "r", "kind": "choice", "options": ["x", "y"], "correct_from": "f"}],
                "timing": {"fixation_ms": 100, "stimulus_ms": None, "isi_ms": 100},
            }
        ),
        generated_at="2000-01-01T00:00:00Z",
    )
    g = {
        "schema_version": 1, "game": {"name": "gs-baseline", "version": "0.1.0"},
        "experiment_ref": {
            "name": b["spec"]["name"], "version": b["spec"]["version"], "seed": b["spec"]["seed"],
            "config_fingerprint": b["reproducibility"]["config_fingerprint"],
            "trials_fingerprint": b["reproducibility"]["trials_fingerprint"],
            "bundle_sha256": b["bundle_sha256"],
        },
        "scene": {"title": "T", "instructions": "I"},
        "input": {"modalities": ["keyboard"], "bindings": [{"response_name": "r", "keys": {"x": "x", "y": "y"}}]},
        "feedback": {"on_response": "none", "duration_ms": 100},
    }
    assert game_config_fingerprint(GameSpec.model_validate(g)) == V1_HANDMADE_FINGERPRINT


def test_v1_gamespec_validation_result_identical_with_v2_engine() -> None:
    """A v1 GameSpec validates against a v2 engine exactly as before: no G8 errors,
    warnings or fingerprint changes (v2 sections absent → no-op)."""
    gamespec, bundle = _load_fixture()
    v1_only = {k: v for k, v in gamespec.items() if k in (
        "schema_version", "game", "experiment_ref", "scene", "input", "feedback", "flow", "gamification")}
    v1_only["schema_version"] = 1
    result = validate_game(v1_only, bundle)
    assert not any(c.startswith("G8") for c in _codes(result)), _codes(result)


# ---------------------------------------------------------------------------
# Version guard + fingerprint stability
# ---------------------------------------------------------------------------

def test_v2_sections_on_version_1_rejected() -> None:
    gamespec, bundle = _load_fixture()
    import copy

    v1 = copy.deepcopy(gamespec)
    v1["schema_version"] = 1  # v2 sections still present → guard
    result = validate_game(v1, bundle)
    assert "G8_VERSION_GUARD" in _codes(result)


def test_v2_explicit_null_sections_equal_absent() -> None:
    gamespec, bundle = _load_fixture()
    import copy

    nullified = copy.deepcopy(gamespec)
    for section in ("world", "narrative", "mechanics", "mapping"):
        nullified[section] = None
    result = validate_game(nullified, bundle)
    # sequential trigger default: input bindings present → valid v1-shaped
    assert result.valid, _codes(result)
    dump = game_spec_dump(result.game_spec)  # type: ignore[arg-type]
    for section in ("world", "narrative", "mechanics", "mapping"):
        assert section not in dump


def test_fingerprint_changes_with_v2_sections() -> None:
    gamespec, bundle = _load_fixture()
    import copy

    fp_full = validate_game(gamespec, bundle).game_config_fingerprint
    stripped = copy.deepcopy(gamespec)
    for section in ("world", "narrative", "mechanics", "mapping"):
        stripped.pop(section)
    stripped["schema_version"] = 1
    fp_v1 = validate_game(stripped, bundle).game_config_fingerprint
    assert fp_full != fp_v1
    # schema_version alone (2, no sections) also differs from 1
    stripped2 = copy.deepcopy(stripped)
    stripped2["schema_version"] = 2
    fp_v2_empty = validate_game(stripped2, bundle).game_config_fingerprint
    assert fp_v2_empty != fp_v1


def test_fingerprint_key_order_independent_and_hashseed_stable() -> None:
    gamespec, bundle = _load_fixture()
    reference = validate_game(gamespec, bundle).game_config_fingerprint
    # key order independence: rebuild the dict in reverse top-level order
    reordered = {k: gamespec[k] for k in reversed(list(gamespec.keys()))}
    assert validate_game(reordered, bundle).game_config_fingerprint == reference
    # PYTHONHASHSEED independence (subprocess)
    code = (
        "import json\n"
        "from src.experiment.game_schemas import validate_game\n"
        f"gamespec = json.loads(open({str(FIXTURE_DIR / 'gamespec.json')!r}).read())\n"
        f"bundle = json.loads(open({str(FIXTURE_DIR / 'bundle.json')!r}).read())\n"
        "print(validate_game(gamespec, bundle).game_config_fingerprint)\n"
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
    assert outputs[0] == outputs[1] == reference


# ---------------------------------------------------------------------------
# G8 negative tests (one per code family)
# ---------------------------------------------------------------------------

def test_g8_version_guard_v1_with_world() -> None:
    gamespec, bundle = _load_fixture()
    import copy

    bad = copy.deepcopy(gamespec)
    bad["schema_version"] = 1
    result = validate_game(bad, bundle)
    assert "G8_VERSION_GUARD" in _codes(result)


def test_g8_world_structure_unknown_exit() -> None:
    gamespec, bundle = _load_fixture()
    import copy

    bad = copy.deepcopy(gamespec)
    bad["world"]["rooms"]["hall"]["exits"]["attic"] = "a hidden stair"  # type: ignore[index]
    result = validate_game(bad, bundle)
    assert "G8_WORLD_STRUCTURE" in _codes(result)


def test_g8_world_structure_orphan_room() -> None:
    gamespec, bundle = _load_fixture()
    import copy

    bad = copy.deepcopy(gamespec)
    # cellar only reachable via parlour; remove that exit → cellar orphaned
    del bad["world"]["rooms"]["parlour"]["exits"]["cellar"]  # type: ignore[index]
    result = validate_game(bad, bundle)
    assert "G8_WORLD_STRUCTURE" in _codes(result)


def test_g8_world_structure_duplicate_object_id() -> None:
    gamespec, bundle = _load_fixture()
    import copy

    bad = copy.deepcopy(gamespec)
    clock = dict(bad["world"]["rooms"]["hall"]["objects"][0])  # type: ignore[index]
    bad["world"]["rooms"]["study"]["objects"][0] = clock  # type: ignore[index]  # replace, not append (6-object cap)
    result = validate_game(bad, bundle)
    assert "G8_WORLD_STRUCTURE" in _codes(result)


def test_g8_world_structure_missing_start_room() -> None:
    gamespec, bundle = _load_fixture()
    import copy

    bad = copy.deepcopy(gamespec)
    bad["world"]["start_room"] = "garden"  # type: ignore[index]
    result = validate_game(bad, bundle)
    assert "G8_WORLD_STRUCTURE" in _codes(result)


def test_g8_world_structure_room_bound() -> None:
    gamespec, bundle = _load_fixture()
    import copy

    bad = copy.deepcopy(gamespec)
    for i in range(9):
        bad["world"]["rooms"][f"room-{i}"] = {  # type: ignore[index]
            "title": f"Room {i}", "description": "", "exits": {}, "objects": []
        }
    result = validate_game(bad, bundle)
    assert "G8_WORLD_STRUCTURE" in _codes(result)


def test_g8_mapping_unknown_encounter_object() -> None:
    gamespec = _manor_mapping_with(encounter_objects=["ghost-ledger"])
    _, bundle = _load_fixture()
    result = validate_game(gamespec, bundle)
    assert "G8_MAPPING_UNKNOWN_REFERENCE" in _codes(result)


def test_g8_mapping_encounter_role_mismatch() -> None:
    gamespec = _manor_mapping_with(encounter_objects=["dusty-clock"])  # flavour role
    _, bundle = _load_fixture()
    result = validate_game(gamespec, bundle)
    assert "G8_MAPPING_UNKNOWN_REFERENCE" in _codes(result)


def test_g8_mapping_role_encounter_not_listed() -> None:
    gamespec, bundle = _load_fixture()
    import copy

    bad = copy.deepcopy(gamespec)
    # drop one encounter from the list → its object declares role=encounter unlisted
    bad["mapping"]["encounter_objects"] = bad["mapping"]["encounter_objects"][:-1]  # type: ignore[index]
    result = validate_game(bad, bundle)
    assert "G8_MAPPING_UNKNOWN_REFERENCE" in _codes(result)


def test_g8_mapping_encounter_shortfall() -> None:
    # 24 encounters for 26 trials (also trips role-not-listed; shortfall must fire too)
    gamespec, bundle = _load_fixture()
    import copy

    bad = copy.deepcopy(gamespec)
    world = bad["world"]  # type: ignore[index]
    # remove 2 encounter objects entirely from world and list → 24 vs 26
    removed = bad["mapping"]["encounter_objects"][-2:]  # type: ignore[index]
    bad["mapping"]["encounter_objects"] = bad["mapping"]["encounter_objects"][:-2]  # type: ignore[index]
    for room in world["rooms"].values():  # type: ignore[union-attr]
        room["objects"] = [o for o in room["objects"] if o["object_id"] not in removed]  # type: ignore[index]
    result = validate_game(bad, bundle)
    assert "G8_MAPPING_ENCOUNTER_SHORTFALL" in _codes(result)


def test_g8_mapping_trigger_conflict() -> None:
    gamespec = _manor_mapping_with(trial_trigger="sequential")  # mechanics says explore
    _, bundle = _load_fixture()
    result = validate_game(gamespec, bundle)
    assert "G8_MAPPING_TRIGGER_CONFLICT" in _codes(result)


def test_g8_mapping_invariant_missing() -> None:
    gamespec = _manor_mapping_with(controlled_invariants=CONTROLLED_INVARIANTS[:4])
    _, bundle = _load_fixture()
    result = validate_game(gamespec, bundle)
    assert "G8_MAPPING_INVARIANT_MISSING" in _codes(result)


def test_g8_mapping_invariant_unknown_literal() -> None:
    gamespec = _manor_mapping_with(
        controlled_invariants=list(CONTROLLED_INVARIANTS) + ["mood_music"])
    _, bundle = _load_fixture()
    result = validate_game(gamespec, bundle)
    assert "G8_MAPPING_INVARIANT_MISSING" in _codes(result)


def test_g8_mapping_freedom_unknown() -> None:
    gamespec = _manor_mapping_with(creative_freedom=list(CREATIVE_FREEDOMS) + ["trial_count"])
    _, bundle = _load_fixture()
    result = validate_game(gamespec, bundle)
    assert "G8_MAPPING_FREEDOM_UNKNOWN" in _codes(result)


def test_g8_stimulus_semantics_v1_bundle_rejected() -> None:
    """C-2a: explore trigger + v1-shaped bundle (no stimulus_spec) → rejected."""
    gamespec, bundle = _load_fixture()
    import copy

    v1_bundle = copy.deepcopy(bundle)
    v1_bundle["spec"].pop("stimulus_spec", None)  # type: ignore[union-attr]
    # keep bundle internally consistent by re-stamping integrity fields the way
    # export would (simulating a genuine v1 bundle): easiest is stripping and
    # recomputing
    from src.experiment.canonical import canonical_json, sha256_hex

    v1_bundle["spec"].pop("derived_spec", None)  # type: ignore[union-attr]
    v1_bundle["spec"].pop("measures", None)  # type: ignore[union-attr]
    v1_bundle["spec"]["schema_version"] = 1  # type: ignore[index]
    v1_bundle["spec"]["seed"] = v1_bundle["spec"]["seed"]  # unchanged
    stripped = {k: v for k, v in v1_bundle.items() if k not in ("bundle_sha256", "generated_at")}
    v1_bundle["bundle_sha256"] = sha256_hex(canonical_json(stripped))
    gamespec = copy.deepcopy(gamespec)
    ref = gamespec["experiment_ref"]  # type: ignore[index]
    ref["bundle_sha256"] = v1_bundle["bundle_sha256"]
    ref["config_fingerprint"] = v1_bundle["reproducibility"]["config_fingerprint"]  # type: ignore[index]
    result = validate_game(gamespec, v1_bundle)
    assert "G8_STIMULUS_SEMANTICS" in _codes(result), _codes(result)


def test_g8_block_briefing_unknown_block() -> None:
    gamespec, bundle = _load_fixture()
    import copy

    bad = copy.deepcopy(gamespec)
    bad["narrative"]["block_briefings"]["finale"] = "text"  # type: ignore[index]
    result = validate_game(bad, bundle)
    assert "G8_MAPPING_UNKNOWN_REFERENCE" in _codes(result)


def test_g8_block_briefing_coverage_missing() -> None:
    gamespec, bundle = _load_fixture()
    import copy

    bad = copy.deepcopy(gamespec)
    del bad["narrative"]["block_briefings"]["practice"]  # type: ignore[index]
    result = validate_game(bad, bundle)
    assert "G8_MAPPING_BLOCK_COVERAGE" in _codes(result)


def test_g8_ending_bands_not_ascending() -> None:
    gamespec, bundle = _load_fixture()
    import copy

    bad = copy.deepcopy(gamespec)
    bad["narrative"]["ending_bands"] = [  # type: ignore[index]
        {"min_accuracy": 0.8, "text": "high"},
        {"min_accuracy": 0.5, "text": "mid"},
        {"min_accuracy": 0.0, "text": "low"},
    ]
    result = validate_game(bad, bundle)
    assert "G8_WORLD_STRUCTURE" in _codes(result)


def test_g8_mapping_response_undeclared() -> None:
    gamespec = _manor_mapping_with(
        response_bindings=[{"response_name": "verdict", "keys": {"a": "a", "b": "b", "c": "c"}}])
    _, bundle = _load_fixture()
    result = validate_game(gamespec, bundle)
    assert "G8_MAPPING_UNKNOWN_REFERENCE" in _codes(result)


def test_g8_mapping_response_option_out_of_domain() -> None:
    gamespec = _manor_mapping_with(
        response_bindings=[{"response_name": "accuse", "keys": {"a": "a", "b": "b", "d": "d"}}])
    _, bundle = _load_fixture()
    result = validate_game(gamespec, bundle)
    assert "OPTION_OUT_OF_DOMAIN" in _codes(result)


def test_g8_mapping_key_collision_with_input() -> None:
    # same key bound to a DIFFERENT option on the two surfaces → conflict
    gamespec = _manor_mapping_with(
        response_bindings=[{"response_name": "accuse", "keys": {"a": "b", "b": "b", "c": "c"}}])
    _, bundle = _load_fixture()
    result = validate_game(gamespec, bundle)
    assert "DUPLICATE_KEY" in _codes(result)


def test_g8_mapping_identical_bindings_across_surfaces_legal() -> None:
    # same keys, same response, same options on both surfaces → consistent, valid
    gamespec = _manor_mapping_with(
        response_bindings=[{"response_name": "accuse", "keys": {"a": "a", "b": "b", "c": "c"}}])
    _, bundle = _load_fixture()
    result = validate_game(gamespec, bundle)
    assert result.valid, _codes(result)


# ---------------------------------------------------------------------------
# Invariant static enforcement: experiment-semantics smuggling rejected
# (declarations are not evidence — the schema itself is the fence)
# ---------------------------------------------------------------------------

def test_smuggled_stimulus_in_object_rejected() -> None:
    gamespec, bundle = _load_fixture()
    import copy

    bad = copy.deepcopy(gamespec)
    bad["world"]["rooms"]["hall"]["objects"][1]["stimulus"] = {  # type: ignore[index]
        "lines": ["tampered line"]}
    result = validate_game(bad, bundle)
    assert "SCHEMA_INVALID" in _codes(result)


def test_smuggled_correct_answer_in_mapping_rejected() -> None:
    gamespec, bundle = _load_fixture()
    import copy

    bad = copy.deepcopy(gamespec)
    bad["mapping"]["correct_from"] = "true_suspect"  # type: ignore[index]
    result = validate_game(bad, bundle)
    assert "SCHEMA_INVALID" in _codes(result)


def test_smuggled_timing_in_mechanics_rejected() -> None:
    gamespec, bundle = _load_fixture()
    import copy

    bad = copy.deepcopy(gamespec)
    bad["mechanics"]["timing"] = {"fixation_ms": 0}  # type: ignore[index]
    result = validate_game(bad, bundle)
    assert "SCHEMA_INVALID" in _codes(result)


def test_smuggled_conditions_in_room_rejected() -> None:
    gamespec, bundle = _load_fixture()
    import copy

    bad = copy.deepcopy(gamespec)
    bad["world"]["rooms"]["hall"]["conditions"] = {"salience": "salient"}  # type: ignore[index]
    result = validate_game(bad, bundle)
    assert "SCHEMA_INVALID" in _codes(result)


def test_smuggled_trial_index_in_mapping_rejected() -> None:
    """trial_order protection: there is no field to select or order trials."""
    gamespec, bundle = _load_fixture()
    import copy

    bad = copy.deepcopy(gamespec)
    bad["mapping"]["trial_indices"] = [3, 1, 2]  # type: ignore[index]
    result = validate_game(bad, bundle)
    assert "SCHEMA_INVALID" in _codes(result)


def test_no_genre_vocabulary_in_v2_schema_source() -> None:
    """GB-8-style guard: shared schema stays paradigm-free (detective terms appear
    only in the fixture example, never in game_schemas.py)."""
    source = (REPO_ROOT / "src" / "experiment" / "game_schemas.py").read_text(encoding="utf-8")
    for term in ("detective", "suspect", "clue", "manor", "mystery", "case_file"):
        assert term not in source.lower(), f"genre term {term!r} leaked into the shared schema"
