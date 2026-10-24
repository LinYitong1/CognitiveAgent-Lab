"""Budget guard + budgeted client wrapper (E1-B preflight; no LLM, no network).

Semantics (the run protocol's honesty rules, executable):

  HARD pre-call guarantee
    - the per-task MODEL-CALL count cap: BudgetExceeded("budget-stop") is
      raised BEFORE the N+1-th call; the wrapper never issues it.

  Post-call accounting, checked before the NEXT call
    - cost is computed from provider-REPORTED usage only (never fabricated);
    - a call whose usage is missing is NOT counted as $0: the guard carries an
      explicit `unreported_calls` counter and, for stopping purposes only,
      assumes a conservative worst-case per-call cost (`assumed_worst_case_usd`)
      so unknown spend cannot silently bypass the cap. The REPORTED cost in
      the ledger stays exactly what providers reported (lower bound, marked).
    - per-task cap exceeded  -> BudgetExceeded("budget-stop-cost");
    - total stop exceeded    -> BudgetExceeded("budget-stop-total").

  What is and is NOT a hard cap (stated plainly)
    - with the client-side `max_tokens` and `max_input_bytes` ceilings set
      (src/agent/llm.py), each call's cost is bounded pre-call by construction:
      (input ceiling + max_tokens) x prices. The count cap times that bound is
      then a genuine worst-case total, and the cost thresholds trigger within
      it. Without those ceilings, only the count cap is pre-call hard and the
      cost caps are post-call stops (cap + at most one in-flight call).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Protocol

from src.models.llm import LLMResponse

Message = dict[str, Any]

REASON_CALL_CAP = "budget-stop"
REASON_TASK_COST = "budget-stop-cost"
REASON_TOTAL_COST = "budget-stop-total"


class BudgetExceeded(Exception):
    """Raised BEFORE a call when a budget boundary is crossed. The loop treats
    it as an unrecoverable failure; the runner reclassifies the run's
    stop_reason from the message (no AgentLoop change needed)."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


class BudgetGuard:
    """Per-task budget ledger: one guard per task; a separate total accumulator."""

    def __init__(
        self,
        max_calls: int,
        per_task_cost_cap: float | None = None,
        total_spent: list[float] | None = None,
        total_cost_stop: float | None = None,
        price_in_per_m: float = 0.75,
        price_out_per_m: float = 3.75,
        assumed_worst_case_usd: float = 0.05,
    ) -> None:
        self.max_calls = max_calls
        self.per_task_cost_cap = per_task_cost_cap
        self.total_spent = total_spent if total_spent is not None else [0.0]
        self.total_cost_stop = total_cost_stop
        self.price_in_per_m = price_in_per_m
        self.price_out_per_m = price_out_per_m
        self.assumed_worst_case_usd = assumed_worst_case_usd
        # ledger state
        self.calls = 0
        self.unreported_calls = 0
        self.usage_log: list[dict[str, int]] = []
        self.latencies_s: list[float] = []
        self.reported_cost_usd = 0.0
        self.cost_is_lower_bound = False

    # -- accounting ---------------------------------------------------------

    def call_cost(self, usage: dict[str, int]) -> float:
        """Billable cost of one call: input tokens at price_in, and
        (total - prompt) at price_out (thinking tokens are billed as output —
        the T5 reconciliation rule)."""
        prompt = usage.get("prompt_tokens", 0)
        total = usage.get("total_tokens", prompt + usage.get("completion_tokens", 0))
        billable_out = max(total - prompt, 0)
        return (prompt * self.price_in_per_m + billable_out * self.price_out_per_m) / 1_000_000

    @property
    def guard_cost_estimate_usd(self) -> float:
        """Stopping-purpose estimate: reported cost plus a conservative
        worst-case assumption for every unreported call (NEVER reported as the
        actual cost — that stays `reported_cost_usd`, a lower bound)."""
        return self.reported_cost_usd + self.unreported_calls * self.assumed_worst_case_usd

    def pre_call(self) -> None:
        """Raise before the next call if a budget boundary is crossed."""
        if self.calls >= self.max_calls:
            raise BudgetExceeded(
                REASON_CALL_CAP,
                f"{self.calls} calls reached the per-task cap of {self.max_calls}",
            )
        if self.per_task_cost_cap is not None and self.guard_cost_estimate_usd >= self.per_task_cost_cap:
            raise BudgetExceeded(
                REASON_TASK_COST,
                f"estimated ${self.guard_cost_estimate_usd:.4f} (reported "
                f"${self.reported_cost_usd:.4f} + {self.unreported_calls} unreported x "
                f"${self.assumed_worst_case_usd:.4f}) reached the per-task cap "
                f"${self.per_task_cost_cap}",
            )
        if self.total_cost_stop is not None and self.total_spent[0] >= self.total_cost_stop:
            raise BudgetExceeded(
                REASON_TOTAL_COST,
                f"total spent ${self.total_spent[0]:.4f} reached the evaluation stop "
                f"${self.total_cost_stop}",
            )

    def post_call(self, usage: dict[str, int] | None, latency_s: float) -> None:
        """Record one completed (or failed-but-billed) call."""
        self.calls += 1
        self.latencies_s.append(latency_s)
        if usage is None:
            self.unreported_calls += 1
            self.cost_is_lower_bound = True
            # still charge the conservative assumption into the shared total so
            # unknown spend cannot bypass the evaluation-level stop
            self.total_spent[0] += self.assumed_worst_case_usd
            return
        self.usage_log.append(usage)
        cost = self.call_cost(usage)
        self.reported_cost_usd += cost
        self.total_spent[0] += cost

    # -- reporting ----------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        tokens_in = sum(u.get("prompt_tokens", 0) for u in self.usage_log)
        tokens_total = sum(u.get("total_tokens", 0) for u in self.usage_log)
        return {
            "calls": self.calls,
            "unreported_usage_calls": self.unreported_calls,
            "usage_log": self.usage_log,
            "llm_latency_s": [round(x, 2) for x in self.latencies_s],
            "tokens_in": tokens_in,
            "tokens_total": tokens_total,
            "tokens_out_billable": max(tokens_total - tokens_in, 0),
            "cost_estimate_usd": round(self.reported_cost_usd, 4),
            "cost_is_lower_bound": self.cost_is_lower_bound,
            "guard_cost_estimate_usd": round(self.guard_cost_estimate_usd, 4),
        }


class _ChatLike(Protocol):
    async def chat(self, messages: list[Message], tools: list[dict[str, Any]]) -> LLMResponse: ...


class BudgetedClient:
    """LLMClientProtocol wrapper: enforces the guard around every chat call and
    (optionally) paces requests. The inner client's exceptions propagate
    unchanged; a failed call still counts as a billed attempt (usage unknown)."""

    def __init__(self, inner: _ChatLike, guard: BudgetGuard, pacing_s: float = 0.0) -> None:
        self._inner = inner
        self.guard = guard
        self._pacing_s = pacing_s

    async def chat(self, messages: list[Message], tools: list[dict[str, Any]]) -> LLMResponse:
        self.guard.pre_call()  # may raise BudgetExceeded (nothing sent)
        if self._pacing_s:
            await asyncio.sleep(self._pacing_s)
        started = time.perf_counter()
        try:
            response = await self._inner.chat(messages, tools)
        except BudgetExceeded:
            raise
        except Exception:
            self.guard.post_call(None, time.perf_counter() - started)
            raise
        self.guard.post_call(response.usage, time.perf_counter() - started)
        return response
