"""B1 单元测试：validate_game 工具（契约 §10 BT-1~BT-3、BT-5）。

fixture 通用性：合法 GameSpec 从黄金 Bundle 动态派生（同 B0 测试模式）。
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from src.agent.game_registry import build_game_registry
from src.config import Settings
from src.tools import game_tools
from src.tools.game_tools import ValidateGameInput

PROJECT_ROOT = Path(__file__).resolve().parents[3]
GOLDEN_BUNDLE_PATH = PROJECT_ROOT / "tests" / "golden" / "generic-2x2-seed7.json"
TEST_SANDBOX = Path("data/.test-sandbox/game-tool")

BUNDLE_REL_PATH = "experiments/golden.json"


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
    target = TEST_SANDBOX / BUNDLE_REL_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(GOLDEN_BUNDLE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    yield TEST_SANDBOX
    _try_cleanup(TEST_SANDBOX)


def _settings(sandbox: Path) -> Settings:
    return Settings(data_sandbox_dir=str(sandbox))


def _game_config(bundle: dict[str, object]) -> dict[str, object]:
    """合法 GameSpec（引用黄金 Bundle 真实六项指纹）。"""
    spec_part = bundle["spec"]  # type: ignore[index]
    repro = bundle["reproducibility"]  # type: ignore[index]
    responses = spec_part["responses"]  # type: ignore[index]
    choice = next(r for r in responses if r["kind"] == "choice")  # type: ignore[union-attr]
    keys = {chr(ord("a") + i): option for i, option in enumerate(choice["options"])}  # type: ignore[call-overload]
    return {
        "schema_version": 1,
        "game": {"name": "generic-demo", "version": "0.1.0"},
        "experiment_ref": {
            "name": spec_part["name"],  # type: ignore[index]
            "version": spec_part["version"],  # type: ignore[index]
            "seed": spec_part["seed"],  # type: ignore[index]
            "config_fingerprint": repro["config_fingerprint"],  # type: ignore[index]
            "trials_fingerprint": repro["trials_fingerprint"],  # type: ignore[index]
            "bundle_sha256": bundle["bundle_sha256"],
        },
        "input": {"modalities": ["keyboard"],
                  "bindings": [{"response_name": choice["name"], "keys": keys}]},  # type: ignore[union-attr]
    }


def _bundle() -> dict[str, object]:
    return json.loads(GOLDEN_BUNDLE_PATH.read_text(encoding="utf-8"))


async def _run(settings: Settings, **kwargs: object) -> object:
    spec = game_tools.build_validate_game_spec(settings)
    args = ValidateGameInput.model_validate(kwargs)
    return await spec.executor(args)


# ---------- BT-1 工具级：BLOCKED ----------


@pytest.mark.asyncio
async def test_bt1_game_config_too_large(sandbox: Path) -> None:
    bundle = _bundle()
    config = _game_config(bundle)
    config["scene"] = {"assets": {"pad": "x" * (300 * 1024)}}  # type: ignore[index]
    result = await _run(_settings(sandbox), game_config=config, bundle_path=BUNDLE_REL_PATH)
    assert result.ok is False
    assert "BLOCKED: game config too large" in result.error


@pytest.mark.asyncio
async def test_bt1_bundle_path_traversal(sandbox: Path) -> None:
    bundle = _bundle()
    result = await _run(
        _settings(sandbox),
        game_config=_game_config(bundle),
        bundle_path="../outside.json",
    )
    assert result.ok is False
    assert "BLOCKED" in result.error


@pytest.mark.asyncio
async def test_bt1_bundle_not_found(sandbox: Path) -> None:
    bundle = _bundle()
    result = await _run(
        _settings(sandbox),
        game_config=_game_config(bundle),
        bundle_path="experiments/missing.json",
    )
    assert result.ok is False
    assert "BLOCKED: bundle not found" in result.error


@pytest.mark.asyncio
async def test_bt1_bundle_corrupt_json(sandbox: Path) -> None:
    (sandbox / "experiments" / "corrupt.json").write_text("{not json", encoding="utf-8")
    bundle = _bundle()
    result = await _run(
        _settings(sandbox),
        game_config=_game_config(bundle),
        bundle_path="experiments/corrupt.json",
    )
    assert result.ok is False
    assert "BLOCKED: bundle not loadable" in result.error


@pytest.mark.asyncio
async def test_bt1_bundle_not_object(sandbox: Path) -> None:
    (sandbox / "experiments" / "array.json").write_text("[1,2]", encoding="utf-8")
    bundle = _bundle()
    result = await _run(
        _settings(sandbox),
        game_config=_game_config(bundle),
        bundle_path="experiments/array.json",
    )
    assert result.ok is False
    assert "BLOCKED: bundle must be a JSON object" in result.error


# ---------- BT-2 领域级：结构化报告（ok=True + valid:false） ----------


@pytest.mark.asyncio
async def test_bt2_invalid_game_spec_structured_report(sandbox: Path) -> None:
    bundle = _bundle()
    config = _game_config(bundle)
    config["experiment_ref"]["seed"] = 999  # type: ignore[index]
    result = await _run(_settings(sandbox), game_config=config, bundle_path=BUNDLE_REL_PATH)
    assert result.ok is True  # 领域级失败不带 ERROR 前缀
    payload = json.loads(str(result.result))
    assert payload["valid"] is False
    assert payload["stalled"] is False
    assert any(e["error_code"] == "REF_MISMATCH" for e in payload["errors"])
    assert payload["game_config_fingerprint"]


@pytest.mark.asyncio
async def test_bt2_valid_game_spec_passes(sandbox: Path) -> None:
    bundle = _bundle()
    result = await _run(
        _settings(sandbox),
        game_config=_game_config(bundle),
        bundle_path=BUNDLE_REL_PATH,
    )
    assert result.ok is True
    payload = json.loads(str(result.result))
    assert payload["valid"] is True
    assert payload["errors"] == []
    assert payload["warnings"] == []


@pytest.mark.asyncio
async def test_bt2_schema_invalid_smuggled_field(sandbox: Path) -> None:
    bundle = _bundle()
    config = _game_config(bundle)
    config["trials"] = [{"index": 0}]  # type: ignore[index]
    result = await _run(_settings(sandbox), game_config=config, bundle_path=BUNDLE_REL_PATH)
    assert result.ok is True
    payload = json.loads(str(result.result))
    assert payload["valid"] is False
    assert any(e["error_code"] == "SCHEMA_INVALID" for e in payload["errors"])


# ---------- BT-3 stalled ----------


@pytest.mark.asyncio
async def test_bt3_stalled_after_repeated_fingerprint(sandbox: Path) -> None:
    bundle = _bundle()
    config = _game_config(bundle)
    config["experiment_ref"]["seed"] = 999  # type: ignore[index]
    fingerprint = "REF_MISMATCH:experiment_ref.seed"
    result = await _run(
        _settings(sandbox),
        game_config=config,
        bundle_path=BUNDLE_REL_PATH,
        previous_errors=[fingerprint, fingerprint],
    )
    payload = json.loads(str(result.result))
    assert payload["stalled"] is True
    assert any(e["error_code"] == "ITERATION_STALLED" for e in payload["errors"])


@pytest.mark.asyncio
async def test_bt3_not_stalled_on_first_submission(sandbox: Path) -> None:
    bundle = _bundle()
    config = _game_config(bundle)
    config["experiment_ref"]["seed"] = 999  # type: ignore[index]
    result = await _run(
        _settings(sandbox),
        game_config=config,
        bundle_path=BUNDLE_REL_PATH,
        previous_errors=["REF_MISMATCH:experiment_ref.seed"],
    )
    payload = json.loads(str(result.result))
    assert payload["stalled"] is False


# ---------- BT-5 ToolSpec 元数据 / tools schema / 组合器 ----------


def test_bt5_toolspec_metadata() -> None:
    spec = game_tools.build_validate_game_spec(Settings())
    assert spec.name == "validate_game"
    assert spec.idempotency == "idempotent"
    assert spec.risk_level == "low"
    assert all(ord(c) < 128 for c in spec.description), "description must be pure ASCII"
    assert "no wrapper" in spec.description
    assert len(spec.description) <= 1200


def test_bt5_registry_registers_validate_game() -> None:
    registry = build_game_registry(Settings(data_sandbox_dir="data/.test-sandbox/game-tool"))
    names = {s["function"]["name"] for s in registry.get_schemas()}
    # M1 三工具 + 实验三工具 + validate_game = 7（B1 冻结集；B2 追加 render_game 后为 8）
    assert {
        "calc", "http_request", "file_write",
        "validate_experiment", "generate_trials", "export_experiment",
        "validate_game",
    } <= names
    assert "render_game" in names  # B2 契约 §11.8：组合器追加注册 render_game


def test_bt5_description_reaches_tools_schema() -> None:
    registry = build_game_registry(Settings(data_sandbox_dir="data/.test-sandbox/game-tool"))
    validate_schema = next(
        s for s in registry.get_schemas() if s["function"]["name"] == "validate_game"
    )
    desc = validate_schema["function"]["description"]
    assert "experiment_ref" in desc
    assert all(ord(c) < 128 for c in desc)
