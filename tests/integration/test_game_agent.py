"""Phase B B1 集成测试：FakeLLM 游戏设计工作流（契约 §10 BT-4）。

流程：export_experiment（写 bundle）→ validate_game（错误 ref）→ 收到结构化
报告 → validate_game（修正 + previous_errors）→ valid:true → final 文本。

Bundle 不可变断言：export 之后快照文件字节，两次 validate_game 调用之后
逐字节比对（validate_game 对沙箱只读的可执行证据）。
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
    """预计算 export 产物的六项指纹（bundle_sha256 与 generated_at 无关，确定性可期）。"""
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
    """BT-4：export → validate(错 ref) → 报告 → validate(修正) → valid → final；
    并断言两次 validate_game 前后 bundle 文件逐字节不变。"""
    settings = _settings(sandbox)
    registry = build_game_registry(settings)

    # 阶段 1：export_experiment 写 bundle（末条 final 供工具执行后收尾）
    fake_export = FakeLLM([
        _tool_calls("fake-0", "export_experiment", {"config": GOOD_SPEC, "path": BUNDLE_REL}),
        LLMResponse(content="Bundle exported.", finish_reason="stop"),
    ])
    loop1 = AgentLoop(client=fake_export, registry=registry, settings=settings, task_id="t-game-1")
    result1 = await loop1.run_task("export the experiment bundle")
    assert result1.status == "completed"
    bundle_file = sandbox / BUNDLE_REL
    assert bundle_file.is_file()
    snapshot = bundle_file.read_bytes()  # 快照：后续 validate_game 不得改变它

    # 阶段 2：错误 ref → 结构化报告 → 修正（previous_errors 携带上轮指纹）→ valid → final
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

    # 阶段 2 第 1 轮收到的 tool 报告：结构化 REF_MISMATCH（无 ERROR: 前缀）
    round2_messages = fake_design.received_messages[1]
    tool_reports = [
        str(m.get("content", "")) for m in round2_messages if m.get("role") == "tool"
    ]
    assert len(tool_reports) == 1
    assert "REF_MISMATCH" in tool_reports[0]
    assert '"valid":false' in tool_reports[0]
    assert not tool_reports[0].startswith("ERROR")

    # 阶段 2 第 2 轮收到的报告：valid:true（消息历史累积，取最后一条 tool 报告）
    round3_messages = fake_design.received_messages[2]
    valid_reports = [
        str(m.get("content", "")) for m in round3_messages if m.get("role") == "tool"
    ]
    assert len(valid_reports) == 2
    assert '"valid":true' in valid_reports[-1]

    # Bundle 不可变：两次 validate_game 之后逐字节一致
    assert bundle_file.read_bytes() == snapshot
