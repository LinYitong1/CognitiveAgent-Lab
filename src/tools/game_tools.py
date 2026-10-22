"""Game tools: validate_game (B1, contract §10) + render_game (B2, contract §11.8).

Style aligned with experiment_tools.py: Input model + internal _GameBlocked exception +
BLOCKED: prefix + build_*(settings) -> ToolSpec factories.

Two-tier error contract (inheriting the Phase A §5.4 semantics):
- tool-level failure (non-dict, size guard, sandbox refusal, unloadable bundle, oversized HTML) → ok=False;
- domain-level failure (GameSpec rules G1~G6) → always ok=True + valid:false + rendered:false
  (B0 validate_game's result passed through verbatim - no rule duplication; nothing rendered, nothing written).

Boundary (§10/§11): the game tools treat the ExperimentBundle as read-only; render_game's only write
is placing the rendered HTML inside the data/ sandbox (five-step rule steps 1~3+5; step 4 is the HTML size guard).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, Field

from src.config import Settings
from src.experiment.canonical import canonical_json, sha256_hex
from src.experiment.game_render import MAX_RENDERED_HTML_BYTES, render_game_html
from src.experiment.game_schemas import (
    MAX_GAME_SPEC_BYTES,
    GameValidationIssue,
    validate_game,
)
from src.models.tool_result import ToolResult
from src.models.tool_spec import ToolSpec
from src.tools._sandbox_io import SandboxBlocked, validate_sandbox_path, write_sandbox_file


class _GameBlocked(Exception):
    """Tool-level security/guard refusal (→ BLOCKED: prefix)."""


class ValidateGameInput(BaseModel):
    """validate_game arguments (contract §10)."""

    game_config: dict[str, object] = Field(  # the GameSpec JSON object (generated inline by the LLM)
        description=(
            "The GameSpec JSON object itself, no wrapper. schema_version 1 keys: "
            "game{name,version},experiment_ref{name,version,seed,config_fingerprint,"
            "trials_fingerprint,bundle_sha256},scene{title,instructions,layout,theme,assets},"
            "input{modalities,bindings[{response_name,keys}]},"
            "feedback{on_response,duration_ms},flow{ready_screen,block_breaks,end_screen},"
            "gamification{score,progress_bar,streak_bonus}. "
            "schema_version 2 adds OPTIONAL sections world, narrative, mechanics, mapping "
            "(all default null; absent == null): "
            "world{start_room,rooms{<room_id>:{title,description,exits{<room_id>:<label>},"
            "objects[{object_id,label,inspect_text,role:'flavour'|'encounter'}]}}} - "
            "max 8 rooms, 6 objects/room, every room reachable from start_room. "
            "narrative{intro,block_briefings{<block>:text},ending_bands[{min_accuracy,text}]}. "
            "mechanics{layout:'explore-and-encounter',trial_trigger:'explore-encounter',"
            "inspect_objects}. mapping{trial_trigger:'explore-encounter',"
            "encounter_objects[object_id...],response_bindings[{response_name,keys}],"
            "creative_freedom[],controlled_invariants[]} - encounter object ids must "
            "reference role=encounter objects (each listed exactly once; count >= trial "
            "count); creative_freedom values from theme,room_labels,object_labels,"
            "narrative_text,feedback_style; controlled_invariants values from trial_order,"
            "conditions,stimulus_content,correct_answers,timing. keys = single lowercase "
            "letters. Trials are consumed in bundle order (monotonic cursor): exploration "
            "order never changes conditions, stimuli, trial count, or correct answers."
        )
    )
    bundle_path: str = Field(min_length=1)  # ExperimentBundle JSON path relative to the data/ sandbox root
    previous_errors: list[str] = Field(default_factory=list)  # error_code:path fingerprints of previous rounds


def _game_config_size_guard(game_config: dict[str, object]) -> None:
    """Size guard: game_config serialized bytes > 256KB → refuse (reuses the B0 limit)."""
    try:
        size = len(canonical_json(game_config).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise _GameBlocked("game config not serializable") from exc
    if size > MAX_GAME_SPEC_BYTES:
        raise _GameBlocked("game config too large")


def _load_bundle(bundle_path: str, sandbox: Path) -> dict[str, object]:
    """Load the ExperimentBundle read-only from the data/ sandbox (five-step rule steps 1~3 reused)."""
    try:
        target = validate_sandbox_path(bundle_path, sandbox)
    except SandboxBlocked as exc:
        raise _GameBlocked(f"bundle path rejected: {exc}") from exc
    if not target.is_file():
        raise _GameBlocked(f"bundle not found: {bundle_path}")
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _GameBlocked(f"bundle not loadable: {exc}") from exc
    if not isinstance(data, dict):
        raise _GameBlocked("bundle must be a JSON object")
    return data


def _issue_payload(issue: GameValidationIssue) -> dict[str, object]:
    return issue.model_dump()


def _stalled_issues(
    errors: list[GameValidationIssue], previous_errors: list[str]
) -> tuple[bool, list[GameValidationIssue]]:
    """Stalled decision (§10 step 3, same protocol as Phase A §5.4):
    any current error_code:path fingerprint appearing ≥2 times in previous_errors."""
    current = [f"{e.error_code}:{e.path}" for e in errors]
    stalled = any(previous_errors.count(fp) >= 2 for fp in current)
    if not stalled:
        return False, errors
    result = list(errors)
    for fp in current:
        count = previous_errors.count(fp)
        if count >= 2:
            result.append(
                GameValidationIssue(
                    error_code="ITERATION_STALLED",
                    path="<root>",
                    message=f"error fingerprint {fp} submitted {count + 1} times without progress",
                    suggestion="stop resubmitting; summarize the unresolved conflict and ask the user to decide",
                )
            )
    return True, result


async def _execute_validate_game(args: ValidateGameInput, sandbox: Path) -> ToolResult:
    try:
        _game_config_size_guard(args.game_config)
    except _GameBlocked as exc:
        return ToolResult(ok=False, error=f"BLOCKED: {exc}")
    try:
        bundle = _load_bundle(args.bundle_path, sandbox)
    except _GameBlocked as exc:
        return ToolResult(ok=False, error=f"BLOCKED: {exc}")

    result = validate_game(args.game_config, bundle)
    stalled, errors = _stalled_issues(result.errors, args.previous_errors)

    payload: dict[str, object] = {
        "valid": result.valid,
        "stalled": stalled,
        "game_config_fingerprint": result.game_config_fingerprint,
        "errors": [_issue_payload(e) for e in errors],
        "warnings": [_issue_payload(w) for w in result.warnings],
    }
    return ToolResult(ok=True, result=canonical_json(payload))


def build_validate_game_spec(settings: Settings) -> ToolSpec:
    """Build validate_game's ToolSpec (idempotent, sandbox read-only, low)."""
    sandbox = Path(settings.data_sandbox_dir)

    async def executor(base: Any) -> ToolResult:
        return await _execute_validate_game(cast(ValidateGameInput, base), sandbox)

    return ToolSpec(
        name="validate_game",
        description=(
            "Validate GameSpec JSON (presentation layer) against an ExperimentBundle "
            "already exported in data/ sandbox. game_config must be the GameSpec object "
            "itself, no wrapper; see the game_config field description for the full "
            "schema of both schema_version 1 (classic single-screen) and schema_version 2 "
            "(explorable rooms: optional world, narrative, mechanics, mapping sections). "
            "Copy experiment_ref values exactly from the bundle file. bundle_path is the "
            "bundle file path inside data/ sandbox. For explorable v2 games: layout "
            "explore-and-encounter, trial_trigger explore-encounter, one encounter object "
            "per trial, response bindings keyed by single lowercase letters; exploration "
            "never changes conditions, stimuli, trial count, or correct answers."
        ),
        input_model=ValidateGameInput,
        idempotency="idempotent",
        risk_level="low",
        executor=executor,
    )


