"""PA-11 export sandbox security tests (contract §7; matched by -k "export_blocks or export_sandbox").

The sandbox root points to a fixed test directory (isomorphic with the M1 file_write tests; evidence that the five-step rule is fully in effect).
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from src.config import Settings
from src.tools import experiment_tools

# Environment note: the host sandbox intermittently blocks session-root mkdir on pytest tmp_path → the M1
# fixed-test-subdirectory pattern is kept (self-created, self-cleaned; leftovers are fine — data/ is gitignored).
TEST_SANDBOX = Path("data/.test-sandbox/experiment-export")


def _try_cleanup(path: Path) -> None:
    try:
        shutil.rmtree(path)
    except OSError:
        pass


def _ensure_dir(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        if not path.is_dir():
            raise


@pytest.fixture()
def sandbox() -> Iterator[Path]:
    _try_cleanup(TEST_SANDBOX)
    _ensure_dir(TEST_SANDBOX)
    yield TEST_SANDBOX
    _try_cleanup(TEST_SANDBOX)

SPEC_DICT: dict[str, object] = {
    "schema_version": 1,
    "name": "generic-2x2",
    "version": "0.1.0",
    "seed": 7,
    "factors": [
        {"name": "difficulty", "levels": [{"name": "easy"}, {"name": "hard"}]},
        {"name": "modality", "levels": [{"name": "visual"}, {"name": "audio"}]},
    ],
    "blocks": [{"name": "main", "trial_count": 8}],
    "constraints": {"balance": True},
    "responses": [
        {"name": "judge_difficulty", "kind": "choice", "options": ["easy", "hard"], "correct_from": "difficulty"}
    ],
    "timing": {"fixation_ms": 500, "stimulus_ms": None, "isi_ms": 1000},
}


async def _export(sandbox: Path, path: str, config: dict[str, object] | None = None):
    settings = Settings(data_sandbox_dir=str(sandbox))
    spec = experiment_tools.build_export_spec(settings)
    return await spec.executor(
        experiment_tools.ExportExperimentInput(config=config or SPEC_DICT, path=path)
    )


@pytest.mark.asyncio
async def test_export_success_in_sandbox(sandbox: Path) -> None:
    result = await _export(sandbox, "experiments/generic-2x2-v0.1.0-seed7.json")
    assert result.ok
    written = sandbox / "experiments" / "generic-2x2-v0.1.0-seed7.json"
    assert written.exists()
    assert "wrote experiments/generic-2x2-v0.1.0-seed7.json" in result.result
    assert "trials_fingerprint=" in result.result
    assert "bundle_sha256=" in result.result
    assert len(result.result) < 512  # §5.3: short text is not truncated by _SUMMARY_LIMIT
    text = written.read_text(encoding="utf-8")
    assert "\n" not in text  # canonical JSON is a single line


@pytest.mark.asyncio
async def test_export_blocks_traversal(sandbox: Path) -> None:
    for path in ("../evil.json", "a/../../evil.json", "/tmp/evil.json"):
        result = await _export(sandbox, path)
        assert not result.ok, f"should be rejected: {path}"
        assert "BLOCKED" in result.error
        assert "path traversal" in result.error
    assert not (TEST_SANDBOX.parent / "evil.json").exists()
    assert not Path("/tmp/evil.json").exists()


@pytest.mark.asyncio
async def test_export_blocks_symlink(sandbox: Path) -> None:
    real_dir = sandbox / "real"
    _ensure_dir(real_dir)
    (real_dir / "inside.json").write_text("{}", encoding="utf-8")

    # directory symlink (rejected even when it points inside the sandbox)
    dir_link = sandbox / f"link-{os.getpid()}"
    if not dir_link.is_symlink():
        os.symlink(real_dir.resolve(), dir_link)
    result = await _export(sandbox, f"{dir_link.name}/evil.json")
    assert not result.ok
    assert "symlink" in result.error

    # the target file itself is a symlink
    file_link = sandbox / f"file-link-{os.getpid()}"
    if not file_link.is_symlink():
        os.symlink((real_dir / "inside.json").resolve(), file_link)
    result = await _export(sandbox, file_link.name)
    assert not result.ok
    assert "symlink" in result.error

    assert not (real_dir / "evil.json").exists()


@pytest.mark.asyncio
async def test_export_blocks_prefix_confusion(sandbox: Path) -> None:
    """Same string prefix as the sandbox root but not a subdirectory (the data-evil shape) — evidence of the is_relative_to component boundary."""
    evil_dir = TEST_SANDBOX.parent / "experiment-export-evil"
    _ensure_dir(evil_dir)
# a symlink inside the sandbox pointing to data-evil (an escape path without ..)
    escape = sandbox / f"escape-{os.getpid()}"
    if not escape.is_symlink():
        os.symlink(evil_dir.resolve(), escape)

    result = await _export(sandbox, f"{escape.name}/x.json")
    assert not result.ok
    assert "BLOCKED" in result.error
    assert "outside sandbox" in result.error
    assert not (evil_dir / "x.json").exists()


@pytest.mark.asyncio
async def test_export_blocks_oversize(sandbox: Path) -> None:
    """Build a >1MB bundle → BLOCKED: export too large (OUT-7 / R-6)."""
    sandbox = TEST_SANDBOX
    big_spec: dict[str, object] = {
        **SPEC_DICT,
        "blocks": [{"name": "main", "trial_count": 20_000}],  # 20k trials ≈ 3MB canonical
    }
    result = await _export(sandbox, "experiments/big.json", config=big_spec)
    assert not result.ok
    assert result.error == "BLOCKED: export too large"
    assert not (sandbox / "experiments" / "big.json").exists()
