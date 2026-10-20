"""ExperimentSpec Pydantic schema (contract §2 field table, field-for-field).

Validation boundary (contract §2.2, frozen):
- this module only handles structure and reference existence (Field constraints + V1~V9); seed-independent and constraint-semantics-independent;
- constraint semantics (C1/C2/C3, all UNSAT forms) belong to src/experiment/validation.py;
- putting semantic validation into this module is forbidden, as is putting reference existence into the validation layer.

Where V1~V9 live: so that every structural error carries a usable path (Pydantic loc),
V1/V3/V4/V5/V8/V9 are implemented as ExperimentSpec-level field_validators (relying on already-validated
preceding fields in info.data), V2 at the Factor level, V6/V7 at the Constraints level, and
options/scale/kind consistency at the ResponseVar level — semantically equivalent to V1~V9 of
contract §2.1 one by one; only the implementation vehicle is field_validator rather than a single
model_validator (what the contract freezes is the validation semantics; internal details are free).
"""

from __future__ import annotations

from itertools import product
from typing import Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator

MAX_COMBINATIONS = 100_000  # V9 / CR-7 guard
MAX_BLOCK_TRIAL_COUNT = 100_000  # CR-7 guard
MAX_BLOCKS = 32  # CR-7 guard
MAX_SEED = 2**63 - 1  # CR-7: non-negative int64


class Level(BaseModel):
    """Factor level (name unique within the factor — V2)."""

    name: str = Field(min_length=1)
    weight: float = Field(default=1.0, gt=0)  # sampling weight (intent declaration; C2 warns when overridden)


class Factor(BaseModel):
    """Experiment factor (name unique across the spec — V1; levels are ordered — one source of expansion determinism)."""

    name: str = Field(min_length=1)
    levels: list[Level] = Field(min_length=1)

    @field_validator("levels")
    @classmethod
    def _levels_unique(cls, value: list[Level]) -> list[Level]:
        # V2: level names unique within each factor
        names = [level.name for level in value]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"duplicate level names within the factor: {duplicates}")
        return value


class RatioRule(BaseModel):
    """Per-factor level ratio rule (factor references a declared factor name — V5; the sum ≈1.0 is the validation layer's RATIO_SUM)."""

    factor: str = Field(min_length=1)
    ratios: dict[str, float]  # level name -> ratio; values ≥ 0.0 (0.0 allowed = explicit exclusion)

    @field_validator("ratios")
    @classmethod
    def _ratios_non_negative(cls, value: dict[str, float]) -> dict[str, float]:
        for name, ratio in value.items():
            if ratio < 0.0:
                raise ValueError(f"ratio values must be ≥ 0.0 (level {name!r} is {ratio})")
        return value


class Constraints(BaseModel):
    """Constraint declarations (balance and ratios are mutually exclusive — C1 belongs to the validation layer)."""

    balance: bool = False
    ratios: list[RatioRule] = Field(default_factory=list)
    mutually_exclusive: list[list[str]] = Field(default_factory=list)
    max_repeat: int | None = None  # reserved Phase A field; non-None → UNSUPPORTED_CONSTRAINT in the validation layer

    @field_validator("ratios")
    @classmethod
    def _ratios_at_most_one_per_factor(cls, value: list[RatioRule]) -> list[RatioRule]:
        # V6: at most one rule per factor
        names = [rule.factor for rule in value]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"multiple ratios rules declared for the same factor: {duplicates}")
        return value

    @field_validator("mutually_exclusive")
    @classmethod
    def _mutex_pairs_length(cls, value: list[list[str]]) -> list[list[str]]:
        # V7: exactly 2 level names per entry
        for i, pair in enumerate(value):
            if len(pair) != 2:
                raise ValueError(f"mutually_exclusive[{i}] must contain exactly 2 level names, got {len(pair)}")
        return value


class ResponseVar(BaseModel):
    """Response variable (name unique across the spec — V4; options/scale consistency with kind)."""

    name: str = Field(min_length=1)
    kind: Literal["choice", "text", "rating"]
    options: list[str] = Field(default_factory=list)
    scale: tuple[int, int] | None = None
    correct_from: str | None = None  # when not None, must be a declared factor name (validation layer CORRECT_FROM_UNKNOWN)

    @model_validator(mode="after")
    def _kind_fields_consistent(self) -> ResponseVar:
        """Consistency of options / scale with kind (contract §2.1: model_validator check)."""
        if self.kind == "choice":
            if not self.options:
                raise ValueError("options must be non-empty when kind='choice'")
        elif self.options:
            raise ValueError(f"options must be an empty list when kind={self.kind!r}")
        if self.kind == "rating":
            if self.scale is None:
                raise ValueError("scale must be (min, max) with min < max when kind='rating'")
            if self.scale[0] >= self.scale[1]:
                raise ValueError(f"rating scale must satisfy min < max, got {self.scale}")
        elif self.scale is not None:
            raise ValueError(f"scale must be None when kind={self.kind!r}")
        return self


class BlockSpec(BaseModel):
    """Experiment block (name unique across the spec — V3; the block-derivation key relies on uniqueness)."""

    name: str = Field(min_length=1)
    trial_count: int = Field(gt=0, le=MAX_BLOCK_TRIAL_COUNT)
    factor_filter: dict[str, list[str]] = Field(default_factory=dict)
    shuffle_within: bool = True


class TimingSpec(BaseModel):
    """Timing parameters (declared at spec level, materialized per trial)."""

    fixation_ms: int = Field(default=500, ge=0)
    stimulus_ms: int | None = Field(default=None, ge=0)  # None = until response
    isi_ms: int = Field(default=1000, ge=0)