class RenderGameInput(BaseModel):
    """render_game arguments (contract §11.8)."""

    game_config: dict[str, object]  # the GameSpec JSON object (must pass validate_game)
    bundle_path: str = Field(min_length=1)  # ExperimentBundle path relative to the data/ sandbox root
    output_path: str = Field(min_length=1)  # sandbox path of the rendered HTML (e.g. games/x.html)
    previous_errors: list[str] = Field(default_factory=list)  # error_code:path fingerprints of previous rounds


async def _execute_render_game(args: RenderGameInput, sandbox: Path) -> ToolResult:
    """render_game execution flow (contract §11.8 steps ①~⑥)."""
    # ① game_config size guard
    try:
        _game_config_size_guard(args.game_config)
    except _GameBlocked as exc:
        return ToolResult(ok=False, error=f"BLOCKED: {exc}")
    # ② read-only bundle load
    try:
        bundle = _load_bundle(args.bundle_path, sandbox)
    except _GameBlocked as exc:
        return ToolResult(ok=False, error=f"BLOCKED: {exc}")
    # ③ precondition check (B0 validate_game, zero rule duplication): failure → nothing rendered, nothing written
    result = validate_game(args.game_config, bundle)
    stalled, errors = _stalled_issues(result.errors, args.previous_errors)
    if not result.valid or result.game_spec is None:
        payload: dict[str, object] = {
            "rendered": False,
            "valid": False,
            "stalled": stalled,
            "game_config_fingerprint": result.game_config_fingerprint,
            "errors": [_issue_payload(e) for e in errors],
            "warnings": [_issue_payload(w) for w in result.warnings],
        }
        return ToolResult(ok=True, result=canonical_json(payload))

    # ④ render + HTML size guard (five-step rule step 4)
    html = render_game_html(bundle, result.game_spec)
    data = html.encode("utf-8")
    if len(data) > MAX_RENDERED_HTML_BYTES:
        return ToolResult(ok=False, error="BLOCKED: rendered html too large")

    # ⑤ sandbox write (five-step rule steps 1~3 + 5)
    try:
        target = validate_sandbox_path(args.output_path, sandbox)
        write_sandbox_file(target, data)
    except SandboxBlocked as exc:
        return ToolResult(ok=False, error=f"BLOCKED: {exc}")

    # ⑥ success payload
    trials = bundle.get("trials")
    payload = {
        "rendered": True,
        "path": args.output_path,
        "html_sha256": sha256_hex(html),
        "bytes": len(data),
        "total_trials": len(trials) if isinstance(trials, list) else 0,
    }
    return ToolResult(ok=True, result=canonical_json(payload))


def build_render_game_spec(settings: Settings) -> ToolSpec:
    """Build render_game's ToolSpec (writes to disk → non-idempotent/medium, aligned with export_experiment)."""
    sandbox = Path(settings.data_sandbox_dir)

    async def executor(base: Any) -> ToolResult:
        return await _execute_render_game(cast(RenderGameInput, base), sandbox)

    return ToolSpec(
        name="render_game",
        description=(
            "Render a validated GameSpec and its ExperimentBundle into a single-file "
            "playable HTML game (opens via file://, no network or external resources). "
            "game_config must be the GameSpec object itself (same schema as "
            "validate_game); it must pass validation against the bundle, otherwise "
            "nothing is rendered. bundle_path is the ExperimentBundle file inside "
            "data/ sandbox. output_path is the HTML file to create inside data/ "
            "sandbox (for example games/my-game.html). Returns rendered path, "
            "html_sha256, bytes, total_trials."
        ),
        input_model=RenderGameInput,
        idempotency="non-idempotent",
        risk_level="medium",
        executor=executor,
    )
