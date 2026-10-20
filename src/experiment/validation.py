"""约束语义验证层（契约 §4/§2.2，冻结）。

职责边界：只做约束语义与可满足性（C1/C2/C3、UNSAT 各形态、支持性错误码）；
结构与引用存在性归 schemas.py 的 Pydantic 层（禁止在此重复）。

验证顺序（契约文末清单）：Pydantic 解析 → 支持性 → 约束语义 → 逐 block 可满足性。
错误上限 20 条 + errors_truncated（上下文膨胀护栏，风险 R-2）。
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ValidationError

from src.experiment.canonical import canonical_json, sha256_hex
from src.experiment.generation import (
    allocation_has_rounding,
    combo_weight,
    effective_weights,
    filter_block,
    filter_mutex,
    mutex_pairs,
    positive_weight_combos,
)
from src.experiment.schemas import ExperimentSpec

MAX_ERRORS = 20  # errors 上限（§5.1）

RATIO_SUM_TOLERANCE = 1e-6


class ErrorCode:
    """错误码稳定枚举（契约 §4.4 表全量，冻结）。"""

    SCHEMA_INVALID = "SCHEMA_INVALID"
    UNKNOWN_PARADIGM = "UNKNOWN_PARADIGM"
    UNSUPPORTED_CONSTRAINT = "UNSUPPORTED_CONSTRAINT"
    CONSTRAINT_CONFLICT = "CONSTRAINT_CONFLICT"
    RATIO_SUM = "RATIO_SUM"
    BLOCK_FILTER_EMPTY = "BLOCK_FILTER_EMPTY"
    TRIAL_COUNT_MISMATCH = "TRIAL_COUNT_MISMATCH"
    MUTEX_VIOLATION = "MUTEX_VIOLATION"
    CORRECT_FROM_UNKNOWN = "CORRECT_FROM_UNKNOWN"
    SEARCH_EXHAUSTED = "SEARCH_EXHAUSTED"  # Phase A 不可触发（框架预留，§4.2/§4.3）
    ITERATION_STALLED = "ITERATION_STALLED"


class WarningCode:
    """警告码枚举（契约 §4.4）。"""

    WEIGHT_IGNORED = "WEIGHT_IGNORED"
    RATIO_ROUNDED = "RATIO_ROUNDED"


# UNSAT 类错误码集合（§4.4 类别映射；test_unsat_error_code_mapping 的断言口径）
UNSAT_ERROR_CODES: tuple[str, ...] = (
    ErrorCode.CONSTRAINT_CONFLICT,
    ErrorCode.RATIO_SUM,
    ErrorCode.BLOCK_FILTER_EMPTY,
    ErrorCode.TRIAL_COUNT_MISMATCH,
    ErrorCode.MUTEX_VIOLATION,
)


class ValidationIssue(BaseModel):
    """验证问题（errors 与 warnings 共用，契约 §4.1）。"""

    error_code: str  # 稳定枚举（§4.4 表）
    path: str  # JSON 路径，如 "constraints.ratios[0].ratios" / "factors[1].levels"
    message: str  # 人类可读描述（含实际值）
    suggestion: str  # 修复建议（LLM 行动指令）


class ValidationResult(BaseModel):
    """validate_spec 的返回。"""

    spec: ExperimentSpec | None  # Pydantic 解析失败时为 None
    valid: bool
    errors: list[ValidationIssue]
    warnings: list[ValidationIssue]
    config_fingerprint: str | None  # schema 解析失败时为 None（§5.1）
    errors_truncated: bool
    stats: dict[str, object]


def _format_loc(loc: object) -> str:
    """Pydantic loc 拼接为 JSON 路径（契约 §2.2：如 factors[1].levels）。"""
    parts: list[str] = []
    for part in loc if isinstance(loc, (list, tuple)) else ():  # type: ignore[union-attr]
        if isinstance(part, int):
            parts[-1] = f"{parts[-1]}[{part}]" if parts else f"[{part}]"
        else:
            parts.append(str(part))
    return ".".join(parts)


def _schema_issues(exc: ValidationError) -> list[ValidationIssue]:
    """每条 Pydantic 错误包装为一个 SCHEMA_INVALID issue（§2.2）。"""
    issues: list[ValidationIssue] = []
    for error in exc.errors():
        path = _format_loc(error.get("loc", ()))
        message = str(error.get("msg", "schema validation failed"))
        issues.append(
            ValidationIssue(
                error_code=ErrorCode.SCHEMA_INVALID,
                path=path,
                message=f"schema 校验失败于 {path or '<root>'}: {message}",
                suggestion="按 ExperimentSpec schema 修正 path 指向的字段后重新调用 validate_experiment",
            )
        )
    return issues


def _stats(spec: ExperimentSpec | None, config: Mapping[str, object]) -> dict[str, object]:
    """验证报告统计（§5.1）；schema 解析失败时从原始 config 尽力提取。"""
    if spec is not None:
        return {
            "trial_count": sum(block.trial_count for block in spec.blocks),
            "factor_count": len(spec.factors),
            "blocks": len(spec.blocks),
            "combinations": spec.combination_count(),
            "plugin": None,
        }
    factors = config.get("factors")
    blocks = config.get("blocks")
    factor_list = factors if isinstance(factors, list) else []
    block_list = blocks if isinstance(blocks, list) else []
    combinations = 1
    for raw in factor_list:
        levels = raw.get("levels") if isinstance(raw, dict) else None
        if isinstance(levels, list):
            combinations *= len(levels)
    trial_count = sum(
        raw["trial_count"]
        for raw in block_list
        if isinstance(raw, dict) and isinstance(raw.get("trial_count"), int)
    )
    return {
        "trial_count": trial_count,
        "factor_count": len(factor_list),
        "blocks": len(block_list),
        "combinations": combinations,
        "plugin": None,
    }


def _check_support(spec: ExperimentSpec, errors: list[ValidationIssue]) -> None:
    """支持性检查：Phase A 无插件系统、无序列约束（§4.4）。"""
    if spec.paradigm is not None:
        errors.append(
            ValidationIssue(
                error_code=ErrorCode.UNKNOWN_PARADIGM,
                path="paradigm",
                message=(
                    f"paradigm={spec.paradigm!r} 不受支持：Phase A 未实现插件系统，"
                    f"paradigm 必须为 null（已注册插件清单：[]）"
                ),
                suggestion="移除 paradigm 字段（或置为 null）并清空 paradigm_params，走纯通用路径",
            )
        )
    if spec.constraints.max_repeat is not None:
        errors.append(
            ValidationIssue(
                error_code=ErrorCode.UNSUPPORTED_CONSTRAINT,
                path="constraints.max_repeat",
                message=(
                    f"max_repeat={spec.constraints.max_repeat} 当前不受支持"
                    "（Phase B 支持序列约束，当前请移除该字段）"
                ),
                suggestion="删除 constraints.max_repeat 字段后重新验证",
            )
        )


def _check_constraint_semantics(
    spec: ExperimentSpec, errors: list[ValidationIssue], warnings: list[ValidationIssue]
) -> None:
    """C1/C2/C3 与 RATIO_SUM、CORRECT_FROM_UNKNOWN、同因素互斥声明（§4.4）。"""
    constraints = spec.constraints

    # C1：balance 与 ratios 互斥（声明矛盾，验证期判定）
    if constraints.balance and constraints.ratios:
        errors.append(
            ValidationIssue(
                error_code=ErrorCode.CONSTRAINT_CONFLICT,
                path="constraints",
                message=(
                    f"balance=true 与 ratios 非空互斥（当前 ratios 声明了 "
                    f"{len(constraints.ratios)} 个因素）"
                ),
                suggestion="删除 ratios（全等权）或将 balance 置 false（用自定义比例）",
            )
        )

    # RATIO_SUM：每条 RatioRule 的和 ≈ 1.0（容差 1e-6）
    for i, rule in enumerate(constraints.ratios):
        total = sum(rule.ratios.values())
        if abs(total - 1.0) > RATIO_SUM_TOLERANCE:
            errors.append(
                ValidationIssue(
                    error_code=ErrorCode.RATIO_SUM,
                    path=f"constraints.ratios[{i}].ratios",
                    message=(
                        f"因素 {rule.factor!r} 的 ratios 和为 {round(total, 6)}，"
                        f"须 ≈1.0（容差 1e-6）"
                    ),
                    suggestion="调整 ratios 值使和为 1.0（显式排除某水平用 0.0 而非缩小总和）",
                )
            )

    # C2：显式权重被覆盖的两种情形（警告，不影响 valid 判定）
    ratio_factors = {rule.factor for rule in constraints.ratios}
    for fi, factor in enumerate(spec.factors):
        for li, level in enumerate(factor.levels):
            if level.weight == 1.0:
                continue
            if constraints.balance:
                warnings.append(
                    ValidationIssue(
                        error_code=WarningCode.WEIGHT_IGNORED,
                        path=f"factors[{fi}].levels[{li}].weight",
                        message=(
                            f"因素 {factor.name!r} 水平 {level.name!r} 的显式 weight={level.weight} "
                            "被 balance=true 的全等权覆盖（有效权重 = 1/水平数）"
                        ),
                        suggestion="删除该 weight（等权无需声明）或将 balance 置 false 以启用权重",
                    )
                )
            elif factor.name in ratio_factors:
                warnings.append(
                    ValidationIssue(
                        error_code=WarningCode.WEIGHT_IGNORED,
                        path=f"factors[{fi}].levels[{li}].weight",
                        message=(
                            f"因素 {factor.name!r} 水平 {level.name!r} 的显式 weight={level.weight} "
                            "被 ratios 声明覆盖（有效权重按 ratios 取值）"
                        ),
                        suggestion="删除该 weight 或移除对应的 ratios 规则，避免意图歧义",
                    )
                )

    # CORRECT_FROM_UNKNOWN：correct_from 只允许已声明因素名（Phase A 无插件派生字段）
    factor_names = set(spec.factor_names())
    for ri, response in enumerate(spec.responses):
        if response.correct_from is not None and response.correct_from not in factor_names:
            errors.append(
                ValidationIssue(
                    error_code=ErrorCode.CORRECT_FROM_UNKNOWN,
                    path=f"responses[{ri}].correct_from",
                    message=(
                        f"correct_from={response.correct_from!r} 不是已声明因素名"
                        f"（已声明因素：{spec.factor_names()}）"
                    ),
                    suggestion="将 correct_from 改为某个已声明的因素名，或置为 null",
                )
            )

    # MUTEX_VIOLATION（同因素内两水平——无意义声明）
    level_owner: dict[str, list[str]] = {}
    for factor in spec.factors:
        for level in factor.levels:
            level_owner.setdefault(level.name, []).append(factor.name)
    for mi, pair in enumerate(constraints.mutually_exclusive):
        shared_factors = set(level_owner.get(pair[0], [])) & set(level_owner.get(pair[1], []))
        if shared_factors:
            errors.append(
                ValidationIssue(
                    error_code=ErrorCode.MUTEX_VIOLATION,
                    path=f"constraints.mutually_exclusive[{mi}]",
                    message=(
                        f"互斥声明 {pair} 指向同一因素内的水平（无意义声明："
                        "同一试次内同因素本就只能取一个水平）"
                    ),
                    suggestion="删除该条 mutually_exclusive 声明",
                )
            )


def _check_block_satisfiability(
    spec: ExperimentSpec,
    errors: list[ValidationIssue],
    warnings: list[ValidationIssue],
) -> None:
    """逐 block 可满足性：MUTEX_VIOLATION（组合空）/ BLOCK_FILTER_EMPTY /
    TRIAL_COUNT_MISMATCH / RATIO_ROUNDED（§4.4，全部验证期可判定）。"""
    full_space = spec.expanded_combinations()
    pairs = mutex_pairs(spec)

    # MUTEX_VIOLATION：互斥声明使（全局）可用组合为空
    mutex_filtered = filter_mutex(full_space, pairs)
    if pairs and not mutex_filtered:
        errors.append(
            ValidationIssue(
                error_code=ErrorCode.MUTEX_VIOLATION,
                path="constraints.mutually_exclusive",
                message=(
                    f"互斥声明 {spec.constraints.mutually_exclusive} 剔除后可用组合为空"
                    f"（展开组合数 {len(full_space)}）"
                ),
                suggestion="减少 mutually_exclusive 声明数量，保留至少一个可用组合",
            )
        )
        return  # 组合空间已空，逐 block 判定无意义

    weights = effective_weights(spec)

    for bi, block in enumerate(spec.blocks):
        # BLOCK_FILTER_EMPTY：factor_filter 语义过滤后（对全展开空间）可用组合为空
        filtered_on_full = filter_block(spec, block, full_space)
        if not filtered_on_full:
            errors.append(
                ValidationIssue(
                    error_code=ErrorCode.BLOCK_FILTER_EMPTY,
                    path=f"blocks[{bi}].factor_filter",
                    message=(
                        f"block {block.name!r} 的 factor_filter 过滤后可用组合为空"
                        f"（展开组合数 {len(full_space)}）"
                    ),
                    suggestion="放宽 factor_filter 的水平允许列表，使其至少圈定一个组合",
                )
            )
            continue
        # TRIAL_COUNT_MISMATCH：filter + 互斥剔除 + 有效权重过滤后正权重组合数为 0
        available = filter_block(spec, block, mutex_filtered)
        positive = positive_weight_combos(spec, available, weights)
        if not positive:
            errors.append(
                ValidationIssue(
                    error_code=ErrorCode.TRIAL_COUNT_MISMATCH,
                    path=f"blocks[{bi}]",
                    message=(
                        f"block {block.name!r} 经 factor_filter + 互斥剔除 + 有效权重"
                        f"（含 ratios 置 0）过滤后正权重组合数为 0，而 trial_count="
                        f"{block.trial_count} > 0"
                    ),
                    suggestion="调整 factor_filter / mutually_exclusive / ratios 置 0 的水平，"
                    "使该 block 至少保留一个正权重组合",
                )
            )
            continue
        # RATIO_ROUNDED：largest remainder 分配存在非整数 exact 值（警告）
        combo_weights = [combo_weight(spec, combo, weights) for combo in positive]
        if allocation_has_rounding(block.trial_count, combo_weights):
            warnings.append(
                ValidationIssue(
                    error_code=WarningCode.RATIO_ROUNDED,
                    path=f"blocks[{bi}].trial_count",
                    message=(
                        f"block {block.name!r} 的 trial_count={block.trial_count} 对 "
                        f"{len(positive)} 个可用组合做 largest remainder 分配存在非整数精确值"
                        "（频数为 floor/floor+1 近似，非严格等频）"
                    ),
                    suggestion="如需严格等频，将 trial_count 调整为可用组合数的整数倍",
                )
            )


def validate_spec(config: Mapping[str, object]) -> ValidationResult:
    """验证入口：Pydantic → 支持性 → 约束语义 → 逐 block 可满足性（冻结顺序）。"""
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []

    spec: ExperimentSpec | None = None
    try:
        spec = ExperimentSpec.model_validate(dict(config))
    except ValidationError as exc:
        errors.extend(_schema_issues(exc))
        return _finalize(None, errors, warnings, None, _stats(None, config))

    assert spec is not None
    _check_support(spec, errors)
    _check_constraint_semantics(spec, errors, warnings)
    _check_block_satisfiability(spec, errors, warnings)
    fingerprint = sha256_hex(canonical_json(spec.model_dump()))
    return _finalize(spec, errors, warnings, fingerprint, _stats(spec, config))


def _finalize(
    spec: ExperimentSpec | None,
    errors: list[ValidationIssue],
    warnings: list[ValidationIssue],
    fingerprint: str | None,
    stats: dict[str, object],
) -> ValidationResult:
    """收尾：errors 截断至 20 条并置 errors_truncated（§5.1）。"""
    truncated = len(errors) > MAX_ERRORS
    return ValidationResult(
        spec=spec,
        valid=not errors,
        errors=errors[:MAX_ERRORS],
        warnings=warnings,
        config_fingerprint=fingerprint,
        errors_truncated=truncated,
        stats=stats,
    )


def issue_fingerprint(issue: ValidationIssue) -> str:
    """error_code:path 指纹（ITERATION_STALLED 软协议的判定单元，§5.1）。"""
    return f"{issue.error_code}:{issue.path}"


def stalled_fingerprints(
    errors: list[ValidationIssue], previous_errors: list[str]
) -> list[str]:
    """当次 errors 中在 previous_errors 里出现 ≥2 次的指纹（MA-1 触发语义）。"""
    current = [issue_fingerprint(issue) for issue in errors]
    return [fp for fp in current if previous_errors.count(fp) >= 2]


def iteration_stalled_issue(fingerprint: str, occurrences: int) -> ValidationIssue:
    """ITERATION_STALLED issue（§5.1 冻结 suggestion 文案）。"""
    return ValidationIssue(
        error_code=ErrorCode.ITERATION_STALLED,
        path=fingerprint,
        message=f"同一验证错误指纹 {fingerprint!r} 已重复出现 {occurrences} 次",
        suggestion="停止重复提交，总结未解决冲突并请用户裁决",
    )
