"""E1-B evaluation runner (preflighted with a zero-cost mock dry-run).

Runs ONE natural-language brief per task through the REAL AgentLoop and the
REAL 9-tool game registry — only the LLM is swappable:

  --provider mock   a scripted MockLLM (zero paid calls; the dry-run scenarios)
  --provider real   LLMClient on the OpenAI-compatible Gemini endpoint
                    (requires explicit user authorization of the budget; this
                    module never starts a real run without --provider real AND
                    a non-empty key AND an explicitly passed --authorize-budget
                    confirmation flag)

Discipline (docs/agent-evaluation/05-gemini-run-protocol.md):
  - the agent sees ONLY the brief text and the normal tool documentation —
    nothing from the scorer, no reference specs, no answer keys;
  - every task runs in a FRESH sandbox (data/e1-runs/<run-id>/<task-id>/);
  - full call trace, usage ledger, latencies, artifacts and the run report are
    retained per task, followed by INDEPENDENT scoring (scripts/e1_scorer);
  - budget: per-task call cap is a pre-call hard stop; cost caps are post-call
    accounting (scripts/e1_budget.py states the exact guarantees);
  - model/transport failures, budget stops and incomplete artifacts are
    recorded as first-class outcomes, never retried silently.

Usage:
  python -m scripts.e1_runner --dryrun                 # 4+1 mock scenarios
  python -m scripts.e1_runner --task e1_flanker --provider real \
      --run-id e1b-<date> --authorize-budget           # single real task
  python -m scripts.e1_runner --all --provider real ... # all five
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, cast

from src.agent.game_registry import build_game_registry
from src.agent.loop import AgentLoop
from src.agent.registry import ToolRegistry
from src.config import Settings
from src.models.llm import LLMResponse, ToolCallRequest
from src.models.tool_result import ToolResult
from scripts.e1_budget import BudgetGuard, BudgetedClient
from scripts.e1_scorer import SCORER_VERSION, score_artifacts, score_run

REPO_ROOT = Path(__file__).resolve().parents[1]

RUNNER_VERSION = "e1-runner-v1"
BRIEFS_VERSION = "e1-briefs-v1"

# The five E1 briefs, verbatim from docs/agent-evaluation/02-task-briefs.md
# (frozen at this version; the docs file is the rendered copy).
BRIEFS: dict[str, str] = {
    "e1_t5_retest": (
        "I need a simple visual discrimination experiment as a browser game. On each "
        "trial the screen shows a color name (red or blue), and the participant "
        "presses the matching key. 10 trials, balanced across the two colors. Give me "
        "a playable single-file HTML game with the standard reproducibility "
        "guarantees, and make sure the event log records what was shown, what was "
        "answered, whether it was correct, and the response time."
    ),
    "e1_flanker": (
        "Design a flanker task. Each trial shows a row of five arrow characters, "
        "like `<<><<` or `>>>>>`. The participant reports the direction of the MIDDLE "
        "arrow (left or right). The flanking arrows are either the same direction as "
        "the middle one (congruent) or the opposite (incongruent); congruent and "
        "incongruent trials should occur equally often, and the middle direction "
        "should also be balanced. The correct answer is always the middle arrow's "
        "direction. 16 trials. I want the game as a single HTML file, and the data "
        "log must let me analyze accuracy and reaction time separately for congruent "
        "vs incongruent trials."
    ),
    "e1_wm": (
        "I need a short-term memory experiment. Each trial has two parts: first a "
        "study screen showing a small set of words to remember, then, after the "
        "study screen, a probe screen showing one word. The participant judges "
        "whether the probe word was in the memorized set (yes) or not (no). Memory "
        "load varies between trials: some trials show 2 words, others show 4; both "
        "loads equally often. Probes are in the set on half the trials and new on "
        "the other half, crossed with load. 16 trials total. The study and probe "
        "screens must be separate presentations (the probe must not be visible while "
        "the study set is on screen). Answer keys must follow the actual words shown. "
        "Deliver the playable HTML game with the reproducibility guarantees."
    ),
    "e1_taskswitch": (
        "Design a task-switching experiment. There are two judgment tasks on the "
        "same kind of stimulus. On each trial a cue first tells the participant "
        "which task to perform, then a word appears. In task A, the participant "
        "answers whether the word is \"same\"; in task B, whether it is \"different\" — "
        "the correct answer depends on the task: for task A the correct answer is "
        "\"yes\" exactly when the word is \"same\", for task B exactly when the word is "
        "\"different\". Both tasks and both answers should occur equally often, 16 "
        "trials. The cue must be shown before the word on every trial. The data log "
        "must let me identify, for every trial, which task was cued, so I can "
        "compute switch costs by comparing trials where the task changed from the "
        "previous trial versus stayed the same. Single playable HTML file please."
    ),
    "e1_t2r_regression": (
        "我要做一个基于可探索场景的工作记忆实验，主题是废弃空间站。实验为"
        "被试内设计，两个因素：记忆序列长度（短/长）× 探测类型（相同/不同），"
        "共 12 个平衡试次。每个试次先呈现记忆序列，再呈现探测项，被试判断"
        "探测项是否在刚才的序列中（相同/不同），用 s/d 键反应。游戏要有至少"
        "3 个可探索的房间，试次通过探索场景中的特定对象触发，但探索顺序"
        "不能改变试次的内容和顺序。请交付可玩的单文件 HTML 游戏和完整的"
        "数据记录。"
    ),
}

TASK_ORDER = ["e1_t5_retest", "e1_flanker", "e1_wm", "e1_taskswitch", "e1_t2r_regression"]

# Budget defaults (docs/agent-evaluation/05-gemini-run-protocol.md)
DEFAULT_MAX_CALLS = 16
DEFAULT_PER_TASK_COST_CAP = 0.30
DEFAULT_TOTAL_COST_STOP = 2.00
DEFAULT_PRICE_IN = 0.75   # $/1M input tokens (gemini-3.8-flash intro rate)
DEFAULT_PRICE_OUT = 3.75  # $/1M output tokens (thinking billed as output)
REAL_MAX_TOKENS = 8192
REAL_MAX_INPUT_BYTES = 96 * 1024


def _git_head() -> tuple[str, bool]:
    """(commit, dirty) of the repo at run time — recorded into every run
    report so the executed baseline is self-documenting; ('unknown', True) on
    any failure (never blocks a run)."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
            capture_output=True, text=True, timeout=10,
        )
        commit = out.stdout.strip() if out.returncode == 0 else "unknown"
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=REPO_ROOT,
            capture_output=True, text=True, timeout=10,
        )
        # only tracked-file modifications make the tree 'dirty' for baseline
        # purposes (intentionally local-only untracked files, e.g. the T2R
        # report, must not flag every run as dirty)
        if status.returncode == 0:
            dirty = any(
                line.strip() and not line.startswith("??")
                for line in status.stdout.splitlines()
            )
        else:
            dirty = True
        return commit, dirty
    except Exception:
        return "unknown", True


