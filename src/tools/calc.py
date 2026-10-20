"""calc tool: AST-whitelist safe expression evaluation (contract §2.1; ARCHITECTURE §6.1 / ADR-005).

eval/exec/compile string execution is banned throughout — evaluation is a hand-written recursive AST evaluator.
"""

from __future__ import annotations

import ast
import math
from typing import Any, Callable, cast

from pydantic import BaseModel, Field

from src.config import Settings
from src.models.tool_result import ToolResult
from src.models.tool_spec import ToolSpec

MAX_DEPTH = 20  # AST nesting depth limit

_ALLOWED_BINOPS: tuple[type[ast.operator], ...] = (
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow,
)
_ALLOWED_UNARYOPS: tuple[type[ast.unaryop], ...] = (ast.UAdd, ast.USub)

# Function whitelist: name → (implementation, (min arity, max arity or None for unlimited))
_FUNCTIONS: dict[str, tuple[Callable[..., Any], tuple[int, int | None]]] = {
    "abs": (abs, (1, 1)),
    "min": (min, (2, None)),
    "max": (max, (2, None)),
    "round": (round, (1, 2)),
    "sqrt": (math.sqrt, (1, 1)),
    "pow": (pow, (2, 2)),
}

_MAX_POW_EXPONENT = 1000  # absolute-value limit for Pow exponents


class _CalcBlocked(Exception):
    """Security refusal (→ BLOCKED: prefix)."""


class _CalcOutOfRange(Exception):
    """Math out of range (oversized exponent / complex / inf)."""


def _power(left: int | float, right: int | float) -> int | float:
    """Unified Pow check: exponent absolute-value limit, complex/inf result interception (shared by BinOp and the pow() function)."""
    if abs(right) > _MAX_POW_EXPONENT:
        raise _CalcOutOfRange
    value = left**right
    if isinstance(value, complex) or (isinstance(value, float) and math.isinf(value)):
        raise _CalcOutOfRange
    return value


class CalcInput(BaseModel):
    """calc arguments."""

    expression: str = Field(min_length=1, max_length=200)


def _paren_depth(expression: str) -> int:
    """Maximum parenthesis nesting depth (parentheses produce no AST node, counted separately)."""
    depth = 0
    max_depth = 0
    for ch in expression:
        if ch == "(":
            depth += 1
            max_depth = max(max_depth, depth)
        elif ch == ")":
            depth -= 1
    return max_depth


def _eval(node: ast.AST, depth: int) -> int | float:
    """Whitelist recursive evaluator: any node not in the whitelist is rejected."""
    if depth > MAX_DEPTH:
        raise _CalcBlocked("expression too deep")
    if isinstance(node, ast.Expression):
        return _eval(node.body, depth)
    if isinstance(node, ast.Constant):
        # bool is an int subclass, excluded explicitly; strings/None rejected
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise _CalcBlocked(f"constant not allowed: {node.value!r}")
        return node.value
    if isinstance(node, ast.BinOp):
        if not isinstance(node.op, _ALLOWED_BINOPS):
            raise _CalcBlocked(f"operator not allowed: {type(node.op).__name__}")
        left = _eval(node.left, depth + 1)
        right = _eval(node.right, depth + 1)
        op = node.op
        if isinstance(op, ast.Add):
            return left + right
        if isinstance(op, ast.Sub):
            return left - right
        if isinstance(op, ast.Mult):
            return left * right
        if isinstance(op, ast.Div):
            return left / right  # division by zero handled by the ZeroDivisionError path
        if isinstance(op, ast.Mod):
            return left % right
        if isinstance(op, ast.Pow):
            return _power(left, right)
        raise _CalcBlocked(f"operator not allowed: {type(op).__name__}")
    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, _ALLOWED_UNARYOPS):
            raise _CalcBlocked(f"unary operator not allowed: {type(node.op).__name__}")
        value = _eval(node.operand, depth + 1)
        if isinstance(node.op, ast.UAdd):
            return +value
        return -value
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCTIONS:
            raise _CalcBlocked("only whitelisted functions may be called")
        if node.keywords:
            raise _CalcBlocked("keyword arguments not allowed")
        if any(isinstance(arg, ast.Starred) for arg in node.args):
            raise _CalcBlocked("star args not allowed")
        func, (min_arity, max_arity) = _FUNCTIONS[node.func.id]
        if len(node.args) < min_arity or (max_arity is not None and len(node.args) > max_arity):
            raise _CalcBlocked(f"invalid arity for {node.func.id}: {len(node.args)}")
        args = [_eval(arg, depth + 1) for arg in node.args]
        if node.func.id == "pow" and len(args) == 2:
            return _power(args[0], args[1])
        return func(*args)
    # Anything not in the whitelist: Name, Attribute, Subscript, Lambda, Compare, BoolOp, IfExp,
    # Tuple/List/Set/Dict, comprehensions, etc. are all rejected
    raise _CalcBlocked(f"node not allowed: {type(node).__name__}")


async def _execute(args: CalcInput) -> ToolResult:
    expression = args.expression
    if _paren_depth(expression) > MAX_DEPTH:
        return ToolResult(ok=False, error="BLOCKED: expression too deep")
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return ToolResult(ok=False, error="BLOCKED: invalid expression")
    try:
        value = _eval(tree, 1)
        text = repr(value) if isinstance(value, float) else str(value)
    except _CalcBlocked as exc:
        return ToolResult(ok=False, error=f"BLOCKED: {exc}")
    except _CalcOutOfRange:
        return ToolResult(ok=False, error="calc: result out of range")
    except ZeroDivisionError:
        return ToolResult(ok=False, error="calc: division by zero")
    except (ValueError, OverflowError):
        return ToolResult(ok=False, error="calc: math domain error")
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return ToolResult(ok=False, error="calc: result out of range")
    return ToolResult(ok=True, result=text)


async def _executor(base: Any) -> ToolResult:
    """BaseModel entry wrapper (unified registry call signature)."""
    return await _execute(cast(CalcInput, base))


def build_tool_spec(settings: Settings) -> ToolSpec:
    """Build calc's ToolSpec (settings keeps the unified signature; calc has no configuration)."""
    return ToolSpec(
        name="calc",
        description="Evaluate an arithmetic expression; supports + - * / % ** and the functions abs/min/max/round/sqrt/pow",
        input_model=CalcInput,
        idempotency="idempotent",
        risk_level="low",
        executor=_executor,
    )
