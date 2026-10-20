"""M1-5 file_write 单元测试（契约 §3.2；-k tool_security 命中）。

环境说明：沙箱拦截 unlink → 不用 tmp_path fixture，用 data/ 下固定测试子目录
（自建自清，清不掉也无妨——data/ 已被 gitignore）。宿主安全代理对跨进程残留
目录的 mkdir(exist_ok=True) 会抛 PermissionError——一律经 _ensure_dir 容错。
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
    """建符号链接（目标用绝对路径，避免 POSIX 相对解析歧义）。

    链接名带 pid：跨进程重复运行时旧链接残留（无法删除）不会干扰本次断言。
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

    # 目录符号链接（即使指向沙箱内也拒绝）
    dir_link = _ensure_symlink(real_dir, "link", sandbox)
    result = await _run(sandbox, f"{dir_link.name}/evil.txt", "x")
    assert not result.ok
    assert "symlink" in result.error

    # 目标文件本身是符号链接
    file_link = _ensure_symlink(real_dir / "inside.txt", "file-link", sandbox)
    result = await _run(sandbox, file_link.name, "x")
    assert not result.ok
    assert "symlink" in result.error

    assert not (real_dir / "evil.txt").exists()


@pytest.mark.asyncio
@pytest.mark.tool_security
async def test_file_write_blocks_prefix_confusion(sandbox: Path) -> None:
    # 与沙箱根同前缀字符串但非子目录（data-evil 形态）——is_relative_to 组件边界证据
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
    # 字符数超限 → 参数校验层拒绝（经 registry 统一入口）
    registry = ToolRegistry()
    settings = Settings(data_sandbox_dir=str(sandbox))
    registry.register(file_write.build_tool_spec(settings))
    result = await registry.execute(
        "file_write", {"path": "too-many-chars.txt", "content": "a" * (file_write.MAX_BYTES + 1)}
    )
    assert not result.ok
    assert "invalid arguments" in result.error

    # 字符不超限但 UTF-8 字节数超限 → executor 复核拒绝
    result2 = await _run(sandbox, "wide.txt", "é" * 600_000)  # 60 万字符、约 1.2MB 字节
    assert not result2.ok
    assert "content too large" in result2.error
    assert "BLOCKED" in result2.error
