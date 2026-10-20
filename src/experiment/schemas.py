"""ExperimentSpec Pydantic schema（契约 §2 字段表，逐字段一致）。

校验分界（契约 §2.2，冻结）：
- 本模块只负责结构与引用存在性（Field 约束 + V1~V9），与 seed 无关、与约束语义无关；
- 约束语义（C1/C2/C3、UNSAT 各形态）归 src/experiment/validation.py；
- 禁止把语义校验放进本模块，禁止把引用存在性放进验证层。

V1~V9 落位说明：为使每条结构错误携带可用 path（Pydantic loc），
V1/V3/V4/V5/V8/V9 以 ExperimentSpec 级 field_validator 实现（依赖 info.data
中已校验的前序字段），V2 在 Factor 级、V6/V7 在 Constraints 级、
options/scale/kind 一致性在 ResponseVar 级实现——语义与契约 §2.1 的
V1~V9 逐条等价，仅实现载体为 field_validator 而非单一 model_validator
（契约冻结的是校验语义，内部实现细节可自定）。
"""

from __future__ import annotations

from itertools import product
from typing import Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator

MAX_COMBINATIONS = 100_000  # V9 / CR-7 护栏
MAX_BLOCK_TRIAL_COUNT = 100_000  # CR-7 护栏
MAX_BLOCKS = 32  # CR-7 护栏
MAX_SEED = 2**63 - 1  # CR-7：非负 int64


class Level(BaseModel):
    """因素水平（因素内名唯一——V2）。"""

    name: str = Field(min_length=1)
    weight: float = Field(default=1.0, gt=0)  # 采样权重（意图声明；被覆盖时 C2 警告）


class Factor(BaseModel):
    """实验因素（名全 spec 唯一——V1；levels 有序——组合展开确定性来源之一）。"""

    name: str = Field(min_length=1)
    levels: list[Level] = Field(min_length=1)

    @field_validator("levels")
    @classmethod
    def _levels_unique(cls, value: list[Level]) -> list[Level]:
        # V2：每 factor 内 levels 名唯一
        names = [level.name for level in value]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"水平名在因素内重复: {duplicates}")
        return value


class RatioRule(BaseModel):
    """因素内水平比例规则（factor 引用已声明因素名——V5；和 ≈1.0 归验证层 RATIO_SUM）。"""

    factor: str = Field(min_length=1)
    ratios: dict[str, float]  # level name -> 比例；值 ≥ 0.0（允许 0.0 = 显式排除）

    @field_validator("ratios")
    @classmethod
    def _ratios_non_negative(cls, value: dict[str, float]) -> dict[str, float]:
        for name, ratio in value.items():
            if ratio < 0.0:
                raise ValueError(f"比例值必须 ≥ 0.0（水平 {name!r} 为 {ratio}）")
        return value


class Constraints(BaseModel):
    """约束声明（balance 与 ratios 互斥——C1 归验证层）。"""

    balance: bool = False
    ratios: list[RatioRule] = Field(default_factory=list)
    mutually_exclusive: list[list[str]] = Field(default_factory=list)
    max_repeat: int | None = None  # Phase A 保留字段；非 None → 验证层 UNSUPPORTED_CONSTRAINT

    @field_validator("ratios")
    @classmethod
    def _ratios_at_most_one_per_factor(cls, value: list[RatioRule]) -> list[RatioRule]:
        # V6：每因素至多一条
        names = [rule.factor for rule in value]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"同一因素声明了多条 ratios 规则: {duplicates}")
        return value

    @field_validator("mutually_exclusive")
    @classmethod
    def _mutex_pairs_length(cls, value: list[list[str]]) -> list[list[str]]:
        # V7：每项恰 2 个水平名
        for i, pair in enumerate(value):
            if len(pair) != 2:
                raise ValueError(f"mutually_exclusive[{i}] 必须恰含 2 个水平名，实际 {len(pair)} 个")
        return value


class ResponseVar(BaseModel):
    """响应变量（名全 spec 唯一——V4；options/scale 与 kind 一致性）。"""

    name: str = Field(min_length=1)
    kind: Literal["choice", "text", "rating"]
    options: list[str] = Field(default_factory=list)
    scale: tuple[int, int] | None = None
    correct_from: str | None = None  # 非 None 时必须为已声明因素名（验证层 CORRECT_FROM_UNKNOWN）

    @model_validator(mode="after")
    def _kind_fields_consistent(self) -> ResponseVar:
        """options / scale 与 kind 的一致性（契约 §2.1：model_validator 校验）。"""
        if self.kind == "choice":
            if not self.options:
                raise ValueError("kind='choice' 时 options 必须非空")
        elif self.options:
            raise ValueError(f"kind={self.kind!r} 时 options 必须为空列表")
        if self.kind == "rating":
            if self.scale is None:
                raise ValueError("kind='rating' 时 scale 必须为 (min, max) 且 min < max")
            if self.scale[0] >= self.scale[1]:
                raise ValueError(f"rating scale 必须 min < max，实际 {self.scale}")
        elif self.scale is not None:
            raise ValueError(f"kind={self.kind!r} 时 scale 必须为 None")
        return self


class BlockSpec(BaseModel):
    """实验 block（名全 spec 唯一——V3，子流派生键依赖唯一）。"""

    name: str = Field(min_length=1)
    trial_count: int = Field(gt=0, le=MAX_BLOCK_TRIAL_COUNT)
    factor_filter: dict[str, list[str]] = Field(default_factory=dict)
    shuffle_within: bool = True


