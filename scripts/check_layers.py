"""静态分层依赖检查（G-4 门禁，规则来自 ARCHITECTURE §3）。

依赖方向（强制单向）：``api → services → agent → tools/storage``。
- 业务层只允许 import 同层或更低层（tools 与 storage 同层，可互引）；
  import 更高层即反向依赖，违规。
- ``src/models/`` 与 ``src/config.py`` 为共享层：可被任何业务层引用，
  但自身不得 import 任何业务层（仅被引用，不引用业务层）。
- 项目外 import（标准库/第三方）不受限。

用法：从项目根执行 ``python -m scripts.check_layers``；
退出码 0 = 通过（无反向 import），1 = 存在违规。
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src"

# 业务分层：数值越大层级越低（被依赖方）；只允许高层 → 低层
LAYER_ORDER: dict[str, int] = {
    "api": 0,
    "services": 1,
    "agent": 2,
    "tools": 3,
    "storage": 3,
}

# 共享层：仅被引用，不得引用任何业务层
SHARED_MODULES: frozenset[str] = frozenset({"models", "config"})


@dataclass(frozen=True)
class ImportEdge:
    """一条项目内 import 依赖：source 模块 → target 顶层包。"""

    source: Path
    source_layer: str  # 业务层名 / 共享模块名 / "src"（src/__init__.py）
    target: str
    lineno: int
    stmt: str


@dataclass(frozen=True)
class Violation:
    """一条分层违规。"""

    edge: ImportEdge
    reason: str


def module_layer(path: Path) -> str:
    """返回模块所属层：src 下第一级包名（或顶层模块名去掉 .py）。"""
    rel = path.relative_to(SRC_ROOT)
    first = rel.parts[0]
    if len(rel.parts) == 1:
        return first[: -len(".py")] if first.endswith(".py") else first
    return first


def iter_project_imports(path: Path) -> list[tuple[str, int]]:
    """提取文件中所有指向项目内 src 包的 import（绝对 + 相对）。

    返回 (目标模块路径, 行号) 列表；目标以 "src." 前缀规范化。
    """
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    # 当前模块在 src 包坐标下的包路径，用于解析相对导入
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
                # 相对导入：按 level 回退包路径
                base_parts = package_parts[: len(package_parts) - (node.level - 1)] if node.level > 1 else package_parts
                prefix = ".".join(base_parts)
                mod = node.module or ""
                targets.append((f"{prefix}.{mod}" if mod else prefix, node.lineno))
    # 仅保留项目内 import（src.* 下）
    return [(t, ln) for t, ln in targets if t == "src" or t.startswith("src.")]


def check() -> list[Violation]:
    """扫描 src/ 全部 .py 文件，返回违规列表。"""
    violations: list[Violation] = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        layer = module_layer(path)
        for target, lineno in iter_project_imports(path):
            # 目标顶层包（src.<pkg>.… → <pkg>；src 本身或 src/__init__ 视为无业务目标）
            parts = target.split(".")
            if len(parts) < 2:
                continue  # `import src` 本身：不指向任何业务/共享模块
            target_pkg = parts[1]
            if target_pkg in LAYER_ORDER:
                if layer in LAYER_ORDER and LAYER_ORDER[layer] > LAYER_ORDER[target_pkg]:
                    violations.append(
                        Violation(
                            edge=ImportEdge(path, layer, target_pkg, lineno, target),
                            reason=f"反向 import：{layer}（层 {LAYER_ORDER[layer]}）"
                            f"不得依赖 {target_pkg}（层 {LAYER_ORDER[target_pkg]}）",
                        )
                    )
                elif layer in SHARED_MODULES:
                    violations.append(
                        Violation(
                            edge=ImportEdge(path, layer, target_pkg, lineno, target),
                            reason=f"共享层 {layer} 仅被引用，不得 import 业务层 {target_pkg}",
                        )
                    )
            # 目标为共享层（models/config）或同层或更低层：合法
    return violations


def main() -> int:
    if not SRC_ROOT.is_dir():
        print(f"[FAIL] 未找到 src/ 目录：{SRC_ROOT}", file=sys.stderr)
        return 1
    violations = check()
    if violations:
        print(f"[FAIL] 分层依赖检查发现 {len(violations)} 处违规：", file=sys.stderr)
        for v in violations:
            rel = v.edge.source.relative_to(PROJECT_ROOT)
            print(
                f"  {rel}:{v.edge.lineno}  import {v.edge.stmt}  → {v.reason}",
                file=sys.stderr,
            )
        return 1
    print("[PASS] 分层依赖检查通过：无反向 import（api → services → agent → tools/storage，models/config 仅被引用）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
