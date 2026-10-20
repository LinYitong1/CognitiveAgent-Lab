"""Phase B B1 integration tests: the FakeLLM game-design workflow (contract §10 BT-4).

Flow: export_experiment (writes the bundle) → validate_game (wrong ref) → a structured
report is received → validate_game (fixed + previous_errors) → valid:true → final text.

Bundle immutability assertion: snapshot the file bytes after export, then compare byte
for byte after both validate_game calls (executable evidence that validate_game is sandbox read-only).
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from src.agent.game_registry import build_game_registry
from src.agent.loop import AgentLoop
from src.config import Settings
from src.experiment.export import build_bundle
from src.experiment.schemas import ExperimentSpec
from src.models.events import AgentEventType
from src.models.llm import LLMResponse, ToolCallRequest

from .fake_llm import FakeLLM

TEST_SANDBOX = Path("data/.test-sandbox/game-agent")
BUNDLE_REL = "experiments/game-flow.json"

GOOD_SPEC: dict[str, object] = {
    "schema_version": 1,
    "name": "generic-demo",
    "version": "0.1.0",
    "seed": 42,
    "factors": [
        {"name": "difficulty", "levels": [{"name": "easy"}, {"name": "hard"}]},
        {"name": "modality", "levels": [{"name": "visual"}, {"name": "audio"}]},
    ],
    "blocks": [
        {"name": "practice", "trial_count": 8},
        {"name": "main", "trial_count": 96},
    ],
    "constraints": {"balance": True},
    "responses": [
        {"name": "respond", "kind": "choice", "options": ["easy", "hard"],
         "correct_from": "difficulty"}
    ],
    "timing": {"fixation_ms": 500, "stimulus_ms": None, "isi_ms": 1000},
}


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


def _settings(sandbox: Path) -> Settings:
    return Settings(calc_agent_max_steps=12, data_sandbox_dir=str(sandbox))


def _tool_calls(remote_id: str, name: str, arguments: dict[str, object]) -> LLMResponse:
    return LLMResponse(
        tool_calls=[ToolCallRequest(remote_id=remote_id, tool_name=name, arguments=arguments)],
        finish_reason="tool_calls",
    )


def _expected_ref() -> dict[str, object]:
    """Precompute the six fingerprints of the export output (bundle_sha256 is independent of generated_at, so determinism is expected)."""
    bundle = build_bundle(ExperimentSpec.model_validate(GOOD_SPEC))
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


def _game_config(seed_override: object = None) -> dict[str, object]:
    ref = _expected_ref()
    if seed_override is not None:
        ref["seed"] = seed_override
    return {
        "schema_version": 1,
        "game": {"name": "generic-game", "version": "0.1.0"},
        "experiment_ref": ref,
        "input": {
            "modalities": ["keyboard"],
            "bindings": [{"response_name": "respond", "keys": {"e": "easy", "h": "hard"}}],
        },
    }


def _tool_call_names(result: object) -> list[str]:
    return [
        str(event.payload.get("tool_name"))
        for event in getattr(result, "events", [])  # type: ignore[attr-defined]
        if event.type == AgentEventType.tool_call
    ]


@pytest.mark.asyncio
async def test_game_design_workflow_with_fix_path(sandbox: Path) -> None:
    """BT-4: export → validate(wrong ref) → report → validate(fixed) → valid → final;
    also asserts the bundle file is byte-identical before and after both validate_game calls."""
    settings = _settings(sandbox)
    registry = build_game_registry(settings)

    # stage 1: export_experiment writes the bundle (the trailing final closes out after tool execution)
    fake_export = FakeLLM([
        _tool_calls("fake-0", "export_experiment", {"config": GOOD_SPEC, "path": BUNDLE_REL}),
        LLMResponse(content="Bundle exported.", finish_reason="stop"),
    ])
    loop1 = AgentLoop(client=fake_export, registry=registry, settings=settings, task_id="t-game-1")
    result1 = await loop1.run_task("export the experiment bundle")
    assert result1.status == "completed"
    bundle_file = sandbox / BUNDLE_REL
    assert bundle_file.is_file()
    snapshot = bundle_file.read_bytes()  # snapshot: the later validate_game calls must not change it

    # stage 2: wrong ref → structured report → fix (previous_errors carries the previous fingerprints) → valid → final
    fake_design = FakeLLM([
        _tool_calls(
            "fake-1", "validate_game",
            {"game_config": _game_config(seed_override=999),
             "bundle_path": BUNDLE_REL, "previous_errors": []},
        ),
        _tool_calls(
            "fake-2", "validate_game",
            {"game_config": _game_config(),
             "bundle_path": BUNDLE_REL,
             "previous_errors": ["REF_MISMATCH:experiment_ref.seed"]},
        ),
        LLMResponse(content="Game design validated successfully.", finish_reason="stop"),
    ])
    loop2 = AgentLoop(client=fake_design, registry=registry, settings=settings, task_id="t-game-2")
    result2 = await loop2.run_task("design a game for the exported experiment")

    assert result2.status == "completed"
    assert result2.result == "Game design validated successfully."
    assert _tool_call_names(result2) == ["validate_game", "validate_game"]

    # round 1 of stage 2 receives the tool report: structured REF_MISMATCH (no ERROR: prefix)
    round2_messages = fake_design.received_messages[1]
    tool_reports = [
        str(m.get("content", "")) for m in round2_messages if m.get("role") == "tool"
    ]
    assert len(tool_reports) == 1
    assert "REF_MISMATCH" in tool_reports[0]
    assert '"valid":false' in tool_reports[0]
    assert not tool_reports[0].startswith("ERROR")

    # round 2 of stage 2 receives the report: valid:true (message history accumulates; take the last tool report)
    round3_messages = fake_design.received_messages[2]
    valid_reports = [
        str(m.get("content", "")) for m in round3_messages if m.get("role") == "tool"
    ]
    assert len(valid_reports) == 2
    assert '"valid":true' in valid_reports[-1]

    # bundle immutable: byte-identical after both validate_game calls
    assert bundle_file.read_bytes() == snapshot


@pytest.mark.asyncio
async def test_render_game_workflow_produces_playable_html(sandbox: Path) -> None:
    """BR-11: export → validate_game(pass) → render_game → the HTML really exists;
    asserts the HTML starts with <!DOCTYPE html> and the bundle is byte-identical before and after."""
    settings = _settings(sandbox)
    registry = build_game_registry(settings)

    # stage 1: export_experiment writes the bundle
    fake_export = FakeLLM([
        _tool_calls("fake-0", "export_experiment", {"config": GOOD_SPEC, "path": BUNDLE_REL}),
        LLMResponse(content="Bundle exported.", finish_reason="stop"),
    ])
    loop1 = AgentLoop(client=fake_export, registry=registry, settings=settings, task_id="t-render-1")
    result1 = await loop1.run_task("export the experiment bundle")
    assert result1.status == "completed"
    bundle_file = sandbox / BUNDLE_REL
    snapshot = bundle_file.read_bytes()

    # stage 2: validate_game (first-pass) → render_game → final
    html_rel = "games/generic-game.html"
    fake_render = FakeLLM([
        _tool_calls(
            "fake-1", "validate_game",
            {"game_config": _game_config(), "bundle_path": BUNDLE_REL, "previous_errors": []},
        ),
        _tool_calls(
            "fake-2", "render_game",
            {"game_config": _game_config(), "bundle_path": BUNDLE_REL,
             "output_path": html_rel, "previous_errors": []},
        ),
        LLMResponse(content="Playable game rendered.", finish_reason="stop"),
    ])
    loop2 = AgentLoop(client=fake_render, registry=registry, settings=settings, task_id="t-render-2")
    result2 = await loop2.run_task("design and render a playable game")

    assert result2.status == "completed"
    assert result2.result == "Playable game rendered."
    assert _tool_call_names(result2) == ["validate_game", "render_game"]

    # render_game's tool report: rendered:true + html_sha256
    render_messages = fake_render.received_messages[2]
    render_reports = [
        str(m.get("content", "")) for m in render_messages if m.get("role") == "tool"
    ]
    assert '"rendered":true' in render_reports[-1]

    # the HTML really exists and has the right shape
    html_file = sandbox / html_rel
    assert html_file.is_file()
    html = html_file.read_text(encoding="utf-8")
    assert html.startswith("<!DOCTYPE html>")
    assert html.count("<script>") == 2

    # bundle immutable: byte-identical after the whole render flow
    assert bundle_file.read_bytes() == snapshot
