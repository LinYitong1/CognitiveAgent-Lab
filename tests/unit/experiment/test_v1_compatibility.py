"""M2-B Phase 1 compatibility gate: v1 bytes, fingerprints and bundles are unchanged.

These tests are the executable form of the D-M2-1 contract §1.2 (M2B_CONTRACT.md):
the spec_dump() projection must keep every legacy v1 serialized byte, config
fingerprint, trials fingerprint, golden artifact and verify_bundle outcome
identical to the pre-M2-B baseline.

The four hardcoded fingerprint baselines below were captured from the v1 engine
on 2026-10-21 BEFORE any M2-B change (recorded in docs/m2/M2B_CONTRACT.md flow):
seed11-demo is the pipeline DEMO_SPEC (its bundle_sha256 matches the value recorded
in the B3 delivery), seed7-example is the examples/run_game_render.py spec.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.experiment.canonical import canonical_json, sha256_hex
from src.experiment.export import build_bundle
from src.experiment.schemas import ExperimentSpec, spec_dump
from src.experiment.verify import verify_bundle

REPO_ROOT = Path(__file__).resolve().parents[3]

# --- pre-change baselines (captured 2026-10-21, pre-M2-B engine) ------------

SPEC_11: dict[str, object] = {
    "schema_version": 1,
    "name": "demo-agent-game",
    "version": "0.1.0",
    "seed": 11,
    "factors": [{"name": "side", "levels": [{"name": "left"}, {"name": "right"}]}],
    "blocks": [{"name": "practice", "trial_count": 4}, {"name": "main", "trial_count": 20}],
    "constraints": {"balance": True},
    "responses": [
        {"name": "answer", "kind": "choice", "options": ["left", "right"], "correct_from": "side"}
    ],
    "timing": {"fixation_ms": 400, "stimulus_ms": None, "isi_ms": 600},
}

SPEC_7: dict[str, object] = {
    "schema_version": 1,
    "name": "example-game",
    "version": "0.1.0",
    "seed": 7,
    "factors": [{"name": "item", "levels": [{"name": "red"}, {"name": "blue"}]}],
    "blocks": [{"name": "practice", "trial_count": 4}, {"name": "main", "trial_count": 20}],
    "constraints": {"balance": True},
    "responses": [
        {"name": "pick", "kind": "choice", "options": ["red", "blue"], "correct_from": "item"}
    ],
    "timing": {"fixation_ms": 400, "stimulus_ms": None, "isi_ms": 800},
}

BASELINES = {
    "seed11-demo": {
        "config_fingerprint": "3dbb2925d3d8608240511e0c65491b38ae7615e7f900256213152e35da4bb891",
        "trials_fingerprint": "c643a35f4faf2e1e03921a8f8caf1eb6dc548c7e8d784c032f3627f6bed39487",
        "bundle_sha256": "9741eb7abd5345279f908706172021ab0177e98662c06008e2cdafba22cba769",
        "canonical_text_sha": "c7937ebda5a40953f46340e50cd9189bd721ec1d4eb6bfdd712da4c3ea08c56e",
        "config": SPEC_11,
    },
    "seed7-example": {
        "config_fingerprint": "0131e0255180db786d4e2e5c715920e7785b997b373510adac618dad79db0e4c",
        "trials_fingerprint": "1aa3c723eb8b5cecfd021fa4fa686b87575a1a814f1231cccf0af3553cda5f99",
        "bundle_sha256": "bf9de76aa13d2ffe24a941e39f25a1331ac6f72143098c695b54c7ffcacd25c5",
        "canonical_text_sha": "9c683f6db38f000e0494cdc50473fdba6fa0e4a5082d41caac353df35d86ee43",
        "config": SPEC_7,
    },
}

FIXED_GENERATED_AT = "2000-01-01T00:00:00Z"


def _bundle_for(tag: str) -> dict[str, object]:
    spec = ExperimentSpec.model_validate(dict(BASELINES[tag]["config"]))
    return build_bundle(spec, generated_at=FIXED_GENERATED_AT)


def test_v1_config_and_trials_fingerprints_unchanged() -> None:
    """The three fingerprints reproduce the pre-M2-B baseline for both fixed specs."""
    for tag, base in BASELINES.items():
        bundle = _bundle_for(tag)
        repro = bundle["reproducibility"]
        assert isinstance(repro, dict)
        assert repro["config_fingerprint"] == base["config_fingerprint"], tag
        assert repro["trials_fingerprint"] == base["trials_fingerprint"], tag
        assert bundle["bundle_sha256"] == base["bundle_sha256"], tag


def test_v1_bundle_canonical_bytes_unchanged() -> None:
    """Full canonical bundle text (fixed generated_at) hashes to the baseline."""
    for tag, base in BASELINES.items():
        bundle = _bundle_for(tag)
        assert sha256_hex(canonical_json(bundle)) == base["canonical_text_sha"], tag


def test_v1_spec_dump_has_no_v2_keys_and_matches_model_dump() -> None:
    """A v1-shaped spec: spec_dump() output equals bare model_dump() minus nothing.

    In Phase 1 (no v2 fields on the model yet) this is trivially true; once the
    v2 fields exist (Phase 2), None-defaulting + projection keeps it true.

    M3-A P0 added nested v2 fields (responses[].correct_rule,
    stimulus_spec.variables); the expressiveness Stage 1 added
    responses[].withhold_option and blocks[].timing; they obey the same
    "unset contributes no bytes" rule, so "bare minus v2 fields" here means
    bare minus those nested keys too.
    """
    for tag, base in BASELINES.items():
        spec = ExperimentSpec.model_validate(dict(base["config"]))
        dump = spec_dump(spec)
        bare = spec.model_dump()
        for v2_field in ("stimulus_spec", "derived_spec", "measures"):
            assert dump.get(v2_field) is None or v2_field in dump, tag  # populated keeps
            if v2_field in dump:
                assert dump[v2_field] is not None, tag
        # the nested v2 fields are removed from the bare dump for the same reason
        # (an unset v2 feature contributes no bytes to the projection)
        for response in bare["responses"]:
            assert response.pop("correct_rule", None) is None, tag
            assert response.pop("withhold_option", None) is None, tag
        for block in bare["blocks"]:
            assert block.pop("timing", None) is None, tag
        # v1 spec: no v2 key may survive the projection once the fields exist;
        # and every surviving key must equal the bare dump (projection only removes).
        assert {k: v for k, v in dump.items()} == {
            k: v for k, v in bare.items() if k not in ("stimulus_spec", "derived_spec", "measures")
        }, tag


def test_v1_bundle_verify_bundle_still_ok() -> None:
    """A freshly exported v1 bundle passes generator-free verification (export/verify round trip)."""
    bundle = _bundle_for("seed11-demo")
    sandbox = Path("data/.test-sandbox/v1-compat")
    sandbox.mkdir(parents=True, exist_ok=True)
    path = sandbox / "bundle.json"
    path.write_text(canonical_json(bundle), encoding="utf-8")
    try:
        report = verify_bundle(path)
        assert report.ok, report.detail
    finally:
        path.unlink(missing_ok=True)
        sandbox.rmdir()


def test_v1_bundle_bytes_independent_of_pythonhashseed() -> None:
    """Subprocess byte-stability under PYTHONHASHSEED variation (golden discipline)."""
    code = (
        "from src.experiment.export import build_bundle\n"
        "from src.experiment.canonical import canonical_json\n"
        "from src.experiment.schemas import ExperimentSpec\n"
        f"spec = ExperimentSpec.model_validate({repr(SPEC_11)})\n"
        f"bundle = build_bundle(spec, generated_at={FIXED_GENERATED_AT!r})\n"
        "print(canonical_json(bundle))\n"
    )
    outputs = []
    for hashseed in ("1", "2"):
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            env={"PYTHONHASHSEED": hashseed, "PATH": "", "CALC_AGENT_ENV_FILE": "/dev/null"},
            timeout=120,
        )
        assert proc.returncode == 0, proc.stderr
        outputs.append(proc.stdout.strip())  # strip print()'s trailing newline
    assert outputs[0] == outputs[1]
    assert sha256_hex(outputs[0]) == BASELINES["seed11-demo"]["canonical_text_sha"]
