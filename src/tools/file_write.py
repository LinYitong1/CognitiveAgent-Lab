"""file_write tool: writes inside the data/ sandbox (contract §2.3; ARCHITECTURE §6.3 / ADR-005)."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, Field

from src.config import Settings
from src.models.tool_result import ToolResult
from src.models.tool_spec import ToolSpec

MAX_BYTES = 1_048_576  # 1MB byte cap


class FileWriteInput(BaseModel):
    """file_write arguments."""

    path: str = Field(min_length=1)  # path relative to the sandbox root
    content: str = Field(max_length=MAX_BYTES)  # character cap (first guard at the Pydantic layer)


class _FileWriteBlocked(Exception):
    """Security refusal (→ BLOCKED: prefix)."""


def _ensure_dir(path: Path) -> None:
    """mkdir tolerance: silently pass when the directory already exists (including the case where the host security agent wraps a cross-process EEXIST into PermissionError)."""
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        if not path.is_dir():
            raise


def _validate_and_write(args: FileWriteInput, sandbox: Path) -> int:
    """Five-step security rule (contract order frozen); returns the number of bytes written."""
    rel_parts = Path(args.path).parts

    # 1. string-level rejection of .. and absolute paths
    if os.path.isabs(args.path) or ".." in rel_parts:
        raise _FileWriteBlocked("path traversal")

    # the sandbox root itself may be auto-created (configured location), ensuring the anchor exists
    _ensure_dir(sandbox)
    sandbox_real = Path(os.path.realpath(sandbox))
    target = sandbox.joinpath(*rel_parts)

    # 2. realpath + component-boundary prefix validation (blocks data-evil string-prefix ambiguity)
    deepest = target
    while not deepest.exists():
        deepest = deepest.parent
    deepest_real = Path(os.path.realpath(deepest))
    if not deepest_real.is_relative_to(sandbox_real):
        raise _FileWriteBlocked("outside sandbox")

    # 3. symlink rejection: lstat check at every level from the sandbox root to the target (TOCTOU mitigation)
    current = sandbox
    for part in rel_parts:
        current = current / part
        try:
            st = os.lstat(current)
        except FileNotFoundError:
            break  # this level and deeper do not exist, so no symlinks are possible
        if stat.S_ISLNK(st.st_mode):
            raise _FileWriteBlocked("symlink in path")

    data = args.content.encode("utf-8")
    # 4. byte-count recheck (Pydantic guards characters, this guards bytes)
    if len(data) > MAX_BYTES:
        raise _FileWriteBlocked("content too large")

    # 5. write: auto-create parent directories inside the sandbox, overwrite
    _ensure_dir(target.parent)
    target.write_bytes(data)
    return len(data)


async def _execute(args: FileWriteInput, sandbox: Path) -> ToolResult:
    try:
        byte_count = _validate_and_write(args, sandbox)
    except _FileWriteBlocked as exc:
        return ToolResult(ok=False, error=f"BLOCKED: {exc}")
    return ToolResult(ok=True, result=f"wrote {args.path} ({byte_count} bytes)")


def build_tool_spec(settings: Settings) -> ToolSpec:
    """Build file_write's ToolSpec (the sandbox root binds to settings.data_sandbox_dir)."""
    sandbox = Path(settings.data_sandbox_dir)

    async def executor(base: Any) -> ToolResult:
        return await _execute(cast(FileWriteInput, base), sandbox)

    return ToolSpec(
        name="file_write",
        description="Write text content to a file inside the data/ sandbox directory (overwrites existing files)",
        input_model=FileWriteInput,
        idempotency="non-idempotent",
        risk_level="medium",
        executor=executor,
    )
