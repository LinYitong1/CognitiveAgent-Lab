"""M2-B v2 research-layer engine: stimulus materialization + v2 semantic validation.

Pure functions only; imports nothing from tools/, agent/, or any game module
(the v2 research layer is game-free by construction — introspection-tested).

Two responsibilities (D-M2-1 contract, docs/m2/M2B_CONTRACT.md):

1. Semantic validation (bounds, references, slot syntax, line-count matching,
   derived-op whitelist, measures metadata) returning raw issue tuples that
   validation.py wraps into ValidationIssue objects with V2_* error codes.
   Shape/type errors and extra keys surface earlier as SCHEMA_INVALID
   (Pydantic layer, schemas.py) — that layering mirrors Phase A.

2. Deterministic materialization (the frozen algorithm):
   - per-trial isolated stream: stream_seed = SHA-256(f"{seed}|{index}|stimulus"),
     first 16 hex chars -> int -> random.Random (PYTHONHASHSEED-independent);
   - M3-A P0, in this order: (a) intra-trial variable bindings in declaration
     order (pool draws / reuse of earlier bindings), (b) template selection or
     phase-line assembly (P1: exactly one line source, factors XOR phases),
     (c) slot rendering left-to-right; then content-driven answer keys;
   - phased trials (P1): trial.stimulus = {"lines": [phase lines concatenated
     in phase order], "phases": [materialized phase objects]}; unphased trials
     keep {"lines": [...]} with no other keys;
   - template selection: for each factor WITH a stimulus entry, in spec factor
     declaration order, one rng.choice over the assigned level's templates;
   - line assembly: selected templates' lines concatenated in the same factor
     order;
   - slot rendering: each line scanned left-to-right; every {pool:x} consumes
     exactly one rng.choice draw in reading order across the whole line list;
     {factor} slots substitute the trial's assigned level name without drawing;
   - output (unphased): trial.stimulus = {"lines": [str, ...]} (no other keys);
   - derived ops computed from trial context only (index / block / factor
     assignment), values always int.

Materialization runs inside generate_trials BEFORE fingerprint computation, so
materialized content is fully covered by trials_fingerprint (and therefore by
bundle_sha256 and verify_bundle). Preconditions: the spec passed v2 semantic
validation (the tool layer guarantees validate-before-generate, as for v1).
"""

from __future__ import annotations

import random
import re

from src.experiment.canonical import sha256_hex
from src.experiment.schemas import (
    CorrectRuleSpec,
    DerivedOpSpec,
    ExperimentSpec,
    MeasureSpec,
    RuleOperandSpec,
    StimulusSpec,
    StimulusVariableSpec,
    Trial,
    VariableCountSpec,
)

# --- v2 semantic bounds (contract §1.3 / §1.5; enforced here, not in Pydantic) ---

MAX_STIMULUS_FACTORS = 16
MAX_TEMPLATES_PER_LEVEL = 4
MAX_LINES_PER_TEMPLATE = 6
MAX_LINE_CHARS = 200
MAX_POOLS = 8
MAX_POOL_LINES = 12
MAX_DERIVED_OPS = 16
MAX_MEASURES = 32

# M3-A P0: intra-trial variables + content-driven correctness bounds
MAX_VARIABLES = 8
MAX_VARIABLE_COUNT = 12

# M3-A P1: trial presentation phases bounds
MAX_PHASES = 8

# Closed correctness-relation set (M3-A P0). Nothing paradigm-specific escapes it.
RULE_OP_WHITELIST: tuple[str, ...] = ("eq", "neq", "in")

# MVP closed derived-op whitelist (contract §1.5). Nothing escapes it.
DERIVED_OP_WHITELIST: tuple[str, ...] = ("trial_number", "block_progress", "count_factor_level")

# Slot grammar: {factor_name}, {pool:pool_name} or {var:name} / {var:name[i]};
# names are [A-Za-z0-9_]+.
_SLOT_RE = re.compile(r"\{([^{}]*)\}")
_SLOT_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")
_VAR_SLOT_RE = re.compile(r"^([A-Za-z0-9_]+)(?:\[([0-9]+)\])?$")
_POOL_PREFIX = "pool:"
_VAR_PREFIX = "var:"

# Slot kind (parsed form): "pool" | "factor" | "var"
Slot = tuple[str, str, str, int | None]  # (content, kind, name, index)

# Raw issue tuple: (error_code, json_path, message, suggestion)
RawIssue = tuple[str, str, str, str]


# ---------------------------------------------------------------------------
# Slot parsing
# ---------------------------------------------------------------------------

def _parse_slots(line: str) -> list[Slot]:
    """Return [(slot_content, kind, name, index)] for every slot, left-to-right.

    kind: "pool" -> {pool:name} (consumes one draw), "factor" -> {name}
    (substitution), "var" -> {var:name} / {var:name[i]} (references a variable
    binding; index None means the whole bound list).
    Raises ValueError on a name that violates the slot-name grammar.
    """
    slots: list[Slot] = []
    for match in _SLOT_RE.finditer(line):
        content = match.group(1)
        if content.startswith(_POOL_PREFIX):
            name = content[len(_POOL_PREFIX):]
            if not _SLOT_NAME_RE.match(name):
                raise ValueError(f"invalid slot name {name!r} (must match [A-Za-z0-9_]+)")
            slots.append((content, "pool", name, None))
        elif content.startswith(_VAR_PREFIX):
            rest = content[len(_VAR_PREFIX):]
            parsed = _VAR_SLOT_RE.match(rest)
            if parsed is None:
                raise ValueError(
                    f"invalid variable slot {content!r} (must be {{var:name}} or {{var:name[i]}})"
                )
            raw_index = parsed.group(2)
            slots.append((content, "var", parsed.group(1), int(raw_index) if raw_index else None))
        else:
            if not _SLOT_NAME_RE.match(content):
                raise ValueError(f"invalid slot name {content!r} (must match [A-Za-z0-9_]+)")
            slots.append((content, "factor", content, None))
    return slots


