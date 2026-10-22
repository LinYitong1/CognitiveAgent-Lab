"""file_read tool: reads a file inside the data/ sandbox (read-only counterpart of file_write).

Path safety reuses the frozen five-step rule's steps 1~3 via
_sandbox_io.validate_sandbox_path (string-level traversal rejection, realpath
component-boundary containment, symlink rejection at every level). Reading
adds: the target must exist and be a regular file, and a byte cap with an
explicit truncation marker (so a caller can never mistake a truncated read
for the full file).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, Field

from src.config import Settings
from src.models.tool_result import ToolResult
from src.models.tool_spec import ToolSpec
from src.tools._sandbox_io import SandboxBlocked, validate_sandbox_path

MAX_READ_BYTES = 65_536  # 64KB read cap (keeps tool results context-bounded)

_TRUNCATION_NOTE = "\n...[truncated: file is larger than the read cap]"


class FileReadInput(BaseModel):
    """file_read arguments."""

    path: str = Field(min_length=1)  # path relative to the sandbox root


class _FileReadBlocked(Exception):
    """Security/guard refusal (→ BLOCKED: prefix)."""


async def _execute(args: FileReadInput, sandbox: Path) -> ToolResult:
    try:
        target = validate_sandbox_path(args.path, sandbox)
    except SandboxBlocked as exc:
        return ToolResult(ok=False, error=f"BLOCKED: {exc}")
    if not target.exists():
        return ToolResult(ok=False, error=f"ERROR: no such file in sandbox: {args.path}")
    if not target.is_file():
        return ToolResult(ok=False, error=f"ERROR: not a regular file: {args.path}")
    try:
        data = target.read_bytes()
    except OSError as exc:
        return ToolResult(ok=False, error=f"ERROR: read failed: {type(exc).__name__}: {exc}")
    truncated = len(data) > MAX_READ_BYTES
    if truncated:
        data = data[:MAX_READ_BYTES]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return ToolResult(
            ok=False,
            error=f"ERROR: {args.path} is not valid UTF-8 text (binary files are not readable)",
        )
    if truncated:
        text += _TRUNCATION_NOTE
    return ToolResult(ok=True, result=text)


def build_tool_spec(settings: Settings) -> ToolSpec:
    """Build file_read's ToolSpec (the sandbox root binds to settings.data_sandbox_dir)."""
    sandbox = Path(settings.data_sandbox_dir)

    async def executor(base: Any) -> ToolResult:
        return await _execute(cast(FileReadInput, base), sandbox)

    return ToolSpec(
        name="file_read",
        description=(
            "Read a UTF-8 text file inside the data/ sandbox (e.g. an exported "
            "ExperimentBundle JSON) and return its content, so generated artifacts "
            "can be inspected and checked. Reads are capped at 64KB with an explicit "
            "truncation marker; binary files are rejected."
        ),
        input_model=FileReadInput,
        idempotency="idempotent",
        risk_level="low",
        executor=executor,
    )