class TimingSpec(BaseModel):
    """计时参数（spec 级声明，逐试次物化）。"""

    fixation_ms: int = Field(default=500, ge=0)
    stimulus_ms: int | None = Field(default=None, ge=0)  # None = 直至响应
    isi_ms: int = Field(default=1000, ge=0)


class ExperimentSpec(BaseModel):
    """实验规格（Phase A：paradigm 必须为 null——非 null 归验证层 UNKNOWN_PARADIGM）。"""

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
        # V1：factors 名唯一
        names = [factor.name for factor in value]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"因素名重复: {duplicates}")
        # V9：展开组合数（∏ len(levels)）≤ 100_000（CR-7）
        combinations = 1
        for factor in value:
            combinations *= len(factor.levels)
            if combinations > MAX_COMBINATIONS:
                raise ValueError(
                    f"展开组合数 {combinations} 超过上限 {MAX_COMBINATIONS}（CR-7 护栏）"
                )
        return value

    @field_validator("paradigm_params")
    @classmethod
    def _paradigm_params_empty_when_null(
        cls, value: dict[str, object], info: ValidationInfo
    ) -> dict[str, object]:
        # V8：paradigm 为 null 时 paradigm_params 必须为空 dict
        if info.data.get("paradigm") is None and value:
            raise ValueError("paradigm 为 null 时 paradigm_params 必须为空（Phase A 无插件系统）")
        return value

    @field_validator("blocks")
    @classmethod
    def _blocks_unique_and_filter_refs(
        cls, value: list[BlockSpec], info: ValidationInfo
    ) -> list[BlockSpec]:
        # V3：blocks 名唯一
        names = [block.name for block in value]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"block 名重复: {duplicates}")
        # V5（factor_filter 部分）：键引用因素名、值引用该因素的水平名
        factors = info.data.get("factors")
        if isinstance(factors, list) and all(isinstance(f, Factor) for f in factors):
            known: dict[str, set[str]] = {f.name: {lvl.name for lvl in f.levels} for f in factors}
            for i, block in enumerate(value):
                for factor_name, level_names in block.factor_filter.items():
                    if factor_name not in known:
                        raise ValueError(
                            f"blocks[{i}].factor_filter 引用未声明因素 {factor_name!r}"
                        )
                    unknown_levels = [n for n in level_names if n not in known[factor_name]]
                    if unknown_levels:
                        raise ValueError(
                            f"blocks[{i}].factor_filter[{factor_name!r}] 引用未声明水平 {unknown_levels}"
                        )
        return value

    @field_validator("responses")
    @classmethod
    def _responses_unique(cls, value: list[ResponseVar]) -> list[ResponseVar]:
        # V4：responses 名唯一
        names = [response.name for response in value]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"响应变量名重复: {duplicates}")
        return value

    @field_validator("constraints")
    @classmethod
    def _constraint_refs_exist(
        cls, value: Constraints, info: ValidationInfo
    ) -> Constraints:
        # V5（ratios / mutually_exclusive 部分）：引用的因素名与水平名必须存在
        factors = info.data.get("factors")
        if isinstance(factors, list) and all(isinstance(f, Factor) for f in factors):
            known: dict[str, set[str]] = {f.name: {lvl.name for lvl in f.levels} for f in factors}
            all_levels: set[str] = set().union(*known.values()) if known else set()
            for i, rule in enumerate(value.ratios):
                if rule.factor not in known:
                    raise ValueError(
                        f"constraints.ratios[{i}].factor 引用未声明因素 {rule.factor!r}"
                    )
                unknown_keys = [k for k in rule.ratios if k not in known[rule.factor]]
                if unknown_keys:
                    raise ValueError(
                        f"constraints.ratios[{i}].ratios 引用因素 {rule.factor!r} 的未声明水平 {unknown_keys}"
                    )
            for i, pair in enumerate(value.mutually_exclusive):
                for level_name in pair:
                    if level_name not in all_levels:
                        raise ValueError(
                            f"constraints.mutually_exclusive[{i}] 引用未声明水平 {level_name!r}"
                        )
        return value

    def combination_count(self) -> int:
        """全组合空间大小（∏ len(levels)）。"""
        count = 1
        for factor in self.factors:
            count *= len(factor.levels)
        return count

    def factor_names(self) -> list[str]:
        """因素声明序名单。"""
        return [factor.name for factor in self.factors]

    def level_names(self, factor_name: str) -> list[str]:
        """指定因素的水平声明序名单。"""
        for factor in self.factors:
            if factor.name == factor_name:
                return [level.name for level in factor.levels]
        return []

    def expanded_combinations(self) -> list[tuple[str, ...]]:
        """按 factors 声明序的笛卡尔积（水平按 levels 声明序）——算法第 1 步。"""
        return [
            tuple(combo)
            for combo in product(*(self.level_names(f.name) for f in self.factors))
        ]


class Trial(BaseModel):
    """单试次（Phase A：stimulus/derived 恒为空 dict）。"""

    index: int  # 全局序（0 起，跨 block 连续）
    block: str
    factors: dict[str, str]  # 因素名 -> 水平名
    stimulus: dict[str, object] = Field(default_factory=dict)
    derived: dict[str, object] = Field(default_factory=dict)
    timing: TimingSpec


class GeneratedExperiment(BaseModel):
    """generate_trials 的返回（§2.4）。"""

    config_fingerprint: str  # 完整 64 hex（CR-2）
    trials_fingerprint: str  # 完整 64 hex
    engine_spec_version: str
    plugin_used: str | None  # Phase A 恒为 None
    trials: list[Trial]
