"""PA-11 export 沙箱安全测试（契约 §7；-k "export_blocks or export_sandbox" 命中）。

沙箱根指固定测试目录（与 M1 file_write 测试同构，五步规则全部生效证据）。
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from src.config import Settings
from src.tools import experiment_tools

# 环境说明：沙箱对 pytest tmp_path 的会话根目录 mkdir 存在间歇性拦截 → 沿用 M1
# 固定测试子目录模式（自建自清，清不掉也无妨——data/ 已被 gitignore）。
TEST_SANDBOX = Path("data/.test-sandbox/experiment-export")


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

SPEC_DICT: dict[str, object] = {
    "schema_version": 1,
    "name": "generic-2x2",
    "version": "0.1.0",
    "seed": 7,
    "factors": [
        {"name": "difficulty", "levels": [{"name": "easy"}, {"name": "hard"}]},
        {"name": "modality", "levels": [{"name": "visual"}, {"name": "audio"}]},
    ],
    "blocks": [{"name": "main", "trial_count": 8}],
    "constraints": {"balance": True},
    "responses": [
        {"name": "judge_difficulty", "kind": "choice", "options": ["easy", "hard"], "correct_from": "difficulty"}
    ],
    "timing": {"fixation_ms": 500, "stimulus_ms": None, "isi_ms": 1000},
}


async def _export(sandbox: Path, path: str, config: dict[str, object] | None = None):
    settings = Settings(data_sandbox_dir=str(sandbox))
    spec = experiment_tools.build_export_spec(settings)
    return await spec.executor(
        experiment_tools.ExportExperimentInput(config=config or SPEC_DICT, path=path)
    )


@pytest.mark.asyncio
async def test_export_success_in_sandbox(sandbox: Path) -> None:
    result = await _export(sandbox, "experiments/generic-2x2-v0.1.0-seed7.json")
    assert result.ok
    written = sandbox / "experiments" / "generic-2x2-v0.1.0-seed7.json"
    assert written.exists()
    assert "wrote experiments/generic-2x2-v0.1.0-seed7.json" in result.result
    assert "trials_fingerprint=" in result.result
    assert "bundle_sha256=" in result.result
    assert len(result.result) < 512  # §5.3：短文本不被 _SUMMARY_LIMIT 截断
    text = written.read_text(encoding="utf-8")
    assert "\n" not in text  # canonical JSON 单行


@pytest.mark.asyncio
async def test_export_blocks_traversal(sandbox: Path) -> None:
    for path in ("../evil.json", "a/../../evil.json", "/tmp/evil.json"):
        result = await _export(sandbox, path)
        assert not result.ok, f"should be rejected: {path}"
        assert "BLOCKED" in result.error
        assert "path traversal" in result.error
    assert not (TEST_SANDBOX.parent / "evil.json").exists()
    assert not Path("/tmp/evil.json").exists()


@pytest.mark.asyncio
async def test_export_blocks_symlink(sandbox: Path) -> None:
    real_dir = sandbox / "real"
    _ensure_dir(real_dir)
    (real_dir / "inside.json").write_text("{}", encoding="utf-8")

    # 目录符号链接（即使指向沙箱内也拒绝）
    dir_link = sandbox / f"link-{os.getpid()}"
    if not dir_link.is_symlink():
        os.symlink(real_dir.resolve(), dir_link)
    result = await _export(sandbox, f"{dir_link.name}/evil.json")
    assert not result.ok
    assert "symlink" in result.error

    # 目标文件本身是符号链接
    file_link = sandbox / f"file-link-{os.getpid()}"
    if not file_link.is_symlink():
        os.symlink((real_dir / "inside.json").resolve(), file_link)
    result = await _export(sandbox, file_link.name)
    assert not result.ok
    assert "symlink" in result.error

    assert not (real_dir / "evil.json").exists()


@pytest.mark.asyncio
async def test_export_blocks_prefix_confusion(sandbox: Path) -> None:
    """与沙箱根同前缀字符串但非子目录（data-evil 形态）——is_relative_to 组件边界证据。"""
    evil_dir = TEST_SANDBOX.parent / "experiment-export-evil"
    _ensure_dir(evil_dir)
    # 沙箱内的符号链接指向 data-evil（无 .. 的逃逸路径）
    escape = sandbox / f"escape-{os.getpid()}"
    if not escape.is_symlink():
        os.symlink(evil_dir.resolve(), escape)

    result = await _export(sandbox, f"{escape.name}/x.json")
    assert not result.ok
    assert "BLOCKED" in result.error
    assert "outside sandbox" in result.error
    assert not (evil_dir / "x.json").exists()


@pytest.mark.asyncio
async def test_export_blocks_oversize(sandbox: Path) -> None:
    """构造 >1MB Bundle → BLOCKED: export too large（OUT-7 / R-6）。"""
    sandbox = TEST_SANDBOX
    big_spec: dict[str, object] = {
        **SPEC_DICT,
        "blocks": [{"name": "main", "trial_count": 20_000}],  # 2 万试次 ≈ 3MB canonical
    }
    result = await _export(sandbox, "experiments/big.json", config=big_spec)
    assert not result.ok
    assert result.error == "BLOCKED: export too large"
    assert not (sandbox / "experiments" / "big.json").exists()