def _has_unbalanced_braces(line: str) -> bool:
    """Detect malformed slot syntax the regex cannot represent (e.g. '{factor' or nested '{{')."""
    depth = 0
    for ch in line:
        if ch == "{":
            depth += 1
            if depth > 1:
                return True
        elif ch == "}":
            depth -= 1
            if depth < 0:
                return True
    return depth != 0


# ---------------------------------------------------------------------------
# Variable binding helpers (M3-A P0: shared by validation and materialization)
# ---------------------------------------------------------------------------

def _count_choices(var: StimulusVariableSpec, variables: list[StimulusVariableSpec],
                   limit: int) -> list[int]:
    """Every element count this binding can produce.

    A copy binding with an index ("any" or a position) yields exactly one
    element; a whole-list copy inherits the source's counts. Sources are
    resolved only among EARLIER declarations, so a self/mutual reference
    terminates instead of recursing.
    """
    if var.copy_from is not None:
        index = var.copy_from.index
        if index is not None:
            return [1]  # "any" and a positional index both yield exactly one element
        counts: list[int] = []
        for i, source in enumerate(variables[:limit]):
            if source.name == var.copy_from.var:
                counts.extend(_count_choices(source, variables, i))
        return counts or [1]
    if var.count is None:
        return [1]
    if isinstance(var.count, int):
        return [var.count]
    return list(var.count.levels.values())


def _variable_counts(spec: ExperimentSpec, name: str) -> list[int]:
    """All element counts a variable name can bind across its declarations."""
    assert spec.stimulus_spec is not None
    variables = spec.stimulus_spec.variables
    counts: list[int] = []
    for i, var in enumerate(variables):
        if var.name == name:
            counts.extend(_count_choices(var, variables, i))
    return counts or [1]


def _min_count(spec: ExperimentSpec, name: str) -> int:
    """Smallest element count a variable name can bind (static index bound)."""
    return min(_variable_counts(spec, name))


def _max_count(spec: ExperimentSpec, name: str) -> int:
    """Largest element count a variable name can bind (exclusion-feasibility bound)."""
    return max(_variable_counts(spec, name))


# ---------------------------------------------------------------------------
# 1. Semantic validation (raw issues; validation.py wraps them)
# ---------------------------------------------------------------------------

