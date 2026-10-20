"""M1-2 专用测试入口（test-only，非 M1 产品代码，M1-2 后保留作审计记录）。

存在原因：用户对 M1-2 的授权将工具集限定为 calc + file_write（禁用 http_request），
而 examples/run_agent.py 经 build_registry 固定注册全部三工具，且 M1 产品代码已冻结
（零修改约束）。本入口以最小侵入方式复用全部真实组件——LLMClient / AgentLoop /
ToolRegistry / calc / file_write 的 ToolSpec 均来自 src/ 现有实现——仅将注册表限定
为授权工具集：http_request 不进入 tools schema，模型结构上无法调用该工具。

对照 examples/run_agent.py 的行为差异仅此一处；退出码约定一致：
completed → 0；failed → 1；缺 key → 2。

用法：python examples/run_agent_m12.py "<goal>"
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # examples/ 不是包

from src.agent.llm import LLMClient  # noqa: E402
from src.agent.loop import AgentLoop  # noqa: E402
from src.agent.registry import ToolRegistry  # noqa: E402
from src.config import get_settings  # noqa: E402
from src.tools import calc, file_write  # noqa: E402  # 有意不导入 http_request


def build_restricted_registry() -> ToolRegistry:
    """M1-2 授权工具集：仅 calc + file_write（settings 与 build_registry 同源）。"""
    settings = get_settings()
    registry = ToolRegistry()
    registry.register(calc.build_tool_spec(settings))
    registry.register(file_write.build_tool_spec(settings))
    return registry


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a single M1-2 task (calc + file_write only)")
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
