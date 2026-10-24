"""The three experiment tools: validate_experiment / generate_trials / export_experiment (contract §5).

Style aligned with calc.py / file_write.py: Input model + internal _ExperimentBlocked exception +
BLOCKED: prefix + build_*(settings) -> ToolSpec factories.

Two-tier error contract (§5.4):
- tool-level failure (non-dict input, serialization failure, security refusal and other infrastructure errors) → ok=False;
- domain-level failure (spec problems) → always ok=True + valid:false (returned to the LLM without the ERROR: prefix).

Guards: config serialized bytes > 256KB → BLOCKED: config too large (shared by all three tools);
export's canonical bundle bytes > 1MB → BLOCKED: export too large (OUT-7 / R-6).
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

MAX_CONFIG_BYTES = 256 * 1024  # config input size guard (§5.1)
MAX_BUNDLE_BYTES = 1_048_576  # 1MB export cap (OUT-7 / R-6, same order as file_write)

# R2 revision (2026-10-20, user-approved diagnostic fix F1): the minimal complete ExperimentSpec example
# embedded in the validate_experiment description (frozen text of the contract §5.1 R2 revision block). A module-level
# constant as the single source; tests share this object with the description to prevent drift.
# R2 requirement: pure ASCII (diagnosis report F1 — the R1 long Chinese description caused empty tool-call
# outputs on qwen2.5:7b + Ollama 0.40.6; the sole correlating variable was the schema form of the description; this revision is a controlled test of that hypothesis).
_SPEC_EXAMPLE_JSON = (
    '{"schema_version":1,"name":"demo","seed":7,'
    '"factors":[{"name":"item","levels":[{"name":"red"},{"name":"blue"}]}],'
    '"blocks":[{"name":"main","trial_count":8}],'
    '"constraints":{"balance":true},'
    '"responses":[{"name":"pick","kind":"choice","options":["red","blue"],'
    '"correct_from":"item"}],'
    '"timing":{"fixation_ms":400,"stimulus_ms":null,"isi_ms":800}}'
)

_GENERATE_NOTE = "full sequence reproducible via export_experiment with identical spec+seed"


class _ExperimentBlocked(Exception):
    """Tool-level security/guard refusal (→ BLOCKED: prefix)."""


class ValidateExperimentInput(BaseModel):
    """validate_experiment arguments (contract §5.1)."""

    # The config field description is the v2 documentation surface (M2-B): it
    # travels with the tools JSON schema to the LLM while the ToolSpec-level
    # description stays within the token budget test's limits.
    config: dict[str, object] = Field(
        description=(
            "The ExperimentSpec JSON object itself (no wrapper). schema_version=1: see the tool "
            "description example. Optional schema_version=2 research fields (omit when unused): "
            "stimulus_spec={factors:{name:{levels:{level:[templates]}},match_line_count}},pools} "
            "where a template is a list of text lines with slots {factor_name} (substitutes the "
            "trial's assigned level) and {pool:name} (draws one pool line); derived_spec=[{name,op,"
            "args}] with ops trial_number, block_progress, count_factor_level(factor,level); "
            "measures=[{name,source}] declared measurement metadata (no runtime collection claim). "
            "stimulus_spec.variables (intra-trial content binding): [{name,pool,count,exclude,"
            "copy_from,when}] in declaration order. pool=pool name to draw from; count=int or "
            "{factor,levels:{level:int}} (elements drawn per condition, so factor levels differ in "
            "real content); exclude=[var names] forbids values already bound there; copy_from="
            "{var,index} reuses an earlier variable's bound content (index null=whole list, "
            "integer=one element, 'any'=one element chosen by the seed; no new pool draw); "
            "when={factor:level} guards a binding per condition (one entry per level, together "
            "covering every level of that factor). Reference bound content in any template line "
            "with slots {var:name} (whole list, space-joined) or {var:name[i]} (element i); "
            "references consume no randomness. stimulus_spec.phases (sequential in-trial "
            "presentation): [{name,lines,duration_ms,advance,response_window}] plays each trial's "
            "lines as ordered phases: duration_ms=null advances on input, advance is auto or "
            "keypress, response_window=true opens the response collection during that phase "
            "(one response per window phase, RT anchored at its onset; keys outside a window are "
            "not recorded). phases replaces per-factor templates (declare factors:{} and list "
            "one window phase per response). "
            "responses[].correct_rule (content-driven answer "
            "key, exclusive with correct_from): {op,left,right,true_option,false_option} where op "
            "is eq, neq or in; left/right are operands {var:name[,index]}, {factor:name} or "
            "{literal:str}; the boolean relation over the MATERIALIZED content selects "
            "true_option or false_option (both must be declared options), so the answer key "
            "follows the generated content instead of a condition label. "
            "responses[].withhold_option (string): declares that NO keypress is a meaningful "
            "answer and names the answer-key value representing it (must differ from options); "
            "the event log keeps value null for a withheld response and scoring treats null as "
            "that value. blocks[].timing: whole-object per-block replacement of the spec-level "
            "timing (set all three fields; omitted fields fall back to defaults). "
            "Composition recipes (v2, for RELATIONAL content across factors): (1) bind a "
            "target element per level of a content factor using singleton pools guarded by "
            "when={factor:level}; a second element REUSES it via copy_from in one condition "
            "(same content) and draws from the full pool with exclude=[target] in the other "
            "(guaranteed different content). (2) conditional correctness: declare the intended "
            "answer as a factor, derive the stimulus from it via when-guards, and set "
            "correct_from to that factor. (3) make factor levels differ in REAL content with "
            "count={factor,levels:{level:int}} element-count maps. (4) score no-press as "
            "correct: withhold_option on the response plus a key that equals the withhold "
            "value on those trials (correct_rule true/false_option may be the withhold value)."
        )
    )
    previous_errors: list[str] = Field(default_factory=list)  # error_code:path fingerprints of previous rounds


class GenerateTrialsInput(BaseModel):
    """generate_trials arguments (contract §5.2)."""

    config: dict[str, object]
    max_preview_trials: int = Field(default=8, ge=0, le=50)  # number of preview trials returned to the LLM


class ExportExperimentInput(BaseModel):
    """export_experiment arguments (contract §5.3)."""

    config: dict[str, object]
    path: str = Field(min_length=1)  # output path relative to the data/ sandbox root


def _config_size_guard(config: dict[str, object]) -> None:
    """Input size guard: config serialized bytes > 256KB → refuse (§5.1 step 1)."""
    try:
        size = len(json.dumps(config, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise _ExperimentBlocked("config too large") from exc
    if size > MAX_CONFIG_BYTES:
        raise _ExperimentBlocked("config too large")


def _validation_payload(result: ValidationResult, stalled: bool) -> dict[str, object]:
    """Validation report JSON (§5.1 output structure; the generate failure path is isomorphic)."""
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
    """Domain-level failure: ok=True + valid:false (no ERROR: prefix, §5.4)."""
    return ToolResult(ok=True, result=canonical_json(_validation_payload(result, False)))


def _stalled_check(
    result: ValidationResult, previous_errors: list[str]
) -> tuple[bool, list[ValidationIssue]]:
    """Stalled decision (§5.1 step 3): any current fingerprint appearing ≥2 times in previous_errors."""
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
        return _invalid_spec_result(result)  # never generate from an invalid spec (§5.2)
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
        return _invalid_spec_result(result)  # never export an invalid experiment (§5.3 step 2)
    spec = result.spec
    # export deterministically regenerates internally (key ruling: generate's output is not accepted, §5.3)
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
    """Build validate_experiment's ToolSpec (idempotent, read-only, low)."""
    async def executor(base: Any) -> ToolResult:
        return await _execute_validate(cast(ValidateExperimentInput, base))

    return ToolSpec(
        name="validate_experiment",
        description=(
            "Validate ExperimentSpec JSON. config must be the spec object itself, no wrapper. "
            "Top keys: schema_version(=1),name,seed,factors[{name,levels[{name}]}],"
            "blocks[{name,trial_count}],constraints{balance},"
            "responses[{name,kind,options,correct_from}],timing{fixation_ms,stimulus_ms,isi_ms}. "
            "Optional v2 fields: stimulus_spec,derived_spec,measures."
            " Minimal example: "
            + _SPEC_EXAMPLE_JSON
        ),
        input_model=ValidateExperimentInput,
        idempotency="idempotent",
        risk_level="low",
        executor=executor,
    )


