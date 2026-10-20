"""Phase A integration tests: the real AgentLoop + real tools (via build_experiment_registry) + FakeLLM.

Acceptance mapping: PA-8 (-k design_iteration_success), PA-9 (-k stalled), PA-10 (-k max_steps).
Runs without keys (FakeLLM; the real client is never triggered); the sandbox root points to a fixed
test subdirectory (the host sandbox intermittently blocks session-root mkdir on pytest tmp_path; M1 pattern kept).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from src.agent.experiment_registry import build_experiment_registry
from src.agent.loop import AgentLoop
from src.config import Settings
from src.models.events import AgentEventType
from src.models.llm import LLMResponse, ToolCallRequest

from .fake_llm import FakeLLM

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEST_SANDBOX = Path("data/.test-sandbox/experiment-agent")


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

BAD_SPEC: dict[str, object] = {
    "schema_version": 1,
    "name": "generic-demo",
    "version": "0.1.0",
    "seed": 42,
    "factors": [
        {"name": "difficulty", "levels": [{"name": "easy"}, {"name": "hard"}]},
        {"name": "modality", "levels": [{"name": "visual"}, {"name": "audio"}]},
    ],
    "blocks": [{"name": "main", "trial_count": 96}],
    # C1 conflict: balance=true together with a non-empty ratios
    "constraints": {
        "balance": True,
        "ratios": [{"factor": "difficulty", "ratios": {"easy": 0.6, "hard": 0.4}}],
    },
    "responses": [
        {"name": "respond", "kind": "choice", "options": ["easy", "hard"], "correct_from": "difficulty"}
    ],
    "timing": {"fixation_ms": 500, "stimulus_ms": None, "isi_ms": 1000},
}

# contract §9.2 demo spec (post-fix shape: practice 8 + main 96, 104 trials)
GOOD_SPEC: dict[str, object] = {
    **BAD_SPEC,
    "blocks": [{"name": "practice", "trial_count": 8}, {"name": "main", "trial_count": 96}],
    "constraints": {"balance": True},
}

STALLED_FINGERPRINT = "CONSTRAINT_CONFLICT:constraints"


def _settings(sandbox: Path, max_steps: int = 12) -> Settings:
    return Settings(calc_agent_max_steps=max_steps, data_sandbox_dir=str(sandbox))


@pytest.fixture()
def sandbox() -> Iterator[Path]:
    _try_cleanup(TEST_SANDBOX)
    _ensure_dir(TEST_SANDBOX)
    yield TEST_SANDBOX
    _try_cleanup(TEST_SANDBOX)


def _tool_calls(remote_id: str, name: str, arguments: dict[str, object]) -> LLMResponse:
    return LLMResponse(
        tool_calls=[ToolCallRequest(remote_id=remote_id, tool_name=name, arguments=arguments)],
        finish_reason="tool_calls",
    )


def _tool_call_names(result: object) -> list[str]:
    """Collect the tool_name sequence of tool_call events (the assertion basis on events)."""
    return [
        str(event.payload.get("tool_name"))
        for event in getattr(result, "events", [])  # type: ignore[attr-defined]
        if event.type == AgentEventType.tool_call
    ]


def _tool_messages(round_messages: list[dict[str, object]]) -> list[str]:
    return [
        str(m.get("content", ""))
        for m in round_messages
        if m.get("role") == "tool"
    ]


@pytest.mark.asyncio
async def test_design_iteration_success(sandbox: Path) -> None:
    """PA-8: the full loop of fail → fix → pass → generate → export."""
    script = [
        _tool_calls("fake-0", "validate_experiment", {"config": BAD_SPEC, "previous_errors": []}),
        _tool_calls("fake-1", "validate_experiment", {"config": GOOD_SPEC, "previous_errors": []}),
        _tool_calls("fake-2", "generate_trials", {"config": GOOD_SPEC}),
        _tool_calls(
            "fake-3",
            "export_experiment",
            {"config": GOOD_SPEC, "path": "experiments/generic-demo-v0.1.0-seed42.json"},
        ),
        LLMResponse(content="Experiment design completed and exported", finish_reason="stop"),
    ]
    fake = FakeLLM(script)
    settings = _settings(sandbox)
    loop = AgentLoop(
        client=fake,
        registry=build_experiment_registry(settings),
        settings=settings,
        task_id="task-expa001",
    )
    result = await loop.run_task("design a generic two-factor experiment and export it")

    assert result.status == "completed"
    assert result.result == "Experiment design completed and exported"

    # event assertions: validate ≥1, generate ≥1, export ==1
    tool_calls = _tool_call_names(result)
    assert tool_calls.count("validate_experiment") >= 1
    assert tool_calls.count("generate_trials") >= 1
    assert tool_calls.count("export_experiment") == 1

    # iteration evidence: round-2 messages contain the round-1 validation JSON (incl. CONSTRAINT_CONFLICT)
    second_round_tool_messages = _tool_messages(fake.received_messages[1])
    assert second_round_tool_messages
    assert "CONSTRAINT_CONFLICT" in second_round_tool_messages[0]
    assert '"valid":false' in second_round_tool_messages[0]

    # generate_trials' trials_fingerprint == the value inside the Bundle (same-pure-function consistency)
    generate_tool_messages = _tool_messages(fake.received_messages[3])
    generate_payload = json.loads(generate_tool_messages[-1])  # the last one is generate's output
    bundle_path = sandbox / "experiments" / "generic-demo-v0.1.0-seed42.json"
    assert bundle_path.exists()
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert generate_payload["trials_fingerprint"] == bundle["reproducibility"]["trials_fingerprint"]
    assert bundle["summary"]["trial_count"] == 104
    assert bundle["summary"]["frequency"]["difficulty"] == {"easy": 52, "hard": 52}

    # the independent verification CLI passes (exit 0)
    proc = subprocess.run(
        [sys.executable, "-m", "src.experiment.verify", str(bundle_path)],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest.mark.asyncio
async def test_design_iteration_stalled(sandbox: Path) -> None:
    """PA-9: the same bad spec submitted three times, previous_errors accumulating per round → the 3rd is ITERATION_STALLED → final."""
    script = [
        _tool_calls("fake-0", "validate_experiment", {"config": BAD_SPEC, "previous_errors": []}),
        _tool_calls("fake-1", "validate_experiment", {"config": BAD_SPEC, "previous_errors": [STALLED_FINGERPRINT]}),
        _tool_calls(
            "fake-2",
            "validate_experiment",
            {"config": BAD_SPEC, "previous_errors": [STALLED_FINGERPRINT, STALLED_FINGERPRINT]},
        ),
        LLMResponse(content="Cannot resolve the conflict; asking the user to decide", finish_reason="stop"),
    ]
    fake = FakeLLM(script)
    settings = _settings(sandbox)
    loop = AgentLoop(
        client=fake,
        registry=build_experiment_registry(settings),
        settings=settings,
        task_id="task-expa002",
    )
    result = await loop.run_task("design an experiment (will stall)")

# terminated without exporting
    assert result.status == "completed"
    tool_calls = _tool_call_names(result)
    assert tool_calls.count("export_experiment") == 0
    assert tool_calls.count("generate_trials") == 0
    assert not list(sandbox.rglob("*.json"))

    # round 3 receives ITERATION_STALLED (stalled: true) — the last tool message of that round is the 3rd validation output
    third_round_tool_messages = _tool_messages(fake.received_messages[3])
    assert third_round_tool_messages
    payload = json.loads(third_round_tool_messages[-1])
    assert payload["stalled"] is True
    assert any(e["error_code"] == "ITERATION_STALLED" for e in payload["errors"])
    stalled_issue = next(e for e in payload["errors"] if e["error_code"] == "ITERATION_STALLED")
    assert stalled_issue["suggestion"] == "stop resubmitting; summarize the unresolved conflict and ask the user to decide"

    # round-by-round derivation (MA-1): rounds 1 and 2 not stalled, round 3 stalls
    first_payload = json.loads(_tool_messages(fake.received_messages[1])[0])
    second_payload = json.loads(_tool_messages(fake.received_messages[2])[0])
    assert first_payload["stalled"] is False
    assert second_payload["stalled"] is False


@pytest.mark.asyncio
async def test_design_iteration_max_steps(sandbox: Path) -> None:
    """PA-10: always returning validate(the same bad spec) → failed + final always emitted (the M1 max-steps backstop against hangs)."""
    max_steps = 5
    script = [
        _tool_calls(
            f"fake-{i}",
            "validate_experiment",
            {"config": BAD_SPEC, "previous_errors": [STALLED_FINGERPRINT] * (i % 3)},
        )
        for i in range(max_steps)
    ]
    fake = FakeLLM(script)  # the max_steps+1-th call raises AssertionError — the loop must not overstep
    settings = _settings(sandbox, max_steps=max_steps)
    loop = AgentLoop(
        client=fake,
        registry=build_experiment_registry(settings),
        settings=settings,
        task_id="task-expa003",
    )
    result = await loop.run_task("design an experiment (never converges)")

    assert result.status == "failed"
    assert "max steps" in result.result
    assert fake.calls == max_steps
    assert [e.type for e in result.events[-2:]] == [AgentEventType.error, AgentEventType.final]
    assert result.events[-1].payload["status"] == "failed"
# no export during the backstop
    assert not list(sandbox.rglob("*.json"))