def validate_stimulus_spec(spec: ExperimentSpec) -> list[RawIssue]:
    """Validate stimulus_spec semantics (bounds, references, slots, line counts)."""
    assert spec.stimulus_spec is not None  # caller checks
    stim = spec.stimulus_spec
    issues: list[RawIssue] = []
    known_factors = {factor.name: {level.name for level in factor.levels} for factor in spec.factors}
    variable_names = {var.name for var in stim.variables}

    if not stim.factors and not stim.phases:
        issues.append((
            "V2_STIM_EMPTY", "stimulus_spec.factors",
            "stimulus_spec must declare either per-factor templates (factors) "
            "or trial phases (phases); both are empty",
            "add a factors entry mapping a declared factor name to its per-level "
            "templates, or a phases list, or remove stimulus_spec entirely",
        ))
        return issues
    if stim.factors and stim.phases:
        issues.append((
            "V2_PHASE_TEMPLATE_CONFLICT", "stimulus_spec",
            "stimulus_spec declares both per-factor templates (factors) and trial "
            "phases (phases) — there must be exactly one line source, never a merge",
            "keep phases only (generic sequential presentation) or factors only "
            "(per-condition templates)",
        ))
    if len(stim.factors) > MAX_STIMULUS_FACTORS:
        issues.append((
            "V2_STIM_FACTOR_BOUNDS", "stimulus_spec.factors",
            f"stimulus_spec.factors has {len(stim.factors)} entries, limit {MAX_STIMULUS_FACTORS}",
            "reduce the number of stimulus-mapped factors",
        ))

    for factor_name, factor_spec in stim.factors.items():
        base = f"stimulus_spec.factors[{factor_name!r}]"
        if factor_name not in known_factors:
            issues.append((
                "V2_STIM_UNKNOWN_FACTOR", base,
                f"stimulus factor {factor_name!r} is not a declared experiment factor",
                "use one of the declared factor names: "
                + ", ".join(sorted(known_factors)),
            ))
            continue
        declared_levels = known_factors[factor_name]
        missing = sorted(declared_levels - set(factor_spec.levels))
        if missing:
            issues.append((
                "V2_STIM_LEVEL_COVERAGE", base + ".levels",
                f"levels missing templates: {missing} (partial coverage is not allowed)",
                "provide templates for every declared level of this factor",
            ))
        unknown = sorted(set(factor_spec.levels) - declared_levels)
        for level in unknown:
            issues.append((
                "V2_STIM_UNKNOWN_LEVEL", f"{base}.levels[{level!r}]",
                f"level {level!r} is not declared for factor {factor_name!r}",
                "use one of the declared level names: " + ", ".join(sorted(declared_levels)),
            ))
        line_counts: set[int] = set()
        for level_name, templates in factor_spec.levels.items():
            if not (1 <= len(templates) <= MAX_TEMPLATES_PER_LEVEL):
                issues.append((
                    "V2_STIM_TEMPLATE_BOUNDS", f"{base}.levels[{level_name!r}]",
                    f"level {level_name!r} has {len(templates)} templates, allowed 1..{MAX_TEMPLATES_PER_LEVEL}",
                    "provide between 1 and "
                    f"{MAX_TEMPLATES_PER_LEVEL} templates (each template = a list of line strings)",
                ))
                continue
            for ti, template in enumerate(templates):
                if not (1 <= len(template) <= MAX_LINES_PER_TEMPLATE):
                    issues.append((
                        "V2_STIM_LINE_BOUNDS", f"{base}.levels[{level_name!r}][{ti}]",
                        f"template {ti} has {len(template)} lines, allowed 1..{MAX_LINES_PER_TEMPLATE}",
                        "provide between 1 and " f"{MAX_LINES_PER_TEMPLATE} non-empty line strings",
                    ))
                    continue
                for li, line in enumerate(template):
                    if not line or len(line) > MAX_LINE_CHARS:
                        issues.append((
                            "V2_STIM_LINE_BOUNDS", f"{base}.levels[{level_name!r}][{ti}][{li}]",
                            f"line {li} is empty or longer than {MAX_LINE_CHARS} chars",
                            f"provide a non-empty line of at most {MAX_LINE_CHARS} characters",
                        ))
                    elif _has_unbalanced_braces(line):
                        issues.append((
                            "V2_STIM_SLOT_SYNTAX", f"{base}.levels[{level_name!r}][{ti}][{li}]",
                            f"line {li} has malformed slot syntax (unbalanced or nested braces)",
                            "slots must be exactly {{name}} or {{pool:name}} with names "
                            "matching [A-Za-z0-9_]+",
                        ))
                    else:
                        try:
                            for _slot in _parse_slots(line):
                                pass  # grammar checked here; resolution below
                        except ValueError as exc:
                            issues.append((
                                "V2_STIM_SLOT_SYNTAX", f"{base}.levels[{level_name!r}][{ti}][{li}]",
                                f"line {li}: {exc}",
                                "slot names must match [A-Za-z0-9_]+; use {{pool:name}} for pools",
                            ))
                if template:
                    line_counts.add(len(template))
        if factor_spec.match_line_count and len(line_counts) > 1:
            issues.append((
                "V2_STIM_LINE_COUNT_MISMATCH", base,
                f"match_line_count=true but templates produce differing line counts: {sorted(line_counts)}",
                "make every template of every level produce the same number of lines "
                "(length-matched levels), or set match_line_count=false deliberately",
            ))

    if len(stim.pools) > MAX_POOLS:
        issues.append((
            "V2_STIM_POOL_BOUNDS", "stimulus_spec.pools",
            f"stimulus_spec.pools has {len(stim.pools)} entries, limit {MAX_POOLS}",
            "reduce the number of pools",
        ))
    for pool_name, lines in stim.pools.items():
        if not lines or len(lines) > MAX_POOL_LINES:
            issues.append((
                "V2_STIM_POOL_BOUNDS", f"stimulus_spec.pools[{pool_name!r}]",
                f"pool {pool_name!r} has {len(lines)} lines, allowed 1..{MAX_POOL_LINES}",
                f"provide between 1 and {MAX_POOL_LINES} non-empty line strings",
            ))

    # slot resolution (after grammar): every {factor} slot names a declared
    # factor; every {pool:x} names a defined pool
    for factor_name, factor_spec in stim.factors.items():
        if factor_name not in known_factors:
            continue
        for level_name, templates in factor_spec.levels.items():
            for ti, template in enumerate(templates):
                for li, line in enumerate(template):
                    if not line or _has_unbalanced_braces(line):
                        continue
                    try:
                        slots = _parse_slots(line)
                    except ValueError:
                        continue  # already reported as SLOT_SYNTAX
                    for content, kind, name, index in slots:
                        path = f"stimulus_spec.factors[{factor_name!r}].levels[{level_name!r}][{ti}][{li}]"
                        if kind == "pool":
                            if name not in stim.pools:
                                issues.append((
                                    "V2_STIM_UNRESOLVED_SLOT", path,
                                    f"slot {content!r} references undefined pool {name!r}",
                                    "define the pool in stimulus_spec.pools, or fix the slot name",
                                ))
                        elif kind == "factor":
                            if name not in known_factors:
                                issues.append((
                                    "V2_STIM_UNRESOLVED_SLOT", path,
                                    f"slot {content!r} does not reference a declared factor "
                                    "(response names are not valid slots)",
                                    "slots must reference declared factor names, or pools via {pool:name}",
                                ))
                        elif name not in variable_names:
                            # {var:...} must name a declared variable (V2_VAR_REF_UNKNOWN)
                            issues.append((
                                "V2_VAR_REF_UNKNOWN", path,
                                f"slot {content!r} references undeclared variable {name!r}",
                                "declare the variable in stimulus_spec.variables "
                                "(declared: " + (", ".join(sorted(variable_names)) or "none") + ")",
                            ))
                        elif index is not None and index >= _min_count(spec, name):
                            issues.append((
                                "V2_VAR_INDEX_BOUNDS", path,
                                f"slot {content!r} indexes element {index} but variable "
                                f"{name!r} binds at most {_min_count(spec, name)} element(s)",
                                "index an element that every binding of the variable provides, "
                                "or drop the index to reference the whole list",
                            ))
    return issues


