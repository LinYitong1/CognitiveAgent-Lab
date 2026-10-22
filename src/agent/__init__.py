"""agent package assembly entry: build_registry (contract §4; the agent → tools direction is legal)."""

from __future__ import annotations

from src.agent.registry import ToolRegistry
from src.config import Settings
from src.tools import calc, file_read, file_write, http_request


def build_registry(settings: Settings) -> ToolRegistry:
    """Register the M1 tools (calc / http_request / file_write) + file_read (generic sandbox read)."""
    registry = ToolRegistry()
    registry.register(calc.build_tool_spec(settings))
    registry.register(http_request.build_tool_spec(settings))
    registry.register(file_write.build_tool_spec(settings))
    registry.register(file_read.build_tool_spec(settings))
    return registry
