"""实验三工具：validate_experiment / generate_trials / export_experiment（契约 §5）。

风格对齐 calc.py / file_write.py：Input 模型 + 内部 _ExperimentBlocked 异常 +
BLOCKED: 前缀 + build_*(settings) -> ToolSpec 工厂。

两级错误契约（§5.4）：
- 工具级失败（输入非 dict、序列化失败、安全拒绝等基础设施错误）→ ok=False；
- 领域级失败（spec 问题）→ 永远 ok=True + valid:false（回传 LLM 不带 ERROR: 前缀）。

护栏：config 序列化字节 > 256KB → BLOCKED: config too large（三工具同守）；
export 的 canonical bundle 字节 > 1MB → BLOCKED: export too large（OUT-7 / R-6）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, Field

from src.config import Settings
from src.experiment.canonical import canonical_json
from src.experiment.export import build_bundle
from src.experiment.generation import (
    ENGINE_SPEC_VERSION,
    compute_frequency,
    generate_trials,
)
from src.experiment.schemas import ExperimentSpec
from src.experiment.validation import (
    ValidationIssue,
    ValidationResult,
    iteration_stalled_issue,
    stalled_fingerprints,
    validate_spec,
)
from src.models.tool_result import ToolResult
from src.models.tool_spec import ToolSpec
from src.tools._sandbox_io import SandboxBlocked, validate_sandbox_path, write_sandbox_file

MAX_CONFIG_BYTES = 256 * 1024  # config 输入体积护栏（§5.1）
MAX_BUNDLE_BYTES = 1_048_576  # 1MB 导出上限（OUT-7 / R-6，与 file_write 同量级）

# R1 修订（2026-10-20，用户批准 PA-14 修复选项 A）：validate_experiment description 内嵌的
# ExperimentSpec 最小完整示例（契约 §5.1 R1 修订块冻结文本）。作为模块级常量单一来源，
# 测试与本 description 共用同一对象，防实现/测试各抄一份漂移。
_SPEC_EXAMPLE_JSON = (
    '{"schema_version":1,"name":"example-cueing","version":"0.1.0","seed":7,"paradigm":null,'
    '"paradigm_params":{},"factors":[{"name":"cue_type","levels":[{"name":"valid"},{"name":"invalid"}]},'
    '{"name":"target_side","levels":[{"name":"left"},{"name":"right"}]}],'
    '"blocks":[{"name":"practice","trial_count":4,"factor_filter":{},"shuffle_within":true},'
    '{"name":"main","trial_count":40,"factor_filter":{},"shuffle_within":true}],'
    '"constraints":{"balance":true},'
    '"responses":[{"name":"locate_target","kind":"choice","options":["left","right"],'
    '"correct_from":"target_side"}],'
    '"timing":{"fixation_ms":400,"stimulus_ms":null,"isi_ms":800}}'
)

_GENERATE_NOTE = "full sequence reproducible via export_experiment with identical spec+seed"


class _ExperimentBlocked(Exception):
    """工具级安全/护栏拒绝（→ BLOCKED: 前缀）。"""


class ValidateExperimentInput(BaseModel):
    """validate_experiment 参数（契约 §5.1）。"""

    config: dict[str, object]  # ExperimentSpec 的 JSON 对象（LLM 直接内联生成）
    previous_errors: list[str] = Field(default_factory=list)  # 此前轮次 error_code:path 指纹列表


class GenerateTrialsInput(BaseModel):
    """generate_trials 参数（契约 §5.2）。"""

    config: dict[str, object]
    max_preview_trials: int = Field(default=8, ge=0, le=50)  # 回传 LLM 的试次预览条数


class ExportExperimentInput(BaseModel):
    """export_experiment 参数（契约 §5.3）。"""

    config: dict[str, object]
    path: str = Field(min_length=1)  # 相对 data/ 沙箱根的输出路径


def _config_size_guard(config: dict[str, object]) -> None:
    """输入体积护栏：config 序列化字节 > 256KB → 拒绝（§5.1 第 1 步）。"""
    try:
        size = len(json.dumps(config, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise _ExperimentBlocked("config too large") from exc
    if size > MAX_CONFIG_BYTES:
        raise _ExperimentBlocked("config too large")


def _validation_payload(result: ValidationResult, stalled: bool) -> dict[str, object]:
    """验证报告 JSON（§5.1 输出结构；generate 失败路径与其同构）。"""
    return {
        "valid": result.valid,
        "stalled": stalled,
        "config_fingerprint": result.config_fingerprint,
        "engine_spec_version": ENGINE_SPEC_VERSION,
        "errors": [issue.model_dump() for issue in result.errors],
        "warnings": [issue.model_dump() for issue in result.warnings],
        "errors_truncated": result.errors_truncated,
        "stats": result.stats,
    }


def _invalid_spec_result(result: ValidationResult) -> ToolResult:
    """领域级失败：ok=True + valid:false（不带 ERROR: 前缀，§5.4）。"""
    return ToolResult(ok=True, result=canonical_json(_validation_payload(result, False)))


def _stalled_check(
    result: ValidationResult, previous_errors: list[str]
) -> tuple[bool, list[ValidationIssue]]:
    """stalled 判定（§5.1 第 3 步）：任一当次指纹在 previous_errors 出现 ≥2 次。"""
    repeated = stalled_fingerprints(result.errors, previous_errors)
    if not repeated:
        return False, list(result.errors)
    stalled_errors = list(result.errors)
    for fingerprint in repeated:
        stalled_errors.append(
            iteration_stalled_issue(fingerprint, previous_errors.count(fingerprint))
        )
    return True, stalled_errors


async def _execute_validate(args: ValidateExperimentInput) -> ToolResult:
    try:
        _config_size_guard(args.config)
    except _ExperimentBlocked as exc:
        return ToolResult(ok=False, error=f"BLOCKED: {exc}")
    result = validate_spec(args.config)
    stalled, errors = _stalled_check(result, args.previous_errors)
    payload = _validation_payload(result, stalled)
    payload["errors"] = [issue.model_dump() for issue in errors]
    return ToolResult(ok=True, result=canonical_json(payload))


async def _execute_generate(
    args: GenerateTrialsInput, max_attempts: int
) -> ToolResult:
    try:
        _config_size_guard(args.config)
    except _ExperimentBlocked as exc:
        return ToolResult(ok=False, error=f"BLOCKED: {exc}")
    result = validate_spec(args.config)
    if not result.valid or result.spec is None:
        return _invalid_spec_result(result)  # 验证失败不生成（§5.2）
    spec = result.spec
    generated = generate_trials(spec, max_attempts=max_attempts)
    frequency = compute_frequency(spec, generated.trials)
    preview: list[dict[str, object]] = [
        {"index": trial.index, "block": trial.block, "factors": trial.factors}
        for trial in generated.trials[: args.max_preview_trials]
    ]
    payload: dict[str, object] = {
        "valid": True,
        "config_fingerprint": generated.config_fingerprint,
        "trials_fingerprint": generated.trials_fingerprint,
        "trial_count": len(generated.trials),
        "engine_spec_version": generated.engine_spec_version,
        "plugin_used": generated.plugin_used,
        "frequency": frequency,
        "preview": preview,
        "note": _GENERATE_NOTE,
    }
    return ToolResult(ok=True, result=canonical_json(payload))


async def _execute_export(args: ExportExperimentInput, sandbox: Path) -> ToolResult:
    try:
        _config_size_guard(args.config)
    except _ExperimentBlocked as exc:
        return ToolResult(ok=False, error=f"BLOCKED: {exc}")
    result = validate_spec(args.config)
    if not result.valid or result.spec is None:
        return _invalid_spec_result(result)  # 不导出无效实验（§5.3 第 2 步）
    spec = result.spec
    # export 内部重新确定性生成（关键裁定：不接受 generate 的输出，§5.3）
    bundle = build_bundle(spec)
    text = canonical_json(bundle)
    data = text.encode("utf-8")
    if len(data) > MAX_BUNDLE_BYTES:
        return ToolResult(ok=False, error="BLOCKED: export too large")
    try:
        target = validate_sandbox_path(args.path, sandbox)
        write_sandbox_file(target, data)
    except SandboxBlocked as exc:
        return ToolResult(ok=False, error=f"BLOCKED: {exc}")
    repro = cast(dict[str, object], bundle["reproducibility"])
    trials_fp = str(repro["trials_fingerprint"])
    bundle_sha = str(bundle["bundle_sha256"])
    summary = (
        f"wrote {args.path} ({len(data)} bytes, "
        f"trials_fingerprint={trials_fp}, bundle_sha256={bundle_sha})"
    )
    return ToolResult(ok=True, result=summary)


def build_validate_spec(settings: Settings) -> ToolSpec:
    """构造 validate_experiment 的 ToolSpec（幂等、只读、low）。"""
    async def executor(base: Any) -> ToolResult:
        return await _execute_validate(cast(ValidateExperimentInput, base))

    return ToolSpec(
        name="validate_experiment",
        description=(
            "校验实验规格（ExperimentSpec JSON）的 schema 合法性与约束可满足性，"
            "返回机器可读验证报告（错误含 error_code/path/suggestion）。修改 spec 后可重复调用。"
            "config 的值必须就是 ExperimentSpec JSON 对象本身——顶层直接是 schema_version/name/seed 等字段，"
            "禁止再包一层（不要包在 inputs、experimentSpec、config 等任何外层键内）。"
            "必需顶层字段：schema_version(=1)、name、seed、paradigm(Phase A 必须为 null)、"
            "paradigm_params(必须为 {})、factors(每项 {name, levels:[{name, weight?}]}，水平名因素内唯一)、"
            "blocks(每项 {name, trial_count, factor_filter(默认 {}), shuffle_within(默认 true)}，块名唯一)、"
            "constraints({balance?, ratios?, mutually_exclusive?})、"
            "responses(每项 {name, kind(choice|text|rating), options(kind=choice 必填非空), "
            "scale(kind=rating 必填 [min,max]), correct_from?(已声明的因素名)}，名唯一)、"
            "timing({fixation_ms?, stimulus_ms?(null=直至响应), isi_ms?})。"
            "最小完整示例（把 factors/levels/blocks/responses/timing/seed 换成任务要求的内容即可）："
            + _SPEC_EXAMPLE_JSON
        ),
        input_model=ValidateExperimentInput,
        idempotency="idempotent",
        risk_level="low",
        executor=executor,
    )


def build_generate_spec(settings: Settings) -> ToolSpec:
    """构造 generate_trials 的 ToolSpec（幂等、纯函数、不落盘、low）。"""
    max_attempts = settings.experiment_max_search_attempts  # SEARCH_EXHAUSTED 框架能力参数（§4.2）

    async def executor(base: Any) -> ToolResult:
        return await _execute_generate(cast(GenerateTrialsInput, base), max_attempts)

    return ToolSpec(
        name="generate_trials",
        description=(
            "按实验规格确定性生成完整试次序列（同 spec+seed 结果逐字节相同）。返回序列指纹与"
            "各因素水平频数统计，供核对设计意图；不写任何文件。完整序列由 export_experiment 用"
            "同一 spec+seed 确定性重新生成并落盘。"
        ),
        input_model=GenerateTrialsInput,
        idempotency="idempotent",
        risk_level="low",
        executor=executor,
    )


def build_export_spec(settings: Settings) -> ToolSpec:
    """构造 export_experiment 的 ToolSpec（非幂等、落盘、medium）。"""
    sandbox = Path(settings.data_sandbox_dir)

    async def executor(base: Any) -> ToolResult:
        return await _execute_export(cast(ExportExperimentInput, base), sandbox)

    return ToolSpec(
        name="export_experiment",
        description=(
            "把实验规格物化为自包含实验导出包（ExperimentBundle：规范化 spec + 全量试次 + 可重复性"
            "元数据 + SHA-256 完整性指纹），写入 data/ 沙箱内指定路径（覆盖已存在文件）。"
        ),
        input_model=ExportExperimentInput,
        idempotency="non-idempotent",
        risk_level="medium",
        executor=executor,
    )
