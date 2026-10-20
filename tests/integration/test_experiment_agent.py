"""Phase A 集成测试：真实 AgentLoop + 真实工具（经 build_experiment_registry）+ FakeLLM。

对应验收：PA-8（-k design_iteration_success）、PA-9（-k stalled）、PA-10（-k max_steps）。
无 key 可跑（FakeLLM，不触发真实客户端）；沙箱根指固定测试子目录
（沙箱对 pytest tmp_path 的会话根目录 mkdir 存在间歇性拦截，沿用 M1 模式）。
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
    # C1 冲突：balance=true 且 ratios 非空
    "constraints": {
        "balance": True,
        "ratios": [{"factor": "difficulty", "ratios": {"easy": 0.6, "hard": 0.4}}],
    },
    "responses": [
        {"name": "respond", "kind": "choice", "options": ["easy", "hard"], "correct_from": "difficulty"}
    ],
    "timing": {"fixation_ms": 500, "stimulus_ms": None, "isi_ms": 1000},
}

# 契约 §9.2 Demo spec（修正后形态：practice 8 + main 96，104 试次）
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
    """收集 tool_call 事件的 tool_name 序列（事件断言口径）。"""
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
    """PA-8：失败→修改→通过→生成→导出全循环。"""
    script = [
        _tool_calls("fake-0", "validate_experiment", {"config": BAD_SPEC, "previous_errors": []}),
        _tool_calls("fake-1", "validate_experiment", {"config": GOOD_SPEC, "previous_errors": []}),
        _tool_calls("fake-2", "generate_trials", {"config": GOOD_SPEC}),
        _tool_calls(
            "fake-3",
            "export_experiment",
            {"config": GOOD_SPEC, "path": "experiments/generic-demo-v0.1.0-seed42.json"},
        ),
        LLMResponse(content="实验设计完成并已导出", finish_reason="stop"),
    ]
    fake = FakeLLM(script)
    settings = _settings(sandbox)
    loop = AgentLoop(
        client=fake,
        registry=build_experiment_registry(settings),
        settings=settings,
        task_id="task-expa001",
    )
    result = await loop.run_task("设计一个通用两因素实验并导出")

    assert result.status == "completed"
    assert result.result == "实验设计完成并已导出"

    # 事件断言：validate ≥1、generate ≥1、export ==1
    tool_calls = _tool_call_names(result)
    assert tool_calls.count("validate_experiment") >= 1
    assert tool_calls.count("generate_trials") >= 1
    assert tool_calls.count("export_experiment") == 1

    # 迭代证据：第二轮 messages 含第一轮验证 JSON（含 CONSTRAINT_CONFLICT）
    second_round_tool_messages = _tool_messages(fake.received_messages[1])
    assert second_round_tool_messages
    assert "CONSTRAINT_CONFLICT" in second_round_tool_messages[0]
    assert '"valid":false' in second_round_tool_messages[0]

    # generate_trials 输出的 trials_fingerprint == Bundle 内值（同纯函数一致性）
    generate_tool_messages = _tool_messages(fake.received_messages[3])
    generate_payload = json.loads(generate_tool_messages[-1])  # 最后一即 generate 的输出
    bundle_path = sandbox / "experiments" / "generic-demo-v0.1.0-seed42.json"
    assert bundle_path.exists()
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert generate_payload["trials_fingerprint"] == bundle["reproducibility"]["trials_fingerprint"]
    assert bundle["summary"]["trial_count"] == 104
    assert bundle["summary"]["frequency"]["difficulty"] == {"easy": 52, "hard": 52}

    # 独立验证 CLI 通过（exit 0）
    proc = subprocess.run(
        [sys.executable, "-m", "src.experiment.verify", str(bundle_path)],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest.mark.asyncio
async def test_design_iteration_stalled(sandbox: Path) -> None:
    """PA-9：三次提交同一错误 spec，previous_errors 逐轮累积 → 第 3 次 ITERATION_STALLED → final。"""
    script = [
        _tool_calls("fake-0", "validate_experiment", {"config": BAD_SPEC, "previous_errors": []}),
        _tool_calls("fake-1", "validate_experiment", {"config": BAD_SPEC, "previous_errors": [STALLED_FINGERPRINT]}),
        _tool_calls(
            "fake-2",
            "validate_experiment",
            {"config": BAD_SPEC, "previous_errors": [STALLED_FINGERPRINT, STALLED_FINGERPRINT]},
        ),
        LLMResponse(content="无法解决冲突，请用户裁决", finish_reason="stop"),
    ]
    fake = FakeLLM(script)
    settings = _settings(sandbox)
    loop = AgentLoop(
        client=fake,
        registry=build_experiment_registry(settings),
        settings=settings,
        task_id="task-expa002",
    )
    result = await loop.run_task("设计实验（会停滞）")

    # 终止且未导出
    assert result.status == "completed"
    tool_calls = _tool_call_names(result)
    assert tool_calls.count("export_experiment") == 0
    assert tool_calls.count("generate_trials") == 0
    assert not list(sandbox.rglob("*.json"))

    # 第 3 轮收到 ITERATION_STALLED（stalled: true）——该轮最后一条 tool 消息即第 3 次验证输出
    third_round_tool_messages = _tool_messages(fake.received_messages[3])
    assert third_round_tool_messages
    payload = json.loads(third_round_tool_messages[-1])
    assert payload["stalled"] is True
    assert any(e["error_code"] == "ITERATION_STALLED" for e in payload["errors"])
    stalled_issue = next(e for e in payload["errors"] if e["error_code"] == "ITERATION_STALLED")
    assert stalled_issue["suggestion"] == "停止重复提交，总结未解决冲突并请用户裁决"

    # 逐轮推演（MA-1）：第 1、2 次不 stalled，第 3 次才 stalled
    first_payload = json.loads(_tool_messages(fake.received_messages[1])[0])
    second_payload = json.loads(_tool_messages(fake.received_messages[2])[0])
    assert first_payload["stalled"] is False
    assert second_payload["stalled"] is False


@pytest.mark.asyncio
async def test_design_iteration_max_steps(sandbox: Path) -> None:
    """PA-10：恒返回 validate(同一坏 spec) → failed + final 必发（M1 机制防挂死兜底）。"""
    max_steps = 5
    script = [
        _tool_calls(
            f"fake-{i}",
            "validate_experiment",
            {"config": BAD_SPEC, "previous_errors": [STALLED_FINGERPRINT] * (i % 3)},
        )
        for i in range(max_steps)
    ]
    fake = FakeLLM(script)  # 第 max_steps+1 次调用会 AssertionError——loop 不得越界
    settings = _settings(sandbox, max_steps=max_steps)
    loop = AgentLoop(
        client=fake,
        registry=build_experiment_registry(settings),
        settings=settings,
        task_id="task-expa003",
    )
    result = await loop.run_task("设计实验（永不收敛）")

    assert result.status == "failed"
    assert "max steps" in result.result
    assert fake.calls == max_steps
    assert [e.type for e in result.events[-2:]] == [AgentEventType.error, AgentEventType.final]
    assert result.events[-1].payload["status"] == "failed"
    # 兜底期间无导出
    assert not list(sandbox.rglob("*.json"))
