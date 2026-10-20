"""cognitive-agent CLI: the installed entry point (``pip install`` provides it on PATH).

Subcommands (user-approved minimal plan):
- ``run "<goal>"``   — drive the real AgentLoop with the configured LLM provider
                       (experimental reliability; see the notice printed at start).
- ``demo``           — deterministic scripted workflow: FakeLLM-style client, zero
                       network, zero keys; produces a verified bundle + playable HTML.
- ``verify <bundle>``— independent ExperimentBundle integrity check (recomputes
                       both SHA-256 fingerprints without the generator).

Both ``run`` and ``demo`` accept ``--output <dir>``: all generated experiment
artifacts are confined to that directory (it becomes the data sandbox root).
Agent event logs still land in ``logs/`` (runtime logs, not artifacts).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

from src.config import Settings
from src.experiment.verify import verify_bundle
from src.pipeline import (
    MissingCredentialsError,
    PipelineResult,
    PipelineVerificationError,
    run_demo,
    run_task,
)

REAL_LLM_NOTICE = (
    "Note: real-LLM end-to-end reliability is not yet validated (known issue PA-14).\n"
    "The deterministic, fully verified path is: cognitive-agent demo"
)


def _settings(output: str | None) -> Settings:
    """Settings with an optional per-invocation sandbox root override."""
    if output is not None:
        return Settings(data_sandbox_dir=str(output))
    return Settings()


def _print_result(result: PipelineResult) -> int:
    """Print the structured outcome; exit code reflects status and verification."""
    print(f"status     : {result.status}")
    print(f"steps      : {result.result.steps}")
    print(f"event log  : logs/agent-{result.result.task_id}.jsonl")
    if result.artifacts:
        print("artifacts  :")
        for artifact in result.artifacts:
            print(f"  - {artifact}")
    else:
        print("artifacts  : (none)")
    exit_code = 0 if result.status == "completed" else 1
    if result.bundle_verification is not None:
        outcome = "OK" if result.bundle_verification.ok else "FAILED"
        print(f"bundle     : verification {outcome}")
        if not result.bundle_verification.ok:
            print(f"             {result.bundle_verification.detail}")
            exit_code = 1
    if result.html_verified is not None:
        outcome = "matches deterministic re-render" if result.html_verified else "MISMATCH"
        print(f"html       : {outcome}")
        if not result.html_verified:
            exit_code = 1
    return exit_code


async def _cmd_run(args: argparse.Namespace) -> int:
    print(REAL_LLM_NOTICE)
    settings = _settings(args.output)
    try:
        result = await run_task(args.goal, settings=settings)
    except MissingCredentialsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return _print_result(result)


async def _cmd_demo(args: argparse.Namespace) -> int:
    print("Running the deterministic scripted demo (no network, no keys, no real LLM)...")
    try:
        result = await run_demo(output_dir=args.output)
    except PipelineVerificationError as exc:
        print("error: demo verification failed (nothing is silently ignored):", file=sys.stderr)
        for problem in exc.problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    return _print_result(result)


def _cmd_verify(args: argparse.Namespace) -> int:
    report = verify_bundle(args.bundle_path)
    print(report.detail)
    return 0 if report.ok else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cognitive-agent",
        description=(
            "CognitiveAgent Lab: turn a natural-language task into validated experiment "
            "files and a playable single-file HTML game."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser(
        "run", help="run a natural-language task with the configured real LLM provider"
    )
    p_run.add_argument("goal", help="task goal in natural language")
    p_run.add_argument(
        "--output",
        metavar="DIR",
        default=None,
        help="directory for all generated files (default: the data/ sandbox)",
    )

    p_demo = sub.add_parser(
        "demo",
        help="run the deterministic scripted demo (no network, no keys)",
    )
    p_demo.add_argument(
        "--output",
        metavar="DIR",
        default=None,
        help="directory for all generated files (default: the data/ sandbox)",
    )

    p_verify = sub.add_parser(
        "verify", help="independently verify an ExperimentBundle JSON file"
    )
    p_verify.add_argument("bundle_path", help="path to the ExperimentBundle JSON file")

    args = parser.parse_args(argv)
    if args.command == "run":
        return asyncio.run(_cmd_run(args))
    if args.command == "demo":
        return asyncio.run(_cmd_demo(args))
    return _cmd_verify(args)


if __name__ == "__main__":
    raise SystemExit(main())
