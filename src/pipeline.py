"""Public Python API facade for CognitiveAgent Lab (user-approved minimal CLI/API plan).

Reuse-only module: it wires together the existing AgentLoop, ToolRegistry (via
build_game_registry), experiment engine, GameSpec validation and the HTML
renderer. No engine, validation or rendering logic is duplicated here.

Two entry points:

- ``run_task(goal, *, settings, client)`` — drive the real AgentLoop with any
  ``LLMClientProtocol`` implementation (the real ``LLMClient`` or a test fake
  injected via ``client``). The caller owns credential policy when injecting a
  client; without one, ``resolve_client`` applies the documented policy:
  a real key for authenticated endpoints, a documented placeholder key for
  keyless local OpenAI-compatible endpoints (e.g. a local Ollama server), and
  ``MissingCredentialsError`` when no credentials are configured at all.
- ``run_demo(*, output_dir)`` — the deterministic scripted workflow (inline
  scripted client, zero network, zero keys): ExperimentSpec → validate →
  generate → export → GameSpec → validate_game → render_game → playable HTML,
  with two-layer verification that fails loudly (``PipelineVerificationError``)
  rather than passing tampered or missing artifacts silently.

Structured result: ``PipelineResult`` wraps the unchanged ``AgentResult``
contract and adds generated artifact paths and verification outcomes.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.agent.game_registry import build_game_registry
from src.agent.llm import LLMClient, LLMClientProtocol
from src.agent.loop import AgentLoop
from src.config import Settings
from src.experiment.export import build_bundle
from src.experiment.game_render import render_game_html
from src.experiment.game_schemas import validate_game
from src.experiment.schemas import ExperimentSpec
from src.experiment.verify import VerifyReport, verify_bundle
from src.models.agent_result import AgentResult
from src.models.events import AgentEventType
from src.models.llm import LLMResponse, ToolCallRequest

# Documented placeholder key for keyless local OpenAI-compatible endpoints
# (e.g. a local Ollama server at http://localhost:11434/v1). Authenticated
# endpoints must set OPENAI_API_KEY instead — see README "Configuration".
LOCAL_ENDPOINT_PLACEHOLDER_KEY = "local-endpoint-placeholder"


class MissingCredentialsError(RuntimeError):
    """No usable LLM credentials are configured (clear-report policy, never silent)."""


class PipelineVerificationError(RuntimeError):
    """Demo pipeline verification failed; problems are listed in ``.problems``."""

    def __init__(self, problems: Sequence[str]) -> None:
        self.problems: tuple[str, ...] = tuple(problems)
        super().__init__("demo verification failed: " + "; ".join(self.problems))


@dataclass(frozen=True)
class PipelineResult:
    """Structured outcome of a pipeline run (wraps the unchanged AgentResult).

    Fields:
        status: ``"completed"`` | ``"failed"`` — the AgentLoop task status.
        result: the underlying ``AgentResult`` (status, result text, steps,
            events) — the existing M1 contract, unmodified and always present.
        artifacts: files created inside the sandbox during the run, sorted by
            path (empty when the run produced nothing).
        bundle_verification: independent ``VerifyReport`` for the newest
            exported bundle artifact (``verify_bundle`` recomputes both
            fingerprints without the generator); ``None`` when no bundle was
            produced.
        html_verified: whether the produced HTML is byte-identical to a
            deterministic re-render (checked by ``run_demo``; ``None`` for
            ``run_task``, which does not re-render).
    """

    status: str
    result: AgentResult
    artifacts: tuple[Path, ...]
    bundle_verification: VerifyReport | None
    html_verified: bool | None


# ---------------------------------------------------------------------------
# Credential policy (shared by the CLI and API default path)
# ---------------------------------------------------------------------------

_CREDENTIALS_GUIDANCE = (
    "No LLM credentials configured. Either:\n"
    "  - set OPENAI_API_KEY (required for the default OpenAI endpoint and any\n"
    "    endpoint that requires authentication), or\n"
    "  - set LLM_BASE_URL to a keyless local OpenAI-compatible endpoint\n"
    "    (e.g. Ollama at http://localhost:11434/v1); such endpoints are called\n"
    "    with a documented placeholder key.\n"
    "Configuration is read from .env (see .env.example) or environment variables."
)


def resolve_client(settings: Settings) -> LLMClient:
    """Build the real LLMClient under the documented credential policy.

    - ``OPENAI_API_KEY`` set → used as-is.
    - key empty but ``LLM_BASE_URL`` set (custom endpoint, assumed local /
      keyless) → the documented placeholder key is used; endpoints that do
      require authentication must still set ``OPENAI_API_KEY``.
    - neither → ``MissingCredentialsError`` with configuration guidance.
    """
    if settings.openai_api_key:
        return LLMClient(settings)
    if settings.llm_base_url:
        return LLMClient(
            settings.model_copy(update={"openai_api_key": LOCAL_ENDPOINT_PLACEHOLDER_KEY})
        )
    raise MissingCredentialsError(_CREDENTIALS_GUIDANCE)


# ---------------------------------------------------------------------------
# Generic entry: run_task
# ---------------------------------------------------------------------------

def _snapshot_files(root: Path) -> set[Path]:
    if not root.is_dir():
        return set()
    return {p for p in root.rglob("*") if p.is_file()}


def _newest_bundle_report(artifacts: tuple[Path, ...]) -> VerifyReport | None:
    """Independently verify the newest .json artifact as an ExperimentBundle."""
    bundles = [p for p in artifacts if p.suffix == ".json"]
    if not bundles:
        return None
    newest = max(bundles, key=lambda p: (p.stat().st_mtime_ns, p.name))
    return verify_bundle(newest)


async def run_task(
    goal: str,
    *,
    settings: Settings | None = None,
    client: LLMClientProtocol | None = None,
) -> PipelineResult:
    """Run one agent task through the full 8-tool registry and report artifacts.

    ``settings``: defaults to ``Settings()`` (.env / environment aware; callers
    can override e.g. ``Settings(data_sandbox_dir=...)`` to confine output).
    ``client``: any ``LLMClientProtocol`` implementation — inject a fake for
    deterministic tests; when omitted, ``resolve_client`` builds the real
    ``LLMClient`` under the documented credential policy.
    """
    settings = settings if settings is not None else Settings()
    if client is None:
        client = resolve_client(settings)

    sandbox = Path(settings.data_sandbox_dir)
    before = _snapshot_files(sandbox)
    registry = build_game_registry(settings)
    task_id = f"task-{uuid4().hex[:12]}"
    loop = AgentLoop(client=client, registry=registry, settings=settings, task_id=task_id)
    agent_result = await loop.run_task(goal)

    artifacts = tuple(sorted(_snapshot_files(sandbox) - before))
    return PipelineResult(
        status=agent_result.status,
        result=agent_result,
        artifacts=artifacts,
        bundle_verification=_newest_bundle_report(artifacts),
        html_verified=None,
    )


# ---------------------------------------------------------------------------
# Deterministic demo: run_demo
# ---------------------------------------------------------------------------

DEMO_BUNDLE_REL = "experiments/demo-agent-game.json"
DEMO_HTML_REL = "games/demo-agent-game.html"

# Generic demo experiment (deliberately paradigm-agnostic): single factor
# side (left/right), 2 blocks / 24 trials, choice response, correctness from
# the factor level. Values match examples/run_game_agent.py (B3 deliverable).
DEMO_SPEC: dict[str, object] = {
    "schema_version": 1,
    "name": "demo-agent-game",
    "version": "0.1.0",
    "seed": 11,
    "factors": [
        {"name": "side", "levels": [{"name": "left"}, {"name": "right"}]},
    ],
    "blocks": [
        {"name": "practice", "trial_count": 4},
        {"name": "main", "trial_count": 20},
    ],
    "constraints": {"balance": True},
    "responses": [
        {"name": "answer", "kind": "choice", "options": ["left", "right"],
         "correct_from": "side"}
    ],
    "timing": {"fixation_ms": 400, "stimulus_ms": None, "isi_ms": 600},
}

DEMO_GOAL = (
    "Generate a playable browser game for the following task: design a single-factor two-level "
    "choice-reaction experiment (factor side, levels left/right; practice 4 trials + main 20 "
    "trials, seed=11). Validate the design and generate trials first, export the bundle; then "
    "design a keyboard-driven GameSpec, validate it, and render a single-file HTML game."
)

_EXPECTED_DEMO_TOOLS = (
    "validate_experiment",
    "generate_trials",
    "export_experiment",
    "validate_game",
    "render_game",
)


class ScriptedLLM:
    """Pops preset responses round by round (duck-typed LLMClientProtocol).

    Records the full message history so verification can inspect the exact
    tool reports the "model" received.
    """

    def __init__(self, script: list[LLMResponse]) -> None:
        self._script = list(script)
        self.received_messages: list[list[dict[str, Any]]] = []

    @property
    def calls(self) -> int:
        return len(self.received_messages)

    async def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LLMResponse:
        self.received_messages.append([dict(m) for m in messages])
        index = len(self.received_messages)
        if index > len(self._script):
            raise AssertionError("ScriptedLLM script exhausted")
        return self._script[index - 1]


def _expected_demo_ref() -> dict[str, object]:
    """Precompute the six fingerprints (deterministic engine: matches the export)."""
    bundle = build_bundle(ExperimentSpec.model_validate(DEMO_SPEC))
    spec_part = bundle["spec"]  # type: ignore[index]
    repro = bundle["reproducibility"]  # type: ignore[index]
    return {
        "name": spec_part["name"],  # type: ignore[index]
        "version": spec_part["version"],  # type: ignore[index]
        "seed": spec_part["seed"],  # type: ignore[index]
        "config_fingerprint": repro["config_fingerprint"],  # type: ignore[index]
        "trials_fingerprint": repro["trials_fingerprint"],  # type: ignore[index]
        "bundle_sha256": bundle["bundle_sha256"],
    }


def demo_game_config() -> dict[str, object]:
    """The demo GameSpec (keyboard bindings; six references precomputed)."""
    return {
        "schema_version": 1,
        "game": {"name": "demo-agent-game", "version": "0.1.0"},
        "experiment_ref": _expected_demo_ref(),
        "scene": {
            "title": "Side Judgement",
            "instructions": "Each trial shows a side. Press [f] for left or [j] for right.",
        },
        "input": {
            "modalities": ["keyboard"],
            "bindings": [{"response_name": "answer", "keys": {"f": "left", "j": "right"}}],
        },
        "feedback": {"on_response": "outcome-text", "duration_ms": 300},
    }


def build_demo_script() -> list[LLMResponse]:
    """Preset response script: 5 tool calls + 1 final answer."""
    game = demo_game_config()

    def call(remote_id: str, name: str, arguments: dict[str, object]) -> LLMResponse:
        return LLMResponse(
            tool_calls=[
                ToolCallRequest(remote_id=remote_id, tool_name=name, arguments=arguments)
            ],
            finish_reason="tool_calls",
        )

    return [
        call("demo-1", "validate_experiment", {"config": DEMO_SPEC, "previous_errors": []}),
        call("demo-2", "generate_trials", {"config": DEMO_SPEC, "max_preview_trials": 8}),
        call("demo-3", "export_experiment", {"config": DEMO_SPEC, "path": DEMO_BUNDLE_REL}),
        call("demo-4", "validate_game",
             {"game_config": game, "bundle_path": DEMO_BUNDLE_REL, "previous_errors": []}),
        call("demo-5", "render_game",
             {"game_config": game, "bundle_path": DEMO_BUNDLE_REL,
              "output_path": DEMO_HTML_REL, "previous_errors": []}),
        LLMResponse(
            content=(
                "Done. Experiment bundle exported and verified; playable game "
                f"rendered at {DEMO_HTML_REL} (single-file HTML, file:// playable)."
            ),
            finish_reason="stop",
        ),
    ]


def _verify_demo_run(
    agent_result: AgentResult, client: ScriptedLLM
) -> list[str]:
    """Agent-level verification: status, tool order, tool ok, domain reports."""
    problems: list[str] = []
    if agent_result.status != "completed":
        problems.append(f"agent status is {agent_result.status!r}, expected 'completed'")
        return problems
    tool_calls = [
        str(e.payload.get("tool_name"))
        for e in agent_result.events
        if e.type == AgentEventType.tool_call
    ]
    if tool_calls != list(_EXPECTED_DEMO_TOOLS):
        problems.append(f"tool call sequence mismatch: {tool_calls}")
    bad = [
        str(e.payload.get("tool_call_id"))
        for e in agent_result.events
        if e.type == AgentEventType.tool_result and e.payload.get("ok") is not True
    ]
    if bad:
        problems.append(f"tool-level failures (BLOCKED): {bad}")
    if not client.received_messages:
        problems.append("no LLM rounds recorded")
        return problems
    reports = [
        str(m.get("content", ""))
        for m in client.received_messages[-1]
        if m.get("role") == "tool"
    ]
    if len(reports) != len(_EXPECTED_DEMO_TOOLS):
        problems.append(
            f"expected {len(_EXPECTED_DEMO_TOOLS)} tool reports in the final round, "
            f"got {len(reports)}"
        )
    return problems


def _verify_demo_html(sandbox: Path) -> bool | None:
    """Artifact-level verification: HTML byte-identical to a deterministic re-render."""
    bundle_path = sandbox / DEMO_BUNDLE_REL
    html_path = sandbox / DEMO_HTML_REL
    if not bundle_path.is_file() or not html_path.is_file():
        return None
    import json

    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    game_result = validate_game(demo_game_config(), bundle)
    if not game_result.valid or game_result.game_spec is None:
        return False
    expected_html = render_game_html(bundle, game_result.game_spec)
    return html_path.read_text(encoding="utf-8") == expected_html


async def run_demo(*, output_dir: str | Path | None = None) -> PipelineResult:
    """Run the deterministic scripted demo (no network, no keys, no real LLM).

    ``output_dir``: sandbox root for all generated files (defaults to the
    configured ``data_sandbox_dir``, i.e. ``data/``). Every experiment
    artifact stays inside it. Any verification failure raises
    ``PipelineVerificationError`` — nothing is silently ignored.
    """
    settings = (
        Settings(data_sandbox_dir=str(output_dir))
        if output_dir is not None
        else Settings()
    )
    sandbox = Path(settings.data_sandbox_dir)
    before = _snapshot_files(sandbox)

    client = ScriptedLLM(build_demo_script())
    registry = build_game_registry(settings)
    loop = AgentLoop(client=client, registry=registry, settings=settings, task_id="demo-game-agent")
    agent_result = await loop.run_task(DEMO_GOAL)

    artifacts = tuple(sorted(_snapshot_files(sandbox) - before))
    problems = _verify_demo_run(agent_result, client)
    bundle_verification = (
        verify_bundle(sandbox / DEMO_BUNDLE_REL)
        if (sandbox / DEMO_BUNDLE_REL).is_file()
        else None
    )
    if bundle_verification is None:
        problems.append(f"bundle file missing: {sandbox / DEMO_BUNDLE_REL}")
    elif not bundle_verification.ok:
        problems.append(f"bundle verification failed: {bundle_verification.detail}")
    html_verified = _verify_demo_html(sandbox)
    if html_verified is None:
        problems.append(f"html file missing: {sandbox / DEMO_HTML_REL}")
    elif html_verified is False:
        problems.append("html is not byte-identical to the deterministic render")
    if problems:
        raise PipelineVerificationError(problems)

    return PipelineResult(
        status=agent_result.status,
        result=agent_result,
        artifacts=artifacts,
        bundle_verification=bundle_verification,
        html_verified=html_verified,
    )
