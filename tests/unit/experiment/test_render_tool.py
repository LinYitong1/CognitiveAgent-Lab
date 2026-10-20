"""Phase B B2 acceptance tests: the render_game tool (contract §11.10 BR-6, BR-9).

Fixture genericity: the legal GameSpec is derived dynamically from the golden bundle (same pattern as the B1 tests).
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest

from src.agent.game_registry import build_game_registry
from src.config import Settings
from src.tools import game_tools
from src.tools.game_tools import RenderGameInput

PROJECT_ROOT = Path(__file__).resolve().parents[3]
GOLDEN_BUNDLE_PATH = PROJECT_ROOT / "tests" / "golden" / "generic-2x2-seed7.json"
TEST_SANDBOX = Path("data/.test-sandbox/render-tool")

BUNDLE_REL_PATH = "experiments/golden.json"
OUTPUT_REL_PATH = "games/generic-demo.html"


def _try_cleanup(path: Path) -> None:
    try:
        shutil.rmtree(path)
    except OSError:
        pass


@pytest.fixture()
def sandbox() -> Iterator[Path]:
    _try_cleanup(TEST_SANDBOX)
    (TEST_SANDBOX / "experiments").mkdir(parents=True, exist_ok=True)
    (TEST_SANDBOX / "experiments" / "golden.json").write_text(
        GOLDEN_BUNDLE_PATH.read_text(encoding="utf-8"), encoding="utf-8"
    )
    yield TEST_SANDBOX
    _try_cleanup(TEST_SANDBOX)


def _settings(sandbox: Path) -> Settings:
    return Settings(data_sandbox_dir=str(sandbox))


def _game_config(bundle: dict[str, object]) -> dict[str, object]:
    spec_part = cast(dict[str, object], bundle["spec"])
    repro = cast(dict[str, object], bundle["reproducibility"])
    responses = cast(list[object], spec_part["responses"])
    choice = cast(dict[str, object], next(r for r in responses if cast(dict[str, object], r)["kind"] == "choice"))
    options = cast(list[str], choice["options"])
    keys = {option[:1]: option for option in options}
    return {
        "schema_version": 1,
        "game": {"name": "generic-demo", "version": "0.1.0"},
        "experiment_ref": {
            "name": spec_part["name"],
            "version": spec_part["version"],
            "seed": spec_part["seed"],
            "config_fingerprint": repro["config_fingerprint"],
            "trials_fingerprint": repro["trials_fingerprint"],
            "bundle_sha256": bundle["bundle_sha256"],
        },
        "input": {"modalities": ["keyboard"],
                  "bindings": [{"response_name": choice["name"], "keys": keys}]},
    }


def _bundle_bytes(sandbox: Path) -> bytes:
    return (sandbox / BUNDLE_REL_PATH).read_bytes()


# ---------- BR-6: tool-level BLOCKED ----------

@pytest.mark.asyncio
async def test_br6_blocked_oversized_game_config(sandbox: Path) -> None:
    bundle = json.loads(GOLDEN_BUNDLE_PATH.read_text(encoding="utf-8"))
    config = _game_config(bundle)
    cast(dict[str, object], config.setdefault("scene", {}))["instructions"] = "x" * 300_000
    tool = game_tools.build_render_game_spec(_settings(sandbox))
    res = await tool.executor(RenderGameInput.model_validate({
        "game_config": config, "bundle_path": BUNDLE_REL_PATH, "output_path": OUTPUT_REL_PATH}))
    assert res.ok is False and res.error is not None and res.error.startswith("BLOCKED:")


@pytest.mark.asyncio
async def test_br6_blocked_bundle_path_escape(sandbox: Path) -> None:
    bundle = json.loads(GOLDEN_BUNDLE_PATH.read_text(encoding="utf-8"))
    tool = game_tools.build_render_game_spec(_settings(sandbox))
    res = await tool.executor(RenderGameInput.model_validate({
        "game_config": _game_config(bundle), "bundle_path": "../escape.json",
        "output_path": OUTPUT_REL_PATH}))
    assert res.ok is False and res.error is not None and res.error.startswith("BLOCKED:")


@pytest.mark.asyncio
async def test_br6_blocked_missing_bundle(sandbox: Path) -> None:
    bundle = json.loads(GOLDEN_BUNDLE_PATH.read_text(encoding="utf-8"))
    tool = game_tools.build_render_game_spec(_settings(sandbox))
    res = await tool.executor(RenderGameInput.model_validate({
        "game_config": _game_config(bundle), "bundle_path": "experiments/nope.json",
        "output_path": OUTPUT_REL_PATH}))
    assert res.ok is False and res.error is not None and res.error.startswith("BLOCKED:")


@pytest.mark.asyncio
async def test_br6_blocked_corrupt_bundle(sandbox: Path) -> None:
    bundle = json.loads(GOLDEN_BUNDLE_PATH.read_text(encoding="utf-8"))
    (sandbox / "experiments" / "corrupt.json").write_text("{not json", encoding="utf-8")
    tool = game_tools.build_render_game_spec(_settings(sandbox))
    res = await tool.executor(RenderGameInput.model_validate({
        "game_config": _game_config(bundle), "bundle_path": "experiments/corrupt.json",
        "output_path": OUTPUT_REL_PATH}))
    assert res.ok is False and res.error is not None and res.error.startswith("BLOCKED:")


@pytest.mark.asyncio
async def test_br6_blocked_output_path_escape(sandbox: Path) -> None:
    bundle = json.loads(GOLDEN_BUNDLE_PATH.read_text(encoding="utf-8"))
    tool = game_tools.build_render_game_spec(_settings(sandbox))
    res = await tool.executor(RenderGameInput.model_validate({
        "game_config": _game_config(bundle), "bundle_path": BUNDLE_REL_PATH,
        "output_path": "../evil.html"}))
    assert res.ok is False and res.error is not None and res.error.startswith("BLOCKED:")


# ---------- BR-6: domain-level (invalid spec → nothing rendered, nothing written) ----------

@pytest.mark.asyncio
async def test_br6_invalid_spec_renders_nothing(sandbox: Path) -> None:
    bundle = json.loads(GOLDEN_BUNDLE_PATH.read_text(encoding="utf-8"))
    config = _game_config(bundle)
    ref = cast(dict[str, object], config["experiment_ref"])
    ref["seed"] = cast(int, ref["seed"]) + 1  # G2 mismatch
    tool = game_tools.build_render_game_spec(_settings(sandbox))
    res = await tool.executor(RenderGameInput.model_validate({
        "game_config": config, "bundle_path": BUNDLE_REL_PATH, "output_path": OUTPUT_REL_PATH}))
    assert res.ok is True and res.result is not None
    payload = json.loads(res.result)
    assert payload["rendered"] is False
    assert payload["valid"] is False
    assert any(e["error_code"] == "REF_MISMATCH" for e in payload["errors"])
    assert not (sandbox / OUTPUT_REL_PATH).exists()  # zero disk writes


# ---------- BR-6: success path ----------

@pytest.mark.asyncio
async def test_br6_valid_spec_writes_playable_html(sandbox: Path) -> None:
    bundle = json.loads(GOLDEN_BUNDLE_PATH.read_text(encoding="utf-8"))
    before = _bundle_bytes(sandbox)
    tool = game_tools.build_render_game_spec(_settings(sandbox))
    res = await tool.executor(RenderGameInput.model_validate({
        "game_config": _game_config(bundle), "bundle_path": BUNDLE_REL_PATH,
        "output_path": OUTPUT_REL_PATH}))
    assert res.ok is True and res.result is not None
    payload = json.loads(res.result)
    assert payload["rendered"] is True
    assert payload["path"] == OUTPUT_REL_PATH
    assert payload["total_trials"] == 48

    target = sandbox / OUTPUT_REL_PATH
    assert target.is_file()
    html = target.read_text(encoding="utf-8")
    assert html.startswith("<!DOCTYPE html>")
    # html_sha256 matches the on-disk content
    from src.experiment.canonical import sha256_hex
    assert payload["html_sha256"] == sha256_hex(html)
    assert payload["bytes"] == len(html.encode("utf-8"))
    # the ExperimentBundle is byte-identical before and after (the game tools cannot modify experiment data)
    assert _bundle_bytes(sandbox) == before


# ---------- BR-9: combinator and tools schema ----------

def test_br9_registry_registers_five_tools_with_ascii_description() -> None:
    registry = build_game_registry(Settings(data_sandbox_dir=str(TEST_SANDBOX)))
    schemas = registry.get_schemas()
    names = {s["function"]["name"] for s in schemas}
    assert names == {
        "calc", "http_request", "file_write",
        "validate_experiment", "generate_trials", "export_experiment",
        "validate_game", "render_game",
    }
    render = next(s for s in schemas if s["function"]["name"] == "render_game")
    desc = cast(str, render["function"]["description"])
    assert all(ord(c) < 128 for c in desc)
    assert "output_path" in desc