class ExperimentSpec(BaseModel):
    """Experiment spec (Phase A: paradigm must be null — non-null goes to the validation layer's UNKNOWN_PARADIGM)."""

    schema_version: Literal[1] = 1
    name: str = Field(min_length=1)
    version: str = "0.1.0"
    seed: int = Field(ge=0, le=MAX_SEED)
    paradigm: str | None = None
    paradigm_params: dict[str, object] = Field(default_factory=dict)
    factors: list[Factor] = Field(min_length=1)
    blocks: list[BlockSpec] = Field(min_length=1, max_length=MAX_BLOCKS)
    constraints: Constraints = Constraints()
    responses: list[ResponseVar] = Field(min_length=1)
    timing: TimingSpec = TimingSpec()

    @field_validator("factors")
    @classmethod
    def _factors_unique_and_bounded(cls, value: list[Factor]) -> list[Factor]:
        # V1: factor names unique
        names = [factor.name for factor in value]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"duplicate factor names: {duplicates}")
        # V9: expanded combination count (∏ len(levels)) ≤ 100_000 (CR-7)
        combinations = 1
        for factor in value:
            combinations *= len(factor.levels)
            if combinations > MAX_COMBINATIONS:
                raise ValueError(
                    f"expanded combination count {combinations} exceeds the limit {MAX_COMBINATIONS} (CR-7 guard)"
                )
        return value

    @field_validator("paradigm_params")
    @classmethod
    def _paradigm_params_empty_when_null(
        cls, value: dict[str, object], info: ValidationInfo
    ) -> dict[str, object]:
        # V8: when paradigm is null, paradigm_params must be an empty dict
        if info.data.get("paradigm") is None and value:
            raise ValueError("paradigm_params must be empty when paradigm is null (Phase A has no plugin system)")
        return value

    @field_validator("blocks")
    @classmethod
    def _blocks_unique_and_filter_refs(
        cls, value: list[BlockSpec], info: ValidationInfo
    ) -> list[BlockSpec]:
        # V3: block names unique
        names = [block.name for block in value]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"duplicate block names: {duplicates}")
        # V5 (factor_filter part): keys reference factor names, values reference level names of that factor
        factors = info.data.get("factors")
        if isinstance(factors, list) and all(isinstance(f, Factor) for f in factors):
            known: dict[str, set[str]] = {f.name: {lvl.name for lvl in f.levels} for f in factors}
            for i, block in enumerate(value):
                for factor_name, level_names in block.factor_filter.items():
                    if factor_name not in known:
                        raise ValueError(
                            f"blocks[{i}].factor_filter references the undeclared factor {factor_name!r}"
                        )
                    unknown_levels = [n for n in level_names if n not in known[factor_name]]
                    if unknown_levels:
                        raise ValueError(
                            f"blocks[{i}].factor_filter[{factor_name!r}] references undeclared levels {unknown_levels}"
                        )
        return value

    @field_validator("responses")
    @classmethod
    def _responses_unique(cls, value: list[ResponseVar]) -> list[ResponseVar]:
        # V4: response names unique
        names = [response.name for response in value]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"duplicate response names: {duplicates}")
        return value

    @field_validator("constraints")
    @classmethod
    def _constraint_refs_exist(
        cls, value: Constraints, info: ValidationInfo
    ) -> Constraints:
        # V5 (ratios / mutually_exclusive part): referenced factor names and level names must exist
        factors = info.data.get("factors")
        if isinstance(factors, list) and all(isinstance(f, Factor) for f in factors):
            known: dict[str, set[str]] = {f.name: {lvl.name for lvl in f.levels} for f in factors}
            all_levels: set[str] = set().union(*known.values()) if known else set()
            for i, rule in enumerate(value.ratios):
                if rule.factor not in known:
                    raise ValueError(
                        f"constraints.ratios[{i}].factor references the undeclared factor {rule.factor!r}"
                    )
                unknown_keys = [k for k in rule.ratios if k not in known[rule.factor]]
                if unknown_keys:
                    raise ValueError(
                        f"constraints.ratios[{i}].ratios references undeclared levels {unknown_keys} of factor {rule.factor!r}"
                    )
            for i, pair in enumerate(value.mutually_exclusive):
                for level_name in pair:
                    if level_name not in all_levels:
                        raise ValueError(
                            f"constraints.mutually_exclusive[{i}] references the undeclared level {level_name!r}"
                        )
        return value

    def combination_count(self) -> int:
        """Size of the full combination space (∏ len(levels))."""
        count = 1
        for factor in self.factors:
            count *= len(factor.levels)
        return count

    def factor_names(self) -> list[str]:
        """Factor names in declaration order."""
        return [factor.name for factor in self.factors]

    def level_names(self, factor_name: str) -> list[str]:
        """Level names of a factor in declaration order."""
        for factor in self.factors:
            if factor.name == factor_name:
                return [level.name for level in factor.levels]
        return []

    def expanded_combinations(self) -> list[tuple[str, ...]]:
        """Cartesian product in factors declaration order (levels in levels declaration order) — algorithm step 1."""
        return [
            tuple(combo)
            for combo in product(*(self.level_names(f.name) for f in self.factors))
        ]


class Trial(BaseModel):
    """A single trial (Phase A: stimulus/derived are always empty dicts)."""

    index: int  # global order (0-based, continuous across blocks)
    block: str
    factors: dict[str, str]  # factor name -> level name
    stimulus: dict[str, object] = Field(default_factory=dict)
    derived: dict[str, object] = Field(default_factory=dict)
    timing: TimingSpec


class GeneratedExperiment(BaseModel):
    """Return value of generate_trials (§2.4)."""

    config_fingerprint: str  # full 64 hex (CR-2)
    trials_fingerprint: str  # full 64 hex
    engine_spec_version: str
    plugin_used: str | None  # always None in Phase A
    trials: list[Trial]
