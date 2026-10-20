"""Phase A Demo 入口：实验设计 Agent（契约 §9，M1-2 模式）。

用法：python examples/run_experiment_agent.py
退出码：completed → 0；failed → 1；缺 key → 2。

工具集裁定（§9.1）：只注册实验三工具（validate_experiment / generate_trials /
export_experiment），不含 calc / http_request / file_write——实验循环的全部算术
权威是引擎，工具面越小 Demo 越稳健，export 自含写盘。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # examples/ 不是包

from src.agent.llm import LLMClient  # noqa: E402
from src.agent.loop import AgentLoop  # noqa: E402
from src.agent.registry import ToolRegistry  # noqa: E402
from src.config import get_settings  # noqa: E402
from src.models.events import AgentEventType  # noqa: E402
from src.tools import experiment_tools  # noqa: E402

GOAL = (
    "设计一个通用两因素实验并导出为实验包。要求：因素 difficulty 有 easy 和 hard 两个水平，"
    "因素 modality 有 visual 和 audio 两个水平；两个 block：practice 8 试次、main 96 试次；"
    "约束 balance=true（所有因素组合等频）；响应变量 respond 为 choice 类型，选项 easy/hard，"
    "正确答案来自因素 difficulty；timing：fixation 500ms、stimulus 直至响应、ISI 1000ms；seed=42。"
    "请先用 validate_experiment 验证规格，再用 generate_trials 确认频数分布，"
    "最后用 export_experiment 导出到 experiments/ 目录下的 JSON 文件。"
)

_EXPORT_SUMMARY_RE = re.compile(
    r"^wrote (\S+) \((\d+) bytes, trials_fingerprint=([0-9a-f]{64}), "
    r"bundle_sha256=([0-9a-f]{64})\)$"
)


def _print_export_lines(result: object, sandbox_dir: str) -> None:
    """从 AgentResult.events 提取 export_experiment 成功结果，打印 bundle 路径与双指纹（§9.3）。

    以 tool_call 事件的 tool_call_id → tool_name 映射定位 export_experiment 的成功
    tool_result，从其 result_summary 提取路径与指纹——不为获取信息修改 AgentLoop。
    """
    events = getattr(result, "events", [])
    export_call_ids = {
        str(event.payload.get("tool_call_id"))
        for event in events
        if event.type == AgentEventType.tool_call
        and str(event.payload.get("tool_name")) == "export_experiment"
    }
    for event in events:
        if event.type != AgentEventType.tool_result:
            continue
        if str(event.payload.get("tool_call_id")) not in export_call_ids:
            continue
        if event.payload.get("ok") is not True:
            continue
        match = _EXPORT_SUMMARY_RE.match(str(event.payload.get("result_summary", "")))
        if match is None:
            continue
        rel_path, _bytes, trials_fp, bundle_sha = match.groups()
        sandbox = Path(sandbox_dir)
        display = rel_path if sandbox.is_absolute() else f"{sandbox_dir}/{rel_path}"
        print(f"bundle: {display}")
        print(f"trials_fingerprint: {trials_fp}")
        print(f"bundle_sha256: {bundle_sha}")
        print(f"verify: python -m src.experiment.verify {display}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Phase A experiment design agent")
    parser.parse_args()

    settings = get_settings()  # 自读 .env，受 CALC_AGENT_ENV_FILE 路径覆盖
    if not settings.openai_api_key and not settings.anthropic_api_key:
        env_file = os.environ.get("CALC_AGENT_ENV_FILE", ".env")
        print(
            "ERROR: no LLM API key configured — both OPENAI_API_KEY and ANTHROPIC_API_KEY "
            f"are empty. Set one of them in your env file "
            f"(CALC_AGENT_ENV_FILE={env_file!r}, default path: .env).",
            file=sys.stderr,
        )
        return 2

    task_id = f"task-{uuid4().hex[:12]}"
    print(f"task_id: {task_id}")  # 首行

    # Demo 组装（§9.1：不经 build_experiment_registry——那是 6 工具组合，供测试与未来通用使用）
    registry = ToolRegistry()
    registry.register(experiment_tools.build_validate_spec(settings))
    registry.register(experiment_tools.build_generate_spec(settings))
    registry.register(experiment_tools.build_export_spec(settings))
    loop = AgentLoop(
        client=LLMClient(settings),
        registry=registry,
        settings=settings,
        task_id=task_id,
    )
    result = asyncio.run(loop.run_task(GOAL))

    print(f"status: {result.status}")
    print(f"result: {result.result[:512]}")
    _print_export_lines(result, settings.data_sandbox_dir)
    return 0 if result.status == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
