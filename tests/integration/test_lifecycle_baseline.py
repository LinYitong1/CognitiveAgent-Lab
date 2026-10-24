"""Agent lifecycle baseline tests (Foundation Hardening Phase B).

Ten scenarios from the hardening spec; the four already covered by
``test_loop.py`` (normal completion, step limit, tool failure not fatal,
LLM error fails task) are not repeated here. These tests pin the CURRENT
behavior before any hardening change: each assertion documents what the
loop does today. A pre-change failure here is audit evidence of a defect,
not a test to be relaxed.

Scenarios covered here:
  7. unknown tool call
  3. invalid tool arguments (validation error)
  4. tool returns structured validation failure (experiment schema error)
  9. partial artifacts then termination
 10. multi tool calls in ONE round: message ordering, tool_call_id pairing,
     and the exact conversation history the next LLM round sees
  8. model returns the final answer directly on round 1 (no tool call at all)
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from src.agent import build_registry
from src.agent.game_registry import build_game_registry
from src.agent.loop import AgentLoop
from src.config import Settings
from src.models.events import AgentEventType
from src.models.llm import LLMResponse, ToolCallRequest

from .fake_llm import FakeLLM

TEST_SANDBOX = Path("data/.test-sandbox/lifecycle")

_VALID_SPEC: dict[str, object] = {
    "schema_version": 1,
    "name": "lifecycle-baseline",
    "version": "0.1.0",
    "seed": 7,
    "factors": [{"name": "side", "levels": [{"name": "left"}, {"name": "right"}]}],
    "blocks": [{"name": "main", "trial_count": 4}],
    "constraints": {"balance": True},
    "responses": [
        {"name": "answer", "kind": "choice", "options": ["left", "right"], "correct_from": "side"}
    ],
    "timing": {"fixation_ms": 200, "stimulus_ms": None, "isi_ms": 200},
}


def _try_cleanup(path: Path) -> None:
    try:
        shutil.rmtree(path)
    except OSError:
        pass


@pytest.fixture()
def sandbox() -> Iterator[Path]:
    _try_cleanup(TEST_SANDBOX)
    TEST_SANDBOX.mkdir(parents=True, exist_ok=True)
    yield TEST_SANDBOX
    _try_cleanup(TEST_SANDBOX)


def _settings(sandbox: Path, max_steps: int = 10) -> Settings:
    return Settings(calc_agent_max_steps=max_steps, data_sandbox_dir=str(sandbox))


@pytest.mark.asyncio
async def test_lifecycle_unknown_tool(sandbox: Path) -> None:
    """Scenario 7: unknown tool name -> ok=False tool_result, fed back, task can still complete."""
    script = [
        LLMResponse(
            tool_calls=[ToolCallRequest(remote_id="fake-0", tool_name="does_not_exist", arguments={})],
            finish_reason="tool_calls",
        ),
        LLMResponse(content="gave up on that tool", finish_reason="stop"),
    ]
    fake = FakeLLM(script)
    settings = _settings(sandbox)
    loop = AgentLoop(client=fake, registry=build_registry(settings), settings=settings)
    result = await loop.run_task("call a tool that does not exist")

    assert result.status == "completed"
    tr = next(e for e in result.events if e.type == AgentEventType.tool_result)
    assert tr.payload["ok"] is False
    assert "unknown tool" in str(tr.payload["result_summary"])
    # fed back to the model with the ERROR: prefix
    tool_msgs = [m for m in fake.received_messages[1] if m.get("role") == "tool"]
    assert tool_msgs[0]["content"].startswith("ERROR:")
    assert "unknown tool" in tool_msgs[0]["content"]


@pytest.mark.asyncio
async def test_lifecycle_invalid_arguments(sandbox: Path) -> None:
    """Scenario 3: arguments violating the input schema -> invalid arguments error, not a crash."""
    script = [
        LLMResponse(
            tool_calls=[
                ToolCallRequest(
                    remote_id="fake-0", tool_name="calc", arguments={"expression": 123}
                )
            ],
            finish_reason="tool_calls",
        ),
        LLMResponse(content="ok after bad args", finish_reason="stop"),
    ]
    fake = FakeLLM(script)
    settings = _settings(sandbox)
    loop = AgentLoop(client=fake, registry=build_registry(settings), settings=settings)
    result = await loop.run_task("send invalid arguments")

    assert result.status == "completed"
    tr = next(e for e in result.events if e.type == AgentEventType.tool_result)
    assert tr.payload["ok"] is False
    assert "invalid arguments" in str(tr.payload["result_summary"]).lower()


@pytest.mark.asyncio
async def test_lifecycle_structured_validation_failure(sandbox: Path) -> None:
    """Scenario 4: an invalid ExperimentSpec -> structured validation errors go back to the LLM.

    Tool semantics pinned here: a validation FAILURE is a SUCCESSFUL tool call
    (ok=True) whose result JSON carries the verdict — the model sees structured
    errors as normal tool output, not an ERROR: prefix. Consequence (audit
    note): the event log alone cannot distinguish "experiment valid" from
    "experiment invalid"; evaluation must parse the result payload.
    """
    bad_spec = dict(_VALID_SPEC, blocks=[{"name": "main", "trial_count": -1}])
    script = [
        LLMResponse(
            tool_calls=[
                ToolCallRequest(
                    remote_id="fake-0",
                    tool_name="validate_experiment",
                    arguments={"config": bad_spec, "previous_errors": []},
                )
            ],
            finish_reason="tool_calls",
        ),
        LLMResponse(content="validation errors received", finish_reason="stop"),
    ]
    fake = FakeLLM(script)
    settings = _settings(sandbox)
    loop = AgentLoop(client=fake, registry=build_game_registry(settings), settings=settings)
    result = await loop.run_task("validate an intentionally invalid spec")

    assert result.status == "completed"
    tr = next(e for e in result.events if e.type == AgentEventType.tool_result)
    assert tr.payload["ok"] is True  # the tool executed; the verdict is inside the payload
    summary = str(tr.payload["result_summary"])
    assert "SCHEMA_INVALID" in summary  # structured error code reaches the model
    assert "trial_count" in summary
    # the model receives it as a normal tool message (no ERROR: prefix)
    tool_msgs = [m for m in fake.received_messages[1] if m.get("role") == "tool"]
    assert not tool_msgs[0]["content"].startswith("ERROR:")


@pytest.mark.asyncio
async def test_lifecycle_partial_artifacts_then_stop(sandbox: Path) -> None:
    """Scenario 9: artifacts produced, then the model stops mid-workflow (no crash, no phantom success).

    The bundle exists on disk, the task reports completed (the model chose to
    stop), and pipeline-level verification — not the loop — owns the question
    of whether the artifacts are complete.
    """
    script = [
        LLMResponse(
            tool_calls=[
                ToolCallRequest(
                    remote_id="fake-0",
                    tool_name="export_experiment",
                    arguments={"config": _VALID_SPEC, "path": "experiments/partial.json"},
                )
            ],
            finish_reason="tool_calls",
        ),
        LLMResponse(content="stopping here", finish_reason="stop"),
    ]
    fake = FakeLLM(script)
    settings = _settings(sandbox)
    loop = AgentLoop(client=fake, registry=build_game_registry(settings), settings=settings)
    result = await loop.run_task("export then stop early")

    assert result.status == "completed"  # execution completed; artifact completeness is separate
    assert result.steps == 2
    bundle = sandbox / "experiments" / "partial.json"
    assert bundle.is_file()  # the partial artifact is real
    # ... and no HTML was produced: partial work is visible from the sandbox


@pytest.mark.asyncio
async def test_lifecycle_multi_tool_single_round(sandbox: Path) -> None:
    """Scenario 10: two tool calls in ONE round — ordering, ID pairing, and history shape."""
    script = [
        LLMResponse(
            tool_calls=[
                ToolCallRequest(remote_id="fake-a", tool_name="calc", arguments={"expression": "2*3"}),
                ToolCallRequest(
                    remote_id="fake-b",
                    tool_name="file_write",
                    arguments={"path": "note.txt", "content": "six"},
                ),
            ],
            finish_reason="tool_calls",
        ),
        LLMResponse(content="both done", finish_reason="stop"),
    ]
    fake = FakeLLM(script)
    settings = _settings(sandbox)
    loop = AgentLoop(client=fake, registry=build_registry(settings), settings=settings)
    result = await loop.run_task("two tools in one round")

    assert result.status == "completed"
    # one LLM round, two tool_call/tool_result pairs, executed in order
    calls = [e for e in result.events if e.type == AgentEventType.tool_call]
    results_ = [e for e in result.events if e.type == AgentEventType.tool_result]
    assert [c.payload["tool_name"] for c in calls] == ["calc", "file_write"]
    for c, r in zip(calls, results_):
        assert r.payload["tool_call_id"] == c.payload["tool_call_id"]
    assert [r.payload["ok"] for r in results_] == [True, True]
    # the history the NEXT round sees: system, user, assistant(2 tool_calls), tool, tool
    hist = fake.received_messages[1]
    assert [m["role"] for m in hist] == ["system", "user", "assistant", "tool", "tool"]
    assistant = hist[2]
    assert len(assistant["tool_calls"]) == 2
    # each tool result is addressed to the provider's own remote id, in order
    assert hist[3]["tool_call_id"] == "fake-a"
    assert hist[4]["tool_call_id"] == "fake-b"
    assert (sandbox / "note.txt").read_text(encoding="utf-8") == "six"


@pytest.mark.asyncio
async def test_lifecycle_direct_answer_round1(sandbox: Path) -> None:
    """Scenario 8: the model answers directly without any tool call — completed in one step."""
    script = [LLMResponse(content="the answer is 42", finish_reason="stop")]
    fake = FakeLLM(script)
    settings = _settings(sandbox)
    loop = AgentLoop(client=fake, registry=build_registry(settings), settings=settings)
    result = await loop.run_task("just answer")

    assert result.status == "completed"
    assert result.result == "the answer is 42"
    assert result.steps == 1
    assert [e.type for e in result.events] == [AgentEventType.status, AgentEventType.final]
    assert fake.calls == 1  # no second LLM round after a direct answer