def validate_variables(spec: ExperimentSpec) -> list[RawIssue]:
    """Validate stimulus_spec.variables (names, guards, sources, draw feasibility).

    Every check is paradigm-neutral: names, pools, counts and references only.
    """
    assert spec.stimulus_spec is not None
    stim = spec.stimulus_spec
    issues: list[RawIssue] = []
    known_factors = {f.name: {l.name for l in f.levels} for f in spec.factors}

    if len(stim.variables) > MAX_VARIABLES:
        issues.append((
            "V2_VAR_BOUNDS", "stimulus_spec.variables",
            f"stimulus_spec.variables has {len(stim.variables)} entries, limit {MAX_VARIABLES}",
            "reduce the number of intra-trial variables",
        ))

    groups: dict[str, list[int]] = {}
    for i, var in enumerate(stim.variables):
        if not var.name or not _SLOT_NAME_RE.match(var.name):
            issues.append((
                "V2_VAR_BAD_NAME", f"stimulus_spec.variables[{i}].name",
                f"variable name {var.name!r} must be non-empty and match [A-Za-z0-9_]+",
                "use a plain identifier (it is referenced as {var:name})",
            ))
        groups.setdefault(var.name, []).append(i)

    # Guard coverage: for every trial exactly one binding of a name must apply.
    for name, indexes in groups.items():
        if any(not stim.variables[i].when for i in indexes):
            if len(indexes) > 1:
                issues.append((
                    "V2_VAR_WHEN_COVERAGE", f"stimulus_spec.variables[{indexes[0]}]",
                    f"variable {name!r} mixes an unconditional binding with guarded ones "
                    "(ambiguous: two bindings could apply to the same trial)",
                    "give every entry of this variable a `when` guard, or keep a single "
                    "unconditional entry",
                ))
            continue
        guards = [stim.variables[i].when for i in indexes]
        if any(len(guard) != 1 for guard in guards):
            issues.append((
                "V2_VAR_WHEN_SHAPE", f"stimulus_spec.variables[{indexes[0]}].when",
                f"variable {name!r} has a guard that is not a single {{factor: level}} pair",
                "use exactly one factor/level pair per `when` guard",
            ))
            continue
        factor_names = {next(iter(guard)) for guard in guards}
        if len(factor_names) > 1:
            issues.append((
                "V2_VAR_WHEN_SHAPE", f"stimulus_spec.variables[{indexes[0]}].when",
                f"variable {name!r} guards different factors {sorted(factor_names)}",
                "guard every entry of one variable on the same factor",
            ))
            continue
        factor_name = next(iter(factor_names))
        if factor_name not in known_factors:
            issues.append((
                "V2_VAR_WHEN_UNKNOWN", f"stimulus_spec.variables[{indexes[0]}].when",
                f"guard factor {factor_name!r} is not a declared experiment factor",
                "use one of the declared factor names: " + ", ".join(sorted(known_factors)),
            ))
            continue
        levels = [next(iter(guard.values())) for guard in guards]
        if len(set(levels)) != len(levels):
            issues.append((
                "V2_VAR_WHEN_COVERAGE", f"stimulus_spec.variables[{indexes[0]}].when",
                f"variable {name!r} guards the same level more than once",
                "guard exactly one binding per level of the guard factor",
            ))
            continue
        declared = known_factors[factor_name]
        if set(levels) != declared:
            missing = sorted(declared - set(levels))
            extra = sorted(set(levels) - declared)
            issues.append((
                "V2_VAR_WHEN_COVERAGE", f"stimulus_spec.variables[{indexes[0]}].when",
                f"variable {name!r} guards {sorted(levels)} of factor {factor_name!r}, "
                f"declared levels are {sorted(declared)}"
                + (f" (missing: {missing})" if missing else "")
                + (f" (unknown: {extra})" if extra else ""),
                "guard exactly one binding for every declared level of the guard factor",
            ))

    for i, var in enumerate(stim.variables):
        base = f"stimulus_spec.variables[{i}]"
        if (var.pool is None) == (var.copy_from is None):
            issues.append((
                "V2_VAR_SOURCE_CONFLICT", base,
                f"variable {var.name!r} must declare exactly one source: pool (draw) or "
                "copy (reference an earlier variable)",
                "set `pool` (+ optional count/exclude) to draw new content, or `copy_from` to "
                "reuse already-bound content",
            ))
            continue
        if var.copy_from is not None:
            if var.pool is not None or var.count is not None or var.exclude:
                issues.append((
                    "V2_VAR_SOURCE_CONFLICT", base,
                    f"variable {var.name!r} declares copy together with pool/count/exclude",
                    "keep only `copy_from` (with an optional index) for a reference binding",
                ))
            source = var.copy_from.var
            if not any(prev.name == source for prev in stim.variables[:i]):
                issues.append((
                    "V2_VAR_REF_UNKNOWN", base + ".copy_from.var",
                    f"copy references {source!r}, which is not a variable declared before "
                    "this entry (references may only point backwards)",
                    "declare the referenced variable earlier in stimulus_spec.variables",
                ))
            index = var.copy_from.index
            if index is not None and not (index == "any" or (isinstance(index, int) and index >= 0)):
                issues.append((
                    "V2_VAR_INDEX_BOUNDS", base + ".copy_from.index",
                    f"copy index {index!r} must be null, \"any\", or a non-negative integer",
                    "use null (whole list), \"any\" (one element, drawn), or a position",
                ))
            elif isinstance(index, int) and index >= _min_count(spec, source):
                issues.append((
                    "V2_VAR_INDEX_BOUNDS", base + ".copy_from.index",
                    f"copy index {index} exceeds the smallest element count of {source!r} "
                    f"({_min_count(spec, source)})",
                    "index a position every binding of the source provides",
                ))
            continue

        # pool source
        assert var.pool is not None
        if var.pool not in stim.pools:
            issues.append((
                "V2_VAR_POOL_UNKNOWN", base + ".pool",
                f"pool {var.pool!r} is not defined in stimulus_spec.pools "
                f"(defined: {sorted(stim.pools)})",
                "define the pool in stimulus_spec.pools, or fix the pool name",
            ))
        count = var.count
        if isinstance(count, int):
            if not 1 <= count <= MAX_VARIABLE_COUNT:
                issues.append((
                    "V2_VAR_COUNT_BOUNDS", base + ".count",
                    f"count {count} is outside 1..{MAX_VARIABLE_COUNT}",
                    f"use a count between 1 and {MAX_VARIABLE_COUNT}",
                ))
        elif isinstance(count, VariableCountSpec):
            if count.factor not in known_factors:
                issues.append((
                    "V2_VAR_COUNT_UNKNOWN_FACTOR", base + ".count.factor",
                    f"count factor {count.factor!r} is not a declared experiment factor",
                    "use one of the declared factor names: " + ", ".join(sorted(known_factors)),
                ))
            else:
                declared = known_factors[count.factor]
                if set(count.levels) != declared:
                    missing = sorted(declared - set(count.levels))
                    extra = sorted(set(count.levels) - declared)
                    issues.append((
                        "V2_VAR_COUNT_COVERAGE", base + ".count.levels",
                        f"count levels {sorted(count.levels)} do not match the declared "
                        f"levels {sorted(declared)} of factor {count.factor!r}"
                        + (f" (missing: {missing})" if missing else "")
                        + (f" (unknown: {extra})" if extra else ""),
                        "provide a count for every declared level of the count factor",
                    ))
                for level, value in count.levels.items():
                    if not 1 <= value <= MAX_VARIABLE_COUNT:
                        issues.append((
                            "V2_VAR_COUNT_BOUNDS", f"{base}.count.levels[{level!r}]",
                            f"count {value} for level {level!r} is outside "
                            f"1..{MAX_VARIABLE_COUNT}",
                            f"use a count between 1 and {MAX_VARIABLE_COUNT}",
                        ))
        for excluded in var.exclude:
            if not any(prev.name == excluded for prev in stim.variables[:i]):
                issues.append((
                    "V2_VAR_REF_UNKNOWN", f"{base}.exclude",
                    f"exclude references {excluded!r}, which is not a variable declared "
                    "before this entry",
                    "exclude only variables declared earlier in stimulus_spec.variables",
                ))
        # static draw feasibility (sound upper bound: no runtime retries needed)
        if var.pool in stim.pools:
            needed = _max_count(spec, var.name) + sum(
                _max_count(spec, name) for name in var.exclude
            )
            available = len(stim.pools[var.pool])
            if available < needed:
                issues.append((
                    "V2_VAR_POOL_EXHAUSTED", base + ".pool",
                    f"pool {var.pool!r} has {available} entries but this binding needs "
                    f"{needed} (count {_max_count(spec, var.name)} plus "
                    f"{sum(_max_count(spec, name) for name in var.exclude)} excluded)",
                    "add pool entries, reduce count, or narrow the exclude list",
                ))
    return issues


