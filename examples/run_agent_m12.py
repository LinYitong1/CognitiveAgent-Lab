"""M1-2 dedicated test entry (test-only, not M1 product code; kept after M1-2 as an audit record).

Rationale: the user's M1-2 authorization limited the tool set to calc + file_write (http_request disabled),
while examples/run_agent.py registers all three tools via build_registry and the M1 product code is frozen
(zero-modification constraint). This entry reuses every real component with minimal intrusion —
LLMClient / AgentLoop / ToolRegistry and the calc / file_write ToolSpecs all come from src/ — and only
restricts the registry to the authorized tool set: http_request never enters the tools schema, so the model

structurally cannot call it. This is the only behavioral difference from examples/run_agent.py; the exit-code convention is the same:
completed → 0; failed → 1; missing key → 2.

Usage: python examples/run_agent_m12.py "<goal>"
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # examples/ is not a package

from src.agent.llm import LLMClient  # noqa: E402
from src.agent.loop import AgentLoop  # noqa: E402
from src.agent.registry import ToolRegistry  # noqa: E402
from src.config import get_settings  # noqa: E402
from src.tools import calc, file_write  # noqa: E402  # deliberately does not import http_request


def build_restricted_registry() -> ToolRegistry:
    """M1-2 authorized tool set: calc + file_write only (settings shares the source with build_registry)."""
    settings = get_settings()
    registry = ToolRegistry()
    registry.register(calc.build_tool_spec(settings))
    registry.register(file_write.build_tool_spec(settings))
    return registry


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a single M1-2 task (calc + file_write only)")
    parser.add_argument("goal", help="task goal in natural language")
    goal = parser.parse_args().goal

    settings = get_settings()  # reads .env, overridable via the CALC_AGENT_ENV_FILE path
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
    print(f"task_id: {task_id}")  # first line (extraction anchor for M1-2)

    client = LLMClient(settings)
    loop = AgentLoop(
        client=client,
        registry=build_restricted_registry(),
        settings=settings,
        task_id=task_id,
    )
    result = asyncio.run(loop.run_task(goal))

    print(f"status: {result.status}")
    print(f"steps: {result.steps}")
    print(f"result: {result.result[:512]}")
    return 0 if result.status == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
