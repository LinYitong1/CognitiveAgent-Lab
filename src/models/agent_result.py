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
