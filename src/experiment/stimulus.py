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
   - template selection: for each factor WITH a stimulus entry, in spec factor
     declaration order, one rng.choice over the assigned level's templates;
   - line assembly: selected templates' lines concatenated in the same factor
     order;
   - slot rendering: each line scanned left-to-right; every {pool:x} consumes
     exactly one rng.choice draw in reading order across the whole line list;
     {factor} slots substitute the trial's assigned level name without drawing;
   - output: trial.stimulus = {"lines": [str, ...]} (no other keys);
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
    DerivedOpSpec,
    ExperimentSpec,
    MeasureSpec,
    StimulusSpec,
    Trial,
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

# MVP closed derived-op whitelist (contract §1.5). Nothing escapes it.
DERIVED_OP_WHITELIST: tuple[str, ...] = ("trial_number", "block_progress", "count_factor_level")

# Slot grammar: {factor_name} or {pool:pool_name}; names are [A-Za-z0-9_]+.
_SLOT_RE = re.compile(r"\{([^{}]*)\}")
_SLOT_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")
_POOL_PREFIX = "pool:"

# Raw issue tuple: (error_code, json_path, message, suggestion)
RawIssue = tuple[str, str, str, str]


# ---------------------------------------------------------------------------
# Slot parsing
# ---------------------------------------------------------------------------

def _parse_slots(line: str) -> list[tuple[str, str]]:
    """Return [(slot_content, name)] for every slot in the line, left-to-right.

    slot_content: the raw inner text; name: the reference name (pool or factor).
    Raises ValueError on a name that violates the slot-name grammar.
    """
    slots: list[tuple[str, str]] = []
    for match in _SLOT_RE.finditer(line):
        content = match.group(1)
        name = content[len(_POOL_PREFIX):] if content.startswith(_POOL_PREFIX) else content
        if not _SLOT_NAME_RE.match(name):
            raise ValueError(f"invalid slot name {name!r} (must match [A-Za-z0-9_]+)")
        slots.append((content, name))
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
# 1. Semantic validation (raw issues; validation.py wraps them)
# ---------------------------------------------------------------------------

def validate_stimulus_spec(spec: ExperimentSpec) -> list[RawIssue]:
    """Validate stimulus_spec semantics (bounds, references, slots, line counts)."""
    assert spec.stimulus_spec is not None  # caller checks
    stim = spec.stimulus_spec
    issues: list[RawIssue] = []
    known_factors = {factor.name: {level.name for level in factor.levels} for factor in spec.factors}

    if not stim.factors:
        issues.append((
            "V2_STIM_EMPTY", "stimulus_spec.factors",
            "stimulus_spec.factors must contain at least one factor entry",
            "add an entry mapping a declared factor name to its per-level templates, "
            "or remove stimulus_spec entirely",
        ))
        return issues
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
                            for content, name in _parse_slots(line):
                                _ = content, name  # grammar checked here; resolution below
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
                    for content, name in slots:
                        path = f"stimulus_spec.factors[{factor_name!r}].levels[{level_name!r}][{ti}][{li}]"
                        if content.startswith(_POOL_PREFIX):
                            if name not in stim.pools:
                                issues.append((
                                    "V2_STIM_UNRESOLVED_SLOT", path,
                                    f"slot {content!r} references undefined pool {name!r}",
                                    "define the pool in stimulus_spec.pools, or fix the slot name",
                                ))
                        elif name not in known_factors:
                            issues.append((
                                "V2_STIM_UNRESOLVED_SLOT", path,
                                f"slot {content!r} does not reference a declared factor "
                                "(response names are not valid slots)",
                                "slots must reference declared factor names, or pools via {pool:name}",
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
                 rng: random.Random) -> str:
    """Render one line: {factor} substitutes the assigned level; {pool:x} draws one line."""
    result: list[str] = []
    cursor = 0
    for match in _SLOT_RE.finditer(line):
        result.append(line[cursor:match.start()])
        content = match.group(1)
        if content.startswith(_POOL_PREFIX):
            pool_name = content[len(_POOL_PREFIX):]
            result.append(rng.choice(pools[pool_name]))  # exactly one draw per slot
        else:
            result.append(trial_factors[content])  # no draw; deterministic substitution
        cursor = match.end()
    result.append(line[cursor:])
    return "".join(result)


def _materialize_stimulus(spec: ExperimentSpec, trial: Trial) -> None:
    """Fill trial.stimulus = {"lines": [...]} (no other keys)."""
    assert spec.stimulus_spec is not None
    stim = spec.stimulus_spec
    rng = _trial_stimulus_rng(spec.seed, trial.index)
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
        "lines": [_render_line(line, trial.factors, stim.pools, rng) for line in lines]
    }


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


def materialize_trials(spec: ExperimentSpec, trials: list[Trial]) -> None:
    """Materialize stimulus content and derived values into the trial list.

    Called by generate_trials BEFORE fingerprint computation: materialized
    content is fully covered by trials_fingerprint. No-op for every unset v2
    feature, so v1-shaped specs are byte-identical to the v1 engine.
    """
    if spec.stimulus_spec is not None:
        for trial in trials:
            _materialize_stimulus(spec, trial)
    if spec.derived_spec is not None:
        _materialize_derived(spec, trials)
