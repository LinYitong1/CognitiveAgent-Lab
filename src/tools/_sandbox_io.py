"""Sandbox path safety validation (same semantics as the five-step rule in src/tools/file_write.py; a reusable implementation).

Sync duty: this module stays in sync with the five-step rule at file_write.py:39-79 — any rule change must be
applied in both places and re-submitted to the Architect (contract §5.3 frozen ruling; file_write.py itself must not be modified, hence the sync note lives here).

Five-step rule (contract order frozen):
1. string-level rejection of `..` and absolute paths;
2. realpath + is_relative_to component-boundary validation (blocks data-evil prefix ambiguity);
3. lstat rejection of symlinks at every level from the sandbox root to the target (TOCTOU mitigation);
4. size cap (the caller's duty: content bytes for file_write, bundle bytes for export);
5. parent directories auto-created inside the sandbox, overwrite on write.

This module covers steps 1~3 (path validation) and step 5 (writing); step 4 is executed by the caller
before writing, under its own BLOCKED semantics.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path


class SandboxBlocked(Exception):
    """Security refusal (→ BLOCKED: prefix)."""


def _ensure_dir(path: Path) -> None:
    """mkdir tolerance: silently pass when the directory already exists (including the case where the host security agent wraps a cross-process EEXIST into PermissionError)."""
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        if not path.is_dir():
            raise


def validate_sandbox_path(path_str: str, sandbox_root: Path) -> Path:
    """Five-step rule steps 1~3: validate an output path relative to the sandbox root and return the absolute target path inside the sandbox."""
    rel_parts = Path(path_str).parts

    # 1. string-level rejection of .. and absolute paths
    if os.path.isabs(path_str) or ".." in rel_parts:
        raise SandboxBlocked("path traversal")

    # the sandbox root itself may be auto-created (configured location), ensuring the anchor exists
    _ensure_dir(sandbox_root)
    sandbox_real = Path(os.path.realpath(sandbox_root))
    target = sandbox_root.joinpath(*rel_parts)

    # 2. realpath + component-boundary prefix validation (blocks data-evil string-prefix ambiguity)
    deepest = target
    while not deepest.exists():
        deepest = deepest.parent
    deepest_real = Path(os.path.realpath(deepest))
    if not deepest_real.is_relative_to(sandbox_real):
        raise SandboxBlocked("outside sandbox")

    # 3. symlink rejection: lstat check at every level from the sandbox root to the target
    current = sandbox_root
    for part in rel_parts:
        current = current / part
        try:
            st = os.lstat(current)
        except FileNotFoundError:
            break  # this level and deeper do not exist, so no symlinks are possible
        if stat.S_ISLNK(st.st_mode):
            raise SandboxBlocked("symlink in path")

    return target


def write_sandbox_file(target: Path, data: bytes) -> None:
    """Five-step rule step 5: auto-create parent directories inside the sandbox, overwrite on write."""
    _ensure_dir(target.parent)
    target.write_bytes(data)
