"""ToolRegistry: the sole runtime tool entry point; exceptions never escape (contract §1.2; M1-3)."""

from __future__ import annotations

import inspect
from typing import Any

from pydantic import BaseModel, ValidationError

from src.models.tool_result import ToolResult
from src.models.tool_spec import ToolSpec


class ToolRegistryError(Exception):
    """Registration-time validation failure (a startup error, not a runtime one)."""


# Deterministic error categories for observability (Foundation Hardening P1).
# Derived from the registry/tool error-string conventions below — no new
# exception system; the loop uses this to tag tool_result events.
TOOL_ERROR_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("unknown tool:", "unknown_tool"),
    ("invalid arguments:", "invalid_arguments"),
    ("tool execution failed:", "execution_failed"),
    ("BLOCKED:", "policy_blocked"),
)


def classify_tool_error(error: str) -> str:
    """Classify a ToolResult error string into a closed category set.

    Returns "unknown_tool" | "invalid_arguments" | "execution_failed" |
    "policy_blocked" | "other". Mirrors the prefixes produced by
    ``ToolRegistry.execute`` and the tools' unified ``BLOCKED:`` refusals —
    the prefixes are part of the frozen tool contract, so this mapping is
    deterministic, not heuristic.
    """
    for prefix, category in TOOL_ERROR_CATEGORIES:
        if error.startswith(prefix):
            return category
    return "other"


class ToolRegistry:
    """The tool registry."""

    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        """Validate and register; any validation failure raises ToolRegistryError."""
        if not spec.name:
            raise ToolRegistryError("tool name must be non-empty")
        if spec.name in self._specs:
            raise ToolRegistryError(f"duplicate tool name: {spec.name}")
        if not (isinstance(spec.input_model, type) and issubclass(spec.input_model, BaseModel)):
            raise ToolRegistryError(f"input_model must be a BaseModel subclass, got {spec.input_model!r}")
        if not callable(spec.executor) or not inspect.iscoroutinefunction(spec.executor):
            raise ToolRegistryError(f"executor must be an async callable, got {spec.executor!r}")
        self._specs[spec.name] = spec

    def get_schemas(self) -> list[dict[str, Any]]:
        """Export in OpenAI tools format (for the tools parameter of LLMClient.chat)."""
        return [
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.input_model.model_json_schema(),
                },
            }
            for spec in self._specs.values()
        ]

    async def execute(self, name: str, args: dict[str, Any]) -> ToolResult:
        """The sole runtime entry: every failure path returns ToolResult(ok=False); nothing escapes."""
        spec = self._specs.get(name)
        if spec is None:
            return ToolResult(ok=False, error=f"unknown tool: {name}")
        try:
            parsed = spec.input_model.model_validate(args)
        except ValidationError as exc:
            return ToolResult(ok=False, error=f"invalid arguments: {exc}"[:512])
        except Exception as exc:  # defensive: unexpected validation errors do not escape either
            return ToolResult(ok=False, error=f"invalid arguments: {exc}"[:512])
        try:
            return await spec.executor(parsed)
        except Exception as exc:
            return ToolResult(ok=False, error=f"tool execution failed: {type(exc).__name__}: {exc}"[:512])

    def get(self, name: str) -> ToolSpec | None:
        """Fetch a spec by name (reserved for tests and M2)."""
        return self._specs.get(name)
