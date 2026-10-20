"""游戏工具：validate_game（Phase B 契约 §10，B1 冻结）。

风格对齐 experiment_tools.py：Input 模型 + 内部 _GameBlocked 异常 +
BLOCKED: 前缀 + build_*(settings) -> ToolSpec 工厂。

两级错误契约（沿用 Phase A §5.4 语义）：
- 工具级失败（非 dict、体积护栏、沙箱拒绝、bundle 不可加载）→ ok=False；
- 领域级失败（GameSpec 规则 G1~G6）→ 永远 ok=True + valid:false（B0 validate_game
  的结果原样回传——规则不重复实现）。

边界（§10）：validate_game 对 data/ 沙箱只读；不存在任何修改 ExperimentBundle
的代码路径。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, Field

from src.config import Settings
from src.experiment.canonical import canonical_json
from src.experiment.game_schemas import (
    MAX_GAME_SPEC_BYTES,
    GameValidationIssue,
    validate_game,
)
from src.models.tool_result import ToolResult
from src.models.tool_spec import ToolSpec
from src.tools._sandbox_io import SandboxBlocked, validate_sandbox_path


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
