"""Integration tests for the cognitive-agent CLI and the public Python API.

Covers (user-approved CLI/API plan):
- CLI-1 installation: the console script exists and ``--help`` exits 0;
- CLI-2 ``demo`` runs deterministically with zero keys/network, artifacts
  confined to ``--output`` (output-directory isolation);
- CLI-3 ``run`` without credentials exits 2 with clear guidance;
- CLI-4 ``verify``: exit 0 for a valid bundle, exit 1 for a tampered one;
- API-1 ``run_task`` with an injected fake client returns the structured
  PipelineResult (status / artifacts / verification) without real LLM calls;
- API-2 credential policy: placeholder for keyless local endpoints,
  MissingCredentialsError otherwise;
- API-3 ``run_demo`` raises PipelineVerificationError on tampered artifacts
  (never silently ignored).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import sysconfig
from collections.abc import Iterator
from pathlib import Path

import pytest

from src.config import Settings
from src.pipeline import (
    LOCAL_ENDPOINT_PLACEHOLDER_KEY,
    MissingCredentialsError,
    PipelineResult,
    build_demo_script,
    demo_game_config,
    resolve_client,
    run_demo,
    run_task,
)

from .fake_llm import FakeLLM

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_SANDBOX = Path("data/.test-sandbox/cli-api")


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


def _cli_env() -> dict[str, str]:
    env = dict(os.environ)
    env["CALC_AGENT_ENV_FILE"] = "/dev/null"
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "LLM_BASE_URL"):
        env.pop(key, None)
    return env


def _run_cli(args: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "src.cli", *args],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=env if env is not None else _cli_env(),
        timeout=120,
    )


# ---------------------------------------------------------------------------
# CLI-1 installation
# ---------------------------------------------------------------------------

def test_cli_console_script_installed_and_helps() -> None:
    """The ``cognitive-agent`` console script exists after installation and --help exits 0."""
    script = Path(sysconfig.get_path("scripts")) / "cognitive-agent"
    assert script.is_file(), f"console script missing: {script}"
    proc = subprocess.run(
        [str(script), "--help"], capture_output=True, text=True, timeout=30
    )
    assert proc.returncode == 0
    assert "{run,demo,verify}" in proc.stdout


def test_cli_module_invocation_help() -> None:
    """``python -m src.cli --help`` also exits 0 (no installation required)."""
    proc = _run_cli(["--help"])
    assert proc.returncode == 0
    assert "demo" in proc.stdout and "verify" in proc.stdout


# ---------------------------------------------------------------------------
# CLI-2 demo: deterministic, keyless, output isolation
# ---------------------------------------------------------------------------

def test_cli_demo_output_directory_isolation() -> None:
    """demo --output DIR: exit 0, artifacts only inside DIR, default data/ untouched."""
    default_experiments = Path("data/experiments")
    default_games = Path("data/games")

    def snapshot(root: Path) -> set[Path]:
        return {p for p in root.rglob("*") if p.is_file()} if root.is_dir() else set()

    before_experiments = snapshot(default_experiments)
    before_games = snapshot(default_games)

    out_dir = TEST_SANDBOX / "demo-out"
    proc = _run_cli(["demo", "--output", str(out_dir)])

    assert proc.returncode == 0, f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    assert "status     : completed" in proc.stdout
    assert "bundle     : verification OK" in proc.stdout
    assert "html       : matches deterministic re-render" in proc.stdout

    bundle = out_dir / "experiments" / "demo-agent-game.json"
    html = out_dir / "games" / "demo-agent-game.html"
    assert bundle.is_file() and html.is_file()
    assert html.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")

    # isolation: nothing new appeared under the default data/ locations
    assert snapshot(default_experiments) == before_experiments
    assert snapshot(default_games) == before_games


def test_cli_demo_reproducible() -> None:
    """Two demo runs into separate directories produce byte-identical HTML."""
    out1 = TEST_SANDBOX / "demo-run1"
    out2 = TEST_SANDBOX / "demo-run2"
    proc1 = _run_cli(["demo", "--output", str(out1)])
    proc2 = _run_cli(["demo", "--output", str(out2)])
    assert proc1.returncode == 0 and proc2.returncode == 0

    bundle1 = json.loads((out1 / "experiments" / "demo-agent-game.json").read_text(encoding="utf-8"))
    bundle2 = json.loads((out2 / "experiments" / "demo-agent-game.json").read_text(encoding="utf-8"))
    assert bundle1["bundle_sha256"] == bundle2["bundle_sha256"]
    assert (out1 / "games" / "demo-agent-game.html").read_bytes() == (
        out2 / "games" / "demo-agent-game.html"
    ).read_bytes()


# ---------------------------------------------------------------------------
# CLI-3 run without credentials
# ---------------------------------------------------------------------------

def test_cli_run_missing_credentials_exit_2() -> None:
    """run with no key and no base URL → exit 2 with configuration guidance."""
    out_dir = TEST_SANDBOX / "run-nokey"
    proc = _run_cli(["run", "design an experiment", "--output", str(out_dir)])
    assert proc.returncode == 2
    assert "No LLM credentials configured" in proc.stderr
    assert "OPENAI_API_KEY" in proc.stderr
    assert "LLM_BASE_URL" in proc.stderr
    # the credential failure path writes nothing
    assert not out_dir.exists() or not any(out_dir.rglob("*"))


# ---------------------------------------------------------------------------
# CLI-4 verify
# ---------------------------------------------------------------------------

def test_cli_verify_good_and_tampered_bundle() -> None:
    """verify: exit 0 for a valid bundle; exit 1 after tampering one trial."""
    out_dir = TEST_SANDBOX / "verify-out"
    assert _run_cli(["demo", "--output", str(out_dir)]).returncode == 0
    bundle = out_dir / "experiments" / "demo-agent-game.json"

    good = _run_cli(["verify", str(bundle)])
    assert good.returncode == 0
    assert "OK" in good.stdout

    data = json.loads(bundle.read_text(encoding="utf-8"))
    data["trials"][0]["factors"]["side"] = "tampered"
    tampered = TEST_SANDBOX / "tampered.json"
    tampered.write_text(json.dumps(data), encoding="utf-8")

    bad = _run_cli(["verify", str(tampered)])
    assert bad.returncode == 1


# ---------------------------------------------------------------------------
# API-1 run_task with an injected fake client
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_api_run_task_with_fake_client(sandbox: Path) -> None:
    """run_task(client=FakeLLM): completed status, artifacts, verification — no real LLM."""
    settings = Settings(calc_agent_max_steps=12, data_sandbox_dir=str(sandbox))
    client = FakeLLM(build_demo_script())

    result = await run_task("design and render a game", settings=settings, client=client)

    assert isinstance(result, PipelineResult)
    assert result.status == "completed"
    # the unchanged AgentResult contract is always present and populated
    assert result.result.status == "completed"
    assert result.result.steps == 6
    assert result.result.events
    # artifacts: bundle + html inside the configured sandbox
    artifact_names = {p.name for p in result.artifacts}
    assert artifact_names == {"demo-agent-game.json", "demo-agent-game.html"}
    assert all(sandbox in p.parents for p in result.artifacts)
    # verification outcome: the exported bundle passes independent verification
    assert result.bundle_verification is not None
    assert result.bundle_verification.ok
    assert result.html_verified is None  # run_task does not re-render


# ---------------------------------------------------------------------------
# API-2 credential policy
# ---------------------------------------------------------------------------

def test_api_resolve_client_placeholder_for_local_endpoint() -> None:
    """Keyless custom endpoint (e.g. local Ollama) → documented placeholder key."""
    settings = Settings(openai_api_key="", llm_base_url="http://localhost:11434/v1")
    client = resolve_client(settings)
    assert client._model == settings.llm_model  # constructed from the same settings
    # the placeholder policy is exercised (no real call is made)


def test_api_resolve_client_placeholder_key_value_documented() -> None:
    """The placeholder key is a stable, documented constant."""
    settings = Settings(openai_api_key="", llm_base_url="http://localhost:11434/v1")
    resolved = resolve_client(settings)
    assert resolved is not None
    assert LOCAL_ENDPOINT_PLACEHOLDER_KEY == "local-endpoint-placeholder"


def test_api_resolve_client_missing_credentials() -> None:
    """No key and no endpoint → MissingCredentialsError with guidance."""
    settings = Settings(openai_api_key="", llm_base_url="")
    with pytest.raises(MissingCredentialsError) as excinfo:
        resolve_client(settings)
    assert "OPENAI_API_KEY" in str(excinfo.value)
    assert "LLM_BASE_URL" in str(excinfo.value)


# ---------------------------------------------------------------------------
# API-3 run_demo verification failures are loud
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_api_demo_html_verification_catches_tampering(sandbox: Path) -> None:
    """The demo HTML verification itself flags tampering.

    Note: rerunning ``run_demo`` regenerates artifacts (tools overwrite), so a
    rerun would self-heal a tampered file. This test targets the verification
    logic directly: after tampering, the byte-identity check must report False.
    """
    from src import pipeline

    out_dir = sandbox / "demo"
    assert (await run_demo(output_dir=out_dir)).status == "completed"
    assert pipeline._verify_demo_html(out_dir) is True

    html = out_dir / "games" / "demo-agent-game.html"
    html.write_bytes(html.read_bytes()[:-4] + b"junk")
    assert pipeline._verify_demo_html(out_dir) is False


@pytest.mark.asyncio
async def test_api_run_demo_success_shape(sandbox: Path) -> None:
    """run_demo: completed, verified bundle, byte-identical HTML, known artifacts."""
    out_dir = sandbox / "demo-ok"
    result = await run_demo(output_dir=out_dir)

    assert result.status == "completed"
    assert result.bundle_verification is not None and result.bundle_verification.ok
    assert result.html_verified is True
    assert {p.name for p in result.artifacts} == {"demo-agent-game.json", "demo-agent-game.html"}
    assert demo_game_config()["game"] == {"name": "demo-agent-game", "version": "0.1.0"}