# ---------------------------------------------------------------------------
# Mock provider (zero paid calls)
# ---------------------------------------------------------------------------


class MockLLM:
    """Scripted provider: pops the next step per chat() call. A step is either
    an LLMResponse or an Exception to raise. Repeats the LAST step forever
    once the script is exhausted (drives call-cap scenarios)."""

    def __init__(self, steps: list[object]) -> None:
        self._steps = list(steps)
        self.calls = 0

    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMResponse:
        self.calls += 1
        idx = min(self.calls - 1, len(self._steps) - 1)
        step = self._steps[idx]
        if isinstance(step, Exception):
            raise step
        return cast(LLMResponse, step)


def _tool(name: str, args: dict[str, Any], rid: str) -> ToolCallRequest:
    return ToolCallRequest(remote_id=rid, tool_name=name, arguments=args)


def _resp_with_tools(calls: list[ToolCallRequest], usage: dict[str, int] | None = None) -> LLMResponse:
    return LLMResponse(content="", tool_calls=calls, finish_reason="tool_calls", usage=usage)


def _final(text: str, usage: dict[str, int] | None = None) -> LLMResponse:
    return LLMResponse(content=text, finish_reason="stop", usage=usage)


# ---------------------------------------------------------------------------
# Registry recorder (artifact discovery without touching the loop)
# ---------------------------------------------------------------------------