def build_generate_spec(settings: Settings) -> ToolSpec:
    """Build generate_trials's ToolSpec (idempotent, pure function, no disk writes, low)."""
    max_attempts = settings.experiment_max_search_attempts  # SEARCH_EXHAUSTED framework capability parameter (§4.2)

    async def executor(base: Any) -> ToolResult:
        return await _execute_generate(cast(GenerateTrialsInput, base), max_attempts)

    return ToolSpec(
        name="generate_trials",
        description=(
            "Deterministically generate the full trial sequence from the experiment spec (the same spec+seed yields "
            "byte-identical results). Returns the sequence fingerprint and per-factor level frequencies for design "
            "review; writes no files. export_experiment regenerates and writes the full sequence from the same spec+seed."
        ),
        input_model=GenerateTrialsInput,
        idempotency="idempotent",
        risk_level="low",
        executor=executor,
    )


def build_export_spec(settings: Settings) -> ToolSpec:
    """Build export_experiment's ToolSpec (non-idempotent, writes to disk, medium)."""
    sandbox = Path(settings.data_sandbox_dir)

    async def executor(base: Any) -> ToolResult:
        return await _execute_export(cast(ExportExperimentInput, base), sandbox)

    return ToolSpec(
        name="export_experiment",
        description=(
            "Materialize the experiment spec into a self-contained ExperimentBundle (normalized spec + full trials "
            "+ reproducibility metadata + SHA-256 integrity fingerprint) and write it to the given path inside the data/ sandbox (overwrites existing files)."
        ),
        input_model=ExportExperimentInput,
        idempotency="non-idempotent",
        risk_level="medium",
        executor=executor,
    )
