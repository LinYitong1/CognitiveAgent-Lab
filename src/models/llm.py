"""Shared LLM interaction models (contract §1.0)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ToolCallRequest(BaseModel):
    """One tool call returned by the LLM (unified structure, isolating provider formats)."""

    remote_id: str  # provider-side id (OpenAI tool_call.id; FakeLLM makes up e.g. "fake-0")
    tool_name: str
    arguments: dict[str, object] = Field(default_factory=dict)
    # opaque provider extensions that MUST round-trip in the conversation history
    # (e.g. Gemini 3.x thought_signature under extra_content.google) — None for
    # providers without such fields; never interpreted by the loop, only echoed back
    provider_extra: dict[str, object] | None = None


class LLMResponse(BaseModel):
    """Unified return of LLMClient.chat."""

    content: str = ""  # model text (internal reasoning — never written to any event/JSONL, ADR-006)
    tool_calls: list[ToolCallRequest] = Field(default_factory=list)
    finish_reason: str = "stop"  # "tool_calls" | "stop" | other provider values
    # provider-reported token usage for this call when available (None for FakeLLM) —
    # observability only (quota accounting); never interpreted by the loop
    usage: dict[str, int] | None = None