class RecordingRegistry:
    """Duck-typed ToolRegistry proxy: records every executed call verbatim so
    the runner can locate artifacts (export/render paths) post-hoc."""

    def __init__(self, inner: ToolRegistry) -> None:
        self._inner = inner
        self.calls: list[dict[str, Any]] = []

    def get_schemas(self) -> list[dict[str, Any]]:
        return self._inner.get_schemas()

    async def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        result = await self._inner.execute(name, arguments)
        self.calls.append({"tool": name, "args": arguments, "ok": result.ok})
        return result


# ---------------------------------------------------------------------------
# Per-task run
# ---------------------------------------------------------------------------


def _sandbox_for(out_root: Path, task_id: str) -> Path:
    sandbox = out_root / task_id
    if sandbox.exists() and any(sandbox.iterdir()):
        raise SystemExit(
            f"sandbox {sandbox} is not empty — the protocol forbids reusing sandboxes; "
            "pass a fresh --run-id"
        )
    sandbox.mkdir(parents=True, exist_ok=True)
    return sandbox


def _classify_stop(result_text: str, termination_reason: str) -> str:
    lowered = result_text.lower()
    if "budgetexceeded" in lowered or "budget exceeded" in lowered:
        for reason in ("budget-stop-cost", "budget-stop-total", "budget-stop"):
            if reason in lowered:
                return reason
        return "budget-stop"
    if termination_reason == "max_steps_exceeded":
        return "max_steps_exceeded"
    if termination_reason == "llm_error":
        return "llm_error"
    return termination_reason or "unknown"


