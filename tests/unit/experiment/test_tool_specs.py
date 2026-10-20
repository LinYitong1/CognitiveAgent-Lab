"""PA-7 tool-layer unit tests (contract §7; matched by -k "tool_" — the filename test_tool_specs contains "tool_").

Two-tier error contract: domain-level valid:false → ok=True (no ERROR:); tool-level → ok=False.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from src.agent.registry import ToolRegistry
from src.config import Settings
from src.tools import experiment_tools

# Environment note: the host sandbox intermittently blocks session-root mkdir on pytest tmp_path → the M1
# fixed-test-subdirectory pattern is kept (self-created, self-cleaned; leftovers are fine — data/ is gitignored).
TEST_SANDBOX = Path("data/.test-sandbox/experiment-tools")


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

BAD_SPEC: dict[str, object] = {
    **SPEC_DICT,
    "constraints": {
        "balance": True,
        "ratios": [{"factor": "difficulty", "ratios": {"easy": 0.5, "hard": 0.5}}],
    },
}


def _settings(sandbox: Path) -> Settings:
    return Settings(data_sandbox_dir=str(sandbox))


def test_tool_specs_registered_flags() -> None:
    """The three tools' idempotency/risk_level declarations: idempotent/low ×2, non-idempotent/medium ×1."""
    settings = Settings()
    validate = experiment_tools.build_validate_spec(settings)
    generate = experiment_tools.build_generate_spec(settings)
    export = experiment_tools.build_export_spec(settings)

    assert validate.name == "validate_experiment"
    assert validate.idempotency == "idempotent"
    assert validate.risk_level == "low"
    assert generate.name == "generate_trials"
    assert generate.idempotency == "idempotent"
    assert generate.risk_level == "low"
    assert export.name == "export_experiment"
    assert export.idempotency == "non-idempotent"
    assert export.risk_level == "medium"

    # effective_idempotency returns the declared value by default (none of the three tools overrides it)
    assert validate.effective_idempotency({}) == "idempotent"
    assert generate.effective_idempotency({}) == "idempotent"
    assert export.effective_idempotency({}) == "non-idempotent"

    # the registry's existing validation applies to all three tools
    registry = ToolRegistry()
    for spec in (validate, generate, export):
        registry.register(spec)
    assert {s["function"]["name"] for s in registry.get_schemas()} == {
        "validate_experiment", "generate_trials", "export_experiment"
    }


@pytest.mark.asyncio
async def test_validate_domain_vs_tool_error(sandbox: Path) -> None:
    """Bad spec → ok=True + valid:false without ERROR:; non-dict config → ok=False via the registry path."""
    spec = experiment_tools.build_validate_spec(_settings(sandbox))

    # domain-level failure: ok=True, valid:false, no ERROR: prefix
    result = await spec.executor(experiment_tools.ValidateExperimentInput(config=BAD_SPEC))
    assert result.ok
    assert not result.result.startswith("ERROR:")
    payload = json.loads(result.result)
    assert payload["valid"] is False
    assert any(e["error_code"] == "CONSTRAINT_CONFLICT" for e in payload["errors"])

    # tool-level failure: config is not a dict → ok=False at the registry unified entry (invalid arguments)
    registry = ToolRegistry()
    registry.register(spec)
    tool_result = await registry.execute("validate_experiment", {"config": "not-a-dict"})
    assert not tool_result.ok
    assert "invalid arguments" in tool_result.error


@pytest.mark.asyncio
async def test_config_size_blocked(sandbox: Path) -> None:
    """config serialized bytes > 256KB → BLOCKED: config too large (shared by all three tools)."""
    huge: dict[str, object] = {**SPEC_DICT, "name": "x" * (300 * 1024)}
    settings = _settings(sandbox)
    validate = experiment_tools.build_validate_spec(settings)
    generate = experiment_tools.build_generate_spec(settings)
    export = experiment_tools.build_export_spec(settings)

    result = await validate.executor(experiment_tools.ValidateExperimentInput(config=huge))
    assert not result.ok
    assert result.error == "BLOCKED: config too large"

    result = await generate.executor(experiment_tools.GenerateTrialsInput(config=huge))
    assert not result.ok
    assert result.error == "BLOCKED: config too large"

    result = await export.executor(
        experiment_tools.ExportExperimentInput(config=huge, path="experiments/x.json")
    )
    assert not result.ok
    assert result.error == "BLOCKED: config too large"


@pytest.mark.asyncio
async def test_generate_no_file_written(sandbox: Path) -> None:
    """generate is a pure function with no disk writes: no new files in the sandbox after execution."""
    before = {p.name for p in sandbox.iterdir()}
    spec = experiment_tools.build_generate_spec(_settings(sandbox))
    result = await spec.executor(experiment_tools.GenerateTrialsInput(config=SPEC_DICT))
    assert result.ok
    payload = json.loads(result.result)
    assert payload["valid"] is True
    assert payload["trial_count"] == 8
    assert {p.name for p in sandbox.iterdir()} == before


@pytest.mark.asyncio
async def test_errors_truncated_at_20(sandbox: Path) -> None:
    """errors cap of 20: excess is truncated and errors_truncated: true is set."""
    broken: dict[str, object] = {
        "schema_version": 1,
        "name": "broken",
        "seed": 1,
        # 25 empty-named factors → 25 Pydantic Field errors
        "factors": [{"name": "", "levels": [{"name": "a"}]} for _ in range(25)],
        "blocks": [{"name": "main", "trial_count": 4}],
        "responses": [{"name": "r", "kind": "text"}],
    }
    spec = experiment_tools.build_validate_spec(_settings(sandbox))
    result = await spec.executor(experiment_tools.ValidateExperimentInput(config=broken))
    assert result.ok
    payload = json.loads(result.result)
    assert payload["valid"] is False
    assert len(payload["errors"]) == 20
    assert payload["errors_truncated"] is True


@pytest.mark.asyncio
async def test_generate_invalid_spec_no_generation(sandbox: Path) -> None:
    """generate returns a validate-isomorphic output for an invalid spec (valid:false + errors) and does not generate."""
    spec = experiment_tools.build_generate_spec(_settings(sandbox))
    result = await spec.executor(experiment_tools.GenerateTrialsInput(config=BAD_SPEC))
    assert result.ok
    payload = json.loads(result.result)
    assert payload["valid"] is False
    assert any(e["error_code"] == "CONSTRAINT_CONFLICT" for e in payload["errors"])
    assert "trials_fingerprint" not in payload
    assert "preview" not in payload
