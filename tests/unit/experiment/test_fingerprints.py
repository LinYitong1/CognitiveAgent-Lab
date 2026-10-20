"""PA-5 SHA-256 与 verify 测试（契约 §7；-k "sha256 or fingerprint or verify" 命中）。

期望值由独立 `python -c "import hashlib; ..."` 计算后写死（不依赖被测代码自证）。
环境说明：沙箱对 pytest tmp_path 的会话根目录 mkdir 存在间歇性拦截 → 沿用 M1
固定测试子目录模式（data/ 已被 gitignore）。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from src.experiment.canonical import canonical_json, sha256_hex
from src.experiment.export import build_bundle
from src.experiment.schemas import ExperimentSpec
from src.experiment.verify import VerifyReport, verify_bundle

PROJECT_ROOT = Path(__file__).resolve().parents[3]
TEST_SANDBOX = Path("data/.test-sandbox/experiment-fingerprints")


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
def scratch() -> Iterator[Path]:
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
    "blocks": [
        {"name": "practice", "trial_count": 8},
        {"name": "main", "trial_count": 40},
    ],
    "constraints": {"balance": True},
    "responses": [
        {"name": "judge_difficulty", "kind": "choice", "options": ["easy", "hard"], "correct_from": "difficulty"}
    ],
    "timing": {"fixation_ms": 500, "stimulus_ms": None, "isi_ms": 1000},
}

_HEX64 = "^[0-9a-f]{64}$"


def test_sha256_known_vectors() -> None:
    # 期望值独立计算：
    #   python -c "import hashlib; print(hashlib.sha256(b'').hexdigest())"
    #   python -c "import hashlib; print(hashlib.sha256(b'abc').hexdigest())"
    #   python -c "import hashlib,json; print(hashlib.sha256(json.dumps({'b':1,'a':'中文'},sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest())"
    assert sha256_hex("") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert sha256_hex("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert sha256_hex(canonical_json({"b": 1, "a": "中文"})) == (
        "78d145429acf033939ca3676748013583b73c65617891b3f6f0cd3cb64fc2dfd"
    )


def test_fingerprint_full_length() -> None:
    """三指纹（config/trials/bundle）均完整 64 小写 hex——无 [:8] 截断（CR-2）。"""
    import re

    spec = ExperimentSpec.model_validate(SPEC_DICT)
    from src.experiment.generation import generate_trials

    generated = generate_trials(spec)
    assert re.match(_HEX64, generated.config_fingerprint)
    assert re.match(_HEX64, generated.trials_fingerprint)
    bundle = build_bundle(spec, generated_at="2026-01-01T00:00:00Z")
    assert re.match(_HEX64, str(bundle["bundle_sha256"]))
    repro = bundle["reproducibility"]
    assert isinstance(repro, dict)
    assert re.match(_HEX64, str(repro["config_fingerprint"]))
    assert re.match(_HEX64, str(repro["trials_fingerprint"]))
    assert generated.trials_fingerprint == repro["trials_fingerprint"]


def test_bundle_sha256_excludes_timestamp() -> None:
    """改 generated_at 不变 bundle_sha256（时间戳不参与任何指纹）。"""
    spec = ExperimentSpec.model_validate(SPEC_DICT)
    first = build_bundle(spec, generated_at="2026-01-01T00:00:00Z")
    second = build_bundle(spec, generated_at="2030-06-15T12:30:45Z")
    assert first["bundle_sha256"] == second["bundle_sha256"]


@pytest.fixture()
def bundle_file(scratch: Path) -> Path:
    spec = ExperimentSpec.model_validate(SPEC_DICT)
    bundle = build_bundle(spec, generated_at="2026-01-01T00:00:00Z")
    path = scratch / "bundle.json"
    path.write_text(canonical_json(bundle), encoding="utf-8")
    return path


def test_verify_bundle_ok(bundle_file: Path) -> None:
    report = verify_bundle(bundle_file)
    assert report.ok
    assert report.bundle_sha256_match
    assert report.trials_fingerprint_match
    # CLI 路径：python -m src.experiment.verify <path> → exit 0
    proc = subprocess.run(
        [sys.executable, "-m", "src.experiment.verify", str(bundle_file)],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )
    assert proc.returncode == 0, proc.stderr
    assert "OK" in proc.stdout


def test_verify_bundle_detects_tamper(bundle_file: Path, scratch: Path) -> None:
    """篡改 trials 任一字节 → 两项 check 失败、CLI exit 1。"""
    data = json.loads(bundle_file.read_text(encoding="utf-8"))
    assert data["trials"][0]["block"] == "practice"
    original_level = data["trials"][0]["factors"]["difficulty"]
    data["trials"][0]["factors"]["difficulty"] = "hard" if original_level == "easy" else "easy"  # 篡改一个试次的因素水平
    tampered = scratch / "tampered.json"
    tampered.write_text(canonical_json(data), encoding="utf-8")

    report: VerifyReport = verify_bundle(tampered)
    assert not report.ok
    assert not report.bundle_sha256_match
    assert not report.trials_fingerprint_match

    proc = subprocess.run(
        [sys.executable, "-m", "src.experiment.verify", str(tampered)],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )
    assert proc.returncode == 1
    assert "FAIL" in proc.stdout
    assert proc.stderr  # 失败详情进 stderr
