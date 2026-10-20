"""B3 端到端 Demo：FakeLLM 驱动的完整 Agent 工作流（用户批准 B3 范围）。

一条自然语言任务 → 单一 AgentLoop（复用 M1，无新框架）内依次调用：

    validate_experiment → generate_trials → export_experiment
    → validate_game → render_game → 单文件可玩 HTML

LLM 为内置 ScriptedLLM（LLMClientProtocol 的鸭子类型实现）：按轮次弹出预设
响应，模拟"模型设计出合法 ExperimentSpec 与 GameSpec"的过程。预设响应中的
experiment_ref 六项指纹由确定性引擎预计算（build_bundle 同 spec+seed 逐字节
可复现，故与 export_experiment 实际产物必然一致）。

零真实 LLM、零密钥、零网络（CALC_AGENT_ENV_FILE=/dev/null 亦可运行）。

运行（仓库根目录）：
    .venv/bin/python examples/run_game_agent.py

沙箱根目录可用环境变量 DATA_SANDBOX_DIR 覆盖（默认 data/）。

验证契约（任何失败 → 非零退出，绝不静默忽略）：
  脚本级 verify_agent_run：状态 completed、5 个工具按序调用、全部
  tool_result ok、各工具域级报告 valid/rendered 均为 true；
  产物级 verify_artifacts：verify_bundle 独立校验、bundle 与确定性重算
  逐字节一致（剥离 generated_at）、GameSpec 对实际 bundle 校验通过、
  HTML 与确定性渲染逐字节一致、双指纹锚点存在、试次数一致。

打开游戏：用浏览器直接打开 data/games/demo-agent-game.html（file:// 直开）。
提示：浏览器原型计时为近似值，不用于正式数据收集。
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agent.game_registry import build_game_registry
from src.agent.loop import AgentLoop
from src.config import Settings
from src.experiment.canonical import canonical_json
from src.experiment.export import build_bundle
from src.experiment.game_render import render_game_html
from src.experiment.game_schemas import validate_game
from src.experiment.schemas import ExperimentSpec
from src.experiment.verify import verify_bundle
from src.models.events import AgentEventType
from src.models.llm import LLMResponse, ToolCallRequest

TASK_ID = "demo-game-agent"
BUNDLE_REL = "experiments/demo-agent-game.json"
HTML_REL = "games/demo-agent-game.html"

# 通用示例实验（刻意不绑定任何认知实验范式）：
# 单因素 side（left/right），2 区组共 24 试次，选择反应、正确性来自因素水平。
DEMO_SPEC: dict[str, object] = {
    "schema_version": 1,
    "name": "demo-agent-game",
    "version": "0.1.0",
    "seed": 11,
    "factors": [
        {"name": "side", "levels": [{"name": "left"}, {"name": "right"}]},
    ],
    "blocks": [
        {"name": "practice", "trial_count": 4},
        {"name": "main", "trial_count": 20},
    ],
    "constraints": {"balance": True},
    "responses": [
        {"name": "answer", "kind": "choice", "options": ["left", "right"],
         "correct_from": "side"}
    ],
    "timing": {"fixation_ms": 400, "stimulus_ms": None, "isi_ms": 600},
}

GOAL = (
    "为以下任务生成一个可玩的浏览器游戏：设计一个单因素二水平的选择反应实验"
    "（因素 side，水平 left/right；practice 4 试次 + main 20 试次，seed=11），"
    "先验证实验设计并生成试次，导出实验包；然后为该实验设计键盘操作的 GameSpec，"
    "校验通过后渲染为单文件 HTML 游戏。"
)

EXPECTED_TOOLS = [
    "validate_experiment",
    "generate_trials",
    "export_experiment",
    "validate_game",
    "render_game",
]


class ScriptedLLM:
    """按轮次弹出预设响应的假 LLM（LLMClientProtocol 鸭子类型；记录完整消息历史）。"""

    def __init__(self, script: list[LLMResponse]) -> None:
        self._script = list(script)
        self.received_messages: list[list[dict[str, Any]]] = []

    @property
    def calls(self) -> int:
        return len(self.received_messages)

    async def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LLMResponse:
        self.received_messages.append([dict(m) for m in messages])
        index = len(self.received_messages)
        if index > len(self._script):
            raise AssertionError("ScriptedLLM script exhausted")
        return self._script[index - 1]


def _expected_ref() -> dict[str, object]:
    """预计算 export_experiment 产物的六项指纹（确定性引擎保证与实际产物一致）。"""
    bundle = build_bundle(ExperimentSpec.model_validate(DEMO_SPEC))
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


def _game_config() -> dict[str, object]:
    """预设的 GameSpec（模拟 LLM 的游戏设计产物；六项引用来自确定性预计算）。"""
    return {
        "schema_version": 1,
        "game": {"name": "demo-agent-game", "version": "0.1.0"},
        "experiment_ref": _expected_ref(),
        "scene": {
            "title": "Side Judgement",
            "instructions": (
                "Each trial shows a side. Press [f] for left or [j] for right."
            ),
        },
        "input": {
            "modalities": ["keyboard"],
            "bindings": [{"response_name": "answer", "keys": {"f": "left", "j": "right"}}],
        },
        "feedback": {"on_response": "outcome-text", "duration_ms": 300},
    }


def _call(remote_id: str, name: str, arguments: dict[str, object]) -> LLMResponse:
    return LLMResponse(
        tool_calls=[ToolCallRequest(remote_id=remote_id, tool_name=name, arguments=arguments)],
        finish_reason="tool_calls",
    )


def build_script() -> list[LLMResponse]:
    """预设响应脚本：5 个工具调用 + 1 条最终答复。"""
    game = _game_config()
    return [
        _call("demo-1", "validate_experiment",
              {"config": DEMO_SPEC, "previous_errors": []}),
        _call("demo-2", "generate_trials",
              {"config": DEMO_SPEC, "max_preview_trials": 8}),
        _call("demo-3", "export_experiment",
              {"config": DEMO_SPEC, "path": BUNDLE_REL}),
        _call("demo-4", "validate_game",
              {"game_config": game, "bundle_path": BUNDLE_REL, "previous_errors": []}),
        _call("demo-5", "render_game",
              {"game_config": game, "bundle_path": BUNDLE_REL,
               "output_path": HTML_REL, "previous_errors": []}),
        LLMResponse(
            content=(
                "Done. Experiment bundle exported and verified; playable game "
                f"rendered at {HTML_REL} (single-file HTML, file:// playable)."
            ),
            finish_reason="stop",
        ),
    ]


# ---------------------------------------------------------------------------
# 验证（两层；任何失败收集为 problem，main 统一裁决退出码）
# ---------------------------------------------------------------------------

def verify_agent_run(result: object, llm: ScriptedLLM) -> list[str]:
    """脚本级验证：AgentLoop 状态 / 工具序列 / 工具级 ok / 域级 valid+rendered。"""
    problems: list[str] = []
    status = getattr(result, "status", None)
    if status != "completed":
        problems.append(f"agent status is {status!r}, expected 'completed'")
        return problems

    events = list(getattr(result, "events", []))
    tool_calls = [
        str(e.payload.get("tool_name"))
        for e in events
        if e.type == AgentEventType.tool_call
    ]
    if tool_calls != EXPECTED_TOOLS:
        problems.append(f"tool call sequence mismatch: {tool_calls}")

    bad_results = [
        str(e.payload.get("tool_call_id"))
        for e in events
        if e.type == AgentEventType.tool_result and e.payload.get("ok") is not True
    ]
    if bad_results:
        problems.append(f"tool-level failures (BLOCKED): {bad_results}")

    # 域级报告：从最后一轮消息历史取全部 tool 报告（完整未截断）
    if not llm.received_messages:
        problems.append("no LLM rounds recorded")
        return problems
    reports = [
        str(m.get("content", ""))
        for m in llm.received_messages[-1]
        if m.get("role") == "tool"
    ]
    if len(reports) != len(EXPECTED_TOOLS):
        problems.append(
            f"expected {len(EXPECTED_TOOLS)} tool reports in final round, got {len(reports)}"
        )
        return problems

    # reports 顺序即调用顺序：validate / generate / export / validate_game / render
    checks: list[tuple[str, str, dict[str, object] | None]] = []
    for label, text in zip(("validate_experiment", "generate_trials"), reports[:2]):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            problems.append(f"{label} report is not JSON")
            continue
        checks.append((label, "valid", payload))
    export_report = reports[2]
    if not export_report.startswith("wrote "):
        problems.append("export_experiment report does not start with 'wrote '")
    for label, text in zip(("validate_game", "render_game"), reports[3:5]):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            problems.append(f"{label} report is not JSON")
            continue
        checks.append((label, "valid" if label == "validate_game" else "rendered", payload))
    for label, key, payload in checks:
        if payload is None:
            continue
        if payload.get(key) is not True:
            problems.append(f"{label} domain check failed: {key} is not true")

    expected_trials = sum(
        int(b["trial_count"]) for b in DEMO_SPEC["blocks"]  # type: ignore[union-attr]
    )
    generate_payload = json.loads(reports[1]) if reports[1].startswith("{") else {}
    if generate_payload.get("trial_count") != expected_trials:
        problems.append(
            f"generate_trials trial_count mismatch: {generate_payload.get('trial_count')!r}"
        )
    render_payload = json.loads(reports[4]) if reports[4].startswith("{") else {}
    if render_payload.get("total_trials") != expected_trials:
        problems.append(
            f"render_game total_trials mismatch: {render_payload.get('total_trials')!r}"
        )
    return problems


def verify_artifacts(
    sandbox: Path,
    spec: dict[str, object],
    game_config: dict[str, object],
    bundle_rel: str,
    html_rel: str,
) -> list[str]:
    """产物级验证：bundle 完整性/可复现性 + HTML 确定性 + 双指纹锚点 + 试次数一致。"""
    problems: list[str] = []
    bundle_path = sandbox / bundle_rel
    html_path = sandbox / html_rel

    if not bundle_path.is_file():
        return [f"bundle file missing: {bundle_path}"]
    if not html_path.is_file():
        return [f"html file missing: {html_path}"]

    # ① 独立完整性校验（免生成器路径：重算双指纹）
    report = verify_bundle(bundle_path)
    if not report.ok:
        problems.append(f"verify_bundle failed: {report.detail}")
        return problems

    actual_bundle: dict[str, object] = json.loads(bundle_path.read_text(encoding="utf-8"))

    # ② 可复现性：同 spec+seed 确定性重算，剥离 generated_at 后逐字节等价
    expected_bundle = build_bundle(ExperimentSpec.model_validate(spec))
    strip = lambda b: {k: v for k, v in b.items() if k != "generated_at"}  # noqa: E731
    if canonical_json(strip(actual_bundle)) != canonical_json(strip(expected_bundle)):
        problems.append("bundle on disk is not reproducible from spec+seed (byte mismatch)")
    if actual_bundle.get("bundle_sha256") != expected_bundle.get("bundle_sha256"):
        problems.append("bundle_sha256 differs from deterministic recomputation")

    # ③ GameSpec 对实际 bundle 校验（不通过 → HTML 不可信，直接返回）
    game_result = validate_game(game_config, actual_bundle)
    if not game_result.valid or game_result.game_spec is None:
        codes = [f"{e.error_code}:{e.path}" for e in game_result.errors]
        problems.append(f"validate_game against actual bundle failed: {codes}")
        return problems

    # ④ HTML 确定性：与纯函数渲染结果逐字节一致
    expected_html = render_game_html(actual_bundle, game_result.game_spec)
    actual_html = html_path.read_text(encoding="utf-8")
    if actual_html != expected_html:
        problems.append("html on disk is not byte-identical to deterministic render")

    # ⑤ 指纹锚点与试次数一致（显式复核；已被 ④ 蕴含，双保险）
    repro = actual_bundle["reproducibility"]  # type: ignore[index]
    for anchor_name, anchor in (
        ("bundle_sha256", actual_bundle.get("bundle_sha256")),
        ("trials_fingerprint", repro.get("trials_fingerprint")),  # type: ignore[union-attr]
    ):
        if anchor is None or str(anchor) not in actual_html:
            problems.append(f"html is missing fingerprint anchor {anchor_name}")
    expected_trials = sum(
        int(b["trial_count"]) for b in spec["blocks"]  # type: ignore[union-attr]
    )
    actual_trials = actual_bundle.get("trials")
    if not isinstance(actual_trials, list) or len(actual_trials) != expected_trials:
        problems.append(
            f"bundle trial count mismatch: expected {expected_trials}, "
            f"got {len(actual_trials) if isinstance(actual_trials, list) else 'n/a'}"
        )
    return problems


def main() -> None:
    settings = Settings()
    sandbox = Path(settings.data_sandbox_dir)

    llm = ScriptedLLM(build_script())
    registry = build_game_registry(settings)
    loop = AgentLoop(client=llm, registry=registry, settings=settings, task_id=TASK_ID)

    print("===== E2E demo: FakeLLM agent workflow =====")
    print(f"goal       : {GOAL[:72]}...")
    result = asyncio.run(loop.run_task(GOAL))

    problems = verify_agent_run(result, llm)
    problems += verify_artifacts(sandbox, DEMO_SPEC, _game_config(), BUNDLE_REL, HTML_REL)

    bundle_path = sandbox / BUNDLE_REL
    html_path = sandbox / HTML_REL
    bundle = json.loads(bundle_path.read_text(encoding="utf-8")) if bundle_path.is_file() else {}
    print(f"llm rounds : {llm.calls} (5 tool calls + 1 final)")
    print(f"event log  : logs/agent-{TASK_ID}.jsonl")
    if bundle:
        print(f"bundle     : {bundle_path} "
              f"(sha256={str(bundle.get('bundle_sha256'))[:16]}..., "
              f"trials={len(bundle.get('trials', []))})")  # type: ignore[arg-type]
    if html_path.is_file():
        print(f"game html  : {html_path} ({html_path.stat().st_size} bytes)")

    if problems:
        print("\n[E2E FAILED] validation problems (not silently ignored):")
        for p in problems:
            print(f"  - {p}")
        sys.exit(1)

    print("\n[E2E OK] all checks passed:")
    print("  - agent: completed, 5 tools in order, all tool results ok, all domain checks true")
    print("  - bundle: verify_bundle ok, byte-reproducible from spec+seed (generated_at stripped)")
    print("  - html: byte-identical to deterministic render, dual fingerprint anchors embedded")
    print("\nOpen the game in a browser (file://) and press any key to start:")
    print(f"    {html_path.resolve()}")
    print("Verify the bundle independently:")
    print(f"    .venv/bin/python -m src.experiment.verify {bundle_path}")
    print("Note: prototype timing is approximate; not for formal data collection.")


if __name__ == "__main__":
    main()
