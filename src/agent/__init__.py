"""agent package assembly entry: build_registry (contract §4; the agent → tools direction is legal)."""

from __future__ import annotations

from src.agent.registry import ToolRegistry
from src.config import Settings
from src.tools import calc, file_write, http_request


def build_registry(settings: Settings) -> ToolRegistry:
    """Register the three M1 tools (calc / http_request / file_write)."""
    registry = ToolRegistry()
    registry.register(calc.build_tool_spec(settings))
    registry.register(http_request.build_tool_spec(settings))
    registry.register(file_write.build_tool_spec(settings))
    return registry
