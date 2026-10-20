"""file_write 工具：data/ 沙箱写入（契约 §2.3；ARCHITECTURE §6.3 / ADR-005）。"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, Field

from src.config import Settings
from src.models.tool_result import ToolResult
from src.models.tool_spec import ToolSpec

MAX_BYTES = 1_048_576  # 1MB 字节上限


class FileWriteInput(BaseModel):
    """file_write 参数。"""

    path: str = Field(min_length=1)  # 相对沙箱根的路径
    content: str = Field(max_length=MAX_BYTES)  # 字符上限（Pydantic 层第一道）


class _FileWriteBlocked(Exception):
    """安全拒绝（→ BLOCKED: 前缀）。"""


def _ensure_dir(path: Path) -> None:
    """mkdir 容错：目录已存在（含宿主安全代理把跨进程 EEXIST 包成 PermissionError 的场景）时静默通过。"""
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        if not path.is_dir():
            raise


def _validate_and_write(args: FileWriteInput, sandbox: Path) -> int:
    """五步安全规则（契约顺序冻结），返回写入字节数。"""
    rel_parts = Path(args.path).parts

    # 1. 字符串级拒绝 .. 与绝对路径
    if os.path.isabs(args.path) or ".." in rel_parts:
        raise _FileWriteBlocked("path traversal")

    # 沙箱根本身允许自动创建（配置指定位置），保证后续锚点存在
    _ensure_dir(sandbox)
    sandbox_real = Path(os.path.realpath(sandbox))
    target = sandbox.joinpath(*rel_parts)

    # 2. realpath + 组件边界前缀校验（防 data-evil 字符串前缀歧义）
    deepest = target
    while not deepest.exists():
        deepest = deepest.parent
    deepest_real = Path(os.path.realpath(deepest))
    if not deepest_real.is_relative_to(sandbox_real):
        raise _FileWriteBlocked("outside sandbox")

    # 3. 符号链接拒绝：沙箱根到目标每一级 lstat 检查（TOCTOU 缓解）
    current = sandbox
    for part in rel_parts:
        current = current / part
        try:
            st = os.lstat(current)
        except FileNotFoundError:
            break  # 该级及更深层均不存在，不可能含符号链接
        if stat.S_ISLNK(st.st_mode):
            raise _FileWriteBlocked("symlink in path")

    data = args.content.encode("utf-8")
    # 4. 字节数复核（Pydantic 管字符数，此处管字节数）
    if len(data) > MAX_BYTES:
        raise _FileWriteBlocked("content too large")

    # 5. 写入：自动创建沙箱内父目录，覆盖写
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
    """构造 file_write 的 ToolSpec（沙箱根绑定自 settings.data_sandbox_dir）。"""
    sandbox = Path(settings.data_sandbox_dir)

    async def executor(base: Any) -> ToolResult:
        return await _execute(cast(FileWriteInput, base), sandbox)

    return ToolSpec(
        name="file_write",
        description="把文本内容写入 data/ 沙箱目录内的文件（覆盖已存在文件）",
        input_model=FileWriteInput,
        idempotency="non-idempotent",
        risk_level="medium",
        executor=executor,
    )
