"""M1 集成测试：真实 AgentLoop + 真实工具 + FakeLLM（契约 §3.2）。

对应验收：M1-1（-k loop）、M1-3（-k tool_failure）、M1-4（-k max_steps）。
环境说明：沙箱拦截 unlink → 不用 tmp_path fixture，用 data/ 下固定测试子目录
（自建自清，清不掉也无妨——data/ 已被 gitignore）。
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
    """尽力清理；沙箱拦截删除时容忍残留（data/ 已 gitignore）。"""
    try:
        shutil.rmtree(path)
    except OSError:
        pass


def _ensure_dir(path: Path) -> None:
    """mkdir 容错：宿主安全代理对跨进程残留目录会抛 PermissionError。"""
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
    """M1-1：多步任务 happy path——事件序列、seq、tool_call_id、JSONL、产出文件。"""
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

    # 事件序列（无 thought）与 seq 连续性
    assert [event.type for event in result.events] == [
        AgentEventType.status,
        AgentEventType.tool_call,
        AgentEventType.tool_result,
        AgentEventType.tool_call,
        AgentEventType.tool_result,
        AgentEventType.final,
    ]
    assert [event.seq for event in result.events] == [1, 2, 3, 4, 5, 6]

    # tool_call / tool_result 的 tool_call_id 成对相等且形如 call_0002
    tool_calls = [e for e in result.events if e.type == AgentEventType.tool_call]
    tool_results = [e for e in result.events if e.type == AgentEventType.tool_result]
    for call_event, result_event in zip(tool_calls, tool_results):
        assert result_event.payload["tool_call_id"] == call_event.payload["tool_call_id"]
    assert tool_calls[0].payload["tool_call_id"] == "call_0002"
    assert tool_calls[1].payload["tool_call_id"] == "call_0004"
    assert tool_results[0].payload["ok"] is True
    assert tool_results[0].payload["result_summary"] == "7"

    # JSONL 存在且逐行与内存事件一致（先落盘）
    jsonl = LOGS_DIR / f"agent-{result.task_id}.jsonl"
    assert jsonl.exists()
    lines = [json.loads(line) for line in jsonl.read_text(encoding="utf-8").splitlines()]
    assert lines == [event.model_dump(mode="json") for event in result.events]

    # file_write 真实产出（沙箱内）
    assert (sandbox / "out.txt").read_text(encoding="utf-8") == "result: 7"


@pytest.mark.asyncio
@pytest.mark.max_steps
@pytest.mark.loop
async def test_loop_step_limit(sandbox: Path) -> None:
    """M1-4：步数上限——failed + error/final 必发，LLM 恰被调用 max_steps 次。"""
    script = [
        LLMResponse(
            tool_calls=[ToolCallRequest(remote_id=f"fake-{i}", tool_name="calc", arguments={"expression": f"{i}+{i}"})],
            finish_reason="tool_calls",
        )
        for i in range(3)
    ]
    fake = FakeLLM(script)  # 第 4 次调用会 AssertionError——loop 不得调用第 4 次
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
    """M1-3：工具失败不致命——BLOCKED 回传 LLM（ERROR: 前缀），任务继续完成。"""
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

    # 第一轮 tool_result 被 BLOCKED
    first_tool_result = next(e for e in result.events if e.type == AgentEventType.tool_result)
    assert first_tool_result.payload["ok"] is False
    assert "BLOCKED" in str(first_tool_result.payload["result_summary"])

    # 错误回传 LLM：第二轮 messages 含 tool message 且以 ERROR: 开头
    second_round = fake.received_messages[1]
    tool_messages = [m for m in second_round if m.get("role") == "tool"]
    assert tool_messages
    assert tool_messages[0]["content"].startswith("ERROR:")

    # 任务不悬挂，最终完成
    assert result.status == "completed"
    assert result.result == "recovered"
    # 沙箱外未产生文件
    assert not (sandbox.parent.parent / "evil.txt").exists()


@pytest.mark.asyncio
@pytest.mark.loop
async def test_loop_llm_error_fails_task(sandbox: Path) -> None:
    """M1-3 补充：LLM 不可恢复异常 → 任务 failed，error + final 必发。"""
    settings = _settings(sandbox)
    loop = AgentLoop(client=ExplodingLLM(), registry=build_registry(settings), settings=settings)
    result = await loop.run_task("boom")

    assert result.status == "failed"
    assert "llm error" in result.result
    assert [e.type for e in result.events[-2:]] == [AgentEventType.error, AgentEventType.final]
    assert result.events[-1].payload["status"] == "failed"
