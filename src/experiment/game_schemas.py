"""GameSpec schema and the validate_game check (Phase B contract B0 version, frozen).

Core rule (contract §1): experiment logic belongs to ExperimentSpec/Bundle, game presentation to GameSpec.
GameSpec only holds "references" (the triple-fingerprint ExperimentRef) and never "recomputation" — there is no
condition-allocation / trial / correctness field at all; every model is extra="forbid" (defense D-1).

Validation rules G1~G7 (contract §4):
- G1 schema layer: Pydantic validation (including rejection of undeclared fields) → SCHEMA_INVALID;
- G2 cross-layer reference: the six experiment_ref fields align with the Bundle + full-bundle fingerprint recomputation → REF_MISMATCH;
- G3/G4/G5/G6 cross-layer key-binding rules → UNKNOWN_RESPONSE / INVALID_BINDING_TARGET /
  OPTION_OUT_OF_DOMAIN / DUPLICATE_KEY / MISSING_BINDING / INVALID_KEY；
- G7 size guard: serialized > 256KB → GAME_SPEC_TOO_LARGE.

Determinism (contract §5): validate_game is a pure function; game_config_fingerprint =
SHA-256(canonical_json(game_spec)) — same content, same fingerprint, independent of key order/whitespace.

MVP marker (contract §9): the state machine and interaction types are the MVP support set, not a permanent architectural limit.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.experiment.canonical import canonical_json, sha256_hex

MAX_GAME_SPEC_BYTES = 256 * 1024  # serialization size guard (G7, mirrors the Phase A config guard)

_HEX64 = r"^[0-9a-f]{64}$"
_NAMED_KEYS = frozenset({"space", "enter", "left", "right", "up", "down"})


class _Forbid(BaseModel):
    """Defense D-1: reject every undeclared field."""

    model_config = ConfigDict(extra="forbid")


class GameMeta(_Forbid):
    """Game self-identification (pure presentation metadata)."""

    name: str = Field(min_length=1, max_length=100)
    version: str = "0.1.0"


class ExperimentRef(_Forbid):
    """Reference to the ExperimentBundle (triple-fingerprint alignment; fields are read-only pointer copies, not experiment logic)."""

    name: str
    version: str
    seed: int
    config_fingerprint: str = Field(pattern=_HEX64)
    trials_fingerprint: str = Field(pattern=_HEX64)
    bundle_sha256: str = Field(pattern=_HEX64)


class SceneSpec(_Forbid):
    """Scene presentation (pure presentation; assets are UI decoration only, forbidden from trial content — renderer contract enforcement)."""

    title: str = Field(default="", max_length=200)
    instructions: str = Field(default="", max_length=2000)
    layout: Literal["canvas-center", "rows"] = "canvas-center"
    theme: Literal["neutral-light", "dark"] = "neutral-light"
    assets: dict[str, str] = Field(default_factory=dict)


class InputBinding(_Forbid):
    """Key binding: physical key → choice option value (bound to a response variable declared in ExperimentSpec)."""

    response_name: str
    keys: dict[str, str]


class InputSpec(_Forbid):
    """Input modality and bindings (B0: keyboard only; pointer/touch are reserved extension points via contract revision)."""

    modalities: list[Literal["keyboard"]] = Field(default_factory=lambda: ["keyboard"])
    bindings: list[InputBinding] = Field(default_factory=list)


class FeedbackSpec(_Forbid):
    """Feedback style (correctness is read-only from the Bundle; this layer only picks the presentation form)."""

    on_response: Literal["none", "correctness-flash", "outcome-text"] = "none"
    duration_ms: int = Field(default=200, ge=0, le=5000)


class FlowSpec(_Forbid):
    """Flow switches (MVP flow: ready/block breaks/end screen, contract §9.1)."""

    ready_screen: bool = True
    block_breaks: bool = True
    end_screen: Literal["none", "summary"] = "summary"


class GamificationSpec(_Forbid):
    """Gamification wrapper (all optional; the score is accumulated by the renderer from Bundle correctness)."""

    score: bool = False
    progress_bar: bool = True
    streak_bonus: bool = False


class GameSpec(_Forbid):
    """Game presentation spec (the root model of the presentation layer)."""

    schema_version: Literal[1] = 1
    game: GameMeta
    experiment_ref: ExperimentRef
    scene: SceneSpec = Field(default_factory=SceneSpec)
    input: InputSpec = Field(default_factory=InputSpec)
    feedback: FeedbackSpec = Field(default_factory=FeedbackSpec)
    flow: FlowSpec = Field(default_factory=FlowSpec)
    gamification: GamificationSpec = Field(default_factory=GamificationSpec)


class GameValidationIssue(BaseModel):
    """Validation issue (shared by errors and warnings; structure aligned with Phase A ValidationIssue)."""

    error_code: str
    path: str
    message: str
    suggestion: str


class GameValidationResult(BaseModel):
    """Return value of validate_game (contract §4 output structure)."""

    game_spec: GameSpec | None  # None when G1 fails
    valid: bool
    errors: list[GameValidationIssue]
    warnings: list[GameValidationIssue]
    game_config_fingerprint: str | None  # None when G1 fails


def game_config_fingerprint(game_spec: GameSpec) -> str:
    """GameSpec fingerprint: SHA-256(canonical_json(model_dump())) — key-order/whitespace independent (§5)."""
    return sha256_hex(canonical_json(game_spec.model_dump()))


def _issue(error_code: str, path: str, message: str, suggestion: str) -> GameValidationIssue:
    return GameValidationIssue(
        error_code=error_code, path=path, message=message, suggestion=suggestion
    )


def _pydantic_issues(exc: ValidationError) -> list[GameValidationIssue]:
    """Pydantic ValidationError → a structured list of SCHEMA_INVALID issues."""
    issues: list[GameValidationIssue] = []
    for err in exc.errors():
        loc = ".".join(str(part) for part in err["loc"]) or "<root>"
        msg = str(err.get("msg", "invalid"))
        issues.append(
            _issue(
                "SCHEMA_INVALID",
                loc,
                msg,
                "fix the field to match the GameSpec schema; unknown fields are forbidden",
            )
        )
    return issues


def _check_size_guard(raw: object, errors: list[GameValidationIssue]) -> bool:
    """G7 size guard: serialized bytes > 256KB → GAME_SPEC_TOO_LARGE. Returns whether to continue."""
    try:
        size = len(canonical_json(raw).encode("utf-8"))
    except (TypeError, ValueError):
        errors.append(
            _issue(
                "SCHEMA_INVALID",
                "<root>",
                "game spec is not serializable to canonical JSON",
                "pass a JSON-compatible dict",
            )
        )
        return False
    if size > MAX_GAME_SPEC_BYTES:
        errors.append(
            _issue(
                "GAME_SPEC_TOO_LARGE",
                "<root>",
                f"game spec serializes to {size} bytes (> {MAX_GAME_SPEC_BYTES})",
                "reduce scene.assets size or text lengths",
            )
        )
        return False
    return True


def _bundle_expected(bundle: dict[str, object]) -> dict[str, tuple[str, object]] | None:
    """Extract the six G2 expected values from the Bundle; return None when the structure is incomplete."""
    spec_part = bundle.get("spec")
    repro = bundle.get("reproducibility")
    if not isinstance(spec_part, dict) or not isinstance(repro, dict):
        return None
    return {
        "experiment_ref.name": ("name", spec_part.get("name")),
        "experiment_ref.version": ("version", spec_part.get("version")),
        "experiment_ref.seed": ("seed", spec_part.get("seed")),
        "experiment_ref.config_fingerprint": (
            "config_fingerprint",
            repro.get("config_fingerprint"),
        ),
        "experiment_ref.trials_fingerprint": (
            "trials_fingerprint",
            repro.get("trials_fingerprint"),
        ),
        "experiment_ref.bundle_sha256": ("bundle_sha256", bundle.get("bundle_sha256")),
    }


def _check_reference(
    ref: ExperimentRef, bundle: dict[str, object], errors: list[GameValidationIssue]
) -> None:
    """G2: full-bundle integrity recomputation + the six references compared one by one (the first mismatch is reported, contract §4)."""
    # Full-bundle integrity recomputation (contract §9.2: reproducible verification, detects a tampered Bundle)
    try:
        stripped = {
            key: value
            for key, value in bundle.items()
            if key not in ("bundle_sha256", "generated_at")
        }
        recomputed = sha256_hex(canonical_json(stripped))
    except (TypeError, ValueError):
        errors.append(
            _issue(
                "REF_MISMATCH",
                "experiment_ref.bundle_sha256",
                "bundle is not serializable; cannot verify integrity",
                "load a valid ExperimentBundle produced by export_experiment",
            )
        )
        return
    if recomputed != bundle.get("bundle_sha256"):
        errors.append(
            _issue(
                "REF_MISMATCH",
                "experiment_ref.bundle_sha256",
                "bundle integrity check failed: recomputed bundle_sha256 does not match",
                "re-export the ExperimentBundle from the ExperimentSpec; do not hand-edit bundles",
            )
        )
        return
    expected = _bundle_expected(bundle)
    if expected is None:
        errors.append(
            _issue(
                "REF_MISMATCH",
                "experiment_ref",
                "bundle is missing spec/reproducibility sections",
                "load a valid ExperimentBundle produced by export_experiment",
            )
        )
        return
    # Compare the six one by one (report the first mismatch)
    for path, (attr, actual) in expected.items():
        given = getattr(ref, attr)
        if given != actual:
            errors.append(
                _issue(
                    "REF_MISMATCH",
                    path,
                    f"reference {attr}={given!r} does not match bundle {actual!r}",
                    f"copy the actual value from the ExperimentBundle ({attr})",
                )
            )
            return


def _check_bindings(
    game_spec: GameSpec, bundle: dict[str, object], errors: list[GameValidationIssue]
) -> list[GameValidationIssue]:
    """G3~G6 cross-layer key-binding rules; also returns warnings (PARTIAL_OPTION_COVERAGE, §9.4)."""
    warnings: list[GameValidationIssue] = []
    spec_part = bundle.get("spec")
    if not isinstance(spec_part, dict):
        return warnings
    raw_responses = spec_part.get("responses")
    if not isinstance(raw_responses, list):
        return warnings

    responses: dict[str, dict[str, object]] = {}
    for raw in raw_responses:
        if isinstance(raw, dict) and isinstance(raw.get("name"), str):
            responses[raw["name"]] = raw

    keyboard = "keyboard" in game_spec.input.modalities
    seen_keys: dict[str, int] = {}  # physical key → index of the first binding that uses it
    bound_options: dict[str, set[str]] = {}

    for i, binding in enumerate(game_spec.input.bindings):
        path = f"input.bindings[{i}]"
        response = responses.get(binding.response_name)
        if response is None:  # G3
            errors.append(
                _issue(
                    "UNKNOWN_RESPONSE",
                    f"{path}.response_name",
                    f"response {binding.response_name!r} is not declared in the experiment spec",
                    "use a response name from the ExperimentBundle spec.responses",
                )
            )
            continue
        if response.get("kind") != "choice":  # G4
            errors.append(
                _issue(
                    "INVALID_BINDING_TARGET",
                    f"{path}.response_name",
                    f"response {binding.response_name!r} has kind {response.get('kind')!r}; "
                    "only choice responses accept key bindings",
                    "remove the binding or target a choice response",
                )
            )
            continue
        options = response.get("options")
        option_set = set(options) if isinstance(options, list) else set()
        for key, value in binding.keys.items():
            # G6 key format
            if not (key in _NAMED_KEYS or (len(key) == 1 and "a" <= key <= "z")):
                errors.append(
                    _issue(
                        "INVALID_KEY",
                        f"{path}.keys.{key}",
                        f"invalid physical key {key!r}",
                        "use a single lowercase letter or one of: "
                        + ", ".join(sorted(_NAMED_KEYS)),
                    )
                )
                continue
            # G5 duplicate key
            if key in seen_keys:
                errors.append(
                    _issue(
                        "DUPLICATE_KEY",
                        f"{path}.keys.{key}",
                        f"key {key!r} already bound in input.bindings[{seen_keys[key]}]",
                        "each physical key must map to exactly one option",
                    )
                )
                continue
            seen_keys[key] = i
            # G5 option out of domain
            if value not in option_set:
                errors.append(
                    _issue(
                        "OPTION_OUT_OF_DOMAIN",
                        f"{path}.keys.{key}",
                        f"value {value!r} is not an option of response "
                        f"{binding.response_name!r}",
                        f"use one of the declared options: {sorted(option_set)}",
                    )
                )
                continue
            bound_options.setdefault(binding.response_name, set()).add(value)

    # G5 missing binding: under the keyboard modality every choice response needs at least one binding
    if keyboard:
        for name, response in responses.items():
            if response.get("kind") != "choice":
                continue
            if name not in bound_options:
                errors.append(
                    _issue(
                        "MISSING_BINDING",
                        "input.bindings",
                        f"choice response {name!r} has no key binding",
                        f"add an InputBinding with response_name={name!r} covering its options",
                    )
                )

    # Warning: partial option coverage (legal but some options may be unreachable, §9.4)
    for name, response in responses.items():
        if response.get("kind") != "choice":
            continue
        options = response.get("options")
        if not isinstance(options, list):
            continue
        covered = bound_options.get(name, set())
        if covered and covered < set(options):
            warnings.append(
                _issue(
                    "PARTIAL_OPTION_COVERAGE",
                    "input.bindings",
                    f"response {name!r}: bound options {sorted(covered)} do not cover "
                    f"all declared options {sorted(set(options))}",
                    "cover every option with a key so all choices are reachable",
                )
            )
    return warnings


def validate_game(game_spec: object, bundle: object) -> GameValidationResult:
    """Validate a GameSpec (G1~G7, pure function). bundle is a loaded ExperimentBundle dict."""
    errors: list[GameValidationIssue] = []

    # G1 precondition: must be a dict
    if not isinstance(game_spec, dict):
        return GameValidationResult(
            game_spec=None,
            valid=False,
            errors=[
                _issue(
                    "SCHEMA_INVALID",
                    "<root>",
                    "game spec must be a JSON object (dict)",
                    "pass the GameSpec JSON object itself",
                )
            ],
            warnings=[],
            game_config_fingerprint=None,
        )

    # G7 size guard (measured on the raw input)
    if not _check_size_guard(game_spec, errors):
        return GameValidationResult(
            game_spec=None, valid=False, errors=errors, warnings=[], game_config_fingerprint=None
        )

    # G1 schema layer
    try:
        parsed = GameSpec.model_validate(game_spec)
    except ValidationError as exc:
        return GameValidationResult(
            game_spec=None,
            valid=False,
            errors=_pydantic_issues(exc),
            warnings=[],
            game_config_fingerprint=None,
        )

    fingerprint = game_config_fingerprint(parsed)

    # G2~G6 need the Bundle; a non-dict bundle → REF_MISMATCH (references cannot be aligned)
    if not isinstance(bundle, dict):
        errors.append(
            _issue(
                "REF_MISMATCH",
                "experiment_ref",
                "bundle must be a loaded ExperimentBundle dict",
                "load the bundle JSON produced by export_experiment",
            )
        )
        return GameValidationResult(
            game_spec=parsed,
            valid=False,
            errors=errors,
            warnings=[],
            game_config_fingerprint=fingerprint,
        )

    _check_reference(parsed.experiment_ref, bundle, errors)
    warnings = _check_bindings(parsed, bundle, errors)

    return GameValidationResult(
        game_spec=parsed,
        valid=not errors,
        errors=errors,
        warnings=warnings,
        game_config_fingerprint=fingerprint,
    )
