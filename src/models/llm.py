"""Shared LLM interaction models (contract §1.0)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ToolCallRequest(BaseModel):
    """One tool call returned by the LLM (unified structure, isolating provider formats)."""

    remote_id: str  # provider-side id (OpenAI tool_call.id; FakeLLM makes up e.g. "fake-0")
    tool_name: str
    arguments: dict[str, object] = Field(default_factory=dict)


class LLMResponse(BaseModel):
    """Unified return of LLMClient.chat."""

    content: str = ""  # model text (internal reasoning — never written to any event/JSONL, ADR-006)
    tool_calls: list[ToolCallRequest] = Field(default_factory=list)
    finish_reason: str = "stop"  # "tool_calls" | "stop" | other provider values
