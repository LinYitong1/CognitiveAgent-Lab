"""ToolRegistry：运行期唯一工具入口，异常不外抛（契约 §1.2；M1-3）。"""

from __future__ import annotations

import inspect
from typing import Any

from pydantic import BaseModel, ValidationError

from src.models.tool_result import ToolResult
from src.models.tool_spec import ToolSpec


class ToolRegistryError(Exception):
    """注册期校验失败（启动期错误，非运行期）。"""


class ToolRegistry:
    """工具注册表。"""

    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        """校验并登记；任何校验失败抛 ToolRegistryError。"""
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
        """导出 OpenAI tools 格式（供 LLMClient.chat 的 tools 参数）。"""
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
        """运行期唯一入口：任何失败路径都返回 ToolResult(ok=False)，不外抛异常。"""
        spec = self._specs.get(name)
        if spec is None:
            return ToolResult(ok=False, error=f"unknown tool: {name}")
        try:
            parsed = spec.input_model.model_validate(args)
        except ValidationError as exc:
            return ToolResult(ok=False, error=f"invalid arguments: {exc}"[:512])
        except Exception as exc:  # 防御：非预期校验错误也不外抛
            return ToolResult(ok=False, error=f"invalid arguments: {exc}"[:512])
        try:
            return await spec.executor(parsed)
        except Exception as exc:
            return ToolResult(ok=False, error=f"tool execution failed: {type(exc).__name__}: {exc}"[:512])

    def get(self, name: str) -> ToolSpec | None:
        """按名取 spec（测试与 M2 预留）。"""
        return self._specs.get(name)
