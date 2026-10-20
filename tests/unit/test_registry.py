"""registry 注册期校验与 schema 导出测试（qa-M1.md §三建议：缓解 agent/ 勉强过线的脆弱性）。"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from src.agent.registry import ToolRegistry, ToolRegistryError
from src.models.tool_result import ToolResult
from src.models.tool_spec import ToolSpec


class DummyInput(BaseModel):
    """测试用参数模型。"""

    value: int = 0


async def _dummy_executor(args: BaseModel) -> ToolResult:
    """测试用 async executor。"""
    return ToolResult(ok=True, result="ok")


def _spec(**overrides: object) -> ToolSpec:
    """构造合法 ToolSpec，按参数覆写。"""
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
    def sync_executor(args: BaseModel) -> ToolResult:  # 非 async callable
        return ToolResult(ok=True)

    registry = ToolRegistry()
    with pytest.raises(ToolRegistryError, match="async"):
        registry.register(_spec(executor=sync_executor))


def test_registry_rejects_non_basemodel_input() -> None:
    """非 BaseModel 的 input_model 在 ToolSpec 构造期即被 pydantic 拒绝（第一道防线，
    registry.register 的 issubclass 校验为第二道防线——对 pydantic 类型系统不可达）。"""
    registry = ToolRegistry()
    with pytest.raises(ValidationError):
        registry.register(_spec(input_model=int))


def test_tool_spec_literal_validation() -> None:
    """idempotency/risk_level 为 Literal——非法值在构造期即失败（契约 §1.2）。"""
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
