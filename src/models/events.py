"""Public event models (contract §1.0; ARCHITECTURE §3.1 / ADR-006; no thought events)."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class AgentEventType(str, Enum):
    """Complete enumeration of public event types."""

    status = "status"
    tool_call = "tool_call"
    tool_result = "tool_result"
    error = "error"
    final = "final"


class AgentEvent(BaseModel):
    """One public event."""

    type: AgentEventType
    seq: int  # task-level monotonically increasing, starting at 1
    ts: datetime  # UTC
    payload: dict[str, object] = Field(default_factory=dict)
