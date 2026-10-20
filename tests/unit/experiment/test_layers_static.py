"""PA-12 layering/dependency/security static-guard tests (contract §7; matched by -k "layers or static_guard").

Import checks are AST-based (only real import statements count; explanatory text in docstrings does not false-positive).
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

# only random.Random instance methods are allowed — module-level random.* functions are banned (§3.2)
_RANDOM_MODULE_FUNC_RE = re.compile(r"random\.(?!Random\b)")

_FORBIDDEN_FOR_EXPERIMENT = ("src.agent", "src.tools", "src.api", "src.services", "src.storage")


def _imported_modules(path: Path) -> list[str]:
    """Parse all import target modules of a file (the module name of an absolute import, or the root module of a from-import)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.append(node.module or "")
    return modules


def test_layers_static_guard() -> None:
    """The experiment layer is registered and the whole repo has no reverse imports (the equivalent assertion of check_layers exit code 0)."""
    assert LAYER_ORDER.get("experiment") == 4
    violations = check()
    assert violations == [], [f"{v.edge.source}:{v.edge.lineno} {v.reason}" for v in violations]


def test_static_guard_experiment_layer_imports() -> None:
    """src/experiment/ does not import src.agent / src.tools / src.api / src.services / src.storage."""
    for source in EXPERIMENT_SOURCES:
        for module in _imported_modules(source):
            assert not any(
                module == forbidden or module.startswith(forbidden + ".")
                for forbidden in _FORBIDDEN_FOR_EXPERIMENT
            ), f"{source.name} must not import {module} (layering §8.4)"


def test_static_guard_random_usage() -> None:
    """src/experiment/ and experiment_tools.py have no module-level random function calls (only random.Random is allowed)."""
    for source in [*EXPERIMENT_SOURCES, EXPERIMENT_TOOLS]:
        text = source.read_text(encoding="utf-8")
        match = _RANDOM_MODULE_FUNC_RE.search(text)
        assert match is None, f"{source.name} contains a module-level random function: {match and match.group(0)}"


def test_static_guard_generation_purity() -> None:
    """generation.py has no datetime / uuid imports and no now( calls (time and random identifiers are banned on deterministic paths)."""
    generation = EXPERIMENT_DIR / "generation.py"
    modules = _imported_modules(generation)
    assert "datetime" not in modules
    assert "uuid" not in modules
    text = generation.read_text(encoding="utf-8")
    assert "now(" not in text


def test_static_guard_tools_layer_imports() -> None:
    """src/tools/experiment_tools.py does not import src.agent (layering §8.4)."""
    for module in _imported_modules(EXPERIMENT_TOOLS):
        assert module != "src.agent" and not module.startswith("src.agent.")


def test_static_guard_no_new_dependencies() -> None:
    """No dependencies outside the allow-list anywhere in the repo (pyproject.toml dependencies unchanged)."""
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
            assert banned not in modules, f"{source.name} contains a non-allow-listed dependency {banned}"
