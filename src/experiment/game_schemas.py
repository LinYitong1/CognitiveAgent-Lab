"""GameSpec schema 与 validate_game 校验（Phase B 契约 B0 版，冻结）。

职责铁律（契约 §1）：实验逻辑归 ExperimentSpec/Bundle，游戏表现归 GameSpec。
GameSpec 只有"引用"（ExperimentRef 三重指纹），没有"重算"——不存在任何
条件分配/试次/正确性判定字段；全部模型 extra="forbid"（防线 D-1）。

校验规则 G1~G7（契约 §4）：
- G1 schema 层：Pydantic 校验（含拒收未声明字段）→ SCHEMA_INVALID；
- G2 跨层引用：experiment_ref 六项与 Bundle 对齐 + 重算整包指纹 → REF_MISMATCH；
- G3/G4/G5/G6 键位绑定跨层规则 → UNKNOWN_RESPONSE / INVALID_BINDING_TARGET /
  OPTION_OUT_OF_DOMAIN / DUPLICATE_KEY / MISSING_BINDING / INVALID_KEY；
- G7 体积护栏：序列化 > 256KB → GAME_SPEC_TOO_LARGE。

确定性（契约 §5）：validate_game 为纯函数；game_config_fingerprint =
SHA-256(canonical_json(game_spec))——同内容同指纹，与键序/空白无关。

MVP 标记（契约 §9）：状态机与交互类型为 MVP 支持集，非永久架构限制。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.experiment.canonical import canonical_json, sha256_hex

MAX_GAME_SPEC_BYTES = 256 * 1024  # 序列化体积护栏（G7，镜像 Phase A config 护栏）

_HEX64 = r"^[0-9a-f]{64}$"
_NAMED_KEYS = frozenset({"space", "enter", "left", "right", "up", "down"})


class _Forbid(BaseModel):
    """防线 D-1：拒收一切未声明字段。"""

    model_config = ConfigDict(extra="forbid")


class GameMeta(_Forbid):
    """游戏自标识（纯呈现层元信息）。"""

    name: str = Field(min_length=1, max_length=100)
    version: str = "0.1.0"


class ExperimentRef(_Forbid):
    """对 ExperimentBundle 的引用（三重指纹对齐；字段均为只读指针复制，非实验逻辑）。"""

    name: str
    version: str
    seed: int
    config_fingerprint: str = Field(pattern=_HEX64)
    trials_fingerprint: str = Field(pattern=_HEX64)
    bundle_sha256: str = Field(pattern=_HEX64)


class SceneSpec(_Forbid):
    """场景呈现（纯表现；assets 仅限界面装饰，禁止参与试次内容——渲染器契约落实）。"""

    title: str = Field(default="", max_length=200)
    instructions: str = Field(default="", max_length=2000)
    layout: Literal["canvas-center", "rows"] = "canvas-center"
    theme: Literal["neutral-light", "dark"] = "neutral-light"
    assets: dict[str, str] = Field(default_factory=dict)


class InputBinding(_Forbid):
    """键位绑定：物理键 → choice 选项值（绑定到 ExperimentSpec 已声明的响应变量）。"""

    response_name: str
    keys: dict[str, str]


class InputSpec(_Forbid):
    """输入模态与绑定（B0 仅 keyboard；pointer/touch 为保留扩展位，走契约修订）。"""

    modalities: list[Literal["keyboard"]] = Field(default_factory=lambda: ["keyboard"])
    bindings: list[InputBinding] = Field(default_factory=list)


class FeedbackSpec(_Forbid):
    """反馈样式（正确性只读 Bundle 判定，本层只选呈现形式）。"""

    on_response: Literal["none", "correctness-flash", "outcome-text"] = "none"
    duration_ms: int = Field(default=200, ge=0, le=5000)


class FlowSpec(_Forbid):
    """交互流程开关（MVP 流程：ready/块间歇/结束页，契约 §9.1）。"""

    ready_screen: bool = True
    block_breaks: bool = True
    end_screen: Literal["none", "summary"] = "summary"


class GamificationSpec(_Forbid):
    """游戏化包装（全部可选；得分由渲染器按 Bundle 正确性累计）。"""

    score: bool = False
    progress_bar: bool = True
    streak_bonus: bool = False


class GameSpec(_Forbid):
    """游戏呈现规格（表现层根模型）。"""

    schema_version: Literal[1] = 1
    game: GameMeta
    experiment_ref: ExperimentRef
    scene: SceneSpec = Field(default_factory=SceneSpec)
    input: InputSpec = Field(default_factory=InputSpec)
    feedback: FeedbackSpec = Field(default_factory=FeedbackSpec)
    flow: FlowSpec = Field(default_factory=FlowSpec)
    gamification: GamificationSpec = Field(default_factory=GamificationSpec)


class GameValidationIssue(BaseModel):
    """验证问题（errors 与 warnings 共用，结构对齐 Phase A ValidationIssue）。"""

    error_code: str
    path: str
    message: str
    suggestion: str


class GameValidationResult(BaseModel):
    """validate_game 的返回（契约 §4 输出结构）。"""

    game_spec: GameSpec | None  # G1 失败时为 None
    valid: bool
    errors: list[GameValidationIssue]
    warnings: list[GameValidationIssue]
    game_config_fingerprint: str | None  # G1 失败时为 None


def game_config_fingerprint(game_spec: GameSpec) -> str:
    """GameSpec 指纹：SHA-256(canonical_json(model_dump()))——键序/空白无关（§5）。"""
    return sha256_hex(canonical_json(game_spec.model_dump()))


def _issue(error_code: str, path: str, message: str, suggestion: str) -> GameValidationIssue:
    return GameValidationIssue(
        error_code=error_code, path=path, message=message, suggestion=suggestion
    )


def _pydantic_issues(exc: ValidationError) -> list[GameValidationIssue]:
    """Pydantic ValidationError → 结构化 SCHEMA_INVALID 问题列表。"""
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
    """G7 体积护栏：序列化字节 > 256KB → GAME_SPEC_TOO_LARGE。返回是否继续。"""
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
    """从 Bundle 提取 G2 六项期望值；结构不完整时返回 None。"""
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
    """G2：Bundle 完整性重算 + 六项引用逐一比对（首个失配即报，契约 §4）。"""
    # 整包完整性重算（契约 §9.2：可复现验证，检出 Bundle 被篡改）
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
    # 六项逐一比对（报首个失配）
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
    """G3~G6 键位绑定跨层规则；同时返回 warnings（PARTIAL_OPTION_COVERAGE，§9.4）。"""
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
    seen_keys: dict[str, int] = {}  # 物理键 → 首次出现的 binding 下标
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
            # G6 键格式
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
            # G5 重复键
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
            # G5 选项越域
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

    # G5 缺失绑定：keyboard 模态下每个 choice 响应至少一个绑定
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

    # 警告：部分选项覆盖（合法但可能有选项不可达，§9.4）
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
    """校验 GameSpec（G1~G7，纯函数）。bundle 为已加载的 ExperimentBundle dict。"""
    errors: list[GameValidationIssue] = []

    # G1 前置：必须是 dict
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

    # G7 体积护栏（在原始输入上度量）
    if not _check_size_guard(game_spec, errors):
        return GameValidationResult(
            game_spec=None, valid=False, errors=errors, warnings=[], game_config_fingerprint=None
        )

    # G1 schema 层
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

    # G2~G6 需 Bundle；bundle 非 dict → REF_MISMATCH（引用无法对齐）
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
