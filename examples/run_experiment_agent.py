"""Phase A demo entry: the experiment-design agent (contract §9, M1-2 mode).

Usage: python examples/run_experiment_agent.py
Exit code: completed → 0; failed → 1; missing key → 2.

Tool-set ruling (§9.1): register only the three experiment tools (validate_experiment /
generate_trials / export_experiment), excluding calc / http_request / file_write — the engine is
the sole arithmetic authority of the experiment loop; a smaller tool surface keeps the demo robust, and export handles its own file writes.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # examples/ is not a package

from src.agent.llm import LLMClient  # noqa: E402
from src.agent.loop import AgentLoop  # noqa: E402
from src.agent.registry import ToolRegistry  # noqa: E402
from src.config import get_settings  # noqa: E402
from src.models.events import AgentEventType  # noqa: E402
from src.tools import experiment_tools  # noqa: E402

GOAL = (
    "Design a generic two-factor experiment and export it as a bundle. Requirements: factor "
    "difficulty with levels easy and hard; factor modality with levels visual and audio; two "
    "blocks: practice with 8 trials and main with 96 trials; balance=true (all combinations "
    "equally frequent); response respond of kind choice, options easy/hard, correct_from "
    "difficulty; timing: fixation 500ms, stimulus until response, ISI 1000ms; seed=42. "
    "Validate with validate_experiment, check frequencies with generate_trials, then export to a JSON file under experiments/ via export_experiment."
)

_EXPORT_SUMMARY_RE = re.compile(
    r"^wrote (\S+) \((\d+) bytes, trials_fingerprint=([0-9a-f]{64}), "
    r"bundle_sha256=([0-9a-f]{64})\)$"
)


def _print_export_lines(result: object, sandbox_dir: str) -> None:
    """Extract the successful export_experiment result from AgentResult.events and print the bundle path and dual fingerprints (§9.3).

    Locate the successful tool_result of export_experiment via the tool_call event's
    tool_call_id → tool_name mapping and read the path/fingerprints from its result_summary — no AgentLoop changes just to extract information.
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
    print(f"task_id: {task_id}")  # first line

    # Demo assembly (§9.1: not via build_experiment_registry — that is the 6-tool combinator, for tests and future general use)
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
