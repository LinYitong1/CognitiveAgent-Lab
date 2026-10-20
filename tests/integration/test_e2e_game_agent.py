"""Phase B B3 集成测试：端到端 FakeLLM Agent 工作流（E2E demo 验收）。

覆盖：
- BD-1 单一 AgentLoop 内完整五工具链（validate_experiment → generate_trials →
  export_experiment → validate_game → render_game）+ final；
- BD-2 examples/run_game_agent.py 子进程真实可运行（无 .env、无密钥）；
- BD-3 二次运行可复现：bundle 指纹一致、HTML 逐字节一致；
- BD-4 任何验证失败不被静默忽略：篡改/缺失产物必被 verify_artifacts 抓出；
- BD-5 "抄近路 LLM"（跳过 render 谎称完成）必被双层验证抓出。

示例模块经 importlib 加载（examples/ 非包），复用其 DEMO_SPEC / build_script /
verify_agent_run / verify_artifacts——测试与 Demo 共用同一验证逻辑，防漂移。
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
    """加载（并缓存）示例模块 run_game_agent。"""
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
    """BD-1：单一 AgentLoop 跑通五工具链；双层验证零问题。"""
    demo = demo_module()
    settings = _settings(sandbox)
    registry = build_game_registry(settings)
    llm = FakeLLM(demo.build_script())
    loop = AgentLoop(client=llm, registry=registry, settings=settings, task_id="t-e2e-1")

    result = await loop.run_task(demo.GOAL)

    assert result.status == "completed"
    # FakeLLM 与示例 ScriptedLLM 鸭子类型兼容：received_messages 同构
    assert demo.verify_agent_run(result, llm) == []  # type: ignore[arg-type]
    assert demo.verify_artifacts(
        sandbox, demo.DEMO_SPEC, demo._game_config(), demo.BUNDLE_REL, demo.HTML_REL
    ) == []
    assert (sandbox / demo.BUNDLE_REL).is_file()
    assert (sandbox / demo.HTML_REL).is_file()


def _run_example(sandbox_dir: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["CALC_AGENT_ENV_FILE"] = "/dev/null"  # 证明无密钥/无 .env 可运行
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
    """BD-2：示例脚本子进程运行退出码 0，产物真实存在。"""
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
    """BD-3：两次独立运行 → bundle_sha256 / trials_fingerprint 一致、HTML 逐字节一致。"""
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
    """BD-4：篡改/缺失产物 → verify_artifacts 报告问题（不静默忽略）。"""
    demo = demo_module()
    _try_cleanup(EXAMPLE_SANDBOX)
    sandbox = EXAMPLE_SANDBOX / "sandbox"
    proc = _run_example(str(sandbox))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    spec = demo.DEMO_SPEC
    game = demo._game_config()

    # 基线：完好产物零问题
    assert demo.verify_artifacts(sandbox, spec, game, demo.BUNDLE_REL, demo.HTML_REL) == []

    # ① HTML 缺失
    html_file = sandbox / demo.HTML_REL
    html_backup = html_file.read_bytes()
    html_file.unlink()
    problems = demo.verify_artifacts(sandbox, spec, game, demo.BUNDLE_REL, demo.HTML_REL)
    assert any("html file missing" in p for p in problems)
    html_file.write_bytes(html_backup)

    # ② Bundle 试次被篡改（verify_bundle 双指纹重算必失配）
    bundle_file = sandbox / demo.BUNDLE_REL
    bundle_backup = bundle_file.read_text(encoding="utf-8")
    bundle = json.loads(bundle_backup)
    bundle["trials"][0]["factors"]["side"] = "tampered"
    bundle_file.write_text(json.dumps(bundle), encoding="utf-8")
    problems = demo.verify_artifacts(sandbox, spec, game, demo.BUNDLE_REL, demo.HTML_REL)
    assert problems, "tampered bundle must be reported"
    bundle_file.write_text(bundle_backup, encoding="utf-8")

    # ③ HTML 被篡改（与确定性渲染逐字节比对必失配）
    html_file.write_bytes(html_backup[:-8] + b"tampered")
    problems = demo.verify_artifacts(sandbox, spec, game, demo.BUNDLE_REL, demo.HTML_REL)
    assert any("byte-identical" in p for p in problems)
    html_file.write_bytes(html_backup)

    # 恢复后再次零问题（证明上述失败确由篡改引起）
    assert demo.verify_artifacts(sandbox, spec, game, demo.BUNDLE_REL, demo.HTML_REL) == []
    _try_cleanup(EXAMPLE_SANDBOX)


@pytest.mark.asyncio
async def test_bd5_shortcut_llm_exposed(sandbox: Path) -> None:
    """BD-5：LLM 跳过 render_game 谎称完成 → 双层验证必须报问题。"""
    demo = demo_module()
    settings = _settings(sandbox)
    registry = build_game_registry(settings)

    shortcut_script = demo.build_script()[:3] + [  # 只做 validate/generate/export
        _final_response("Done, everything finished and verified.")
    ]
    llm = FakeLLM(shortcut_script)
    loop = AgentLoop(client=llm, registry=registry, settings=settings, task_id="t-e2e-5")
    result = await loop.run_task(demo.GOAL)

    assert result.status == "completed"  # Agent 层面"形式完成"……
    run_problems = demo.verify_agent_run(result, llm)  # type: ignore[arg-type]
    artifact_problems = demo.verify_artifacts(
        sandbox, demo.DEMO_SPEC, demo._game_config(), demo.BUNDLE_REL, demo.HTML_REL
    )
    # ……但验证层必须揭穿：工具序列不完整 + HTML 缺失
    assert any("tool call sequence mismatch" in p for p in run_problems)
    assert any("html file missing" in p for p in artifact_problems)
