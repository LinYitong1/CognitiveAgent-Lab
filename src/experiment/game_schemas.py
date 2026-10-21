"""GameSpec schema and the validate_game check (Phase B contract B0 version, frozen; M2-C v2 extensions).

Core rule (contract §1): experiment logic belongs to ExperimentSpec/Bundle, game presentation to GameSpec.
GameSpec only holds "references" (the triple-fingerprint ExperimentRef) and never "recomputation" — there is no
condition-allocation / trial / correctness field at all; every model is extra="forbid" (defense D-1).

Validation rules G1~G7 (contract §4):
- G1 schema layer: Pydantic validation (including rejection of undeclared fields) → SCHEMA_INVALID;
- G2 cross-layer reference: the six experiment_ref fields align with the Bundle + full-bundle fingerprint recomputation → REF_MISMATCH;
- G3/G4/G5/G6 cross-layer key-binding rules → UNKNOWN_RESPONSE / INVALID_BINDING_TARGET /
  OPTION_OUT_OF_DOMAIN / DUPLICATE_KEY / MISSING_BINDING / INVALID_KEY；
- G7 size guard: serialized > 256KB → GAME_SPEC_TOO_LARGE.

M2-C v2 extensions (schema_version 2 only; docs/m2/M2C_CONTRACT.md, user-approved):
- four optional sections — world (room graph + interactive objects), narrative (static text
  surfaces), mechanics (registered interaction patterns), mapping (research–game mapping);
- v1 GameSpecs validate identically: unset v2 sections are excluded from game_config_fingerprint
  (game_spec_dump projection, same discipline as M2-B's spec_dump), so v1 fingerprints are stable;
- G8_* validation family for v2 sections (G1~G7 paths untouched, run unchanged for both versions).

Invariant enforcement map (user condition: declarations are NOT sufficient evidence — each of the
five controlled invariants is enforced where possible and its residual runtime need documented):

| Invariant        | Static enforcement (this module, design time)                              | Requires runtime / post-session verification |
|------------------|-----------------------------------------------------------------------------|----------------------------------------------|
| trial_order      | no field expresses trial selection or ordering (extra="forbid"); encounter  | full played-sequence reconciliation against  |
|                  | count >= trial count (G8_MAPPING_ENCOUNTER_SHORTFALL); cursor semantics     | the bundle (M2-E verify_game_events)         |
|                  | are the only consumption model (bundle index order, monotonic)              |                                              |
| conditions       | no conditions field exists in any v2 section (extra="forbid" rejects        | trial_start events carry conditions that     |
|                  | smuggled keys); encounter content renders trial.factors at runtime          | must match the bundle trial (M2-E)           |
| stimulus_content | no stimulus field exists in any v2 section; encounters render the           | byte-identity of rendered encounters vs      |
|                  | bundle's materialized trial.stimulus verbatim (no override surface)         | trial.stimulus lines (M2-E re-render check)  |
| correct_answers  | no correctness/correct_from field exists in any v2 section; correctness     | response events recomputed from the bundle   |
|                  | is computed by the renderer from the bundle only                            | (M2-E)                                       |
| timing           | no timing field exists in any v2 section; timings come from trial.timing    | event timestamps vs declared timing (M2-E)   |

Determinism (contract §5): validate_game is a pure function; game_config_fingerprint =
SHA-256(canonical_json(game_spec_dump(game_spec))) — same content, same fingerprint, independent of key
order/whitespace; unset v2 sections are projected out so v1 fingerprints are unchanged.

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


# ---------------------------------------------------------------------------
# M2-C v2 sections (schema_version 2 only; docs/m2/M2C_CONTRACT.md Part 2)
#
# Paradigm independence: a room is a named context with exits; an object is a
# labeled inspectable with a role; a narrative surface is bounded static text.
# No genre/task vocabulary anywhere. All models extra="forbid" (defense D-1
# extended to v2: smuggled experiment-semantics keys are rejected by G1).
# ---------------------------------------------------------------------------

_SLUG = r"^[a-z0-9]+(-[a-z0-9]+)*$"

MAX_ROOMS = 8
MAX_EXITS_PER_ROOM = 4
MAX_OBJECTS_PER_ROOM = 6
MAX_ENDING_BANDS = 3

# Closed literal lists (checked semantically with G8 codes; see M2C_CONTRACT §3)
CREATIVE_FREEDOMS: tuple[str, ...] = (
    "theme", "room_labels", "object_labels", "narrative_text", "feedback_style",
)
CONTROLLED_INVARIANTS: tuple[str, ...] = (
    "trial_order", "conditions", "stimulus_content", "correct_answers", "timing",
)


class WorldObjectSpec(_Forbid):
    """Interactive object: flavour (engagement only) or encounter (pulls the next bundle trial)."""

    object_id: str = Field(pattern=_SLUG, max_length=24)
    label: str = Field(min_length=1, max_length=40)
    inspect_text: str = Field(min_length=1, max_length=400)
    role: Literal["flavour", "encounter"]


class RoomSpec(_Forbid):
    """A named context: bounded exits (target roomId -> label) and bounded objects."""

    title: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=400)
    exits: dict[str, str] = Field(default_factory=dict)
    objects: list[WorldObjectSpec] = Field(default_factory=list, max_length=MAX_OBJECTS_PER_ROOM)


class WorldSpec(_Forbid):
    """Scene graph: rooms + start room (bounded and fully reachable, G8_WORLD_STRUCTURE)."""

    rooms: dict[str, RoomSpec]
    start_room: str = Field(pattern=_SLUG, max_length=24)


class EndingBand(_Forbid):
    """Ending text band: accuracy >= min_accuracy maps to this band (bands strictly ascending)."""

    min_accuracy: float = Field(ge=0.0, le=1.0)
    text: str = Field(min_length=1, max_length=400)


class NarrativeSpec(_Forbid):
    """Static narrative surfaces (presentation only; briefings must cover every declared block, G8)."""

    intro: str = Field(default="", max_length=800)
    block_briefings: dict[str, str] = Field(default_factory=dict)
    ending_bands: list[EndingBand] = Field(default_factory=list, max_length=MAX_ENDING_BANDS)


class MechanicsSpec(_Forbid):
    """Registered interaction patterns (new layouts join the renderer's layout registry in M2-D)."""

    layout: Literal["canvas-center", "rows", "explore-and-encounter"] = "canvas-center"
    inspect_objects: bool = True
    trial_trigger: Literal["sequential", "explore-encounter"] = "sequential"


class MappingResponseBinding(_Forbid):
    """Key binding for the mapping surface (same semantics as v1 InputBinding)."""

    response_name: str
    keys: dict[str, str]


class MappingSpec(_Forbid):
    """Research–game mapping: how player actions become measurement trials.

    trial_trigger=explore-encounter: examining an encounter object pulls the NEXT
    unconsumed bundle trial in index order (monotonic cursor; no skip, no reorder —
    there is no field expressing trial selection). Encounter content renders the
    bundle's materialized trial.stimulus verbatim; there is no override surface.
    """

    trial_trigger: Literal["sequential", "explore-encounter"]
    encounter_objects: list[str] | None = None
    response_bindings: list[MappingResponseBinding] = Field(default_factory=list)
    creative_freedom: list[str] = Field(default_factory=list)
    controlled_invariants: list[str] = Field(default_factory=list)


class GameSpec(_Forbid):
    """Game presentation spec (the root model of the presentation layer)."""

    schema_version: Literal[1, 2] = 1
    game: GameMeta
    experiment_ref: ExperimentRef
    scene: SceneSpec = Field(default_factory=SceneSpec)
    input: InputSpec = Field(default_factory=InputSpec)
    feedback: FeedbackSpec = Field(default_factory=FeedbackSpec)
    flow: FlowSpec = Field(default_factory=FlowSpec)
    gamification: GamificationSpec = Field(default_factory=GamificationSpec)
    # M2-C v2 sections (schema_version 2 only; None = feature absent; explicit
    # null is treated as absent — see game_spec_dump() below)
    world: WorldSpec | None = None
    narrative: NarrativeSpec | None = None
    mechanics: MechanicsSpec | None = None
    mapping: MappingSpec | None = None


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


# v2 sections excluded from the dump when unset (v1 fingerprints stay stable —
# the same projection discipline as M2-B's spec_dump)
_V2_SECTIONS: tuple[str, ...] = ("world", "narrative", "mechanics", "mapping")


def game_spec_dump(game_spec: GameSpec) -> dict[str, object]:
    """Canonical projection of a GameSpec for fingerprinting.

    model_dump() with UNSET v2 sections removed. Absent and explicitly-null
    sections are equivalent (both mean "no v2 feature"); populated sections are
    kept and covered by game_config_fingerprint. A v1 GameSpec therefore dumps
    with zero v2 keys — byte-identical to the historical bare model_dump().
    """
    dump = game_spec.model_dump()
    for section in _V2_SECTIONS:
        if dump.get(section) is None:
            dump.pop(section, None)
    return dump


def game_config_fingerprint(game_spec: GameSpec) -> str:
    """GameSpec fingerprint: SHA-256(canonical_json(game_spec_dump())) — key-order/whitespace independent (§5)."""
    return sha256_hex(canonical_json(game_spec_dump(game_spec)))


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


def _bundle_blocks_and_responses(
    bundle: dict[str, object],
) -> tuple[list[str], dict[str, dict[str, object]], dict[str, object] | None]:
    """Extract declared block names, responses (name -> raw response dict) and the spec part."""
    spec_part = bundle.get("spec")
    if not isinstance(spec_part, dict):
        return [], {}, None
    blocks_raw = spec_part.get("blocks")
    block_names: list[str] = [
        b.get("name") for b in blocks_raw  # type: ignore[union-attr,misc]
        if isinstance(b, dict) and isinstance(b.get("name"), str)
    ] if isinstance(blocks_raw, list) else []
    responses: dict[str, dict[str, object]] = {}
    responses_raw = spec_part.get("responses")
    if isinstance(responses_raw, list):
        for raw in responses_raw:
            if isinstance(raw, dict) and isinstance(raw.get("name"), str):
                responses[raw["name"]] = raw
    return block_names, responses, spec_part


def _check_world_structure(
    game_spec: GameSpec, errors: list[GameValidationIssue]
) -> None:
    """G8_WORLD_STRUCTURE: room bounds, exit targets, duplicate object ids, orphan rooms."""
    assert game_spec.world is not None
    world = game_spec.world
    if len(world.rooms) > MAX_ROOMS:
        errors.append(
            _issue(
                "G8_WORLD_STRUCTURE",
                "world.rooms",
                f"world has {len(world.rooms)} rooms, limit {MAX_ROOMS}",
                f"reduce to at most {MAX_ROOMS} rooms",
            )
        )
    if world.start_room not in world.rooms:
        errors.append(
            _issue(
                "G8_WORLD_STRUCTURE",
                "world.start_room",
                f"start_room {world.start_room!r} is not a declared room",
                "use one of the declared room ids: " + ", ".join(sorted(world.rooms)),
            )
        )
    for room_id, room in world.rooms.items():
        if len(room.exits) > MAX_EXITS_PER_ROOM:
            errors.append(
                _issue(
                    "G8_WORLD_STRUCTURE",
                    f"world.rooms[{room_id!r}].exits",
                    f"room {room_id!r} has {len(room.exits)} exits, limit {MAX_EXITS_PER_ROOM}",
                    f"reduce to at most {MAX_EXITS_PER_ROOM} exits",
                )
            )
        for target in room.exits:
            if target not in world.rooms:
                errors.append(
                    _issue(
                        "G8_WORLD_STRUCTURE",
                        f"world.rooms[{room_id!r}].exits[{target!r}]",
                        f"exit target {target!r} is not a declared room",
                        "use one of the declared room ids: " + ", ".join(sorted(world.rooms)),
                    )
                )
    # duplicate object ids across the world
    seen_objects: dict[str, str] = {}
    for room_id, room in world.rooms.items():
        for obj in room.objects:
            if obj.object_id in seen_objects:
                errors.append(
                    _issue(
                        "G8_WORLD_STRUCTURE",
                        f"world.rooms[{room_id!r}].objects[{obj.object_id!r}]",
                        f"duplicate object_id {obj.object_id!r} (also in room {seen_objects[obj.object_id]!r})",
                        "object ids must be unique across the whole world",
                    )
                )
            else:
                seen_objects[obj.object_id] = room_id
    # orphan rooms: every room must be reachable from start_room (this also
    # guarantees every encounter object is reachable — a statically checkable
    # trial_order protection)
    if world.start_room in world.rooms:
        visited = {world.start_room}
        frontier = [world.start_room]
        while frontier:
            current = frontier.pop()
            for target in world.rooms[current].exits:
                if target in world.rooms and target not in visited:
                    visited.add(target)
                    frontier.append(target)
        for room_id in sorted(set(world.rooms) - visited):
            errors.append(
                _issue(
                    "G8_WORLD_STRUCTURE",
                    f"world.rooms[{room_id!r}]",
                    f"room {room_id!r} is unreachable from start_room {world.start_room!r}",
                    "connect the room to the start_room exit graph or remove it "
                    "(unreachable rooms can hide encounter objects whose trials could never fire)",
                )
            )


def _check_narrative(
    game_spec: GameSpec,
    block_names: list[str],
    errors: list[GameValidationIssue],
) -> None:
    """G8: briefing references + coverage; ending-band ordering (narrative structure)."""
    assert game_spec.narrative is not None
    narrative = game_spec.narrative
    for block_name in narrative.block_briefings:
        if block_name not in block_names:
            errors.append(
                _issue(
                    "G8_MAPPING_UNKNOWN_REFERENCE",
                    f"narrative.block_briefings[{block_name!r}]",
                    f"block {block_name!r} is not declared in the experiment spec",
                    "use one of the declared block names: " + ", ".join(block_names),
                )
            )
    missing = [b for b in block_names if b not in narrative.block_briefings]
    if missing:
        errors.append(
            _issue(
                "G8_MAPPING_BLOCK_COVERAGE",
                "narrative.block_briefings",
                f"blocks without a briefing: {missing} (every declared block needs one)",
                "add a briefing for every declared block so each block break carries its narrative",
            )
        )
    accuracies = [band.min_accuracy for band in narrative.ending_bands]
    if any(a >= b for a, b in zip(accuracies, accuracies[1:])):
        errors.append(
            _issue(
                "G8_WORLD_STRUCTURE",
                "narrative.ending_bands",
                f"ending band min_accuracy values must be strictly ascending, got {accuracies}",
                "sort the bands by min_accuracy and remove overlaps",
            )
        )


def _check_mapping_bindings(
    game_spec: GameSpec,
    responses: dict[str, dict[str, object]],
    errors: list[GameValidationIssue],
) -> None:
    """Mapping response bindings: v1 G3~G6 semantics extended to the mapping surface."""
    assert game_spec.mapping is not None
    mapping = game_spec.mapping
    # keys already bound in the v1 input surface: collision only when the same
    # key maps to a DIFFERENT response/option (identical bindings on both
    # surfaces are consistent and legal)
    input_keys: dict[str, tuple[str, str]] = {}
    for binding in game_spec.input.bindings:
        for key, value in binding.keys.items():
            input_keys[key] = (binding.response_name, value)

    bound_options: dict[str, set[str]] = {}
    seen_keys: dict[str, str] = {}
    for i, binding in enumerate(mapping.response_bindings):
        path = f"mapping.response_bindings[{i}]"
        response = responses.get(binding.response_name)
        if response is None:
            errors.append(
                _issue(
                    "G8_MAPPING_UNKNOWN_REFERENCE",
                    f"{path}.response_name",
                    f"response {binding.response_name!r} is not declared in the experiment spec",
                    "use a response name from the ExperimentBundle spec.responses",
                )
            )
            continue
        if response.get("kind") != "choice":
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
            if not (key in _NAMED_KEYS or (len(key) == 1 and "a" <= key <= "z")):
                errors.append(
                    _issue(
                        "INVALID_KEY",
                        f"{path}.keys.{key}",
                        f"invalid physical key {key!r}",
                        "use a single lowercase letter or one of: " + ", ".join(sorted(_NAMED_KEYS)),
                    )
                )
                continue
            if key in seen_keys:
                errors.append(
                    _issue(
                        "DUPLICATE_KEY",
                        f"{path}.keys.{key}",
                        f"key {key!r} already bound in {seen_keys[key]}",
                        "each physical key must map to exactly one option",
                    )
                )
                continue
            if key in input_keys and input_keys[key] != (binding.response_name, value):
                errors.append(
                    _issue(
                        "DUPLICATE_KEY",
                        f"{path}.keys.{key}",
                        f"key {key!r} is already bound to {input_keys[key]!r} in input.bindings "
                        "(input and mapping surfaces must agree on a key or use different keys)",
                        "make both surfaces bind the key identically, or use a different key",
                    )
                )
                continue
            seen_keys[key] = path
            if value not in option_set:
                errors.append(
                    _issue(
                        "OPTION_OUT_OF_DOMAIN",
                        f"{path}.keys.{key}",
                        f"value {value!r} is not an option of response {binding.response_name!r}",
                        f"use one of the declared options: {sorted(option_set)}",
                    )
                )
                continue
            bound_options.setdefault(binding.response_name, set()).add(value)

    # completeness: with an active mapping surface every choice response needs
    # a mapping binding (MISSING_BINDING, v1 semantics)
    for name, response in responses.items():
        if response.get("kind") != "choice":
            continue
        if name not in bound_options:
            errors.append(
                _issue(
                    "MISSING_BINDING",
                    "mapping.response_bindings",
                    f"choice response {name!r} has no mapping key binding",
                    f"add a MappingResponseBinding with response_name={name!r} covering its options",
                )
            )


def _check_v2_sections(
    game_spec: GameSpec, bundle: dict[str, object], errors: list[GameValidationIssue]
) -> None:
    """G8 family: version guard + world/narrative/mechanics/mapping cross-layer rules.

    Runs after G2~G6; a no-op for v1 GameSpecs (no v2 sections set) so v1
    validation results are identical. Declarative fields (controlled_invariants,
    creative_freedom) are checked for closed-list membership AND the underlying
    invariants are enforced structurally (see the invariant enforcement map in
    the module docstring) — declarations alone are never treated as evidence.
    """
    set_sections = [s for s in _V2_SECTIONS if s in game_spec.model_fields_set]
    if game_spec.schema_version == 1:
        for section in set_sections:
            errors.append(
                _issue(
                    "G8_VERSION_GUARD",
                    section,
                    f"section {section!r} is a schema_version 2 feature but this GameSpec "
                    "declares schema_version 1",
                    "set schema_version to 2 to use v2 sections, or remove the section",
                )
            )
        return
    if not any(getattr(game_spec, s) is not None for s in _V2_SECTIONS):
        return  # schema_version 2 with no v2 sections: legal, nothing to check

    block_names, responses, spec_part = _bundle_blocks_and_responses(bundle)

    if game_spec.world is not None:
        _check_world_structure(game_spec, errors)
    if game_spec.narrative is not None:
        _check_narrative(game_spec, block_names, errors)

    mapping = game_spec.mapping
    mechanics = game_spec.mechanics

    # effective trigger + layout consistency (G8_MAPPING_TRIGGER_CONFLICT)
    mapping_trigger = mapping.trial_trigger if mapping is not None else None
    mechanics_trigger = mechanics.trial_trigger if mechanics is not None else None
    if (
        mapping_trigger is not None
        and mechanics_trigger is not None
        and mapping_trigger != mechanics_trigger
    ):
        errors.append(
            _issue(
                "G8_MAPPING_TRIGGER_CONFLICT",
                "mapping.trial_trigger",
                f"mapping.trial_trigger={mapping_trigger!r} but mechanics.trial_trigger="
                f"{mechanics_trigger!r}",
                "the two trigger declarations must agree",
            )
        )
    effective_trigger = mapping_trigger or mechanics_trigger or "sequential"
    if (
        mechanics is not None
        and mechanics.layout == "explore-and-encounter"
        and effective_trigger != "explore-encounter"
    ):
        errors.append(
            _issue(
                "G8_MAPPING_TRIGGER_CONFLICT",
                "mechanics.layout",
                "mechanics.layout='explore-and-encounter' requires an explore-encounter trigger",
                "set trial_trigger='explore-encounter' in the mapping (and mechanics)",
            )
        )
    if effective_trigger == "explore-encounter":
        if mechanics is None or mechanics.layout != "explore-and-encounter":
            errors.append(
                _issue(
                    "G8_MAPPING_TRIGGER_CONFLICT",
                    "mechanics.layout",
                    "trigger 'explore-encounter' requires mechanics.layout='explore-and-encounter'",
                    "set mechanics.layout='explore-and-encounter' (the explore runtime renders it)",
                )
            )
        if mapping is None:
            errors.append(
                _issue(
                    "G8_MAPPING_TRIGGER_CONFLICT",
                    "mapping",
                    "trigger 'explore-encounter' requires a mapping section "
                    "(encounter objects and response bindings)",
                    "add a mapping section with trial_trigger='explore-encounter'",
                )
            )

    if mapping is not None:
        # closed-list declarations (declarations are necessary, NOT sufficient —
        # the structural enforcement is the schema itself + the rules below)
        unknown_invariants = [
            v for v in mapping.controlled_invariants if v not in CONTROLLED_INVARIANTS
        ]
        if unknown_invariants:
            errors.append(
                _issue(
                    "G8_MAPPING_INVARIANT_MISSING",
                    "mapping.controlled_invariants",
                    f"unknown invariant literals: {unknown_invariants} "
                    f"(closed list: {list(CONTROLLED_INVARIANTS)})",
                    "use exactly the five controlled invariant literals",
                )
            )
        missing_invariants = [
            v for v in CONTROLLED_INVARIANTS if v not in mapping.controlled_invariants
        ]
        if missing_invariants:
            errors.append(
                _issue(
                    "G8_MAPPING_INVARIANT_MISSING",
                    "mapping.controlled_invariants",
                    f"missing controlled invariants: {missing_invariants} (all five are mandatory; "
                    "omitting one does not release it — the fence is architectural)",
                    "declare all five: " + ", ".join(CONTROLLED_INVARIANTS),
                )
            )
        unknown_freedoms = [f for f in mapping.creative_freedom if f not in CREATIVE_FREEDOMS]
        if unknown_freedoms:
            errors.append(
                _issue(
                    "G8_MAPPING_FREEDOM_UNKNOWN",
                    "mapping.creative_freedom",
                    f"unknown creative freedom literals: {unknown_freedoms} "
                    f"(closed list: {list(CREATIVE_FREEDOMS)})",
                    "use only the declared freedom surfaces",
                )
            )
        if mapping.response_bindings:
            _check_mapping_bindings(game_spec, responses, errors)
        elif effective_trigger == "explore-encounter":
            # completeness is enforced inside _check_mapping_bindings; an empty
            # list with an active trigger means every choice response is unbound
            for name, response in responses.items():
                if response.get("kind") == "choice":
                    errors.append(
                        _issue(
                            "MISSING_BINDING",
                            "mapping.response_bindings",
                            f"choice response {name!r} has no mapping key binding "
                            "(required for the explore-encounter trigger)",
                            f"add a MappingResponseBinding with response_name={name!r}",
                        )
                    )

    # encounter configuration (only meaningful for the explore trigger)
    if effective_trigger == "explore-encounter" and mapping is not None:
        assert game_spec.world is not None or mapping.encounter_objects, (
            "encounter objects require a world (checked below via unknown references)"
        )
        world_objects: dict[str, WorldObjectSpec] = {}
        if game_spec.world is not None:
            for room in game_spec.world.rooms.values():
                for obj in room.objects:
                    world_objects[obj.object_id] = obj
        encounters = mapping.encounter_objects or []
        seen: set[str] = set()
        for object_id in encounters:
            if object_id in seen:
                errors.append(
                    _issue(
                        "G8_MAPPING_UNKNOWN_REFERENCE",
                        f"mapping.encounter_objects[{object_id!r}]",
                        f"duplicate encounter object {object_id!r}",
                        "list each encounter object exactly once",
                    )
                )
                continue
            seen.add(object_id)
            obj = world_objects.get(object_id)
            if obj is None:
                errors.append(
                    _issue(
                        "G8_MAPPING_UNKNOWN_REFERENCE",
                        f"mapping.encounter_objects[{object_id!r}]",
                        f"encounter object {object_id!r} is not declared in world",
                        "use object ids declared in world.rooms[*].objects",
                    )
                )
                continue
            if obj.role != "encounter":
                errors.append(
                    _issue(
                        "G8_MAPPING_UNKNOWN_REFERENCE",
                        f"mapping.encounter_objects[{object_id!r}]",
                        f"object {object_id!r} has role {obj.role!r}; encounter objects must "
                        "declare role='encounter'",
                        "set the object's role to 'encounter' or remove it from the list",
                    )
                )
        # every world object with role 'encounter' must be listed (an unlisted
        # encounter object would be dead or, worse, runtime-ambiguous)
        listed = set(encounters)
        for object_id, obj in world_objects.items():
            if obj.role == "encounter" and object_id not in listed:
                errors.append(
                    _issue(
                        "G8_MAPPING_UNKNOWN_REFERENCE",
                        "mapping.encounter_objects",
                        f"object {object_id!r} declares role='encounter' but is not listed in "
                        "mapping.encounter_objects",
                        "list every encounter object, or change its role to 'flavour'",
                    )
                )
        # trial-order protection: enough encounters to consume every trial
        trials = bundle.get("trials")
        total_trials = len(trials) if isinstance(trials, list) else 0
        if len(encounters) < total_trials:
            errors.append(
                _issue(
                    "G8_MAPPING_ENCOUNTER_SHORTFALL",
                    "mapping.encounter_objects",
                    f"{len(encounters)} encounter objects for {total_trials} trials — the session "
                    "would exhaust encounters before trials",
                    f"declare at least {total_trials} encounter objects "
                    "(extra encounters after the last trial are fine)",
                )
            )
        # G8_STIMULUS_SEMANTICS (decision C-2a): explore trigger requires a
        # v2-shaped bundle (materialized stimuli); v1-shaped bundles are rejected
        if spec_part is not None and not spec_part.get("stimulus_spec"):
            errors.append(
                _issue(
                    "G8_STIMULUS_SEMANTICS",
                    "mechanics.trial_trigger",
                    "explore-encounter trigger requires a bundle with materialized stimuli "
                    "(ExperimentSpec schema_version 2 with stimulus_spec); this bundle is v1-shaped",
                    "re-export the bundle from a schema_version 2 ExperimentSpec with "
                    "stimulus_spec, or use trial_trigger='sequential'",
                )
            )


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
    _check_v2_sections(parsed, bundle, errors)

    return GameValidationResult(
        game_spec=parsed,
        valid=not errors,
        errors=errors,
        warnings=warnings,
        game_config_fingerprint=fingerprint,
    )
