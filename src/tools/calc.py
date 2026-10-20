"""calc 工具：AST 白名单安全表达式计算（契约 §2.1；ARCHITECTURE §6.1 / ADR-005）。

全程禁用 eval/exec/compile 字符串执行——求值为自实现 AST 递归求值器。
"""

from __future__ import annotations

import ast
import math
from typing import Any, Callable, cast

from pydantic import BaseModel, Field

from src.config import Settings
from src.models.tool_result import ToolResult
from src.models.tool_spec import ToolSpec

MAX_DEPTH = 20  # AST 嵌套深度上限

_ALLOWED_BINOPS: tuple[type[ast.operator], ...] = (
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow,
)
_ALLOWED_UNARYOPS: tuple[type[ast.unaryop], ...] = (ast.UAdd, ast.USub)

# 函数白名单：名 → (实现, (最少元数, 最多元数或 None 表示不限))
_FUNCTIONS: dict[str, tuple[Callable[..., Any], tuple[int, int | None]]] = {
    "abs": (abs, (1, 1)),
    "min": (min, (2, None)),
    "max": (max, (2, None)),
    "round": (round, (1, 2)),
    "sqrt": (math.sqrt, (1, 1)),
    "pow": (pow, (2, 2)),
}

_MAX_POW_EXPONENT = 1000  # Pow 指数绝对值上限


class _CalcBlocked(Exception):
    """安全拒绝（→ BLOCKED: 前缀）。"""


class _CalcOutOfRange(Exception):
    """数学越界（指数过大/复数/inf）。"""


def _power(left: int | float, right: int | float) -> int | float:
    """Pow 统一检查：指数绝对值上限、复数/inf 结果拦截（BinOp 与 pow() 函数共用）。"""
    if abs(right) > _MAX_POW_EXPONENT:
        raise _CalcOutOfRange
    value = left**right
    if isinstance(value, complex) or (isinstance(value, float) and math.isinf(value)):
        raise _CalcOutOfRange
    return value


class CalcInput(BaseModel):
    """calc 参数。"""

    expression: str = Field(min_length=1, max_length=200)


def _paren_depth(expression: str) -> int:
    """括号最大嵌套深度（括号不产生 AST 节点，需单独计数）。"""
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
    """白名单递归求值器：凡不在白名单的节点一律拒绝。"""
    if depth > MAX_DEPTH:
        raise _CalcBlocked("expression too deep")
    if isinstance(node, ast.Expression):
        return _eval(node.body, depth)
    if isinstance(node, ast.Constant):
        # bool 是 int 子类，显式排除；字符串/None 拒绝
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
            return left / right  # 除零由 ZeroDivisionError 路径处理
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
    # 凡不在白名单：Name、Attribute、Subscript、Lambda、Compare、BoolOp、IfExp、
    # Tuple/List/Set/Dict、推导式等一律拒绝
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
    """BaseModel 入口包装（registry 统一调用签名）。"""
    return await _execute(cast(CalcInput, base))


def build_tool_spec(settings: Settings) -> ToolSpec:
    """构造 calc 的 ToolSpec（settings 保留统一签名，calc 无配置项）。"""
    return ToolSpec(
        name="calc",
        description="计算算术表达式，支持 + - * / % ** 与函数 abs/min/max/round/sqrt/pow",
        input_model=CalcInput,
        idempotency="idempotent",
        risk_level="low",
        executor=_executor,
    )