def validate_phases(spec: ExperimentSpec) -> list[RawIssue]:
    """Validate stimulus_spec.phases (bounds, names, line/slot rules, windows).

    Phases are a generic sequencing primitive: every check is structural.
    """
    assert spec.stimulus_spec is not None
    stim = spec.stimulus_spec
    assert stim.phases is not None
    issues: list[RawIssue] = []
    known_factors = {factor.name: {level.name for level in factor.levels} for factor in spec.factors}
    variable_names = {var.name for var in stim.variables}

    if not stim.phases:
        return issues
    if len(stim.phases) > MAX_PHASES:
        issues.append((
            "V2_PHASE_BOUNDS", "stimulus_spec.phases",
            f"stimulus_spec.phases has {len(stim.phases)} entries, limit {MAX_PHASES}",
            f"reduce to at most {MAX_PHASES} presentation phases per trial",
        ))

    seen_names: set[str] = set()
    for i, phase in enumerate(stim.phases):
        base = f"stimulus_spec.phases[{i}]"
        if not phase.name or not _SLOT_NAME_RE.match(phase.name):
            issues.append((
                "V2_PHASE_NAME", base + ".name",
                f"phase name {phase.name!r} must be non-empty and match [A-Za-z0-9_]+",
                "use a plain identifier (names identify the phase in the materialized trial)",
            ))
        elif phase.name in seen_names:
            issues.append((
                "V2_PHASE_NAME", base + ".name",
                f"duplicate phase name {phase.name!r}",
                "phase names must be unique within the trial",
            ))
        else:
            seen_names.add(phase.name)
        if not (1 <= len(phase.lines) <= MAX_LINES_PER_TEMPLATE):
            issues.append((
                "V2_PHASE_LINE_BOUNDS", base + ".lines",
                f"phase {phase.name!r} has {len(phase.lines)} lines, allowed "
                f"1..{MAX_LINES_PER_TEMPLATE}",
                f"provide between 1 and {MAX_LINES_PER_TEMPLATE} non-empty line strings",
            ))
            continue
        for li, line in enumerate(phase.lines):
            path = f"{base}.lines[{li}]"
            if not line or len(line) > MAX_LINE_CHARS:
                issues.append((
                    "V2_PHASE_LINE_BOUNDS", path,
                    f"line {li} is empty or longer than {MAX_LINE_CHARS} chars",
                    f"provide a non-empty line of at most {MAX_LINE_CHARS} characters",
                ))
            elif _has_unbalanced_braces(line):
                issues.append((
                    "V2_STIM_SLOT_SYNTAX", path,
                    f"line {li} has malformed slot syntax (unbalanced or nested braces)",
                    "slots must be exactly {{name}} or {{pool:name}} with names "
                    "matching [A-Za-z0-9_]+",
                ))
            else:
                try:
                    slots = _parse_slots(line)
                except ValueError as exc:
                    issues.append((
                        "V2_STIM_SLOT_SYNTAX", path,
                        f"line {li}: {exc}",
                        "slot names must match [A-Za-z0-9_]+; use {{pool:name}} for pools",
                    ))
                    continue
                for content, kind, name, index in slots:
                    if kind == "pool" and name not in stim.pools:
                        issues.append((
                            "V2_STIM_UNRESOLVED_SLOT", path,
                            f"slot {content!r} references undefined pool {name!r}",
                            "define the pool in stimulus_spec.pools, or fix the slot name",
                        ))
                    elif kind == "factor" and name not in known_factors:
                        issues.append((
                            "V2_STIM_UNRESOLVED_SLOT", path,
                            f"slot {content!r} does not reference a declared factor "
                            "(response names are not valid slots)",
                            "slots must reference declared factor names, or pools via {pool:name}",
                        ))
                    elif kind == "var":
                        if name not in variable_names:
                            issues.append((
                                "V2_VAR_REF_UNKNOWN", path,
                                f"slot {content!r} references undeclared variable {name!r}",
                                "declare the variable in stimulus_spec.variables "
                                "(declared: " + (", ".join(sorted(variable_names)) or "none") + ")",
                            ))
                        elif index is not None and index >= _min_count(spec, name):
                            issues.append((
                                "V2_VAR_INDEX_BOUNDS", path,
                                f"slot {content!r} indexes element {index} but variable "
                                f"{name!r} binds at most {_min_count(spec, name)} element(s)",
                                "index an element that every binding of the variable provides, "
                                "or drop the index to reference the whole list",
                            ))

    # response windows: one window phase collects one response; without enough
    # windows, trailing responses would be recorded as missed on every trial
    windows = sum(1 for phase in stim.phases if phase.response_window)
    if windows < len(spec.responses):
        issues.append((
            "V2_PHASE_WINDOW_COUNT", "stimulus_spec.phases",
            f"{windows} phase(s) open a response_window but the spec declares "
            f"{len(spec.responses)} response(s); each response needs one window "
            "phase (uncollected responses are recorded as missed)",
            "flag response_window on one phase per declared response, in the "
            "order the responses should be collected",
        ))
    return issues


