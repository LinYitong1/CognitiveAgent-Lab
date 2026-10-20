"""agent 包组装入口：build_registry（契约 §4，agent → tools 方向合法）。"""

from __future__ import annotations

from src.agent.registry import ToolRegistry
from src.config import Settings
from src.tools import calc, file_write, http_request


def build_registry(settings: Settings) -> ToolRegistry:
    """注册 M1 三工具（calc / http_request / file_write）。"""
    registry = ToolRegistry()
    registry.register(calc.build_tool_spec(settings))
    registry.register(http_request.build_tool_spec(settings))
    registry.register(file_write.build_tool_spec(settings))
    return registry
