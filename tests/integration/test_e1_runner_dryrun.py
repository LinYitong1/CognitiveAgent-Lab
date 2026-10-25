"""E1-B runner dry-run regression tests (zero paid calls, zero network).

Invokes the real dry-run (real AgentLoop + real 9-tool registry + real scorer;
only the LLM is a MockLLM) and pins the four required outcomes plus the
usage-missing guard scenario.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from scripts.e1_runner import run_dryrun

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_dryrun_all_scenarios_ok() -> None:
    results = asyncio.run(run_dryrun())
    assert results["_all_ok"] is True, json.dumps(results, indent=2, ensure_ascii=False)

    # 1. success: completed run, artifacts produced, independently scored
    succ = results["success"]
    assert succ["stop_reason"] == "model_final_answer"
    assert (succ["D1"], succ["D3"], succ["D6"]) == ("PASS", "PASS", "PASS")

    # 2. validation failure: model claims success without artifacts
    vf = results["validation_failure"]
    assert vf["failure_class"] == "no-artifacts"
    assert vf["D1"] == "FAIL"

    # 3. budget stop (call cap): pre-call hard stop, distinct reason
    bc = results["budget_call_cap"]
    assert bc["stop_reason"] == "budget-stop"
    assert bc["llm_calls"] == 3

    # 4. budget stop (cost cap): post-call accounting stops the next call
    bcc = results["budget_cost_cap"]
    assert bcc["stop_reason"] == "budget-stop-cost"
    assert bcc["llm_calls"] == 1

    # 5. missing usage: never counted as $0; conservative guard; marked lower bound
    um = results["usage_missing"]
    assert um["stop_reason"] == "budget-stop-cost"
    assert um["llm_calls"] == 2
    assert um["cost_estimate_usd"] == 0.0
    assert um["cost_is_lower_bound"] is True

    # 6. API error: clean failure, the failed call still counted as billed
    ae = results["api_error"]
    assert ae["stop_reason"] == "llm_error"
    assert ae["llm_calls"] == 1


def test_dryrun_artifacts_retained() -> None:
    """Every scenario sandbox retains its report/scored JSON (the protocol's
    artifact-retention rule), even for failed runs."""
    root = REPO_ROOT / "data" / ".test-sandbox" / "e1-dryrun"
    asyncio.run(run_dryrun())
    for scenario in ("success", "validation-failure", "budget-call-cap",
                     "budget-cost-cap", "usage-missing", "api-error"):
        sandbox = root / scenario / "e1_t5_retest"
        assert (sandbox / "run-report.json").is_file(), scenario
        assert (sandbox / "scored.json").is_file(), scenario
        assert (sandbox / "brief.txt").is_file(), scenario
    # the success sandbox additionally holds the produced artifacts
    ok_sandbox = root / "success" / "e1_t5_retest"
    assert (ok_sandbox / "experiments" / "dryrun.json").is_file()
    assert (ok_sandbox / "games" / "dryrun.html").is_file()
    report = json.loads((ok_sandbox / "run-report.json").read_text(encoding="utf-8"))
    assert report["briefs_version"] == "e1-briefs-v1"
    assert report["scenarios"][0]["artifacts"]["html"] == "games/dryrun.html"
    # the report self-documents the executing baseline (commit + dirty flag)
    assert isinstance(report["commit"], str) and len(report["commit"]) >= 7
    assert isinstance(report["commit_dirty"], bool)


def test_sandbox_reuse_refused() -> None:
    """A non-empty sandbox refuses a second run (no state reuse)."""
    import shutil

    import pytest

    from scripts.e1_runner import _sandbox_for

    root = REPO_ROOT / "data" / ".test-sandbox" / "e1-dryrun-reuse"
    if root.exists():
        shutil.rmtree(root)  # keep the test idempotent across suite re-runs
    sandbox = _sandbox_for(root, "task-x")
    (sandbox / "stale.txt").write_text("x", encoding="utf-8")
    with pytest.raises(SystemExit, match="not empty"):
        _sandbox_for(root, "task-x")
