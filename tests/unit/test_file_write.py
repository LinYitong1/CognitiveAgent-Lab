"""M1-5 file_write unit tests (contract §3.2; matched by -k tool_security).

Environment note: the host sandbox blocks unlink → no tmp_path fixture; a fixed test subdirectory
under data/ is used instead (self-created, self-cleaned; leftovers are fine — data/ is gitignored).
The host security agent raises PermissionError on cross-process mkdir(exist_ok=True) for leftover
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from src.agent.registry import ToolRegistry
from src.config import Settings
from src.models.tool_result import ToolResult
from src.tools import file_write

TEST_SANDBOX = Path("data/.test-sandbox/file_write")


def _try_cleanup(path: Path) -> None:
    try:
        shutil.rmtree(path)
    except OSError:
        pass


def _ensure_dir(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        if not path.is_dir():
            raise


@pytest.fixture()
def sandbox() -> Iterator[Path]:
    _try_cleanup(TEST_SANDBOX)
    _ensure_dir(TEST_SANDBOX)
    yield TEST_SANDBOX
    _try_cleanup(TEST_SANDBOX)


async def _run(sandbox: Path, path: str, content: str) -> ToolResult:
    settings = Settings(data_sandbox_dir=str(sandbox))
    spec = file_write.build_tool_spec(settings)
    return await spec.executor(file_write.FileWriteInput(path=path, content=content))


def _ensure_symlink(source: Path, name: str, sandbox: Path) -> Path:
    """Create a symlink (the target uses an absolute path to avoid POSIX relative-resolution ambiguity).

    The link name carries the pid: when reruns across processes leave old links behind (undeletable), they do not disturb this assertion.
    """
    link = sandbox / f"{name}-{os.getpid()}"
    if not link.is_symlink():
        os.symlink(source.resolve(), link)
    return link


@pytest.mark.asyncio
@pytest.mark.tool_security
async def test_file_write_success_in_sandbox(sandbox: Path) -> None:
    result = await _run(sandbox, "sub/out.txt", "hello world")

    assert result.ok
    assert (sandbox / "sub" / "out.txt").read_text(encoding="utf-8") == "hello world"
    assert "bytes" in result.result
    assert "11 bytes" in result.result


@pytest.mark.asyncio
@pytest.mark.tool_security
async def test_file_write_blocks_traversal(sandbox: Path) -> None:
    for path in ["../evil.txt", "a/../../evil", "/tmp/x"]:
        result = await _run(sandbox, path, "x")
        assert not result.ok, f"should be rejected: {path}"
        assert "BLOCKED" in result.error
        assert "path traversal" in result.error
    assert not (sandbox.parent / "evil.txt").exists()


@pytest.mark.asyncio
@pytest.mark.tool_security
async def test_file_write_blocks_symlink(sandbox: Path) -> None:
    real_dir = sandbox / "real"
    _ensure_dir(real_dir)
    (real_dir / "inside.txt").write_text("inside", encoding="utf-8")

    # directory symlink (rejected even when it points inside the sandbox)
    dir_link = _ensure_symlink(real_dir, "link", sandbox)
    result = await _run(sandbox, f"{dir_link.name}/evil.txt", "x")
    assert not result.ok
    assert "symlink" in result.error

    # the target file itself is a symlink
    file_link = _ensure_symlink(real_dir / "inside.txt", "file-link", sandbox)
    result = await _run(sandbox, file_link.name, "x")
    assert not result.ok
    assert "symlink" in result.error

    assert not (real_dir / "evil.txt").exists()


@pytest.mark.asyncio
@pytest.mark.tool_security
async def test_file_write_blocks_prefix_confusion(sandbox: Path) -> None:
    # same string prefix as the sandbox root but not a subdirectory (the data-evil shape) — evidence of the is_relative_to component boundary
    evil_dir = sandbox.parent / "file_write-evil"
    _ensure_dir(evil_dir)
    escape = _ensure_symlink(evil_dir, "escape", sandbox)

    result = await _run(sandbox, f"{escape.name}/x.txt", "x")
    assert not result.ok
    assert "outside sandbox" in result.error
    assert not (evil_dir / "x.txt").exists()


@pytest.mark.asyncio
@pytest.mark.tool_security
async def test_file_write_blocks_oversize(sandbox: Path) -> None:
    # character count over the limit → rejected at the parameter-validation layer (via the registry unified entry)
    registry = ToolRegistry()
    settings = Settings(data_sandbox_dir=str(sandbox))
    registry.register(file_write.build_tool_spec(settings))
    result = await registry.execute(
        "file_write", {"path": "too-many-chars.txt", "content": "a" * (file_write.MAX_BYTES + 1)}
    )
    assert not result.ok
    assert "invalid arguments" in result.error

    # characters within the limit but UTF-8 bytes over the limit → rejected at the executor recheck
    result2 = await _run(sandbox, "wide.txt", "é" * 600_000)  # 600k characters ≈ 1.2MB of bytes
    assert not result2.ok
    assert "content too large" in result2.error
    assert "BLOCKED" in result2.error
