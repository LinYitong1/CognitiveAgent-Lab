"""Budget guard tests (E1-B preflight; zero paid calls, zero network).

Pins the protocol's budget semantics:
  - the CALL-COUNT cap is a pre-call hard stop (distinct reason);
  - cost caps are post-call accounting checked before the NEXT call (distinct reason);
  - missing usage is never counted as $0 for stopping purposes (conservative
    worst-case assumption; the reported cost stays a marked lower bound);
  - insufficient budget stops with a clear reason instead of proceeding;
  - the shared total stop halts a second task's guard;
  - failed (exception) calls still count as billed attempts;
  - pacing does not alter the guard semantics.
"""

from __future__ import annotations

import pytest

from scripts.e1_budget import (
    REASON_CALL_CAP,
    REASON_TASK_COST,
    REASON_TOTAL_COST,
    BudgetExceeded,
    BudgetGuard,
    BudgetedClient,
)
from src.models.llm import LLMResponse


def _resp(usage: dict[str, int] | None) -> LLMResponse:
    return LLMResponse(content="ok", finish_reason="stop", usage=usage)


class _ScriptedInner:
    def __init__(self, outcomes: list[object]) -> None:
        self._outcomes = list(outcomes)
        self.calls = 0

    async def chat(self, messages, tools):  # type: ignore[no-untyped-def]
        self.calls += 1
        item = self._outcomes.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.mark.asyncio
async def test_call_count_cap_is_precall_hard_stop() -> None:
    guard = BudgetGuard(max_calls=3)
    inner = _ScriptedInner([_resp({"prompt_tokens": 10, "total_tokens": 20})] * 10)
    client = BudgetedClient(inner, guard)
    for _ in range(3):
        await client.chat([{"role": "user", "content": "x"}], [])
    with pytest.raises(BudgetExceeded) as exc:
        await client.chat([{"role": "user", "content": "x"}], [])
    assert exc.value.reason == REASON_CALL_CAP
    assert inner.calls == 3, "the capped call must never reach the provider"


@pytest.mark.asyncio
async def test_cost_cap_stops_before_next_call() -> None:
    # one reported call costs ~$0.86 (1M in + ~0 out) -> over a $0.50 cap
    guard = BudgetGuard(max_calls=16, per_task_cost_cap=0.50)
    inner = _ScriptedInner([
        _resp({"prompt_tokens": 1_000_000, "total_tokens": 1_000_100}),
        _resp({"prompt_tokens": 10, "total_tokens": 20}),
    ])
    client = BudgetedClient(inner, guard)
    await client.chat([{"role": "user", "content": "x"}], [])
    with pytest.raises(BudgetExceeded) as exc:
        await client.chat([{"role": "user", "content": "x"}], [])
    assert exc.value.reason == REASON_TASK_COST
    assert inner.calls == 1


@pytest.mark.asyncio
async def test_missing_usage_not_counted_as_zero() -> None:
    # two unreported calls at $0.05 assumed each reach the $0.10 cap, so the
    # THIRD call is refused; the REPORTED cost stays 0.0 (marked lower bound)
    guard = BudgetGuard(max_calls=16, per_task_cost_cap=0.10, assumed_worst_case_usd=0.05)
    inner = _ScriptedInner([_resp(None)] * 10)
    client = BudgetedClient(inner, guard)
    await client.chat([{"role": "user", "content": "x"}], [])
    await client.chat([{"role": "user", "content": "x"}], [])
    with pytest.raises(BudgetExceeded) as exc:
        await client.chat([{"role": "user", "content": "x"}], [])
    assert exc.value.reason == REASON_TASK_COST
    summary = guard.summary()
    assert summary["calls"] == 2
    assert summary["cost_estimate_usd"] == 0.0  # reported only — never fabricated
    assert summary["cost_is_lower_bound"] is True
    assert summary["unreported_usage_calls"] == 2
    assert summary["guard_cost_estimate_usd"] == 0.10


@pytest.mark.asyncio
async def test_insufficient_budget_stops_immediately() -> None:
    guard = BudgetGuard(max_calls=16, per_task_cost_cap=0.01)
    guard.post_call({"prompt_tokens": 1_000_000, "total_tokens": 1_000_050}, 0.1)
    inner = _ScriptedInner([])
    client = BudgetedClient(inner, guard)
    with pytest.raises(BudgetExceeded) as exc:
        await client.chat([{"role": "user", "content": "x"}], [])
    assert exc.value.reason == REASON_TASK_COST
    assert inner.calls == 0


@pytest.mark.asyncio
async def test_shared_total_stop_halts_next_task() -> None:
    total = [2.00]
    guard1 = BudgetGuard(max_calls=2, total_spent=total, total_cost_stop=2.00)
    guard1.post_call({"prompt_tokens": 2_000_000, "total_tokens": 2_000_100}, 0.1)
    guard2 = BudgetGuard(max_calls=16, total_spent=total, total_cost_stop=2.00)
    inner = _ScriptedInner([])
    client = BudgetedClient(inner, guard2)
    with pytest.raises(BudgetExceeded) as exc:
        await client.chat([{"role": "user", "content": "x"}], [])
    assert exc.value.reason == REASON_TOTAL_COST


@pytest.mark.asyncio
async def test_failed_call_counts_as_billed_attempt() -> None:
    guard = BudgetGuard(max_calls=2, per_task_cost_cap=0.20, assumed_worst_case_usd=0.05)
    inner = _ScriptedInner([RuntimeError("connection reset"), _resp(None)])
    client = BudgetedClient(inner, guard)
    with pytest.raises(RuntimeError):
        await client.chat([{"role": "user", "content": "x"}], [])
    assert guard.calls == 1
    assert guard.unreported_calls == 1
    # the third attempt is refused by the call cap (2 reached)
    with pytest.raises(BudgetExceeded) as exc:
        await client.chat([{"role": "user", "content": "x"}], [])
        await client.chat([{"role": "user", "content": "x"}], [])
    assert exc.value.reason == REASON_CALL_CAP


def test_call_cost_uses_billable_output_rule() -> None:
    guard = BudgetGuard(max_calls=1)
    cost = guard.call_cost({"prompt_tokens": 9_000, "completion_tokens": 1_000,
                            "total_tokens": 10_000, "reasoning_tokens": 1_673})
    # thinking tokens ride inside total-prompt (the T5 reconciliation):
    # 9000 * 0.75/M + (10000-9000) * 3.75/M
    assert abs(cost - (0.00675 + 0.00375)) < 1e-9


def test_summary_shape() -> None:
    guard = BudgetGuard(max_calls=16)
    guard.post_call({"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}, 0.5)
    guard.post_call({"prompt_tokens": 200, "completion_tokens": 30, "total_tokens": 230}, 0.6)
    s = guard.summary()
    assert s["calls"] == 2 and s["tokens_in"] == 300 and s["tokens_total"] == 350
    assert s["tokens_out_billable"] == 50
    assert s["cost_is_lower_bound"] is False
    assert len(s["llm_latency_s"]) == 2
