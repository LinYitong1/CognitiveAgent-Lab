"""PA-12 分层/依赖/安全静态守卫测试（契约 §7；-k "layers or static_guard" 命中）。

import 检查基于 AST（只看真实 import 语句，docstring 中的说明文字不误报）。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from scripts.check_layers import LAYER_ORDER, check

PROJECT_ROOT = Path(__file__).resolve().parents[3]
EXPERIMENT_DIR = PROJECT_ROOT / "src" / "experiment"
EXPERIMENT_SOURCES = sorted(EXPERIMENT_DIR.glob("*.py"))
EXPERIMENT_TOOLS = PROJECT_ROOT / "src" / "tools" / "experiment_tools.py"

# 只允许 random.Random 实例方法——禁止模块级 random.* 函数（§3.2）
_RANDOM_MODULE_FUNC_RE = re.compile(r"random\.(?!Random\b)")

_FORBIDDEN_FOR_EXPERIMENT = ("src.agent", "src.tools", "src.api", "src.services", "src.storage")


def _imported_modules(path: Path) -> list[str]:
    """解析文件的全部 import 目标模块（绝对 import 的模块名或 from 的根模块）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.append(node.module or "")
    return modules


def test_layers_static_guard() -> None:
    """experiment 层已登记且全仓无反向 import（check_layers 退出码 0 的等价断言）。"""
    assert LAYER_ORDER.get("experiment") == 4
    violations = check()
    assert violations == [], [f"{v.edge.source}:{v.edge.lineno} {v.reason}" for v in violations]


def test_static_guard_experiment_layer_imports() -> None:
    """src/experiment/ 无 import src.agent / src.tools / src.api / src.services / src.storage。"""
    for source in EXPERIMENT_SOURCES:
        for module in _imported_modules(source):
            assert not any(
                module == forbidden or module.startswith(forbidden + ".")
                for forbidden in _FORBIDDEN_FOR_EXPERIMENT
            ), f"{source.name} 不得 import {module}（分层 §8.4）"


def test_static_guard_random_usage() -> None:
    """src/experiment/ 与 experiment_tools.py 无 random 模块级函数调用（只允许 random.Random）。"""
    for source in [*EXPERIMENT_SOURCES, EXPERIMENT_TOOLS]:
        text = source.read_text(encoding="utf-8")
        match = _RANDOM_MODULE_FUNC_RE.search(text)
        assert match is None, f"{source.name} 出现模块级 random 函数: {match and match.group(0)}"


def test_static_guard_generation_purity() -> None:
    """generation.py 无 datetime / uuid import、无 now( 调用（确定性路径禁时间与随机标识）。"""
    generation = EXPERIMENT_DIR / "generation.py"
    modules = _imported_modules(generation)
    assert "datetime" not in modules
    assert "uuid" not in modules
    text = generation.read_text(encoding="utf-8")
    assert "now(" not in text


def test_static_guard_tools_layer_imports() -> None:
    """src/tools/experiment_tools.py 无 import src.agent（分层 §8.4）。"""
    for module in _imported_modules(EXPERIMENT_TOOLS):
        assert module != "src.agent" and not module.startswith("src.agent.")


def test_static_guard_no_new_dependencies() -> None:
    """全仓无白名单外依赖（pyproject.toml dependencies 不变）。"""
    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    expected_dependencies = """dependencies = [
    "fastapi",
    "uvicorn",
    "pydantic",
    "pydantic-settings",
    "httpx",
    "openai",
]"""
    assert expected_dependencies in pyproject
    for source in [*EXPERIMENT_SOURCES, EXPERIMENT_TOOLS]:
        modules = _imported_modules(source)
        for banned in ("numpy", "scipy", "pandas"):
            assert banned not in modules, f"{source.name} 含白名单外依赖 {banned}"
