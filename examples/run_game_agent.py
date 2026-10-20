"""B3 end-to-end demo: the full agent workflow driven by a scripted fake LLM (user-approved B3 scope).

One natural-language task → a single AgentLoop (reusing M1, no new framework) calling in order:

    validate_experiment → generate_trials → export_experiment
    → validate_game → render_game → single-file playable HTML

The LLM is an inline ScriptedLLM (a duck-typed LLMClientProtocol implementation): it pops preset
responses round by round, simulating "the model designs a valid ExperimentSpec and GameSpec". The
six experiment_ref fingerprints in the preset responses are precomputed by the deterministic engine
(build_bundle is byte-reproducible for the same spec+seed, so they necessarily match what export_experiment produces).

Zero real LLM, zero keys, zero network (runs even with CALC_AGENT_ENV_FILE=/dev/null).

Run (from the repo root):
    .venv/bin/python examples/run_game_agent.py

The sandbox root can be overridden via the DATA_SANDBOX_DIR environment variable (default data/).

Verification contract (any failure → non-zero exit, never silently ignored):
  run-level verify_agent_run: status completed, 5 tools called in order, all
  tool_result ok, and every domain report valid/rendered true;
  artifact-level verify_artifacts: independent verify_bundle check, bundle byte-identical
  to the deterministic recomputation (generated_at stripped), GameSpec validated against the
  actual bundle, HTML byte-identical to the deterministic render, dual fingerprint anchors present, trial count reconciled.

Open the game: open data/games/demo-agent-game.html directly in a browser (file://).
Note: browser prototype timing is approximate; not for formal data collection.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agent.game_registry import build_game_registry
from src.agent.loop import AgentLoop
from src.config import Settings
from src.experiment.canonical import canonical_json
from src.experiment.export import build_bundle
from src.experiment.game_render import render_game_html
from src.experiment.game_schemas import validate_game
from src.experiment.schemas import ExperimentSpec
from src.experiment.verify import verify_bundle
from src.models.events import AgentEventType
from src.models.llm import LLMResponse, ToolCallRequest

TASK_ID = "demo-game-agent"
BUNDLE_REL = "experiments/demo-agent-game.json"
HTML_REL = "games/demo-agent-game.html"

# Generic demo experiment (deliberately not bound to any cognitive paradigm):
# single factor side (left/right), 2 blocks / 24 trials, choice response, correctness from the factor level.
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

GOAL = (
    "Generate a playable browser game for the following task: design a single-factor two-level "
    "choice-reaction experiment (factor side, levels left/right; practice 4 trials + main 20 "
    "trials, seed=11). Validate the design and generate trials first, export the bundle; then "
    "design a keyboard-driven GameSpec, validate it, and render a single-file HTML game."
)

EXPECTED_TOOLS = [
    "validate_experiment",
    "generate_trials",
    "export_experiment",
    "validate_game",
    "render_game",
]


class ScriptedLLM:
    """Fake LLM popping preset responses round by round (duck-typed LLMClientProtocol; records the full message history)."""

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


def _expected_ref() -> dict[str, object]:
    """Precompute the six fingerprints of the export_experiment output (the deterministic engine guarantees they match the actual artifact)."""
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


def _game_config() -> dict[str, object]:
    """Preset GameSpec (simulating the LLM's game-design output; the six reference values come from deterministic precomputation)."""
    return {
        "schema_version": 1,
        "game": {"name": "demo-agent-game", "version": "0.1.0"},
        "experiment_ref": _expected_ref(),
        "scene": {
            "title": "Side Judgement",
            "instructions": (
                "Each trial shows a side. Press [f] for left or [j] for right."
            ),
        },
        "input": {
            "modalities": ["keyboard"],
            "bindings": [{"response_name": "answer", "keys": {"f": "left", "j": "right"}}],
        },
        "feedback": {"on_response": "outcome-text", "duration_ms": 300},
    }


def _call(remote_id: str, name: str, arguments: dict[str, object]) -> LLMResponse:
    return LLMResponse(
        tool_calls=[ToolCallRequest(remote_id=remote_id, tool_name=name, arguments=arguments)],
        finish_reason="tool_calls",
    )


def build_script() -> list[LLMResponse]:
    """Preset response script: 5 tool calls + 1 final answer."""
    game = _game_config()
    return [
        _call("demo-1", "validate_experiment",
              {"config": DEMO_SPEC, "previous_errors": []}),
        _call("demo-2", "generate_trials",
              {"config": DEMO_SPEC, "max_preview_trials": 8}),
        _call("demo-3", "export_experiment",
              {"config": DEMO_SPEC, "path": BUNDLE_REL}),
        _call("demo-4", "validate_game",
              {"game_config": game, "bundle_path": BUNDLE_REL, "previous_errors": []}),
        _call("demo-5", "render_game",
              {"game_config": game, "bundle_path": BUNDLE_REL,
               "output_path": HTML_REL, "previous_errors": []}),
        LLMResponse(
            content=(
                "Done. Experiment bundle exported and verified; playable game "
                f"rendered at {HTML_REL} (single-file HTML, file:// playable)."
            ),
            finish_reason="stop",
        ),
    ]


# ---------------------------------------------------------------------------
# Verification (two layers; any failure is collected as a problem, main decides the exit code)
# ---------------------------------------------------------------------------

def verify_agent_run(result: object, llm: ScriptedLLM) -> list[str]:
    """Run-level verification: AgentLoop status / tool sequence / tool-level ok / domain-level valid+rendered."""
    problems: list[str] = []
    status = getattr(result, "status", None)
    if status != "completed":
        problems.append(f"agent status is {status!r}, expected 'completed'")
        return problems

    events = list(getattr(result, "events", []))
    tool_calls = [
        str(e.payload.get("tool_name"))
        for e in events
        if e.type == AgentEventType.tool_call
    ]
    if tool_calls != EXPECTED_TOOLS:
        problems.append(f"tool call sequence mismatch: {tool_calls}")

    bad_results = [
        str(e.payload.get("tool_call_id"))
        for e in events
        if e.type == AgentEventType.tool_result and e.payload.get("ok") is not True
    ]
    if bad_results:
        problems.append(f"tool-level failures (BLOCKED): {bad_results}")

    # Domain reports: take all tool reports from the last round of message history (full, untruncated)
    if not llm.received_messages:
        problems.append("no LLM rounds recorded")
        return problems
    reports = [
        str(m.get("content", ""))
        for m in llm.received_messages[-1]
        if m.get("role") == "tool"
    ]
    if len(reports) != len(EXPECTED_TOOLS):
        problems.append(
            f"expected {len(EXPECTED_TOOLS)} tool reports in final round, got {len(reports)}"
        )
        return problems

    # reports are in call order: validate / generate / export / validate_game / render
    checks: list[tuple[str, str, dict[str, object] | None]] = []
    for label, text in zip(("validate_experiment", "generate_trials"), reports[:2]):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            problems.append(f"{label} report is not JSON")
            continue
        checks.append((label, "valid", payload))
    export_report = reports[2]
    if not export_report.startswith("wrote "):
        problems.append("export_experiment report does not start with 'wrote '")
    for label, text in zip(("validate_game", "render_game"), reports[3:5]):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            problems.append(f"{label} report is not JSON")
            continue
        checks.append((label, "valid" if label == "validate_game" else "rendered", payload))
    for label, key, payload in checks:
        if payload is None:
            continue
        if payload.get(key) is not True:
            problems.append(f"{label} domain check failed: {key} is not true")

    expected_trials = sum(
        int(b["trial_count"]) for b in DEMO_SPEC["blocks"]  # type: ignore[union-attr]
    )
    generate_payload = json.loads(reports[1]) if reports[1].startswith("{") else {}
    if generate_payload.get("trial_count") != expected_trials:
        problems.append(
            f"generate_trials trial_count mismatch: {generate_payload.get('trial_count')!r}"
        )
    render_payload = json.loads(reports[4]) if reports[4].startswith("{") else {}
    if render_payload.get("total_trials") != expected_trials:
        problems.append(
            f"render_game total_trials mismatch: {render_payload.get('total_trials')!r}"
        )
    return problems


def verify_artifacts(
    sandbox: Path,
    spec: dict[str, object],
    game_config: dict[str, object],
    bundle_rel: str,
    html_rel: str,
) -> list[str]:
    """Artifact-level verification: bundle integrity/reproducibility + HTML determinism + dual fingerprint anchors + trial-count consistency."""
    problems: list[str] = []
    bundle_path = sandbox / bundle_rel
    html_path = sandbox / html_rel

    if not bundle_path.is_file():
        return [f"bundle file missing: {bundle_path}"]
    if not html_path.is_file():
        return [f"html file missing: {html_path}"]

    # (1) independent integrity check (generator-free path: recompute both fingerprints)
    report = verify_bundle(bundle_path)
    if not report.ok:
        problems.append(f"verify_bundle failed: {report.detail}")
        return problems

    actual_bundle: dict[str, object] = json.loads(bundle_path.read_text(encoding="utf-8"))

    # (2) reproducibility: deterministic recomputation with the same spec+seed, byte-equivalent after stripping generated_at
    expected_bundle = build_bundle(ExperimentSpec.model_validate(spec))
    strip = lambda b: {k: v for k, v in b.items() if k != "generated_at"}  # noqa: E731
    if canonical_json(strip(actual_bundle)) != canonical_json(strip(expected_bundle)):
        problems.append("bundle on disk is not reproducible from spec+seed (byte mismatch)")
    if actual_bundle.get("bundle_sha256") != expected_bundle.get("bundle_sha256"):
        problems.append("bundle_sha256 differs from deterministic recomputation")

    # (3) validate the GameSpec against the actual bundle (failure → HTML untrusted, return immediately)
    game_result = validate_game(game_config, actual_bundle)
    if not game_result.valid or game_result.game_spec is None:
        codes = [f"{e.error_code}:{e.path}" for e in game_result.errors]
        problems.append(f"validate_game against actual bundle failed: {codes}")
        return problems

    # (4) HTML determinism: byte-identical to the pure-function render
    expected_html = render_game_html(actual_bundle, game_result.game_spec)
    actual_html = html_path.read_text(encoding="utf-8")
    if actual_html != expected_html:
        problems.append("html on disk is not byte-identical to deterministic render")

    # (5) fingerprint anchors and trial count (explicit recheck; implied by (4), double assurance)
    repro = actual_bundle["reproducibility"]  # type: ignore[index]
    for anchor_name, anchor in (
        ("bundle_sha256", actual_bundle.get("bundle_sha256")),
        ("trials_fingerprint", repro.get("trials_fingerprint")),  # type: ignore[union-attr]
    ):
        if anchor is None or str(anchor) not in actual_html:
            problems.append(f"html is missing fingerprint anchor {anchor_name}")
    expected_trials = sum(
        int(b["trial_count"]) for b in spec["blocks"]  # type: ignore[union-attr]
    )
    actual_trials = actual_bundle.get("trials")
    if not isinstance(actual_trials, list) or len(actual_trials) != expected_trials:
        problems.append(
            f"bundle trial count mismatch: expected {expected_trials}, "
            f"got {len(actual_trials) if isinstance(actual_trials, list) else 'n/a'}"
        )
    return problems


def main() -> None:
    settings = Settings()
    sandbox = Path(settings.data_sandbox_dir)

    llm = ScriptedLLM(build_script())
    registry = build_game_registry(settings)
    loop = AgentLoop(client=llm, registry=registry, settings=settings, task_id=TASK_ID)

    print("===== E2E demo: FakeLLM agent workflow =====")
    print(f"goal       : {GOAL[:72]}...")
    result = asyncio.run(loop.run_task(GOAL))

    problems = verify_agent_run(result, llm)
    problems += verify_artifacts(sandbox, DEMO_SPEC, _game_config(), BUNDLE_REL, HTML_REL)

    bundle_path = sandbox / BUNDLE_REL
    html_path = sandbox / HTML_REL
    bundle = json.loads(bundle_path.read_text(encoding="utf-8")) if bundle_path.is_file() else {}
    print(f"llm rounds : {llm.calls} (5 tool calls + 1 final)")
    print(f"event log  : logs/agent-{TASK_ID}.jsonl")
    if bundle:
        print(f"bundle     : {bundle_path} "
              f"(sha256={str(bundle.get('bundle_sha256'))[:16]}..., "
              f"trials={len(bundle.get('trials', []))})")  # type: ignore[arg-type]
    if html_path.is_file():
        print(f"game html  : {html_path} ({html_path.stat().st_size} bytes)")

    if problems:
        print("\n[E2E FAILED] validation problems (not silently ignored):")
        for p in problems:
            print(f"  - {p}")
        sys.exit(1)

    print("\n[E2E OK] all checks passed:")
    print("  - agent: completed, 5 tools in order, all tool results ok, all domain checks true")
    print("  - bundle: verify_bundle ok, byte-reproducible from spec+seed (generated_at stripped)")
    print("  - html: byte-identical to deterministic render, dual fingerprint anchors embedded")
    print("\nOpen the game in a browser (file://) and press any key to start:")
    print(f"    {html_path.resolve()}")
    print("Verify the bundle independently:")
    print(f"    .venv/bin/python -m src.experiment.verify {bundle_path}")
    print("Note: prototype timing is approximate; not for formal data collection.")


if __name__ == "__main__":
    main()
