"""M1 CLI 入口：经 pydantic-settings 自读 .env，驱动 AgentLoop（契约 §1.5）。

用法：python examples/run_agent.py "<goal>"
退出码：completed → 0；failed → 1；缺 key → 2。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # examples/ 不是包

from src.agent import build_registry  # noqa: E402
from src.agent.llm import LLMClient  # noqa: E402
from src.agent.loop import AgentLoop  # noqa: E402
from src.config import get_settings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a single CognitiveAgent Lab task")
    parser.add_argument("goal", help="task goal in natural language")
    goal = parser.parse_args().goal

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
    print(f"task_id: {task_id}")  # 首行（M1-2 的 TASK_ID 提取依据）

    client = LLMClient(settings)
    loop = AgentLoop(
        client=client,
        registry=build_registry(settings),
        settings=settings,
        task_id=task_id,
    )
    result = asyncio.run(loop.run_task(goal))

    print(f"status: {result.status}")
    print(f"result: {result.result[:512]}")
    return 0 if result.status == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
