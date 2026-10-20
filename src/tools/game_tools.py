"""游戏工具：validate_game（B1，契约 §10）+ render_game（B2，契约 §11.8）。

风格对齐 experiment_tools.py：Input 模型 + 内部 _GameBlocked 异常 +
BLOCKED: 前缀 + build_*(settings) -> ToolSpec 工厂。

两级错误契约（沿用 Phase A §5.4 语义）：
- 工具级失败（非 dict、体积护栏、沙箱拒绝、bundle 不可加载、HTML 超护栏）→ ok=False；
- 领域级失败（GameSpec 规则 G1~G6）→ 永远 ok=True + valid:false + rendered:false
  （B0 validate_game 的结果原样回传——规则不重复实现；不渲染、不写文件）。

边界（§10/§11）：游戏工具对 ExperimentBundle 只读；render_game 唯一写动作是
把渲染产物 HTML 写入 data/ 沙箱（沙箱五步规则 1~3+5，第 4 步为 HTML 体积护栏）。
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
    """工具级安全/护栏拒绝（→ BLOCKED: 前缀）。"""


class ValidateGameInput(BaseModel):
    """validate_game 参数（契约 §10）。"""

    game_config: dict[str, object]  # GameSpec 的 JSON 对象（LLM 直接内联生成）
    bundle_path: str = Field(min_length=1)  # 相对 data/ 沙箱根的 ExperimentBundle JSON 路径
    previous_errors: list[str] = Field(default_factory=list)  # 此前轮次 error_code:path 指纹


def _game_config_size_guard(game_config: dict[str, object]) -> None:
    """体积护栏：game_config 序列化字节 > 256KB → 拒绝（复用 B0 上限）。"""
    try:
        size = len(canonical_json(game_config).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise _GameBlocked("game config not serializable") from exc
    if size > MAX_GAME_SPEC_BYTES:
        raise _GameBlocked("game config too large")


def _load_bundle(bundle_path: str, sandbox: Path) -> dict[str, object]:
    """从 data/ 沙箱只读加载 ExperimentBundle（沙箱五步规则第 1~3 步复用）。"""
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
    """stalled 判定（§10 第 3 步，与 Phase A §5.4 同协议）：
    任一当次 error_code:path 指纹在 previous_errors 出现 ≥2 次。"""
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
                    suggestion="停止重复提交，总结未解决冲突并请用户裁决",
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
    """构造 validate_game 的 ToolSpec（幂等、只读沙箱、low）。"""
    sandbox = Path(settings.data_sandbox_dir)

    async def executor(base: Any) -> ToolResult:
        return await _execute_validate_game(cast(ValidateGameInput, base), sandbox)

    return ToolSpec(
        name="validate_game",
        description=(
            "Validate GameSpec JSON (presentation layer) against an ExperimentBundle "
            "already exported in data/ sandbox. game_config must be the GameSpec object "
            "itself, no wrapper. Top keys: schema_version(=1),game{name,version},"
            "experiment_ref{name,version,seed,config_fingerprint,trials_fingerprint,"
            "bundle_sha256},scene{title,instructions,layout,theme,assets},"
            "input{modalities,bindings[{response_name,keys}]},"
            "feedback{on_response,duration_ms},flow{ready_screen,block_breaks,end_screen},"
            "gamification{score,progress_bar,streak_bonus}. Copy experiment_ref values "
            "exactly from the bundle file. bundle_path is the bundle file path inside "
            "data/ sandbox."
        ),
        input_model=ValidateGameInput,
        idempotency="idempotent",
        risk_level="low",
        executor=executor,
    )


class RenderGameInput(BaseModel):
    """render_game 参数（契约 §11.8）。"""

    game_config: dict[str, object]  # GameSpec 的 JSON 对象（须通过 validate_game）
    bundle_path: str = Field(min_length=1)  # 相对 data/ 沙箱根的 ExperimentBundle 路径
    output_path: str = Field(min_length=1)  # 渲染产物 HTML 的沙箱内路径（如 games/x.html）
    previous_errors: list[str] = Field(default_factory=list)  # 此前轮次 error_code:path 指纹


async def _execute_render_game(args: RenderGameInput, sandbox: Path) -> ToolResult:
    """render_game 执行流程（契约 §11.8 步骤①~⑥）。"""
    # ① game_config 体积护栏
    try:
        _game_config_size_guard(args.game_config)
    except _GameBlocked as exc:
        return ToolResult(ok=False, error=f"BLOCKED: {exc}")
    # ② bundle 只读加载
    try:
        bundle = _load_bundle(args.bundle_path, sandbox)
    except _GameBlocked as exc:
        return ToolResult(ok=False, error=f"BLOCKED: {exc}")
    # ③ 前置校验（B0 validate_game，规则零重复）：不通过 → 不渲染、不写文件
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

    # ④ 渲染 + HTML 体积护栏（沙箱五步规则第 4 步）
    html = render_game_html(bundle, result.game_spec)
    data = html.encode("utf-8")
    if len(data) > MAX_RENDERED_HTML_BYTES:
        return ToolResult(ok=False, error="BLOCKED: rendered html too large")

    # ⑤ 沙箱写盘（五步规则 1~3 + 5）
    try:
        target = validate_sandbox_path(args.output_path, sandbox)
        write_sandbox_file(target, data)
    except SandboxBlocked as exc:
        return ToolResult(ok=False, error=f"BLOCKED: {exc}")

    # ⑥ 成功 payload
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
    """构造 render_game 的 ToolSpec（写盘 → non-idempotent/medium，对齐 export_experiment）。"""
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
