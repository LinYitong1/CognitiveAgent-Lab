"""file_read unit tests (sandbox read; mirrors the file_write security tests).

Same five-step path-safety semantics (steps 1-3 via _sandbox_io), plus read-specific
guards: missing file, non-regular file, binary content, and the truncation marker.
Matched by -k tool_security.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from src.config import Settings
from src.models.tool_result import ToolResult
from src.tools import file_write
from src.tools.file_read import MAX_READ_BYTES, FileReadInput, build_tool_spec

TEST_SANDBOX = Path("data/.test-sandbox/file_read")


def _try_cleanup(path: Path) -> None:
    try:
        shutil.rmtree(path)
    except OSError:
        pass


@pytest.fixture()
def sandbox() -> Iterator[Path]:
    _try_cleanup(TEST_SANDBOX)
    TEST_SANDBOX.mkdir(parents=True, exist_ok=True)
    yield TEST_SANDBOX
    _try_cleanup(TEST_SANDBOX)


async def _read(sandbox: Path, path: str) -> ToolResult:
    settings = Settings(data_sandbox_dir=str(sandbox))
    spec = build_tool_spec(settings)
    return await spec.executor(FileReadInput(path=path))


async def _write(sandbox: Path, path: str, content: str) -> None:
    settings = Settings(data_sandbox_dir=str(sandbox))
    spec = file_write.build_tool_spec(settings)
    result = await spec.executor(file_write.FileWriteInput(path=path, content=content))
    assert result.ok, result.error


@pytest.mark.asyncio
@pytest.mark.tool_security
async def test_file_read_roundtrip(sandbox: Path) -> None:
    await _write(sandbox, "experiments/a.json", '{"trials": 12}')
    result = await _read(sandbox, "experiments/a.json")
    assert result.ok, result.error
    assert result.result == '{"trials": 12}'


@pytest.mark.asyncio
@pytest.mark.tool_security
async def test_file_read_blocks_traversal(sandbox: Path) -> None:
    for bad in ("../outside.txt", "/etc/passwd", "notes/../../outside.txt"):
        result = await _read(sandbox, bad)
        assert not result.ok and "BLOCKED" in result.error, bad


@pytest.mark.asyncio
@pytest.mark.tool_security
async def test_file_read_blocks_symlink(sandbox: Path) -> None:
    outside = sandbox.parent / f"file-read-outside-{os.getpid()}.txt"
    outside.write_text("secret", encoding="utf-8")
    try:
        link = sandbox / f"leak-{os.getpid()}"
        if not link.is_symlink():
            os.symlink(outside.resolve(), link)
        result = await _read(sandbox, link.name)
        assert not result.ok and "BLOCKED" in result.error
    finally:
        link = sandbox / f"leak-{os.getpid()}"
        if link.is_symlink():
            link.unlink()
        outside.unlink(missing_ok=True)


@pytest.mark.asyncio
@pytest.mark.tool_security
async def test_file_read_missing_and_directory(sandbox: Path) -> None:
    missing = await _read(sandbox, "nope.json")
    assert not missing.ok and "no such file" in missing.error
    (sandbox / "sub").mkdir()
    directory = await _read(sandbox, "sub")
    assert not directory.ok and "not a regular file" in directory.error


@pytest.mark.asyncio
@pytest.mark.tool_security
async def test_file_read_rejects_binary(sandbox: Path) -> None:
    (sandbox / "blob.bin").write_bytes(b"\x00\x01\x02\xff")
    result = await _read(sandbox, "blob.bin")
    assert not result.ok and "not valid UTF-8" in result.error


@pytest.mark.asyncio
@pytest.mark.tool_security
async def test_file_read_truncation_marker(sandbox: Path) -> None:
    # a file above the cap comes back capped, with the explicit truncation marker
    big = sandbox / "big.txt"
    big.write_text("x" * (MAX_READ_BYTES + 100), encoding="utf-8")
    result = await _read(sandbox, "big.txt")
    assert result.ok
    marker = "...[truncated: file is larger than the read cap]"
    assert result.result.endswith(marker)
    assert len(result.result) <= MAX_READ_BYTES + len(marker) + 1  # +1: leading newline


@pytest.mark.asyncio
@pytest.mark.tool_security
async def test_file_read_tool_spec_metadata() -> None:
    spec = build_tool_spec(Settings(data_sandbox_dir="data/.test-sandbox/x"))
    assert spec.name == "file_read"
    assert spec.idempotency == "idempotent"
    assert spec.risk_level == "low"
    assert all(ord(c) < 128 for c in spec.description), "description must be pure ASCII"
