"""公开事件模型（契约 §1.0；ARCHITECTURE §3.1 / ADR-006，无 thought）。"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class AgentEventType(str, Enum):
    """公开事件类型完整枚举。"""

    status = "status"
    tool_call = "tool_call"
    tool_result = "tool_result"
    error = "error"
    final = "final"


class AgentEvent(BaseModel):
    """单条公开事件。"""

    type: AgentEventType
    seq: int  # 任务级单调递增，从 1 开始
    ts: datetime  # UTC
    payload: dict[str, object] = Field(default_factory=dict)