def validate_correct_rules(spec: ExperimentSpec) -> list[RawIssue]:
    """Validate content-driven correctness rules (responses[].correct_rule)."""
    issues: list[RawIssue] = []
    declared_vars = (
        {var.name for var in spec.stimulus_spec.variables}
        if spec.stimulus_spec is not None else set()
    )
    known_factors = {factor.name for factor in spec.factors}
    for ri, response in enumerate(spec.responses):
        rule = response.correct_rule
        if rule is None:
            continue
        base = f"responses[{ri}].correct_rule"
        if spec.stimulus_spec is None:
            issues.append((
                "V2_RULE_NO_STIMULUS", base,
                f"correct_rule on response {response.name!r} requires a stimulus_spec "
                "declaring the referenced variables",
                "declare stimulus_spec (with variables) or switch this response to correct_from",
            ))
            continue
        if response.correct_from is not None:
            issues.append((
                "V2_RULE_CONFLICT", base,
                f"response {response.name!r} declares both correct_from="
                f"{response.correct_from!r} and correct_rule (two answer sources)",
                "keep exactly one: correct_from (label-derived) or correct_rule (content-derived)",
            ))
        if response.kind != "choice":
            issues.append((
                "V2_RULE_KIND", base,
                f"correct_rule maps to declared options but response {response.name!r} has "
                f"kind {response.kind!r}",
                "use kind='choice' (with options) for a rule-scored response",
            ))
        if rule.op not in RULE_OP_WHITELIST:
            issues.append((
                "V2_RULE_UNKNOWN_OP", base + ".op",
                f"op {rule.op!r} is not in the whitelist {list(RULE_OP_WHITELIST)}",
                "use one of: " + ", ".join(RULE_OP_WHITELIST),
            ))
        for value, key in ((rule.true_option, "true_option"), (rule.false_option, "false_option")):
            if value not in response.options:
                issues.append((
                    "V2_RULE_OPTION_UNKNOWN", f"{base}.{key}",
                    f"{key} {value!r} is not a declared option of response "
                    f"{response.name!r} (options: {response.options})",
                    "map the rule result onto declared options of this response",
                ))
        for side in ("left", "right"):
            operand = getattr(rule, side)
            operand_base = f"{base}.{side}"
            given = [key for key in ("var", "literal", "factor") if getattr(operand, key) is not None]
            if len(given) != 1:
                issues.append((
                    "V2_RULE_OPERAND_SHAPE", operand_base,
                    f"{side} operand must set exactly one of var / literal / factor, "
                    f"got {given}",
                    "reference bound content with var, a condition with factor, or a "
                    "constant with literal",
                ))
                continue
            if operand.var is not None:
                if operand.var not in declared_vars:
                    issues.append((
                        "V2_RULE_REF_UNKNOWN", operand_base + ".var",
                        f"operand references undeclared variable {operand.var!r} "
                        f"(declared: {sorted(declared_vars) or 'none'})",
                        "declare the variable in stimulus_spec.variables",
                    ))
                elif operand.index is not None and operand.index >= _min_count(spec, operand.var):
                    issues.append((
                        "V2_RULE_INDEX_BOUNDS", operand_base + ".index",
                        f"index {operand.index} exceeds the smallest element count of "
                        f"{operand.var!r} ({_min_count(spec, operand.var)})",
                        "index a position every binding of the variable provides",
                    ))
            elif operand.index is not None:
                issues.append((
                    "V2_RULE_OPERAND_SHAPE", operand_base + ".index",
                    "index is only meaningful together with var",
                    "remove the index, or reference a variable element",
                ))
            elif operand.factor is not None and operand.factor not in known_factors:
                issues.append((
                    "V2_RULE_REF_UNKNOWN", operand_base + ".factor",
                    f"operand references undeclared factor {operand.factor!r}",
                    "use one of the declared factor names: " + ", ".join(sorted(known_factors)),
                ))
    return issues


def validate_derived_spec(spec: ExperimentSpec) -> list[RawIssue]:
    """Validate derived_spec semantics (whitelist, args, duplicates, bounds)."""
    assert spec.derived_spec is not None  # caller checks
    ops = spec.derived_spec
    issues: list[RawIssue] = []
    known_factors = {factor.name: {level.name for level in factor.levels} for factor in spec.factors}

    if len(ops) > MAX_DERIVED_OPS:
        issues.append((
            "V2_DERIVED_BOUNDS", "derived_spec",
            f"derived_spec has {len(ops)} ops, limit {MAX_DERIVED_OPS}",
            f"reduce to at most {MAX_DERIVED_OPS} declared derived values",
        ))
    seen: set[str] = set()
    for i, op_spec in enumerate(ops):
        base = f"derived_spec[{i}]"
        if not op_spec.name:
            issues.append((
                "V2_DERIVED_BAD_NAME", base + ".name",
                "derived value name must be a non-empty string",
                "provide a unique non-empty name",
            ))
        elif op_spec.name in seen:
            issues.append((
                "V2_DERIVED_DUPLICATE_NAME", base + ".name",
                f"duplicate derived value name {op_spec.name!r}",
                "derived value names must be unique",
            ))
        else:
            seen.add(op_spec.name)
        if op_spec.op not in DERIVED_OP_WHITELIST:
            issues.append((
                "V2_DERIVED_UNKNOWN_OP", base + ".op",
                f"op {op_spec.op!r} is not in the whitelist {list(DERIVED_OP_WHITELIST)}",
                "use one of: " + ", ".join(DERIVED_OP_WHITELIST),
            ))
            continue
        if op_spec.op == "count_factor_level":
            for key in ("factor", "level"):
                if key not in op_spec.args:
                    issues.append((
                        "V2_DERIVED_BAD_ARGS", base + ".args",
                        f"op count_factor_level requires args {set(('factor', 'level'))}, "
                        f"got {sorted(op_spec.args)}",
                        "provide args: {\"factor\": <name>, \"level\": <name>}",
                    ))
            extra = set(op_spec.args) - {"factor", "level"}
            if extra:
                issues.append((
                    "V2_DERIVED_BAD_ARGS", base + ".args",
                    f"op count_factor_level got unexpected args {sorted(extra)}",
                    "provide exactly args: {\"factor\": <name>, \"level\": <name>}",
                ))
            factor = op_spec.args.get("factor")
            level = op_spec.args.get("level")
            if factor is not None and factor not in known_factors:
                issues.append((
                    "V2_DERIVED_BAD_ARGS", base + ".args.factor",
                    f"factor {factor!r} is not a declared factor",
                    "use one of the declared factor names: " + ", ".join(sorted(known_factors)),
                ))
            elif factor is not None and level is not None and level not in known_factors.get(factor, set()):
                issues.append((
                    "V2_DERIVED_BAD_ARGS", base + ".args.level",
                    f"level {level!r} is not declared for factor {factor!r}",
                    "use one of the declared levels of that factor",
                ))
        else:  # trial_number, block_progress: no args
            if op_spec.args:
                issues.append((
                    "V2_DERIVED_BAD_ARGS", base + ".args",
                    f"op {op_spec.op!r} takes no args, got {sorted(op_spec.args)}",
                    "remove args for this op",
                ))
    return issues


