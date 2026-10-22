"""M3-B agent design-workflow tests: design-first, tool-driven, self-checking (mock LLM).

Two structurally different research requirements drive the SAME generic workflow
through the real AgentLoop and the real tool registry (only the LLM is scripted):

- Case A (attention control / cue-validity orienting): two factors, label-derived
  correctness (correct_from), classic single-screen GameSpec. The agent's
  post-export check PASSES — the read-verify step confirms the design holds.
- Case B (short-term memory / sequence load): P0 variables (a factor-level count
  map = real load difference), content-driven correctness (correct_rule),
  P1 phases, explorable v2 GameSpec. The agent's FIRST validate_experiment call
  carries a genuine design mistake (incomplete count coverage), the tool reports
  V2_VAR_COUNT_COVERAGE, and the agent revises and re-validates — the
  iterate-on-validation-feedback path.

What the scripts encode is the mock model's OWN design and tool arguments (the
harness never authors the spec); the assertions then verify, against the real
exported artifacts, that the design the agent stated is the design the engine
produced — the same checks the system prompt instructs the agent to perform
via file_read (balance, per-condition content differences, content-following
answer keys).

No real LLM is called: this is the mock flow-test layer (real-model validation
is a separate, user-authorized step).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, cast

import pytest

from src.agent.game_registry import build_game_registry
from src.agent.loop import AgentLoop
from src.config import Settings
from src.experiment.export import build_bundle
from src.experiment.game_render import build_run_plan
from src.experiment.game_schemas import GameSpec
from src.experiment.schemas import ExperimentSpec
from src.experiment.verify import verify_bundle
from src.models.events import AgentEventType
from src.models.llm import LLMResponse, ToolCallRequest
from src.pipeline import ScriptedLLM

SANDBOX_ROOT = Path("data/.test-sandbox/design-flow")


def _cleanup(path: Path) -> None:
    try:
        shutil.rmtree(path)
    except OSError:
        pass


class _Script:
    """ScriptedLLM with a call() helper (tool-call responses with design content)."""

    def __init__(self, script: list[LLMResponse]) -> None:
        self.inner = ScriptedLLM(script)

    @property
    def received_messages(self) -> list[list[dict[str, Any]]]:
        return self.inner.received_messages

    # duck-typed LLMClientProtocol
    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMResponse:
        return await self.inner.chat(messages, tools)


def _call(remote_id: str, name: str, arguments: dict[str, object],
          content: str = "") -> LLMResponse:
    return LLMResponse(
        content=content,
        tool_calls=[ToolCallRequest(remote_id=remote_id, tool_name=name, arguments=arguments)],
        finish_reason="tool_calls",
    )


def _final(content: str) -> LLMResponse:
    return LLMResponse(content=content, finish_reason="stop")


def _run_agent(client: Any, sandbox: Path, goal: str) -> Any:
    settings = Settings(data_sandbox_dir=str(sandbox))
    registry = build_game_registry(settings)
    loop = AgentLoop(client=client, registry=registry, settings=settings,
                     task_id="design-flow-test")
    return loop.run_task(goal)


def _tool_calls(result: Any) -> list[str]:
    return [
        str(e.payload.get("tool_name"))
        for e in result.events
        if e.type == AgentEventType.tool_call
    ]


def _all_tools_ok(result: Any) -> bool:
    return all(
        e.payload.get("ok") is True
        for e in result.events
        if e.type == AgentEventType.tool_result
    )


def _design_statement(client: _Script) -> str:
    """The assistant message of round 1 (the design stated before/with the first tool call)."""
    round2 = client.received_messages[1]  # messages as seen by the SECOND chat call
    assistant = [m for m in round2 if m.get("role") == "assistant"]
    assert assistant, "no assistant message recorded for round 1"
    return str(assistant[-1].get("content", ""))


# ---------------------------------------------------------------------------
# Case A — attention control: cue-validity orienting (classic layout)
# ---------------------------------------------------------------------------

A_BUNDLE_REL = "experiments/cue-orienting.json"
A_HTML_REL = "games/cue-orienting.html"

A_SPEC: dict[str, object] = {
    "schema_version": 2,
    "name": "cue-orienting",
    "version": "0.1.0",
    "seed": 77,
    "factors": [
        {"name": "cue", "levels": [{"name": "valid"}, {"name": "invalid"}]},
        {"name": "target_side", "levels": [{"name": "left"}, {"name": "right"}]},
    ],
    "blocks": [{"name": "main", "trial_count": 16}],
    "constraints": {"balance": True},
    "responses": [
        {"name": "hit", "kind": "choice", "options": ["left", "right"],
         "correct_from": "target_side"}
    ],
    "timing": {"fixation_ms": 300, "stimulus_ms": None, "isi_ms": 400},
    "stimulus_spec": {
        "factors": {
            "cue": {
                "levels": {
                    "valid": [["Cue points to {target_side}.", "Respond to the target side."]],
                    "invalid": [["The cue flickers, uninformative.", "Respond to the target side."]],
                },
                "match_line_count": True,
            }
        },
        "pools": {},
    },
}

A_DESIGN = (
    "Design: Manipulation - cue validity (valid: the cue names this trial's actual target "
    "side; invalid: the cue carries no side information), crossed with target side "
    "(left/right). Measured - choice accuracy and RT for naming the target side. "
    "Player action - press f (left) or j (right). Mapping - faster/more accurate responses "
    "on valid-cue trials index attentional orienting; 16 balanced trials."
)


def _a_game_config() -> dict[str, object]:
    bundle = build_bundle(ExperimentSpec.model_validate(A_SPEC))
    spec = cast(dict[str, object], bundle["spec"])
    repro = cast(dict[str, object], bundle["reproducibility"])
    return {
        "schema_version": 1,
        "game": {"name": "cue-orienting", "version": "0.1.0"},
        "experiment_ref": {
            "name": spec["name"], "version": spec["version"], "seed": spec["seed"],
            "config_fingerprint": repro["config_fingerprint"],
            "trials_fingerprint": repro["trials_fingerprint"],
            "bundle_sha256": bundle["bundle_sha256"],
        },
        "scene": {
            "title": "Signal Watch",
            "instructions": "A cue, then a target. Press [f] left or [j] right for the target side.",
        },
        "input": {
            "modalities": ["keyboard"],
            "bindings": [{"response_name": "hit", "keys": {"f": "left", "j": "right"}}],
        },
        "feedback": {"on_response": "outcome-text", "duration_ms": 300},
    }


A_GOAL = (
    "Design an attention-control experiment as a browser game: does a spatial cue speed up "
    "responding to a target? 16 balanced trials, keyboard responses."
)


def _a_script() -> list[LLMResponse]:
    game = _a_game_config()
    return [
        _call("a-1", "validate_experiment", {"config": A_SPEC, "previous_errors": []},
              content=A_DESIGN),
        _call("a-2", "generate_trials", {"config": A_SPEC, "max_preview_trials": 8}),
        _call("a-3", "export_experiment", {"config": A_SPEC, "path": A_BUNDLE_REL}),
        _call("a-4", "file_read", {"path": A_BUNDLE_REL}),
        _call("a-5", "validate_game",
              {"game_config": game, "bundle_path": A_BUNDLE_REL, "previous_errors": []}),
        _call("a-6", "render_game",
              {"game_config": game, "bundle_path": A_BUNDLE_REL,
               "output_path": A_HTML_REL, "previous_errors": []}),
        _final(
            "Done. The cue-validity orienting experiment was generated and rendered at "
            f"{A_HTML_REL}. I read the exported bundle and verified the design: 16 trials, "
            "4 per cue x side combination; valid-cue trials present the actual target side "
            "in the cue line while invalid-cue trials do not; correct answers follow the "
            "target side. Bundle fingerprints verified."
        ),
    ]


@pytest.mark.asyncio
async def test_design_flow_attention_control() -> None:
    sandbox = SANDBOX_ROOT / "case-a"
    _cleanup(sandbox)
    sandbox.mkdir(parents=True, exist_ok=True)
    try:
        client = _Script(_a_script())
        result = await _run_agent(client, sandbox, A_GOAL)

        # workflow shape: design stated with the first tool call, then the tool chain
        assert result.status == "completed", result.result
        assert _all_tools_ok(result)
        assert _tool_calls(result) == [
            "validate_experiment", "generate_trials", "export_experiment",
            "file_read", "validate_game", "render_game",
        ]
        design = _design_statement(client)
        for element in ("Manipulation", "Measured", "Player action", "Mapping"):
            assert element in design, f"design statement missing {element!r}"

        # artifacts exist and the bundle verifies independently
        bundle_path = sandbox / A_BUNDLE_REL
        html_path = sandbox / A_HTML_REL
        assert bundle_path.is_file() and html_path.is_file()
        report = verify_bundle(bundle_path)
        assert report.ok, report.detail

        # the agent's design actually holds in the exported bundle (the same
        # check file_read made available to the model)
        import json
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        trials = cast(list[dict[str, object]], bundle["trials"])
        assert len(trials) == 16
        combos: dict[tuple[str, str], int] = {}
        for t in trials:
            factors = cast(dict[str, str], t["factors"])
            key = (factors["cue"], factors["target_side"])
            combos[key] = combos.get(key, 0) + 1
            lines = cast(list[str], cast(dict[str, object], t["stimulus"])["lines"])
            cue_line = lines[0]
            if factors["cue"] == "valid":
                assert factors["target_side"] in cue_line, t  # cue names the real side
            else:
                assert factors["target_side"] not in cue_line, t  # cue carries no side info
        assert set(combos.values()) == {4}, combos  # balanced

        # the rendered run plan scores by the target side (correct_from)
        game = GameSpec.model_validate(_a_game_config())
        plan = build_run_plan(bundle, game)
        steps = [s for s in cast(list[dict[str, object]], plan["steps"])
                 if s.get("type") == "trial"]
        assert len(steps) == 16
        for step, t in zip(steps, trials):
            factors = cast(dict[str, str], t["factors"])
            assert cast(dict[str, object], step["correct"]) == {"hit": factors["target_side"]}
    finally:
        _cleanup(sandbox)


# ---------------------------------------------------------------------------
# Case B — short-term memory: sequence load x probe relation (phased, explore layout)
# ---------------------------------------------------------------------------

B_BUNDLE_REL = "experiments/memory-vault.json"
B_HTML_REL = "games/memory-vault.html"

B_TOKENS = ["amber", "basalt", "cobalt", "dune", "ember", "frost", "gale", "harbor"]

B_SPEC_FIXED: dict[str, object] = {
    "schema_version": 2,
    "name": "memory-vault",
    "version": "0.1.0",
    "seed": 4242,
    "factors": [
        {"name": "load", "levels": [{"name": "short"}, {"name": "long"}]},
        {"name": "relation", "levels": [{"name": "match"}, {"name": "mismatch"}]},
    ],
    "blocks": [{"name": "main", "trial_count": 12}],
    "constraints": {"balance": True},
    "responses": [
        {
            "name": "judge",
            "kind": "choice",
            "options": ["match", "mismatch"],
            "correct_rule": {
                "op": "in",
                "left": {"var": "probe"},
                "right": {"var": "seq"},
                "true_option": "match",
                "false_option": "mismatch",
            },
        }
    ],
    "timing": {"fixation_ms": 200, "stimulus_ms": None, "isi_ms": 200},
    "stimulus_spec": {
        "factors": {},
        "pools": {"tokens": list(B_TOKENS)},
        "variables": [
            {"name": "seq", "pool": "tokens",
             "count": {"factor": "load", "levels": {"short": 3, "long": 5}}},
            {"name": "probe", "when": {"relation": "match"},
             "copy_from": {"var": "seq", "index": "any"}},
            {"name": "probe", "when": {"relation": "mismatch"},
             "pool": "tokens", "count": 1, "exclude": ["seq"]},
        ],
        "phases": [
            {"name": "encoding", "lines": ["Memorize: {var:seq}"],
             "duration_ms": 400, "advance": "auto", "response_window": False},
            {"name": "retention", "lines": ["Hold the sequence..."],
             "duration_ms": 300, "advance": "auto", "response_window": False},
            {"name": "probe", "lines": ["Probe: {var:probe}"],
             "duration_ms": None, "advance": "auto", "response_window": True},
        ],
    },
}


def _b_spec_broken() -> dict[str, object]:
    """The mock agent's first design attempt: a real mistake — the load count
    map covers only one level (the model forgot the 'long' level)."""
    import copy
    spec = copy.deepcopy(B_SPEC_FIXED)
    stimulus = cast(dict[str, object], spec["stimulus_spec"])
    variables = cast(list[dict[str, object]], stimulus["variables"])
    cast(dict[str, object], variables[0])["count"] = {"factor": "load", "levels": {"short": 3}}
    return spec


B_DESIGN = (
    "Design: Manipulation - memory load (short: 3-item sequence vs long: 5-item sequence) "
    "crossed with probe relation (match: the probe reuses one item from the sequence; "
    "mismatch: the probe is drawn outside it). Measured - match-judgement accuracy and RT. "
    "Player action - explore the vault, open marked crates; each crate plays one trial "
    "(memorize phase, hold phase, then a probe phase where pressing s (match) or "
    "d (mismatch) is recorded). Mapping - accuracy/RT falling with load and the "
    "load x relation interaction index short-term memory; answers are scored from the "
    "actual sequence content, not the condition labels."
)


def _b_game_config() -> dict[str, object]:
    bundle = build_bundle(ExperimentSpec.model_validate(B_SPEC_FIXED))
    spec = cast(dict[str, object], bundle["spec"])
    repro = cast(dict[str, object], bundle["reproducibility"])
    keys = {"s": "match", "d": "mismatch"}
    rooms: dict[str, object] = {}
    layout = [
        ("hub", ["west-wing", "east-wing"], range(1, 5)),
        ("west-wing", ["hub"], range(5, 9)),
        ("east-wing", ["hub"], range(9, 13)),
    ]
    for room_id, exits, crates in layout:
        rooms[room_id] = {
            "title": room_id.replace("-", " ").title(),
            "description": f"{room_id.replace('-', ' ')} of the memory vault.",
            "exits": {target: f"to the {target.replace('-', ' ')}" for target in exits},
            "objects": [
                {
                    "object_id": f"crate-{i}",
                    "label": f"crate {i}",
                    "inspect_text": "A marked crate; opening it starts a controlled trial.",
                    "role": "encounter",
                }
                for i in crates
            ],
        }
    return {
        "schema_version": 2,
        "game": {"name": "memory-vault", "version": "0.1.0"},
        "experiment_ref": {
            "name": spec["name"], "version": spec["version"], "seed": spec["seed"],
            "config_fingerprint": repro["config_fingerprint"],
            "trials_fingerprint": repro["trials_fingerprint"],
            "bundle_sha256": bundle["bundle_sha256"],
        },
        "scene": {
            "title": "The Memory Vault",
            "instructions": "Open marked crates. Memorize the sequence, hold it, then judge the probe: [s] match, [d] mismatch.",
        },
        "input": {
            "modalities": ["keyboard"],
            "bindings": [{"response_name": "judge", "keys": keys}],
        },
        "feedback": {"on_response": "correctness-flash", "duration_ms": 200},
        "flow": {"ready_screen": True, "block_breaks": False, "end_screen": "summary"},
        "gamification": {"score": True, "progress_bar": True, "streak_bonus": False},
        "world": {"start_room": "hub", "rooms": rooms},
        "narrative": {
            "intro": "Twelve marked crates across three wings.",
            "block_briefings": {"main": "Controlled section: memorize, hold, judge."},
            "ending_bands": [
                {"min_accuracy": 0.0, "text": "The vault seals itself."},
                {"min_accuracy": 0.8, "text": "The vault hums in approval."},
            ],
        },
        "mechanics": {
            "layout": "explore-and-encounter",
            "inspect_objects": True,
            "trial_trigger": "explore-encounter",
        },
        "mapping": {
            "trial_trigger": "explore-encounter",
            "encounter_objects": [f"crate-{i}" for i in range(1, 13)],
            "response_bindings": [{"response_name": "judge", "keys": keys}],
            "creative_freedom": [
                "theme", "room_labels", "object_labels", "narrative_text", "feedback_style",
            ],
            "controlled_invariants": [
                "trial_order", "conditions", "stimulus_content", "correct_answers", "timing",
            ],
        },
    }


B_GOAL = (
    "Design a short-term-memory experiment as an explorable browser game: players explore "
    "a vault and open crates; each crate presents a short sequence to memorize, then a probe "
    "to judge as matching the sequence or not. Manipulate sequence length and probe relation, "
    "12 balanced trials, keyboard answers."
)


def _b_script() -> list[LLMResponse]:
    game = _b_game_config()
    return [
        _call("b-1", "validate_experiment",
              {"config": _b_spec_broken(), "previous_errors": []}, content=B_DESIGN),
        _call("b-2", "validate_experiment",
              {"config": B_SPEC_FIXED,
               "previous_errors": [
                   "V2_VAR_COUNT_COVERAGE:stimulus_spec.variables[0].count.levels"
               ]}),
        _call("b-3", "generate_trials", {"config": B_SPEC_FIXED, "max_preview_trials": 12}),
        _call("b-4", "export_experiment", {"config": B_SPEC_FIXED, "path": B_BUNDLE_REL}),
        _call("b-5", "file_read", {"path": B_BUNDLE_REL}),
        _call("b-6", "validate_game",
              {"game_config": game, "bundle_path": B_BUNDLE_REL, "previous_errors": []}),
        _call("b-7", "render_game",
              {"game_config": game, "bundle_path": B_BUNDLE_REL,
               "output_path": B_HTML_REL, "previous_errors": []}),
        _final(
            "Done. The memory-vault experiment was generated and rendered at "
            f"{B_HTML_REL}. My first validation attempt failed (the load count map missed "
            "the 'long' level); after fixing it, validation, generation, export, game "
            "validation and rendering all passed. I read the exported bundle and verified: "
            "12 trials, 3 per load x relation combination; short trials carry 3-item "
            "sequences and long trials 5-item ones; match probes reuse a sequence item "
            "while mismatch probes never appear in the sequence; every answer key follows "
            "the actual sequence content."
        ),
    ]


@pytest.mark.asyncio
async def test_design_flow_short_term_memory_with_iteration() -> None:
    sandbox = SANDBOX_ROOT / "case-b"
    _cleanup(sandbox)
    sandbox.mkdir(parents=True, exist_ok=True)
    try:
        client = _Script(_b_script())
        result = await _run_agent(client, sandbox, B_GOAL)

        assert result.status == "completed", result.result
        assert _all_tools_ok(result)
        # the iterate-on-validation-feedback path: first validate reports the
        # mistake, the second (revised) call passes
        assert _tool_calls(result) == [
            "validate_experiment", "validate_experiment", "generate_trials",
            "export_experiment", "file_read", "validate_game", "render_game",
        ]
        first_validate = [
            e for e in result.events
            if e.type == AgentEventType.tool_result
        ][0]
        assert "V2_VAR_COUNT_COVERAGE" in str(first_validate.payload.get("result_summary"))
        design = _design_statement(client)
        for element in ("Manipulation", "Measured", "Player action", "Mapping"):
            assert element in design, f"design statement missing {element!r}"

        # artifacts
        bundle_path = sandbox / B_BUNDLE_REL
        html_path = sandbox / B_HTML_REL
        assert bundle_path.is_file() and html_path.is_file()
        assert verify_bundle(bundle_path).ok

        # design implementation, recomputed from the exported bundle
        import json
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        trials = cast(list[dict[str, object]], bundle["trials"])
        assert len(trials) == 12
        combos: dict[tuple[str, str], int] = {}
        for t in trials:
            factors = cast(dict[str, str], t["factors"])
            stimulus = cast(dict[str, object], t["stimulus"])
            phases = cast(list[dict[str, object]], stimulus["phases"])
            seq = cast(list[str], phases[0]["lines"])[0].removeprefix("Memorize: ").split()
            probe = cast(list[str], phases[2]["lines"])[0].removeprefix("Probe: ")
            key = (factors["load"], factors["relation"])
            combos[key] = combos.get(key, 0) + 1
            # load is a REAL content difference: 3 vs 5 distinct tokens
            if factors["load"] == "short":
                assert len(seq) == 3 and len(set(seq)) == 3, t
            else:
                assert len(seq) == 5 and len(set(seq)) == 5, t
            # probe relation is a verifiable stimulus relationship
            if factors["relation"] == "match":
                assert probe in seq, t
            else:
                assert probe not in seq, t
            # the answer key follows the materialized content
            expected = "match" if probe in seq else "mismatch"
            assert cast(dict[str, str], t["correct"])["judge"] == expected, t
        assert set(combos.values()) == {3}, combos

        # the explorable game renders with phased playback
        html = html_path.read_text(encoding="utf-8")
        assert "layout-explore-and-encounter" in html
        assert "playPhases" in html
    finally:
        _cleanup(sandbox)
