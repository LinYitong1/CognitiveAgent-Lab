"""Registry registration-time validation and schema-export tests (qa-M1.md §3 suggestion: mitigating the fragility of agent/ barely passing)."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from src.agent.registry import ToolRegistry, ToolRegistryError
from src.models.tool_result import ToolResult
from src.models.tool_spec import ToolSpec


class DummyInput(BaseModel):
    """A parameter model for tests."""

    value: int = 0


async def _dummy_executor(args: BaseModel) -> ToolResult:
    """An async executor for tests."""
    return ToolResult(ok=True, result="ok")


def _spec(**overrides: object) -> ToolSpec:
    """Build a legal ToolSpec, overriding per arguments."""
    params: dict[str, object] = {
        "name": "dummy",
        "description": "dummy tool for registry tests",
        "input_model": DummyInput,
        "idempotency": "idempotent",
        "risk_level": "low",
        "executor": _dummy_executor,
    }
    params.update(overrides)
    return ToolSpec(**params)  # type: ignore[arg-type]


def test_registry_rejects_empty_name() -> None:
    registry = ToolRegistry()
    with pytest.raises(ToolRegistryError, match="non-empty"):
        registry.register(_spec(name=""))


def test_registry_rejects_duplicate_name() -> None:
    registry = ToolRegistry()
    registry.register(_spec(name="dummy"))
    with pytest.raises(ToolRegistryError, match="duplicate"):
        registry.register(_spec(name="dummy"))


def test_registry_rejects_non_async_executor() -> None:
    def sync_executor(args: BaseModel) -> ToolResult:  # a non-async callable
        return ToolResult(ok=True)

    registry = ToolRegistry()
    with pytest.raises(ToolRegistryError, match="async"):
        registry.register(_spec(executor=sync_executor))


def test_registry_rejects_non_basemodel_input() -> None:
    """A non-BaseModel input_model is rejected by pydantic at ToolSpec construction (the first line of
    defense); the registry.register issubclass check is the second — unreachable for pydantic types."""
    registry = ToolRegistry()
    with pytest.raises(ValidationError):
        registry.register(_spec(input_model=int))


def test_tool_spec_literal_validation() -> None:
    """idempotency/risk_level are Literals — invalid values fail at construction (contract §1.2)."""
    with pytest.raises(ValidationError):
        _spec(idempotency="sometimes")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        _spec(risk_level="extreme")  # type: ignore[arg-type]


def test_registry_get_schemas_format() -> None:
    registry = ToolRegistry()
    registry.register(_spec())
    schemas = registry.get_schemas()
    assert len(schemas) == 1
    entry = schemas[0]
    assert entry["type"] == "function"
    function = entry["function"]
    assert function["name"] == "dummy"
    assert function["description"] == "dummy tool for registry tests"
    assert function["parameters"] == DummyInput.model_json_schema()
