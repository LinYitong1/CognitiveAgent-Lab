"""M1-5 calc unit tests (contract §3.2; matched by -k tool_security)."""

from __future__ import annotations

import pytest

from src.agent.registry import ToolRegistry
from src.config import Settings
from src.models.tool_result import ToolResult
from src.tools import calc


async def _run(expression: str) -> ToolResult:
    spec = calc.build_tool_spec(Settings())
    return await spec.executor(calc.CalcInput(expression=expression))


@pytest.mark.asyncio
@pytest.mark.tool_security
async def test_calc_evaluates_expression() -> None:
    plain = await _run("1+2*3")
    assert plain.ok and plain.result == "7"

    division = await _run("(123*456)/7")
    assert division.ok and float(division.result) == 56088 / 7

    sqrt2 = await _run("sqrt(2)")
    assert sqrt2.ok and abs(float(sqrt2.result) - 1.41421356) < 1e-6

    power = await _run("pow(2,10)")
    assert power.ok and power.result == "1024"

    unary = await _run("-5 + +3")
    assert unary.ok and unary.result == "-2"

    funcs = await _run("min(abs(-3), max(1, 2))")
    assert funcs.ok and funcs.result == "2"


@pytest.mark.asyncio
@pytest.mark.tool_security
async def test_calc_rejects_name_injection() -> None:
    for expression in [
        "__import__('os').system('id')",
        "open('/etc/passwd')",
        "x",
        "True",
        "abc",
    ]:
        result = await _run(expression)
        assert not result.ok, f"should be rejected: {expression}"
        assert "BLOCKED" in result.error, f"expected BLOCKED for: {expression}"


@pytest.mark.asyncio
@pytest.mark.tool_security
async def test_calc_rejects_attribute_and_lambda() -> None:
    for expression in [
        "''.join([])",
        "(lambda: 1)()",
        "[1,2][0]",
        "a if b else c",
    ]:
        result = await _run(expression)
        assert not result.ok, f"should be rejected: {expression}"
        assert "BLOCKED" in result.error, f"expected BLOCKED for: {expression}"


@pytest.mark.asyncio
@pytest.mark.tool_security
async def test_calc_rejects_depth_and_length() -> None:
    # length > 200: rejected at the parameter-validation layer (via the registry unified entry)
    registry = ToolRegistry()
    registry.register(calc.build_tool_spec(Settings()))
    too_long = await registry.execute("calc", {"expression": "1+" * 110 + "1"})  # 221 characters
    assert not too_long.ok
    assert "invalid arguments" in too_long.error

    # parenthesis nesting depth > 20
    paren = await _run("(" * 25 + "1" + ")" * 25)
    assert not paren.ok and "BLOCKED" in paren.error

    # structural AST depth > 20 (left-associative operator chain)
    deep = await _run("1+" * 21 + "1")  # depth 22
    assert not deep.ok and "BLOCKED" in deep.error


@pytest.mark.asyncio
@pytest.mark.tool_security
async def test_calc_math_errors() -> None:
    division = await _run("1/0")
    assert not division.ok
    assert division.error == "calc: division by zero"
    assert "BLOCKED" not in division.error

    overflow = await _run("pow(10,10000)")
    assert not overflow.ok
    assert overflow.error == "calc: result out of range"
    assert "BLOCKED" not in overflow.error

    domain = await _run("sqrt(-1)")
    assert not domain.ok
    assert "BLOCKED" not in domain.error
