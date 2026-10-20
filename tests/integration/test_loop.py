"""M1 integration tests: the real AgentLoop + real tools + FakeLLM (contract §3.2).

Acceptance mapping: M1-1 (-k loop), M1-3 (-k tool_failure), M1-4 (-k max_steps).
Environment note: the host sandbox blocks unlink → no tmp_path fixture; a fixed test subdirectory
under data/ is used instead (self-created, self-cleaned; leftovers are fine — data/ is gitignored).
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from src.agent import build_registry
from src.agent.loop import AgentLoop
from src.config import Settings
from src.models.events import AgentEventType
from src.models.llm import LLMResponse, ToolCallRequest

from .fake_llm import ExplodingLLM, FakeLLM

TEST_SANDBOX = Path("data/.test-sandbox/loop")
LOGS_DIR = Path("logs")


def _try_cleanup(path: Path) -> None:
    """Best-effort cleanup; tolerate leftovers when the sandbox blocks deletion (data/ is gitignored)."""
    try:
        shutil.rmtree(path)
    except OSError:
        pass


def _ensure_dir(path: Path) -> None:
    """mkdir tolerance: the host security agent raises PermissionError on cross-process leftover directories."""
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


def _settings(sandbox: Path, max_steps: int = 10) -> Settings:
    return Settings(calc_agent_max_steps=max_steps, data_sandbox_dir=str(sandbox))


@pytest.mark.asyncio
@pytest.mark.loop
async def test_loop_completes_multistep_task(sandbox: Path) -> None:
    """M1-1: multi-step task happy path — event sequence, seq, tool_call_id, JSONL, output files."""
    script = [
        LLMResponse(
            tool_calls=[
                ToolCallRequest(remote_id="fake-0", tool_name="calc", arguments={"expression": "1+2*3"})
            ],
            finish_reason="tool_calls",
        ),
        LLMResponse(
            tool_calls=[
                ToolCallRequest(
                    remote_id="fake-1",
                    tool_name="file_write",
                    arguments={"path": "out.txt", "content": "result: 7"},
                )
            ],
            finish_reason="tool_calls",
        ),
        LLMResponse(content="done", finish_reason="stop"),
    ]
    fake = FakeLLM(script)
    loop = AgentLoop(client=fake, registry=build_registry(_settings(sandbox)), settings=_settings(sandbox))
    result = await loop.run_task("compute 1+2*3 and save to out.txt")

    assert result.status == "completed"
    assert result.result == "done"
    assert result.steps == 3

# event sequence (no thought) and seq continuity
    assert [event.type for event in result.events] == [
        AgentEventType.status,
        AgentEventType.tool_call,
        AgentEventType.tool_result,
        AgentEventType.tool_call,
        AgentEventType.tool_result,
        AgentEventType.final,
    ]
    assert [event.seq for event in result.events] == [1, 2, 3, 4, 5, 6]

# tool_call / tool_result tool_call_id pairs are equal and look like call_0002
    tool_calls = [e for e in result.events if e.type == AgentEventType.tool_call]
    tool_results = [e for e in result.events if e.type == AgentEventType.tool_result]
    for call_event, result_event in zip(tool_calls, tool_results):
        assert result_event.payload["tool_call_id"] == call_event.payload["tool_call_id"]
    assert tool_calls[0].payload["tool_call_id"] == "call_0002"
    assert tool_calls[1].payload["tool_call_id"] == "call_0004"
    assert tool_results[0].payload["ok"] is True
    assert tool_results[0].payload["result_summary"] == "7"

# the JSONL exists and line-by-line matches the in-memory events (disk first)
    jsonl = LOGS_DIR / f"agent-{result.task_id}.jsonl"
    assert jsonl.exists()
    lines = [json.loads(line) for line in jsonl.read_text(encoding="utf-8").splitlines()]
    assert lines == [event.model_dump(mode="json") for event in result.events]

# file_write really produces output (inside the sandbox)
    assert (sandbox / "out.txt").read_text(encoding="utf-8") == "result: 7"


@pytest.mark.asyncio
@pytest.mark.max_steps
@pytest.mark.loop
async def test_loop_step_limit(sandbox: Path) -> None:
    """M1-4: step limit — failed + error/final always emitted; the LLM is called exactly max_steps times."""
    script = [
        LLMResponse(
            tool_calls=[ToolCallRequest(remote_id=f"fake-{i}", tool_name="calc", arguments={"expression": f"{i}+{i}"})],
            finish_reason="tool_calls",
        )
        for i in range(3)
    ]
    fake = FakeLLM(script)  # the 4th call raises AssertionError — the loop must not make a 4th call
    settings = _settings(sandbox, max_steps=3)
    loop = AgentLoop(client=fake, registry=build_registry(settings), settings=settings)
    result = await loop.run_task("never finishes")

    assert result.status == "failed"
    assert "max steps" in result.result
    assert fake.calls == 3
    assert [e.type for e in result.events[-2:]] == [AgentEventType.error, AgentEventType.final]
    assert result.events[-1].payload["status"] == "failed"


@pytest.mark.asyncio
@pytest.mark.tool_failure
async def test_loop_tool_failure_not_fatal(sandbox: Path) -> None:
    """M1-3: tool failure is not fatal — BLOCKED goes back to the LLM (ERROR: prefix), the task still completes."""
    script = [
        LLMResponse(
            tool_calls=[
                ToolCallRequest(
                    remote_id="fake-0",
                    tool_name="file_write",
                    arguments={"path": "../evil.txt", "content": "x"},
                )
            ],
            finish_reason="tool_calls",
        ),
        LLMResponse(content="recovered", finish_reason="stop"),
    ]
    fake = FakeLLM(script)
    settings = _settings(sandbox)
    loop = AgentLoop(client=fake, registry=build_registry(settings), settings=settings)
    result = await loop.run_task("try to escape the sandbox")

# the first round's tool_result is BLOCKED
    first_tool_result = next(e for e in result.events if e.type == AgentEventType.tool_result)
    assert first_tool_result.payload["ok"] is False
    assert "BLOCKED" in str(first_tool_result.payload["result_summary"])

# the error goes back to the LLM: round-2 messages contain a tool message starting with ERROR:
    second_round = fake.received_messages[1]
    tool_messages = [m for m in second_round if m.get("role") == "tool"]
    assert tool_messages
    assert tool_messages[0]["content"].startswith("ERROR:")

# the task does not hang; it ultimately completes
    assert result.status == "completed"
    assert result.result == "recovered"
# no files were produced outside the sandbox
    assert not (sandbox.parent.parent / "evil.txt").exists()


@pytest.mark.asyncio
@pytest.mark.loop
async def test_loop_llm_error_fails_task(sandbox: Path) -> None:
    """M1-3 supplement: an unrecoverable LLM exception → the task fails; error + final always emitted."""
    settings = _settings(sandbox)
    loop = AgentLoop(client=ExplodingLLM(), registry=build_registry(settings), settings=settings)
    result = await loop.run_task("boom")

    assert result.status == "failed"
    assert "llm error" in result.result
    assert [e.type for e in result.events[-2:]] == [AgentEventType.error, AgentEventType.final]
    assert result.events[-1].payload["status"] == "failed"
