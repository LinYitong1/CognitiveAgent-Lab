"""Constraint-semantics validation layer (contract §4/§2.2, frozen).

Responsibility boundary: only constraint semantics and satisfiability
(C1/C2/C3, all UNSAT forms, support error codes); structure and reference
existence belong to the Pydantic layer in schemas.py (no duplication here).

Validation order (checklist at end of contract): Pydantic parse → support →
constraint semantics → per-block satisfiability. Error cap of 20 plus
errors_truncated (context-bloat guard, risk R-2).

Note (2026-10-20, user-approved English-first standardisation): human-readable
message/suggestion texts are English; error codes, paths, and the
error_code:path fingerprint protocol are unchanged.
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
from src.experiment.schemas import ExperimentSpec, _V2_OPTIONAL_FIELDS, spec_dump
from src.experiment.stimulus import (
    validate_correct_rules,
    validate_derived_spec,
    validate_measures,
    validate_phases,
    validate_stimulus_spec,
    validate_variables,
)

MAX_ERRORS = 20  # errors cap (§5.1)

RATIO_SUM_TOLERANCE = 1e-6


class ErrorCode:
    """Stable error-code enumeration (full contract §4.4 table, frozen)."""

    SCHEMA_INVALID = "SCHEMA_INVALID"
    UNKNOWN_PARADIGM = "UNKNOWN_PARADIGM"
    UNSUPPORTED_CONSTRAINT = "UNSUPPORTED_CONSTRAINT"
    CONSTRAINT_CONFLICT = "CONSTRAINT_CONFLICT"
    RATIO_SUM = "RATIO_SUM"
    BLOCK_FILTER_EMPTY = "BLOCK_FILTER_EMPTY"
    TRIAL_COUNT_MISMATCH = "TRIAL_COUNT_MISMATCH"
    MUTEX_VIOLATION = "MUTEX_VIOLATION"
    CORRECT_FROM_UNKNOWN = "CORRECT_FROM_UNKNOWN"
    SEARCH_EXHAUSTED = "SEARCH_EXHAUSTED"  # not triggerable in Phase A (framework-reserved, §4.2/§4.3)
    ITERATION_STALLED = "ITERATION_STALLED"

    # M2-B v2 research-layer codes (D-M2-1 contract; additive — the v1 table above is untouched)
    V2_VERSION_MISMATCH = "V2_VERSION_MISMATCH"
    V2_STIM_EMPTY = "V2_STIM_EMPTY"
    V2_STIM_FACTOR_BOUNDS = "V2_STIM_FACTOR_BOUNDS"
    V2_STIM_UNKNOWN_FACTOR = "V2_STIM_UNKNOWN_FACTOR"
    V2_STIM_UNKNOWN_LEVEL = "V2_STIM_UNKNOWN_LEVEL"
    V2_STIM_LEVEL_COVERAGE = "V2_STIM_LEVEL_COVERAGE"
    V2_STIM_TEMPLATE_BOUNDS = "V2_STIM_TEMPLATE_BOUNDS"
    V2_STIM_LINE_BOUNDS = "V2_STIM_LINE_BOUNDS"
    V2_STIM_LINE_COUNT_MISMATCH = "V2_STIM_LINE_COUNT_MISMATCH"
    V2_STIM_POOL_BOUNDS = "V2_STIM_POOL_BOUNDS"
    V2_STIM_SLOT_SYNTAX = "V2_STIM_SLOT_SYNTAX"
    V2_STIM_UNRESOLVED_SLOT = "V2_STIM_UNRESOLVED_SLOT"
    V2_DERIVED_UNKNOWN_OP = "V2_DERIVED_UNKNOWN_OP"
    V2_DERIVED_BAD_NAME = "V2_DERIVED_BAD_NAME"
    V2_DERIVED_DUPLICATE_NAME = "V2_DERIVED_DUPLICATE_NAME"
    V2_DERIVED_BAD_ARGS = "V2_DERIVED_BAD_ARGS"
    V2_DERIVED_BOUNDS = "V2_DERIVED_BOUNDS"
    V2_MEASURE_BAD_NAME = "V2_MEASURE_BAD_NAME"
    V2_MEASURE_DUPLICATE_NAME = "V2_MEASURE_DUPLICATE_NAME"
    V2_MEASURE_BAD_SOURCE = "V2_MEASURE_BAD_SOURCE"
    V2_MEASURE_BOUNDS = "V2_MEASURE_BOUNDS"

    # M3-A P0: intra-trial variables + content-driven correctness (additive)
    V2_VAR_BOUNDS = "V2_VAR_BOUNDS"
    V2_VAR_BAD_NAME = "V2_VAR_BAD_NAME"
    V2_VAR_SOURCE_CONFLICT = "V2_VAR_SOURCE_CONFLICT"
    V2_VAR_POOL_UNKNOWN = "V2_VAR_POOL_UNKNOWN"
    V2_VAR_POOL_EXHAUSTED = "V2_VAR_POOL_EXHAUSTED"
    V2_VAR_COUNT_BOUNDS = "V2_VAR_COUNT_BOUNDS"
    V2_VAR_COUNT_COVERAGE = "V2_VAR_COUNT_COVERAGE"
    V2_VAR_COUNT_UNKNOWN_FACTOR = "V2_VAR_COUNT_UNKNOWN_FACTOR"
    V2_VAR_REF_UNKNOWN = "V2_VAR_REF_UNKNOWN"
    V2_VAR_INDEX_BOUNDS = "V2_VAR_INDEX_BOUNDS"
    V2_VAR_WHEN_SHAPE = "V2_VAR_WHEN_SHAPE"
    V2_VAR_WHEN_UNKNOWN = "V2_VAR_WHEN_UNKNOWN"
    V2_VAR_WHEN_COVERAGE = "V2_VAR_WHEN_COVERAGE"
    V2_RULE_NO_STIMULUS = "V2_RULE_NO_STIMULUS"
    V2_RULE_CONFLICT = "V2_RULE_CONFLICT"
    V2_RULE_KIND = "V2_RULE_KIND"
    V2_RULE_UNKNOWN_OP = "V2_RULE_UNKNOWN_OP"
    V2_RULE_OPTION_UNKNOWN = "V2_RULE_OPTION_UNKNOWN"
    V2_RULE_OPERAND_SHAPE = "V2_RULE_OPERAND_SHAPE"
    V2_RULE_REF_UNKNOWN = "V2_RULE_REF_UNKNOWN"
    V2_RULE_INDEX_BOUNDS = "V2_RULE_INDEX_BOUNDS"

    # M3-A P1: trial presentation phases (additive)
    V2_PHASE_BOUNDS = "V2_PHASE_BOUNDS"
    V2_PHASE_NAME = "V2_PHASE_NAME"
    V2_PHASE_LINE_BOUNDS = "V2_PHASE_LINE_BOUNDS"
    V2_PHASE_TEMPLATE_CONFLICT = "V2_PHASE_TEMPLATE_CONFLICT"
    V2_PHASE_WINDOW_COUNT = "V2_PHASE_WINDOW_COUNT"


class WarningCode:
    """Warning-code enumeration (contract §4.4)."""

    WEIGHT_IGNORED = "WEIGHT_IGNORED"
    RATIO_ROUNDED = "RATIO_ROUNDED"


# UNSAT error-code set (§4.4 category mapping; assertion scope of test_unsat_error_code_mapping)
UNSAT_ERROR_CODES: tuple[str, ...] = (
    ErrorCode.CONSTRAINT_CONFLICT,
    ErrorCode.RATIO_SUM,
    ErrorCode.BLOCK_FILTER_EMPTY,
    ErrorCode.TRIAL_COUNT_MISMATCH,
    ErrorCode.MUTEX_VIOLATION,
)


class ValidationIssue(BaseModel):
    """Validation issue (shared by errors and warnings, contract §4.1)."""

    error_code: str  # stable enumeration (§4.4 table)
    path: str  # JSON path, e.g. "constraints.ratios[0].ratios" / "factors[1].levels"
    message: str  # human-readable description (includes actual values)
    suggestion: str  # fix suggestion (an action instruction for the LLM)


def _issue(error_code: str, path: str, message: str, suggestion: str) -> ValidationIssue:
    """Build a ValidationIssue (single place where the four fields are assembled)."""
    return ValidationIssue(
        error_code=error_code, path=path, message=message, suggestion=suggestion
    )


class ValidationResult(BaseModel):
    """Return value of validate_spec."""

    spec: ExperimentSpec | None  # None when Pydantic parsing fails
    valid: bool
    errors: list[ValidationIssue]
    warnings: list[ValidationIssue]
    config_fingerprint: str | None  # None when schema parsing fails (§5.1)
    errors_truncated: bool
    stats: dict[str, object]


def _format_loc(loc: object) -> str:
    """Join a Pydantic loc into a JSON path (contract §2.2: e.g. factors[1].levels)."""
    parts: list[str] = []
    for part in loc if isinstance(loc, (list, tuple)) else ():  # type: ignore[union-attr]
        if isinstance(part, int):
            parts[-1] = f"{parts[-1]}[{part}]" if parts else f"[{part}]"
        else:
            parts.append(str(part))
    return ".".join(parts)


def _schema_issues(exc: ValidationError) -> list[ValidationIssue]:
    """Wrap each Pydantic error as one SCHEMA_INVALID issue (§2.2)."""
    issues: list[ValidationIssue] = []
    for error in exc.errors():
        path = _format_loc(error.get("loc", ()))
        message = str(error.get("msg", "schema validation failed"))
        issues.append(
            ValidationIssue(
                error_code=ErrorCode.SCHEMA_INVALID,
                path=path,
                message=f"schema validation failed at {path or '<root>'}: {message}",
                suggestion=(
                    "fix the field at path per the ExperimentSpec schema, "
                    "then call validate_experiment again"
                ),
            )
        )
    return issues


def _stats(spec: ExperimentSpec | None, config: Mapping[str, object]) -> dict[str, object]:
    """Validation-report stats (§5.1); on schema-parse failure, best-effort from raw config."""
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
    """Support checks: Phase A has no plugin system and no sequence constraints (§4.4)."""
    if spec.paradigm is not None:
        errors.append(
            ValidationIssue(
                error_code=ErrorCode.UNKNOWN_PARADIGM,
                path="paradigm",
                message=(
                    f"paradigm={spec.paradigm!r} is not supported: Phase A has no plugin "
                    f"system, paradigm must be null (registered plugins: [])"
                ),
                suggestion=(
                    "remove the paradigm field (or set it to null) and empty "
                    "paradigm_params to use the fully generic path"
                ),
            )
        )
    if spec.constraints.max_repeat is not None:
        errors.append(
            ValidationIssue(
                error_code=ErrorCode.UNSUPPORTED_CONSTRAINT,
                path="constraints.max_repeat",
                message=(
                    f"max_repeat={spec.constraints.max_repeat} is not supported yet "
                    "(sequence constraints arrive in Phase B; remove the field for now)"
                ),
                suggestion="remove the constraints.max_repeat field and validate again",
            )
        )


def _check_constraint_semantics(
    spec: ExperimentSpec, errors: list[ValidationIssue], warnings: list[ValidationIssue]
) -> None:
    """C1/C2/C3 plus RATIO_SUM, CORRECT_FROM_UNKNOWN, same-factor mutex declarations (§4.4)."""
    constraints = spec.constraints

    # C1: balance and ratios are mutually exclusive (declaration conflict, checked at validation time)
    if constraints.balance and constraints.ratios:
        errors.append(
            ValidationIssue(
                error_code=ErrorCode.CONSTRAINT_CONFLICT,
                path="constraints",
                message=(
                    f"balance=true and a non-empty ratios declaration are mutually "
                    f"exclusive (ratios currently covers {len(constraints.ratios)} factor(s))"
                ),
                suggestion=(
                    "remove ratios (equal weights) or set balance to false (custom ratios)"
                ),
            )
        )

    # RATIO_SUM: each RatioRule's values sum to ≈1.0 (tolerance 1e-6)
    for i, rule in enumerate(constraints.ratios):
        total = sum(rule.ratios.values())
        if abs(total - 1.0) > RATIO_SUM_TOLERANCE:
            errors.append(
                ValidationIssue(
                    error_code=ErrorCode.RATIO_SUM,
                    path=f"constraints.ratios[{i}].ratios",
                    message=(
                        f"ratios for factor {rule.factor!r} sum to {round(total, 6)}, "
                        f"must be ≈1.0 (tolerance 1e-6)"
                    ),
                    suggestion=(
                        "adjust the ratios values to sum to 1.0 (exclude a level "
                        "explicitly with 0.0 instead of shrinking the total)"
                    ),
                )
            )

    # C2: two cases where an explicit weight gets overridden (warnings; do not affect valid)
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
                            f"explicit weight={level.weight} on factor {factor.name!r} "
                            f"level {level.name!r} is overridden by balance=true equal "
                            "weights (effective weight = 1/number of levels)"
                        ),
                        suggestion=(
                            "remove this weight (unneeded for equal weights) or set "
                            "balance to false to enable weights"
                        ),
                    )
                )
            elif factor.name in ratio_factors:
                warnings.append(
                    ValidationIssue(
                        error_code=WarningCode.WEIGHT_IGNORED,
                        path=f"factors[{fi}].levels[{li}].weight",
                        message=(
                            f"explicit weight={level.weight} on factor {factor.name!r} "
                            f"level {level.name!r} is overridden by a ratios rule "
                            "(effective weights follow ratios)"
                        ),
                        suggestion=(
                            "remove this weight or the corresponding ratios rule to "
                            "avoid ambiguity of intent"
                        ),
                    )
                )

    # CORRECT_FROM_UNKNOWN: correct_from only accepts declared factor names (Phase A has no plugin-derived fields)
    factor_names = set(spec.factor_names())
    for ri, response in enumerate(spec.responses):
        if response.correct_from is not None and response.correct_from not in factor_names:
            errors.append(
                ValidationIssue(
                    error_code=ErrorCode.CORRECT_FROM_UNKNOWN,
                    path=f"responses[{ri}].correct_from",
                    message=(
                        f"correct_from={response.correct_from!r} is not a declared "
                        f"factor name (declared factors: {spec.factor_names()})"
                    ),
                    suggestion=(
                        "set correct_from to a declared factor name, or to null"
                    ),
                )
            )

    # MUTEX_VIOLATION (two levels within the same factor — a meaningless declaration)
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
                        f"mutex declaration {pair} targets two levels of the same "
                        "factor (meaningless: one factor already takes exactly one "
                        "level per trial)"
                    ),
                    suggestion="remove this mutually_exclusive entry",
                )
            )


def _check_block_satisfiability(
    spec: ExperimentSpec,
    errors: list[ValidationIssue],
    warnings: list[ValidationIssue],
) -> None:
    """Per-block satisfiability: MUTEX_VIOLATION (empty space) / BLOCK_FILTER_EMPTY /
    TRIAL_COUNT_MISMATCH / RATIO_ROUNDED (§4.4; all decidable at validation time)."""
    full_space = spec.expanded_combinations()
    pairs = mutex_pairs(spec)

    # MUTEX_VIOLATION: mutex declarations empty the (global) available combination space
    mutex_filtered = filter_mutex(full_space, pairs)
    if pairs and not mutex_filtered:
        errors.append(
            ValidationIssue(
                error_code=ErrorCode.MUTEX_VIOLATION,
                path="constraints.mutually_exclusive",
                message=(
                    f"no available combinations remain after applying mutex "
                    f"declarations {spec.constraints.mutually_exclusive} "
                    f"(expanded combinations: {len(full_space)})"
                ),
                suggestion=(
                    "reduce the mutually_exclusive declarations to keep at least "
                    "one available combination"
                ),
            )
        )
        return  # combination space is empty; per-block checks are meaningless

    weights = effective_weights(spec)

    for bi, block in enumerate(spec.blocks):
        # BLOCK_FILTER_EMPTY: no available combinations after factor_filter semantics (on the fully expanded space)
        filtered_on_full = filter_block(spec, block, full_space)
        if not filtered_on_full:
            errors.append(
                ValidationIssue(
                    error_code=ErrorCode.BLOCK_FILTER_EMPTY,
                    path=f"blocks[{bi}].factor_filter",
                    message=(
                        f"block {block.name!r} has no available combinations after "
                        f"factor_filter (expanded combinations: {len(full_space)})"
                    ),
                    suggestion=(
                        "widen the factor_filter level allow-lists so at least one "
                        "combination remains"
                    ),
                )
            )
            continue
        # TRIAL_COUNT_MISMATCH: zero positive-weight combinations after filter + mutex exclusion + effective weights
        available = filter_block(spec, block, mutex_filtered)
        positive = positive_weight_combos(spec, available, weights)
        if not positive:
            errors.append(
                ValidationIssue(
                    error_code=ErrorCode.TRIAL_COUNT_MISMATCH,
                    path=f"blocks[{bi}]",
                    message=(
                        f"block {block.name!r} has zero positive-weight combinations "
                        "after factor_filter + mutex exclusion + effective weights "
                        f"(including ratios set to 0), while trial_count="
                        f"{block.trial_count} > 0"
                    ),
                    suggestion=(
                        "adjust factor_filter / mutually_exclusive / ratios-zeroed "
                        "levels so the block keeps at least one positive-weight "
                        "combination"
                    ),
                )
            )
            continue
        # RATIO_ROUNDED: largest-remainder allocation has non-integer exact shares (warning)
        combo_weights = [combo_weight(spec, combo, weights) for combo in positive]
        if allocation_has_rounding(block.trial_count, combo_weights):
            warnings.append(
                ValidationIssue(
                    error_code=WarningCode.RATIO_ROUNDED,
                    path=f"blocks[{bi}].trial_count",
                    message=(
                        f"trial_count={block.trial_count} for block {block.name!r} "
                        f"yields non-integer exact shares across {len(positive)} "
                        "available combinations under largest-remainder allocation "
                        "(frequencies approximate floor/floor+1, not strictly equal)"
                    ),
                    suggestion=(
                        "for strictly equal frequencies, set trial_count to a "
                        "multiple of the number of available combinations"
                    ),
                )
            )


def _check_v2_fields(spec: ExperimentSpec, errors: list[ValidationIssue]) -> None:
    """M2-B v2 research-layer checks (D-M2-1 contract §1.5/§1.7).

    - schema_version 1 with any v2 field SET (including explicit null) → V2_VERSION_MISMATCH;
    - schema_version 2: run the v2 semantic validators for each SET feature
      (M3-A P0 adds intra-trial variables and content-driven correctness rules).
    Explicit null on schema_version 2 is equivalent to absent (no checks, no dump key).
    """
    v2_set = [name for name in _V2_OPTIONAL_FIELDS if name in spec.model_fields_set]
    if spec.schema_version == 1:
        for name in v2_set:
            errors.append((
                _issue(ErrorCode.V2_VERSION_MISMATCH, name,
                       f"field {name!r} is a schema_version 2 feature but this spec "
                       "declares schema_version 1",
                       "set schema_version to 2 to use v2 research fields, or remove the field")
            ))
        for ri, response in enumerate(spec.responses):
            if response.correct_rule is not None:
                errors.append((
                    _issue(ErrorCode.V2_VERSION_MISMATCH, f"responses[{ri}].correct_rule",
                           "correct_rule is a schema_version 2 feature but this spec "
                           "declares schema_version 1",
                           "set schema_version to 2 to use content-driven correctness, "
                           "or remove the field")
                ))
        return
    raw_issues: list[tuple[str, str, str, str]] = []
    if spec.stimulus_spec is not None:
        raw_issues.extend(validate_stimulus_spec(spec))
        raw_issues.extend(validate_variables(spec))
        if spec.stimulus_spec.phases is not None:
            raw_issues.extend(validate_phases(spec))
    raw_issues.extend(validate_correct_rules(spec))
    if spec.derived_spec is not None:
        raw_issues.extend(validate_derived_spec(spec))
    if spec.measures is not None:
        raw_issues.extend(validate_measures(spec))
    for code, path, message, suggestion in raw_issues:
        errors.append(
            ValidationIssue(error_code=code, path=path, message=message, suggestion=suggestion)
        )


def validate_spec(config: Mapping[str, object]) -> ValidationResult:
    """Entry point: Pydantic → support → constraint semantics → per-block satisfiability (frozen order)."""
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
    _check_v2_fields(spec, errors)
    fingerprint = sha256_hex(canonical_json(spec_dump(spec)))
    return _finalize(spec, errors, warnings, fingerprint, _stats(spec, config))


def _finalize(
    spec: ExperimentSpec | None,
    errors: list[ValidationIssue],
    warnings: list[ValidationIssue],
    fingerprint: str | None,
    stats: dict[str, object],
) -> ValidationResult:
    """Finalise: truncate errors to 20 and set errors_truncated (§5.1)."""
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
    """error_code:path fingerprint (the decision unit of the ITERATION_STALLED soft protocol, §5.1)."""
    return f"{issue.error_code}:{issue.path}"


def stalled_fingerprints(
    errors: list[ValidationIssue], previous_errors: list[str]
) -> list[str]:
    """Fingerprints among current errors that appear ≥2 times in previous_errors (MA-1 trigger semantics)."""
    current = [issue_fingerprint(issue) for issue in errors]
    return [fp for fp in current if previous_errors.count(fp) >= 2]


def iteration_stalled_issue(fingerprint: str, occurrences: int) -> ValidationIssue:
    """ITERATION_STALLED issue (§5.1; suggestion copy standardised to English per
    user-approved 2026-10-20 English-first decision — was frozen in Chinese)."""
    return ValidationIssue(
        error_code=ErrorCode.ITERATION_STALLED,
        path=fingerprint,
        message=f"validation error fingerprint {fingerprint!r} has occurred {occurrences} times",
        suggestion="stop resubmitting; summarize the unresolved conflict and ask the user to decide",
    )
