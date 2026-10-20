"""PA-2 determinism tests (contract §7; matched by -k "determin or cross_ or isolation or regenerate").

- two runs in the same process produce identical canonical output;
- subprocess outputs with PYTHONHASHSEED=1/=2 have an empty diff (§3.4 verification method);
- block isolation (the block-derivation key = block.name);
- two build_bundle runs with the same spec+seed are byte-identical after stripping generated_at.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from src.experiment.canonical import canonical_json
from src.experiment.export import build_bundle
from src.experiment.generation import generate_trials
from src.experiment.schemas import ExperimentSpec

PROJECT_ROOT = Path(__file__).resolve().parents[3]

SPEC_DICT: dict[str, object] = {
    "schema_version": 1,
    "name": "generic-2x2",
    "version": "0.1.0",
    "seed": 7,
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

_SUBPROCESS_CODE = """
import json, sys
from src.experiment.schemas import ExperimentSpec
from src.experiment.export import build_bundle
from src.experiment.canonical import canonical_json
spec = ExperimentSpec.model_validate(json.loads(sys.argv[1]))
bundle = build_bundle(spec, generated_at="2026-01-01T00:00:00Z")
sys.stdout.write(canonical_json(bundle))
"""


def _spec() -> ExperimentSpec:
    return ExperimentSpec.model_validate(SPEC_DICT)


def test_generation_same_seed_byte_identical() -> None:
    first = generate_trials(_spec())
    second = generate_trials(_spec())
    assert canonical_json([t.model_dump() for t in first.trials]) == canonical_json(
        [t.model_dump() for t in second.trials]
    )
    assert first.trials_fingerprint == second.trials_fingerprint
    assert first.config_fingerprint == second.config_fingerprint


def test_generation_cross_pythonhashseed() -> None:
    """Generate once per subprocess with PYTHONHASHSEED=1 / =2; the output diff is empty (§3.4 item 6)."""
    outputs: list[str] = []
    for hashseed in ("1", "2"):
        env = dict(os.environ, PYTHONHASHSEED=hashseed)
        proc = subprocess.run(
            [sys.executable, "-c", _SUBPROCESS_CODE, json.dumps(SPEC_DICT)],
            capture_output=True,
            text=True,
            env=env,
            cwd=PROJECT_ROOT,
        )
        assert proc.returncode == 0, proc.stderr
        outputs.append(proc.stdout)
    assert outputs[0] == outputs[1], "two runs with different PYTHONHASHSEED must produce byte-identical output"


def test_block_isolation() -> None:
    """Appending/removing/inserting blocks does not disturb other blocks' sequences (block-derivation key = block.name)."""
    base = _spec()  # blocks: practice(8), main(40)
    base_gen = generate_trials(base)

# append a new block at the tail: existing blocks' trials (incl. global index) stay byte-identical
    with_extra = base.model_copy(deep=True)
    extra_block = base.blocks[0].model_copy(deep=True)
    extra_block.name = "extra"
    with_extra.blocks.append(extra_block)
    extra_gen = generate_trials(with_extra)
    assert canonical_json([t.model_dump() for t in base_gen.trials]) == canonical_json(
        [t.model_dump() for t in extra_gen.trials[: len(base_gen.trials)]]
    )

# insert a new block in the middle: existing blocks' trial content (global index stripped) stays byte-identical
    with_middle = base.model_copy(deep=True)
    middle_block = base.blocks[0].model_copy(deep=True)
    middle_block.name = "middle"
    with_middle.blocks.insert(1, middle_block)
    middle_gen = generate_trials(with_middle)

    def _block_trials(gen: object, block_name: str) -> str:
        trials = [t for t in gen.trials if t.block == block_name]  # type: ignore[attr-defined]
        stripped = [
            {k: v for k, v in t.model_dump().items() if k != "index"} for t in trials
        ]
        return canonical_json(stripped)

    for block_name in ("practice", "main"):
        assert _block_trials(base_gen, block_name) == _block_trials(middle_gen, block_name)


def test_regenerate_bundle_identical() -> None:
    """Two build_bundle runs with the same spec+seed are byte-identical after stripping generated_at (incl. bundle_sha256)."""
    first = build_bundle(_spec(), generated_at="2026-01-01T00:00:00Z")
    second = build_bundle(_spec(), generated_at="2027-12-31T23:59:59Z")
    strip = lambda bundle: {  # noqa: E731
        k: v for k, v in bundle.items() if k != "generated_at"
    }
    assert canonical_json(strip(first)) == canonical_json(strip(second))
    assert first["bundle_sha256"] == second["bundle_sha256"]
    assert first["generated_at"] == "2026-01-01T00:00:00Z"
    assert second["generated_at"] == "2027-12-31T23:59:59Z"
