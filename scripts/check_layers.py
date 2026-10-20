"""Static layering dependency check (G-4 gate; rules from ARCHITECTURE §3).

Dependency direction (strictly one-way): ``api → services → agent → tools/storage``.
- Business layers may only import the same layer or lower (tools and storage share a
  layer and may reference each other); importing a higher layer is a reverse dependency.
- ``src/models/`` and ``src/config.py`` are shared layers: any business layer may reference
  them, but they must not import any business layer (referenced only, never referencing).
- Imports outside the project (stdlib/third-party) are unrestricted.

Usage: run ``python -m scripts.check_layers`` from the project root;
exit code 0 = pass (no reverse imports), 1 = violations found.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src"

# Business layers: higher number = lower layer (the depended-on side); only higher → lower is allowed
LAYER_ORDER: dict[str, int] = {
    "api": 0,
    "services": 1,
    "agent": 2,
    "tools": 3,
    "storage": 3,
    "experiment": 4,  # added in Phase A: the experiment engine layer below tools (approved extension, contract §8.3)
}

# Shared layers: referenced only; must not reference any business layer
SHARED_MODULES: frozenset[str] = frozenset({"models", "config"})


@dataclass(frozen=True)
class ImportEdge:
    """One intra-project import dependency: source module → target top-level package."""

    source: Path
    source_layer: str  # business layer name / shared module name / "src" (src/__init__.py)
    target: str
    lineno: int
    stmt: str


@dataclass(frozen=True)
class Violation:
    """One layering violation."""

    edge: ImportEdge
    reason: str


def module_layer(path: Path) -> str:
    """Return the layer a module belongs to: the first-level package under src (or the top-level module name minus .py)."""
    rel = path.relative_to(SRC_ROOT)
    first = rel.parts[0]
    if len(rel.parts) == 1:
        return first[: -len(".py")] if first.endswith(".py") else first
    return first


def iter_project_imports(path: Path) -> list[tuple[str, int]]:
    """Extract all imports in a file that target project src packages (absolute + relative).

    Returns a list of (target module path, line number); targets are normalized with the "src." prefix.
    """
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    # Package path of the current module in src coordinates, used to resolve relative imports
    rel = path.relative_to(SRC_ROOT)
    package_parts: tuple[str, ...] = ("src",)
    if len(rel.parts) > 1:
        package_parts = ("src", *rel.parts[:-1])

    targets: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                targets.append((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if node.module:
                    targets.append((node.module, node.lineno))
            else:
    # Relative import: walk the package path back by the given level
                base_parts = package_parts[: len(package_parts) - (node.level - 1)] if node.level > 1 else package_parts
                prefix = ".".join(base_parts)
                mod = node.module or ""
                targets.append((f"{prefix}.{mod}" if mod else prefix, node.lineno))
    # Keep only intra-project imports (under src.*)
    return [(t, ln) for t, ln in targets if t == "src" or t.startswith("src.")]


def check() -> list[Violation]:
    """Scan all .py files under src/ and return the violation list."""
    violations: list[Violation] = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        layer = module_layer(path)
        for target, lineno in iter_project_imports(path):
            # Target top-level package (src.<pkg>.… → <pkg>; src itself or src/__init__ counts as no business target)
            parts = target.split(".")
            if len(parts) < 2:
                continue  # bare `import src`: targets no business/shared module
            target_pkg = parts[1]
            if target_pkg in LAYER_ORDER:
                if layer in LAYER_ORDER and LAYER_ORDER[layer] > LAYER_ORDER[target_pkg]:
                    violations.append(
                        Violation(
                            edge=ImportEdge(path, layer, target_pkg, lineno, target),
                            reason=f"reverse import: {layer} (layer {LAYER_ORDER[layer]}) "
                            f"must not depend on {target_pkg} (layer {LAYER_ORDER[target_pkg]})",
                        )
                    )
                elif layer in SHARED_MODULES:
                    violations.append(
                        Violation(
                            edge=ImportEdge(path, layer, target_pkg, lineno, target),
                            reason=f"shared layer {layer} is referenced only; must not import business layer {target_pkg}",
                        )
                    )
            # Target is a shared layer (models/config), the same layer, or lower: legal
    return violations


def main() -> int:
    if not SRC_ROOT.is_dir():
        print(f"[FAIL] src/ directory not found: {SRC_ROOT}", file=sys.stderr)
        return 1
    violations = check()
    if violations:
        print(f"[FAIL] layering check found {len(violations)} violation(s):", file=sys.stderr)
        for v in violations:
            rel = v.edge.source.relative_to(PROJECT_ROOT)
            print(
                f"  {rel}:{v.edge.lineno}  import {v.edge.stmt}  → {v.reason}",
                file=sys.stderr,
            )
        return 1
    print("[PASS] layering check passed: no reverse imports (api → services → agent → tools/storage; models/config referenced only)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
