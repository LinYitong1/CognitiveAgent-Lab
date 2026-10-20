"""Unified tool return (contract §1.0; tool exceptions never escape to the loop, M1-3)."""

from __future__ import annotations

from pydantic import BaseModel


class ToolResult(BaseModel):
    """Tool execution result."""

    ok: bool
    result: str = ""  # result text on success (sent back to the LLM)
    error: str = ""  # failure reason (sent back to the LLM); security refusals use the unified "BLOCKED: " prefix
