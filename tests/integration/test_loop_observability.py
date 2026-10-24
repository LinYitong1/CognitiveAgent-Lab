"""Observability hardening tests (Foundation Hardening P1).

Covers the additive loop/result fields:
- AgentResult.termination_reason (closed set) + mirrored in the final event
- cumulative usage (summed when the provider reports; None when it never does)
- tool_result duration_ms and error_category (deterministic prefix mapping)
- final event model_calls / tool_calls_total

All assertions are additive — no existing event key semantics change.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from src.agent import build_registry
from src.agent.loop import AgentLoop
from src.agent.registry import classify_tool_error
from src.config import Settings
from src.models.events import AgentEventType
from src.models.llm import LLMResponse, ToolCallRequest

from .fake_llm import ExplodingLLM, FakeLLM

TEST_SANDBOX = Path("data/.test-sandbox/loop-obs")


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
async def test_termination_reason_model_final_answer(sandbox: Path) -> None:
    script = [
        LLMResponse(
            tool_calls=[ToolCallRequest(remote_id="f0", tool_name="calc", arguments={"expression": "1+1"})],
            finish_reason="tool_calls",
        ),
        LLMResponse(content="done", finish_reason="stop"),
    ]
    loop = AgentLoop(client=FakeLLM(script), registry=build_registry(_settings(sandbox)), settings=_settings(sandbox))
    result = await loop.run_task("x")

    assert result.termination_reason == "model_final_answer"
    final = result.events[-1]
    assert final.type is AgentEventType.final
    assert final.payload["termination_reason"] == "model_final_answer"
    assert final.payload["model_calls"] == 2
    assert final.payload["tool_calls_total"] == 1
    # FakeLLM never reports usage -> null, never fabricated
    assert result.usage is None
    assert final.payload["usage"] is None


@pytest.mark.asyncio
async def test_termination_reason_max_steps(sandbox: Path) -> None:
    script = [
        LLMResponse(
            tool_calls=[ToolCallRequest(remote_id=f"f{i}", tool_name="calc", arguments={"expression": "1"})],
            finish_reason="tool_calls",
        )
        for i in range(2)
    ]
    settings = _settings(sandbox, max_steps=2)
    loop = AgentLoop(client=FakeLLM(script), registry=build_registry(settings), settings=settings)
    result = await loop.run_task("never ends")

    assert result.status == "failed"
    assert result.termination_reason == "max_steps_exceeded"
    assert result.events[-1].payload["termination_reason"] == "max_steps_exceeded"


@pytest.mark.asyncio
async def test_termination_reason_llm_error(sandbox: Path) -> None:
    settings = _settings(sandbox)
    loop = AgentLoop(client=ExplodingLLM(), registry=build_registry(settings), settings=settings)
    result = await loop.run_task("boom")

    assert result.status == "failed"
    assert result.termination_reason == "llm_error"
    error_event = next(e for e in result.events if e.type is AgentEventType.error)
    assert error_event.payload["error_category"] == "llm_error"


@pytest.mark.asyncio
async def test_usage_accumulates_across_rounds(sandbox: Path) -> None:
    script = [
        LLMResponse(
            tool_calls=[ToolCallRequest(remote_id="f0", tool_name="calc", arguments={"expression": "1"})],
            finish_reason="tool_calls",
            usage={"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110},
        ),
        LLMResponse(
            tool_calls=[ToolCallRequest(remote_id="f1", tool_name="calc", arguments={"expression": "2"})],
            finish_reason="tool_calls",
            usage={"prompt_tokens": 200, "completion_tokens": 20, "total_tokens": 220, "reasoning_tokens": 5},
        ),
        LLMResponse(content="done", finish_reason="stop", usage={"prompt_tokens": 50, "total_tokens": 60}),
    ]
    loop = AgentLoop(client=FakeLLM(script), registry=build_registry(_settings(sandbox)), settings=_settings(sandbox))
    result = await loop.run_task("accumulate usage")

    assert result.usage == {
        "prompt_tokens": 350,
        "completion_tokens": 30,
        "total_tokens": 390,
        "reasoning_tokens": 5,
    }
    assert result.events[-1].payload["usage"] == result.usage


@pytest.mark.asyncio
async def test_tool_result_duration_and_error_category(sandbox: Path) -> None:
    script = [
        LLMResponse(
            tool_calls=[
                ToolCallRequest(remote_id="f0", tool_name="calc", arguments={"expression": "2+2"}),
                ToolCallRequest(remote_id="f1", tool_name="no_such_tool", arguments={}),
                ToolCallRequest(
                    remote_id="f2", tool_name="calc", arguments={"expression": 123}  # wrong type -> schema
                ),
                ToolCallRequest(  # policy refusal
                    remote_id="f3", tool_name="file_write", arguments={"path": "../evil.txt", "content": "x"}
                ),
            ],
            finish_reason="tool_calls",
        ),
        LLMResponse(content="done", finish_reason="stop"),
    ]
    loop = AgentLoop(client=FakeLLM(script), registry=build_registry(_settings(sandbox)), settings=_settings(sandbox))
    result = await loop.run_task("mix of failures")

    tool_results = [e for e in result.events if e.type is AgentEventType.tool_result]
    # every tool_result carries a non-negative duration
    assert all(isinstance(e.payload["duration_ms"], int) and e.payload["duration_ms"] >= 0 for e in tool_results)
    # categories classify deterministically
    assert tool_results[0].payload["ok"] is True
    assert "error_category" not in tool_results[0].payload  # only failures carry a category
    assert tool_results[1].payload["error_category"] == "unknown_tool"
    assert tool_results[2].payload["error_category"] == "invalid_arguments"
    assert tool_results[3].payload["error_category"] == "policy_blocked"


def test_classify_tool_error_closed_set() -> None:
    assert classify_tool_error("unknown tool: x") == "unknown_tool"
    assert classify_tool_error("invalid arguments: boom") == "invalid_arguments"
    assert classify_tool_error("tool execution failed: ValueError: x") == "execution_failed"
    assert classify_tool_error("BLOCKED: path traversal") == "policy_blocked"
    assert classify_tool_error("something else") == "other"
