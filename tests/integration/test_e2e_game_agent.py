"""Phase B B3 integration tests: the end-to-end FakeLLM agent workflow (E2E demo acceptance).

Coverage:
- BD-1 the full five-tool chain inside a single AgentLoop (validate_experiment → generate_trials →
  export_experiment → validate_game → render_game）+ final；
- BD-2 examples/run_game_agent.py actually runs as a subprocess (no .env, no keys);
- BD-3 a second run reproduces: identical bundle fingerprints, byte-identical HTML;
- BD-4 no verification failure is silently ignored: tampered/missing artifacts must be caught by verify_artifacts;
- BD-5 a "shortcut LLM" (skipping render while claiming success) must be caught by the two-layer verification.

The example module is loaded via importlib (examples/ is not a package) and its DEMO_SPEC / build_script /
verify_agent_run / verify_artifacts are reused — tests and demo share the same verification logic, preventing drift.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from src.agent.game_registry import build_game_registry
from src.agent.loop import AgentLoop
from src.config import Settings
from src.models.llm import LLMResponse, ToolCallRequest

from .fake_llm import FakeLLM

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_SANDBOX = Path("data/.test-sandbox/e2e-game-agent")
EXAMPLE_SANDBOX = Path("data/.test-sandbox/e2e-example")
EXAMPLE_PATH = REPO_ROOT / "examples" / "run_game_agent.py"

_demo_module = None


def demo_module():  # type: ignore[no-untyped-def]
    """Load (and cache) the example module run_game_agent."""
    global _demo_module
    if _demo_module is None:
        spec = importlib.util.spec_from_file_location("run_game_agent", EXAMPLE_PATH)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _demo_module = module
    return _demo_module


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


def _settings(sandbox: Path) -> Settings:
    return Settings(calc_agent_max_steps=12, data_sandbox_dir=str(sandbox))


def _final_response(text: str) -> LLMResponse:
    return LLMResponse(content=text, finish_reason="stop")


@pytest.mark.asyncio
async def test_bd1_full_workflow_single_agent_loop(sandbox: Path) -> None:
    """BD-1: the five-tool chain runs inside a single AgentLoop; both verification layers report zero problems."""
    demo = demo_module()
    settings = _settings(sandbox)
    registry = build_game_registry(settings)
    llm = FakeLLM(demo.build_script())
    loop = AgentLoop(client=llm, registry=registry, settings=settings, task_id="t-e2e-1")

    result = await loop.run_task(demo.GOAL)

    assert result.status == "completed"
    # FakeLLM is duck-type compatible with the example's ScriptedLLM: received_messages is isomorphic
    assert demo.verify_agent_run(result, llm) == []  # type: ignore[arg-type]
    assert demo.verify_artifacts(
        sandbox, demo.DEMO_SPEC, demo._game_config(), demo.BUNDLE_REL, demo.HTML_REL
    ) == []
    assert (sandbox / demo.BUNDLE_REL).is_file()
    assert (sandbox / demo.HTML_REL).is_file()


def _run_example(sandbox_dir: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["CALC_AGENT_ENV_FILE"] = "/dev/null"  # proves it runs without keys or .env
    env["DATA_SANDBOX_DIR"] = sandbox_dir
    return subprocess.run(
        [sys.executable, str(EXAMPLE_PATH)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=env,
        timeout=120,
    )


def test_bd2_example_script_runs_clean() -> None:
    """BD-2: the example script exits 0 as a subprocess; the artifacts really exist."""
    demo = demo_module()
    _try_cleanup(EXAMPLE_SANDBOX)
    run_dir = EXAMPLE_SANDBOX / "run1"
    proc = _run_example(str(run_dir))

    assert proc.returncode == 0, f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    assert "[E2E OK]" in proc.stdout
    assert (run_dir / demo.BUNDLE_REL).is_file()
    assert (run_dir / demo.HTML_REL).is_file()
    _try_cleanup(EXAMPLE_SANDBOX)


def test_bd3_example_output_reproducible() -> None:
    """BD-3: two independent runs → identical bundle_sha256 / trials_fingerprint, byte-identical HTML."""
    demo = demo_module()
    _try_cleanup(EXAMPLE_SANDBOX)
    proc1 = _run_example(str(EXAMPLE_SANDBOX / "run1"))
    proc2 = _run_example(str(EXAMPLE_SANDBOX / "run2"))
    assert proc1.returncode == 0, proc1.stdout + proc1.stderr
    assert proc2.returncode == 0, proc2.stdout + proc2.stderr

    bundle1 = json.loads(
        (EXAMPLE_SANDBOX / "run1" / demo.BUNDLE_REL).read_text(encoding="utf-8")
    )
    bundle2 = json.loads(
        (EXAMPLE_SANDBOX / "run2" / demo.BUNDLE_REL).read_text(encoding="utf-8")
    )
    assert bundle1["bundle_sha256"] == bundle2["bundle_sha256"]
    repro1 = bundle1["reproducibility"]
    repro2 = bundle2["reproducibility"]
    assert repro1["trials_fingerprint"] == repro2["trials_fingerprint"]
    assert repro1["config_fingerprint"] == repro2["config_fingerprint"]

    html1 = (EXAMPLE_SANDBOX / "run1" / demo.HTML_REL).read_bytes()
    html2 = (EXAMPLE_SANDBOX / "run2" / demo.HTML_REL).read_bytes()
    assert html1 == html2
    _try_cleanup(EXAMPLE_SANDBOX)


def test_bd4_verification_catches_tampering() -> None:
    """BD-4: tampered/missing artifacts → verify_artifacts reports problems (never silently ignored)."""
    demo = demo_module()
    _try_cleanup(EXAMPLE_SANDBOX)
    sandbox = EXAMPLE_SANDBOX / "sandbox"
    proc = _run_example(str(sandbox))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    spec = demo.DEMO_SPEC
    game = demo._game_config()

# baseline: intact artifacts report zero problems
    assert demo.verify_artifacts(sandbox, spec, game, demo.BUNDLE_REL, demo.HTML_REL) == []

# (1) HTML missing
    html_file = sandbox / demo.HTML_REL
    html_backup = html_file.read_bytes()
    html_file.unlink()
    problems = demo.verify_artifacts(sandbox, spec, game, demo.BUNDLE_REL, demo.HTML_REL)
    assert any("html file missing" in p for p in problems)
    html_file.write_bytes(html_backup)

# (2) a bundle trial tampered (verify_bundle dual-fingerprint recomputation must mismatch)
    bundle_file = sandbox / demo.BUNDLE_REL
    bundle_backup = bundle_file.read_text(encoding="utf-8")
    bundle = json.loads(bundle_backup)
    bundle["trials"][0]["factors"]["side"] = "tampered"
    bundle_file.write_text(json.dumps(bundle), encoding="utf-8")
    problems = demo.verify_artifacts(sandbox, spec, game, demo.BUNDLE_REL, demo.HTML_REL)
    assert problems, "tampered bundle must be reported"
    bundle_file.write_text(bundle_backup, encoding="utf-8")

# (3) HTML tampered (byte comparison against the deterministic render must mismatch)
    html_file.write_bytes(html_backup[:-8] + b"tampered")
    problems = demo.verify_artifacts(sandbox, spec, game, demo.BUNDLE_REL, demo.HTML_REL)
    assert any("byte-identical" in p for p in problems)
    html_file.write_bytes(html_backup)

# after restoring, zero problems again (proving the failures above were caused by the tampering)
    assert demo.verify_artifacts(sandbox, spec, game, demo.BUNDLE_REL, demo.HTML_REL) == []
    _try_cleanup(EXAMPLE_SANDBOX)


@pytest.mark.asyncio
async def test_bd5_shortcut_llm_exposed(sandbox: Path) -> None:
    """BD-5: an LLM that skips render_game while claiming success → both verification layers must report problems."""
    demo = demo_module()
    settings = _settings(sandbox)
    registry = build_game_registry(settings)

    shortcut_script = demo.build_script()[:3] + [  # only validate/generate/export
        _final_response("Done, everything finished and verified.")
    ]
    llm = FakeLLM(shortcut_script)
    loop = AgentLoop(client=llm, registry=registry, settings=settings, task_id="t-e2e-5")
    result = await loop.run_task(demo.GOAL)

    assert result.status == "completed"  # "formally completed" at the agent layer...
    run_problems = demo.verify_agent_run(result, llm)  # type: ignore[arg-type]
    artifact_problems = demo.verify_artifacts(
        sandbox, demo.DEMO_SPEC, demo._game_config(), demo.BUNDLE_REL, demo.HTML_REL
    )
    # ...but the verification layer must expose it: incomplete tool sequence + missing HTML
    assert any("tool call sequence mismatch" in p for p in run_problems)
    assert any("html file missing" in p for p in artifact_problems)