async def run_task(
    task_id: str,
    run_id: str,
    client_inner: Any,
    guard: BudgetGuard,
    out_root: Path,
    provider: str,
    model: str,
    base_url: str,
    pacing_s: float = 0.0,
) -> dict[str, Any]:
    """Run one brief end-to-end (loop + scoring). Returns the run report dict
    and writes run-report.json / scored.json into the task sandbox."""
    if task_id not in BRIEFS:
        raise SystemExit(f"unknown task {task_id!r} (known: {TASK_ORDER})")
    sandbox = _sandbox_for(out_root, task_id)
    settings = Settings(
        data_sandbox_dir=str(sandbox),
        # loop-level backstop one call beyond the guard cap so the BUDGET stop
        # (with its distinct reason) is always the recorded stop, and the guard
        # remains the authoritative pre-call hard limit
        calc_agent_max_steps=guard.max_calls + 1,
    )
    registry = RecordingRegistry(build_game_registry(settings))
    client = BudgetedClient(client_inner, guard, pacing_s=pacing_s)
    agent_task_id = f"e1-{run_id}-{task_id}"
    loop = AgentLoop(client, registry, settings, task_id=agent_task_id)

    brief_path = sandbox / "brief.txt"
    brief_path.write_text(BRIEFS[task_id], encoding="utf-8")

    started = time.perf_counter()
    result = await loop.run_task(BRIEFS[task_id])
    wall_s = round(time.perf_counter() - started, 1)

    stop_reason = _classify_stop(result.result, result.termination_reason)
    rendered = [c for c in registry.calls if c["tool"] == "render_game" and c["ok"]]
    exported = [c for c in registry.calls if c["tool"] == "export_experiment" and c["ok"]]
    artifacts: dict[str, str] = {}
    if rendered:
        args = cast(dict[str, Any], rendered[-1]["args"])
        artifacts = {
            "bundle": args["bundle_path"],
            "html": args["output_path"],
        }
    elif exported:
        artifacts = {"bundle": cast(dict[str, Any], exported[-1]["args"])["path"]}

    failure_class = ""
    if stop_reason != "completed" and stop_reason != "model_final_answer":
        failure_class = stop_reason
    elif not rendered:
        failure_class = "no-artifacts"

    commit, commit_dirty = _git_head()
    summary = guard.summary()
    scenario: dict[str, Any] = {
        "scenario": task_id,
        "success": bool(rendered) and result.status == "completed",
        "detail": result.result[:400],
        "failure_class": failure_class,
        "stop_reason": stop_reason,
        "loop_status": result.status,
        "termination_reason": result.termination_reason,
        "steps": result.steps,
        "llm_calls": summary["calls"],
        "tool_calls": [{"tool": c["tool"], "ok": c["ok"]} for c in registry.calls],
        "n_tool_calls": len(registry.calls),
        "wall_s": wall_s,
        "usage_log": summary["usage_log"],
        "llm_latency_s": summary["llm_latency_s"],
        "tokens_total": summary["tokens_total"],
        "tokens_in": summary["tokens_in"],
        "tokens_out": summary["tokens_out_billable"],
        "cost_estimate_usd": summary["cost_estimate_usd"],
        "cost_is_lower_bound": summary["cost_is_lower_bound"],
        "guard_cost_estimate_usd": summary["guard_cost_estimate_usd"],
        "unreported_usage_calls": summary["unreported_usage_calls"],
        "artifacts": artifacts,
        "result_head": result.result[:400],
    }
    report: dict[str, Any] = {
        "runner_version": RUNNER_VERSION,
        "briefs_version": BRIEFS_VERSION,
        "scorer_version": SCORER_VERSION,
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "commit": commit,
        "commit_dirty": commit_dirty,
        "sandbox": str(sandbox),
        "budget": {
            "max_calls": guard.max_calls,
            "per_task_cost_cap": guard.per_task_cost_cap,
            "total_cost_stop": guard.total_cost_stop,
            "price_in_per_m": guard.price_in_per_m,
            "price_out_per_m": guard.price_out_per_m,
        },
        "scenarios": [scenario],
    }
    report_path = sandbox / "run-report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    # independent scoring AFTER the run (never during; nothing injected)
    scored: dict[str, Any] = {"task": task_id, "scorer_version": SCORER_VERSION}
    if artifacts.get("bundle"):
        bundle_path = sandbox / artifacts["bundle"]
        html_path = sandbox / artifacts["html"] if artifacts.get("html") else None
        if bundle_path.is_file():
            scored["artifacts"] = score_artifacts(task_id, bundle_path, html_path)
        else:
            scored["artifacts"] = {
                "error": f"declared bundle {artifacts['bundle']} not found in the sandbox"
            }
    else:
        scored["artifacts"] = {"error": "no artifacts produced (run did not reach export/render)"}
    scored["run_record"] = score_run(task_id, report_path)
    scored["stop_reason"] = stop_reason
    (sandbox / "scored.json").write_text(
        json.dumps(scored, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return {"report": report, "scored": scored}


# ---------------------------------------------------------------------------
# Dry-run (mock) scenarios: success / validation-failure / budget / api error
# ---------------------------------------------------------------------------

_DRYRUN_ROOT = REPO_ROOT / "data" / ".test-sandbox" / "e1-dryrun"

_MOCK_T5_SPEC: dict[str, Any] = {
    "schema_version": 2,
    "name": "dryrun-color",
    "version": "0.1.0",
    "seed": 41,
    "factors": [{"name": "color", "levels": [{"name": "red"}, {"name": "blue"}]}],
    "blocks": [{"name": "main", "trial_count": 10}],
    "constraints": {"balance": True},
    "responses": [
        {"name": "answer", "kind": "choice", "options": ["red", "blue"], "correct_from": "color"}
    ],
    "timing": {"fixation_ms": 20, "stimulus_ms": None, "isi_ms": 20},
    "stimulus_spec": {
        "factors": {
            "color": {"levels": {"red": [["RED"]], "blue": [["BLUE"]]}, "match_line_count": True}
        },
        "pools": {},
    },
}

_MOCK_INVALID_SPEC: dict[str, Any] = {
    "schema_version": 1,
    "name": "dryrun-invalid",
    "version": "0.1.0",
    "seed": 1,
    "factors": [],
    "blocks": [{"name": "main", "trial_count": 4}],
    "responses": [{"name": "answer", "kind": "choice", "options": ["a"]}],
    "timing": {"fixation_ms": 10, "stimulus_ms": 10, "isi_ms": 10},
}


def _mock_game_config() -> dict[str, Any]:
    from src.experiment.export import build_bundle
    from src.experiment.schemas import ExperimentSpec

    bundle = build_bundle(ExperimentSpec.model_validate(_MOCK_T5_SPEC),
                          generated_at="2000-01-01T00:00:00Z")
    s = cast(dict[str, Any], bundle["spec"])
    r = cast(dict[str, Any], bundle["reproducibility"])
    return {
        "schema_version": 1,
        "game": {"name": "dryrun-color", "version": "0.1.0"},
        "experiment_ref": {
            "name": s["name"], "version": s["version"], "seed": s["seed"],
            "config_fingerprint": r["config_fingerprint"],
            "trials_fingerprint": r["trials_fingerprint"],
            "bundle_sha256": bundle["bundle_sha256"],
        },
        "scene": {"title": "Colors", "instructions": "Match the color."},
        "input": {"modalities": ["keyboard"],
                  "bindings": [{"response_name": "answer", "keys": {"r": "red", "b": "blue"}}]},
        "feedback": {"on_response": "outcome-text", "duration_ms": 20},
    }


def _success_script() -> list[object]:
    game = _mock_game_config()
    return [
        _resp_with_tools([_tool("validate_experiment", {"config": _MOCK_T5_SPEC}, "r1")]),
        _resp_with_tools([_tool("export_experiment",
                                {"config": _MOCK_T5_SPEC, "path": "experiments/dryrun.json"}, "r2")]),
        _resp_with_tools([_tool("validate_game",
                                {"game_config": game, "bundle_path": "experiments/dryrun.json"}, "r3")]),
        _resp_with_tools([_tool("render_game",
                                {"game_config": game, "bundle_path": "experiments/dryrun.json",
                                 "output_path": "games/dryrun.html"}, "r4")]),
        _final("The playable HTML game has been delivered.",
               {"prompt_tokens": 1000, "completion_tokens": 50, "total_tokens": 1050}),
    ]


def _validation_failure_script() -> list[object]:
    return [
        _resp_with_tools([_tool("validate_experiment", {"config": _MOCK_INVALID_SPEC}, "r1")]),
        _final("The experiment is done and delivered successfully."),  # false success claim
    ]


def _budget_loop_script(usage: dict[str, int] | None = None) -> list[object]:
    # never reaches a final answer: validate forever (the guard must stop it)
    return [
        _resp_with_tools([_tool("validate_experiment", {"config": _MOCK_T5_SPEC}, "r1")], usage),
    ]


def _make_guard(**overrides: Any) -> BudgetGuard:
    kwargs: dict[str, Any] = {
        "max_calls": DEFAULT_MAX_CALLS,
        "per_task_cost_cap": DEFAULT_PER_TASK_COST_CAP,
        "total_spent": [0.0],
        "total_cost_stop": DEFAULT_TOTAL_COST_STOP,
        "price_in_per_m": DEFAULT_PRICE_IN,
        "price_out_per_m": DEFAULT_PRICE_OUT,
    }
    kwargs.update(overrides)
    return BudgetGuard(**kwargs)


async def run_dryrun() -> dict[str, Any]:
    """Zero-cost end-to-end dry run of the runner itself: success, validation
    failure, call-cap budget stop, cost-cap budget stop, usage-missing guard,
    and API error. Returns the scenario outcomes with expectations checked."""
    if _DRYRUN_ROOT.exists():
        shutil.rmtree(_DRYRUN_ROOT)  # test-sandbox area only; dry runs are repeatable
    results: dict[str, Any] = {}

    # 1. success: loop completes, artifacts produced, scorer grades them
    out = _DRYRUN_ROOT / "success"
    outcome = await run_task(
        "e1_t5_retest", "dryrun", MockLLM(_success_script()),
        _make_guard(), out, "mock", "mock-llm", "mock://local",
    )
    sc = outcome["report"]["scenarios"][0]
    d1 = outcome["scored"]["run_record"]["D1_task_completion"]
    d3 = outcome["scored"]["artifacts"]["D3_artifact_validity"]
    d6 = outcome["scored"]["artifacts"]["D6_html_interaction"]
    results["success"] = {
        "expected": ["stop_reason=completed", "D1=PASS", "D3=PASS", "D6=PASS"],
        "stop_reason": sc["stop_reason"],
        "D1": d1["verdict"], "D3": d3["verdict"], "D6": d6["verdict"],
        "ok": (sc["stop_reason"] == "model_final_answer" and sc["success"]
               and d1["verdict"] == "PASS" and d3["verdict"] == "PASS"
               and d6["verdict"] == "PASS"),
    }

    # 2. validation failure: model claims success without artifacts -> D1 FAIL
    out = _DRYRUN_ROOT / "validation-failure"
    outcome = await run_task(
        "e1_t5_retest", "dryrun", MockLLM(_validation_failure_script()),
        _make_guard(), out, "mock", "mock-llm", "mock://local",
    )
    sc = outcome["report"]["scenarios"][0]
    d1 = outcome["scored"]["run_record"]["D1_task_completion"]
    results["validation_failure"] = {
        "expected": ["failure_class=no-artifacts", "D1=FAIL"],
        "stop_reason": sc["stop_reason"],
        "failure_class": sc["failure_class"],
        "D1": d1["verdict"],
        "ok": (sc["failure_class"] == "no-artifacts" and d1["verdict"] == "FAIL"
               and "no artifacts" in str(outcome["scored"]["artifacts"].get("error", ""))),
    }

    # 3. budget stop (call cap): hard pre-call stop at 3 calls
    out = _DRYRUN_ROOT / "budget-call-cap"
    guard = _make_guard(max_calls=3)
    outcome = await run_task(
        "e1_t5_retest", "dryrun", MockLLM(_budget_loop_script(None)),
        guard, out, "mock", "mock-llm", "mock://local",
    )
    sc = outcome["report"]["scenarios"][0]
    results["budget_call_cap"] = {
        "expected": ["stop_reason=budget-stop", "llm_calls=3", "failure_class=budget-stop"],
        "stop_reason": sc["stop_reason"],
        "llm_calls": sc["llm_calls"],
        "failure_class": sc["failure_class"],
        "ok": (sc["stop_reason"] == "budget-stop" and sc["llm_calls"] == 3
               and sc["failure_class"] == "budget-stop"),
    }

    # 4. budget stop (cost cap): one reported $0.9 call exceeds a $0.50 cap
    out = _DRYRUN_ROOT / "budget-cost-cap"
    guard = _make_guard(per_task_cost_cap=0.50)
    mock = MockLLM(_budget_loop_script(
        {"prompt_tokens": 1_000_000, "completion_tokens": 100, "total_tokens": 1_000_100}
    ))
    outcome = await run_task(
        "e1_t5_retest", "dryrun", mock, guard, out, "mock", "mock-llm", "mock://local",
    )
    sc = outcome["report"]["scenarios"][0]
    results["budget_cost_cap"] = {
        "expected": ["stop_reason=budget-stop-cost", "llm_calls=1"],
        "stop_reason": sc["stop_reason"],
        "llm_calls": sc["llm_calls"],
        "ok": (sc["stop_reason"] == "budget-stop-cost" and sc["llm_calls"] == 1),
    }

    # 5. usage missing: unreported usage must not be counted as $0 (guard uses
    #    the conservative assumption; reported cost stays 0 and is marked)
    out = _DRYRUN_ROOT / "usage-missing"
    guard = _make_guard(per_task_cost_cap=0.10, assumed_worst_case_usd=0.05)
    mock = MockLLM([
        _resp_with_tools([_tool("validate_experiment", {"config": _MOCK_T5_SPEC}, "r1")]),
    ])
    outcome = await run_task(
        "e1_t5_retest", "dryrun", mock, guard, out, "mock", "mock-llm", "mock://local",
    )
    sc = outcome["report"]["scenarios"][0]
    results["usage_missing"] = {
        "expected": ["stop_reason=budget-stop-cost after 2 unreported calls",
                     "cost_estimate_usd=0.0 (lower bound)", "unreported=2"],
        "stop_reason": sc["stop_reason"],
        "llm_calls": sc["llm_calls"],
        "cost_estimate_usd": sc["cost_estimate_usd"],
        "cost_is_lower_bound": sc["cost_is_lower_bound"],
        "ok": (sc["stop_reason"] == "budget-stop-cost" and sc["llm_calls"] == 2
               and sc["cost_estimate_usd"] == 0.0 and sc["cost_is_lower_bound"] is True),
    }

    # 6. API error: first call raises; run fails cleanly, artifacts retained (none)
    out = _DRYRUN_ROOT / "api-error"
    outcome = await run_task(
        "e1_t5_retest", "dryrun", MockLLM([RuntimeError("connection reset by peer")]),
        _make_guard(), out, "mock", "mock-llm", "mock://local",
    )
    sc = outcome["report"]["scenarios"][0]
    results["api_error"] = {
        "expected": ["stop_reason=llm_error", "llm_calls=1 (failed call counted)"],
        "stop_reason": sc["stop_reason"],
        "llm_calls": sc["llm_calls"],
        "failure_class": sc["failure_class"],
        "ok": (sc["stop_reason"] == "llm_error" and sc["llm_calls"] == 1
               and sc["failure_class"] == "llm_error"),
    }

    results["_all_ok"] = all(v["ok"] for v in results.values() if isinstance(v, dict))
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_real_client(settings: Settings) -> Any:
    """The INNER client for real runs (run_task wraps it in the BudgetedClient
    with 15 s pacing); refuses to start without a key."""
    from src.agent.llm import (
        DEFAULT_E1_MAX_INPUT_BYTES,
        DEFAULT_E1_MAX_TOKENS,
        LLMClient,
    )

    if not settings.openai_api_key:
        raise SystemExit(
            "refusing to start a real run: no API key in settings "
            "(CALC_AGENT_ENV_FILE discipline; the key never enters the conversation)"
        )
    return LLMClient(
        settings,
        timeout=60.0,
        max_retries=0,
        max_tokens=DEFAULT_E1_MAX_TOKENS,
        max_input_bytes=DEFAULT_E1_MAX_INPUT_BYTES,
    )


async def _main_async(args: argparse.Namespace) -> None:
    if args.dryrun:
        results = await run_dryrun()
        print(json.dumps(results, indent=2, ensure_ascii=False))
        if args.out:
            Path(args.out).write_text(
                json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
        raise SystemExit(0 if results["_all_ok"] else 1)

    if args.provider != "real":
        raise SystemExit("only --dryrun runs without --provider real")
    if not args.authorize_budget:
        raise SystemExit(
            "real runs require explicit budget authorization (--authorize-budget); "
            "see docs/agent-evaluation/05-gemini-run-protocol.md"
        )

    run_id = args.run_id or "e1b-manual"
    out_root = REPO_ROOT / "data" / "e1-runs" / run_id
    settings = Settings()
    total_spent = [0.0]
    tasks = TASK_ORDER if args.all else [args.task]
    for task_id in tasks:
        guard = _make_guard(
            max_calls=args.max_calls,
            per_task_cost_cap=args.per_task_cost_cap,
            total_spent=total_spent,
            total_cost_stop=args.total_cost_stop,
            price_in_per_m=args.price_in,
            price_out_per_m=args.price_out,
        )
        inner = _build_real_client(settings)
        outcome = await run_task(
            task_id, run_id, inner, guard, out_root, "real",
            settings.llm_model, settings.llm_base_url, pacing_s=15.0,
        )
        sc = outcome["report"]["scenarios"][0]
        print(json.dumps({
            "task": task_id,
            "stop_reason": sc["stop_reason"],
            "success": sc["success"],
            "llm_calls": sc["llm_calls"],
            "cost_estimate_usd": sc["cost_estimate_usd"],
            "scored_path": str(Path(out_root) / task_id / "scored.json"),
            "total_spent_usd": round(total_spent[0], 4),
        }, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="E1-B evaluation runner")
    parser.add_argument("--dryrun", action="store_true",
                        help="zero-cost mock dry run (success/validation-failure/budget/api-error)")
    parser.add_argument("--task", choices=TASK_ORDER, default=None)
    parser.add_argument("--all", action="store_true", help="run all five tasks")
    parser.add_argument("--provider", choices=["mock", "real"], default="mock")
    parser.add_argument("--run-id", default=None, help="e.g. e1b-20261025")
    parser.add_argument("--authorize-budget", action="store_true",
                        help="required confirmation for --provider real")
    parser.add_argument("--max-calls", type=int, default=DEFAULT_MAX_CALLS)
    parser.add_argument("--per-task-cost-cap", type=float, default=DEFAULT_PER_TASK_COST_CAP)
    parser.add_argument("--total-cost-stop", type=float, default=DEFAULT_TOTAL_COST_STOP)
    parser.add_argument("--price-in", type=float, default=DEFAULT_PRICE_IN)
    parser.add_argument("--price-out", type=float, default=DEFAULT_PRICE_OUT)
    parser.add_argument("--out", default=None, help="write dry-run results JSON here")
    args = parser.parse_args()

    sys.path.insert(0, str(REPO_ROOT))
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
