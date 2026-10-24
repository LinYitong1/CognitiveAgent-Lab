"""Agent task result models (contract §1.0)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.models.events import AgentEvent


class AgentResult(BaseModel):
    """Return value of run_task."""

    task_id: str
    status: str  # "completed" | "failed"
    result: str  # final answer (completed) or failure reason (failed)
    steps: int  # LLM rounds actually consumed
    events: list[AgentEvent] = Field(default_factory=list)  # full event sequence (matches the JSONL)
    # structured termination cause (Foundation Hardening P1): disambiguates the
    # binary status without changing it — closed set:
    #   "model_final_answer" | "max_steps_exceeded" | "llm_error" | "" (legacy/absent)
    termination_reason: str = ""
    # cumulative provider-reported token usage over the run (None when the
    # provider never reported usage — never fabricated; observability only)
    usage: dict[str, int] | None = None