_SOURCE_PATH_RE = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)*$")


def validate_measures(spec: ExperimentSpec) -> list[RawIssue]:
    """Validate measures metadata (names, source paths, duplicates, bounds).

    Metadata only: describes measurement intent; claims no runtime collection
    capability (conformance is verified by M2-D reconciliation, not here).
    """
    assert spec.measures is not None  # caller checks
    measures = spec.measures
    issues: list[RawIssue] = []
    if len(measures) > MAX_MEASURES:
        issues.append((
            "V2_MEASURE_BOUNDS", "measures",
            f"measures has {len(measures)} entries, limit {MAX_MEASURES}",
            f"reduce to at most {MAX_MEASURES} declared measures",
        ))
    seen: set[str] = set()
    for i, measure in enumerate(measures):
        base = f"measures[{i}]"
        if not measure.name:
            issues.append((
                "V2_MEASURE_BAD_NAME", base + ".name",
                "measure name must be a non-empty string",
                "provide a unique non-empty name",
            ))
        elif measure.name in seen:
            issues.append((
                "V2_MEASURE_DUPLICATE_NAME", base + ".name",
                f"duplicate measure name {measure.name!r}",
                "measure names must be unique",
            ))
        else:
            seen.add(measure.name)
        if not measure.source or not _SOURCE_PATH_RE.match(measure.source):
            issues.append((
                "V2_MEASURE_BAD_SOURCE", base + ".source",
                f"source {measure.source!r} is not a dotted lowercase path "
                "(e.g. \"response.rt_ms\")",
                "provide a dotted path of [a-z0-9_] segments naming the intended log field",
            ))
    return issues


# ---------------------------------------------------------------------------
# 2. Deterministic materialization (frozen algorithm, contract §1.4)
# ---------------------------------------------------------------------------

def _trial_stimulus_rng(seed: int, index: int) -> random.Random:
    """Per-trial isolated random stream (digest-derived; PYTHONHASHSEED-independent)."""
    digest = sha256_hex(f"{seed}|{index}|stimulus")
    return random.Random(int(digest[:16], 16))


def _render_line(line: str, trial_factors: dict[str, str], pools: dict[str, list[str]],
                 bindings: dict[str, list[str]], rng: random.Random) -> str:
    """Render one line.

    {factor} substitutes the assigned level (no draw); {pool:x} draws one line;
    {var:name} / {var:name[i]} reuses already-bound content (no draw), so a
    reference costs nothing and stays reproducible across identical trials.
    """
    result: list[str] = []
    cursor = 0
    for match in _SLOT_RE.finditer(line):
        result.append(line[cursor:match.start()])
        content = match.group(1)
        if content.startswith(_POOL_PREFIX):
            pool_name = content[len(_POOL_PREFIX):]
            result.append(rng.choice(pools[pool_name]))  # exactly one draw per slot
        elif content.startswith(_VAR_PREFIX):
            parsed = _VAR_SLOT_RE.match(content[len(_VAR_PREFIX):])
            assert parsed is not None  # validated before materialization
            values = bindings[parsed.group(1)]
            raw_index = parsed.group(2)
            result.append(
                " ".join(values) if raw_index is None else values[int(raw_index)]
            )
        else:
            result.append(trial_factors[content])  # no draw; deterministic substitution
        cursor = match.end()
    result.append(line[cursor:])
    return "".join(result)


# ---------------------------------------------------------------------------
# Intra-trial variable binding (M3-A P0)
# ---------------------------------------------------------------------------

def _count_for(var: StimulusVariableSpec, trial_factors: dict[str, str]) -> int:
    """Element count for this trial: a constant, or the level's count from the map."""
    if var.count is None:
        return 1
    if isinstance(var.count, int):
        return var.count
    return var.count.levels[trial_factors[var.count.factor]]


def _bind_variable(var: StimulusVariableSpec, trial_factors: dict[str, str],
                   bindings: dict[str, list[str]], pools: dict[str, list[str]],
                   rng: random.Random) -> list[str]:
    """Bind one variable: reference an earlier binding, or draw from a pool."""
    if var.copy_from is not None:
        source = bindings[var.copy_from.var]
        index = var.copy_from.index
        if index == "any":
            return [rng.choice(source)]  # the only reference form that consumes a draw
        if isinstance(index, int):
            return [source[index]]
        return list(source)
    assert var.pool is not None
    excluded: set[str] = set()
    for name in var.exclude:
        excluded.update(bindings[name])
    candidates = [value for value in pools[var.pool] if value not in excluded]
    count = _count_for(var, trial_factors)
    if len(candidates) < count:
        # unreachable for a validated spec (V2_VAR_POOL_EXHAUSTED is a sound bound)
        raise ValueError(
            f"pool {var.pool!r} cannot supply {count} distinct values for variable "
            f"{var.name!r} (available after exclusions: {len(candidates)})"
        )
    return rng.sample(candidates, count)


def _materialize_variables(spec: ExperimentSpec, trial: Trial,
                           rng: random.Random) -> dict[str, list[str]]:
    """Bind every variable whose `when` guard matches this trial, in declaration order.

    Draw order (frozen): variables (declaration order) -> template selection ->
    slot rendering left-to-right. Only pool draws and copy index "any" consume
    randomness; plain references consume none.
    """
    assert spec.stimulus_spec is not None
    bindings: dict[str, list[str]] = {}
    for var in spec.stimulus_spec.variables:
        if var.when and any(trial.factors.get(key) != value for key, value in var.when.items()):
            continue  # guarded binding that does not apply to this trial
        bindings[var.name] = _bind_variable(
            var, trial.factors, bindings, spec.stimulus_spec.pools, rng
        )
    return bindings


def _materialize_stimulus(spec: ExperimentSpec, trial: Trial) -> dict[str, list[str]]:
    """Fill trial.stimulus and return this trial's variable bindings.

    Unphased (factors path): stimulus = {"lines": [...]} — the M2-B shape.
    Phased (phases path): stimulus = {"lines": [concatenation in phase order],
    "phases": [materialized phases]} — `lines` keeps the historical shape so
    phase-unaware consumers are unchanged.
    """
    assert spec.stimulus_spec is not None
    stim = spec.stimulus_spec
    rng = _trial_stimulus_rng(spec.seed, trial.index)
    bindings = _materialize_variables(spec, trial, rng)

    if stim.phases:
        materialized_phases: list[dict[str, object]] = []
        all_lines: list[str] = []
        for phase in stim.phases:
            rendered = [
                _render_line(line, trial.factors, stim.pools, bindings, rng)
                for line in phase.lines
            ]
            materialized_phases.append(
                {
                    "name": phase.name,
                    "lines": rendered,
                    "duration_ms": phase.duration_ms,
                    "advance": phase.advance,
                    "response_window": phase.response_window,
                }
            )
            all_lines.extend(rendered)
        trial.stimulus = {"lines": all_lines, "phases": materialized_phases}
        return bindings

    lines: list[str] = []
    # template selection per stimulus-mapped factor, in spec factor declaration order
    for factor in spec.factors:
        factor_spec = stim.factors.get(factor.name)
        if factor_spec is None:
            continue
        templates = factor_spec.levels[trial.factors[factor.name]]
        lines.extend(rng.choice(templates))
    # slot rendering across the whole line list, left-to-right in reading order
    trial.stimulus = {
        "lines": [
            _render_line(line, trial.factors, stim.pools, bindings, rng) for line in lines
        ]
    }
    return bindings


def _materialize_derived(spec: ExperimentSpec, trials: list[Trial]) -> None:
    """Fill trial.derived[name] for every declared op (values always int)."""
    assert spec.derived_spec is not None
    ops = spec.derived_spec
    block_first: dict[str, int] = {}
    for trial in trials:
        block_first.setdefault(trial.block, trial.index)
    cumulative: dict[tuple[str, str], int] = {}
    for trial in trials:
        for op_spec in ops:
            trial.derived[op_spec.name] = _derived_value(op_spec, trial, block_first, cumulative)
        for factor_name, level_name in trial.factors.items():
            key = (factor_name, level_name)
            cumulative[key] = cumulative.get(key, 0) + 1


def _derived_value(op_spec: DerivedOpSpec, trial: Trial,
                   block_first: dict[str, int],
                   cumulative: dict[tuple[str, str], int]) -> int:
    """Compute one derived value from trial context only (never prior outcomes)."""
    if op_spec.op == "trial_number":
        return trial.index + 1
    if op_spec.op == "block_progress":
        return trial.index - block_first[trial.block] + 1
    # count_factor_level: cumulative count through the current trial, inclusive
    key = (op_spec.args["factor"], op_spec.args["level"])
    count = cumulative.get(key, 0)
    if trial.factors.get(op_spec.args["factor"]) == op_spec.args["level"]:
        count += 1
    return count


# ---------------------------------------------------------------------------
# Content-driven correctness (M3-A P0)
# ---------------------------------------------------------------------------

def _operand_value(operand: RuleOperandSpec, bindings: dict[str, list[str]],
                   trial_factors: dict[str, str]) -> object:
    """Resolve one rule operand to a string, or to a list for a multi-element binding."""
    if operand.var is not None:
        values = bindings[operand.var]
        if operand.index is not None:
            return values[operand.index]
        return values[0] if len(values) == 1 else list(values)
    if operand.factor is not None:
        return trial_factors[operand.factor]
    return operand.literal


def _eval_rule(rule: CorrectRuleSpec, bindings: dict[str, list[str]],
               trial_factors: dict[str, str]) -> bool:
    """Evaluate a closed relation over materialized content (eq / neq / in)."""
    left = _operand_value(rule.left, bindings, trial_factors)
    right = _operand_value(rule.right, bindings, trial_factors)
    if rule.op == "eq":
        return bool(left == right)
    if rule.op == "neq":
        return bool(left != right)
    # in: membership in the right operand (a single value behaves as a singleton)
    return bool(left in right) if isinstance(right, list) else bool(left == right)


def _materialize_correct(spec: ExperimentSpec, trial: Trial,
                         bindings: dict[str, list[str]]) -> None:
    """Write trial.correct[response_name] for every response carrying a correct_rule."""
    for response in spec.responses:
        rule = response.correct_rule
        if rule is None:
            continue
        outcome = _eval_rule(rule, bindings, trial.factors)
        trial.correct[response.name] = rule.true_option if outcome else rule.false_option


def materialize_trials(spec: ExperimentSpec, trials: list[Trial]) -> None:
    """Materialize stimulus content, derived values and content-driven answer keys.

    Called by generate_trials BEFORE fingerprint computation: materialized
    content is fully covered by trials_fingerprint. No-op for every unset v2
    feature, so v1-shaped specs are byte-identical to the v1 engine.
    """
    if spec.stimulus_spec is not None:
        for trial in trials:
            bindings = _materialize_stimulus(spec, trial)
            _materialize_correct(spec, trial, bindings)
    if spec.derived_spec is not None:
        _materialize_derived(spec, trials)
