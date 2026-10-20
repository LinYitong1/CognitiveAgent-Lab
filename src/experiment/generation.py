"""确定性生成引擎（契约 §3 九步算法，冻结）。

试次生成 = 纯函数：无 IO、无时间依赖、无隐藏状态、不触全局 random。
随机消费唯一处：block 内 shuffle（每 block 恰一次 rng.shuffle 调用）。
seed 派生（CR-1）：SHA-256(f"{seed}:block:{block.name}") 前 8 字节 big-endian int64。

确定性保证（§3.4）：无 set 构造/迭代；dict 依赖 ≥3.7 插入序；
canonical JSON sort_keys 消除键序差异；无 datetime.now / uuid / 全局状态。
"""

from __future__ import annotations

import hashlib
import math
import random

from src.experiment.canonical import canonical_json, sha256_hex
from src.experiment.schemas import (
    BlockSpec,
    ExperimentSpec,
    GeneratedExperiment,
    Trial,
)

ENGINE_SPEC_VERSION: str = "1.0"  # 算法任何变更（分配/派生/洗牌/序列化）必须递增

_FLOAT_EPSILON = 1e-9  # 整数判定容差（浮点表示噪声防护，非分配语义容差）


def derive_block_seed(seed: int, block_name: str) -> int:
    """每 block 独立子流种子（契约 §3.1 冻结算法：显式 SHA-256 派生）。"""
    digest = hashlib.sha256(f"{seed}:block:{block_name}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")  # 无符号 int64


def effective_weights(spec: ExperimentSpec) -> dict[str, dict[str, float]]:
    """C3 有效权重（契约 §3.3 第 3 步）。

    - balance=true → 每水平 1 / len(levels)（等权；显式 weight 由验证层 C2 警告后忽略）；
    - 否则 → ratios 声明的因素用 ratios 值（允许 0.0）；
      未声明因素用 Level.weight 因素内归一化。
    返回：因素名 -> (水平名 -> 有效权重)，构造序 = 声明序。
    """
    weights: dict[str, dict[str, float]] = {}
    ratio_by_factor = {rule.factor: rule.ratios for rule in spec.constraints.ratios}
    for factor in spec.factors:
        if spec.constraints.balance:
            equal = 1.0 / len(factor.levels)
            weights[factor.name] = {level.name: equal for level in factor.levels}
        elif factor.name in ratio_by_factor:
            weights[factor.name] = {
                level.name: float(ratio_by_factor[factor.name].get(level.name, 0.0))
                for level in factor.levels
            }
        else:
            total = sum(level.weight for level in factor.levels)
            weights[factor.name] = {
                level.name: (level.weight / total if total > 0 else 0.0)
                for level in factor.levels
            }
    return weights


def mutex_pairs(spec: ExperimentSpec) -> list[tuple[str, str]]:
    """互斥声明归一为水平名对列表（保持声明序）。"""
    return [(pair[0], pair[1]) for pair in spec.constraints.mutually_exclusive]


def filter_mutex(
    combos: list[tuple[str, ...]], pairs: list[tuple[str, str]]
) -> list[tuple[str, ...]]:
    """互斥静态过滤（契约 §3.3 第 2 步 / CR-4）：同现声明水平对的组合剔除，序保持声明序。"""
    if not pairs:
        return list(combos)
    return [combo for combo in combos if not _pair_present(combo, pairs)]


def _pair_present(combo: tuple[str, ...], pairs: list[tuple[str, str]]) -> bool:
    for first, second in pairs:
        if first in combo and second in combo:
            return True
    return False


def filter_block(
    spec: ExperimentSpec, block: BlockSpec, combos: list[tuple[str, ...]]
) -> list[tuple[str, ...]]:
    """factor_filter 过滤（契约 §3.3 第 4 步）：组合中该因素水平须在允许列表内。"""
    if not block.factor_filter:
        return list(combos)
    factor_index = {factor.name: i for i, factor in enumerate(spec.factors)}
    return [
        combo
        for combo in combos
        if all(
            combo[factor_index[factor_name]] in allowed
            for factor_name, allowed in block.factor_filter.items()
        )
    ]


def combo_weight(
    spec: ExperimentSpec, combo: tuple[str, ...], weights: dict[str, dict[str, float]]
) -> float:
    """组合权重 w_c = ∏ 各因素水平有效权重。"""
    value = 1.0
    for i, factor in enumerate(spec.factors):
        value *= weights[factor.name][combo[i]]
    return value


def positive_weight_combos(
    spec: ExperimentSpec, combos: list[tuple[str, ...]], weights: dict[str, dict[str, float]]
) -> list[tuple[str, ...]]:
    """过滤后保留正权重的组合（权重 0 = 显式排除，不参与分配）。"""
    return [combo for combo in combos if combo_weight(spec, combo, weights) > 0.0]


def largest_remainder_counts(trial_count: int, combo_weights: list[float]) -> list[int]:
    """largest remainder 整数分配（契约 §3.3 第 5 步，冻结）。

    exact_c = trial_count * w_c / Σw；floor 后余量按 fractional part 降序、
    并列按组合声明序（索引升序）分配 +1，共 R 个。
    前置条件：Σw > 0（验证层已保证正权重组合存在）。
    """
    total = sum(combo_weights)
    if total <= 0.0:
        raise ValueError("largest remainder 分配要求组合权重和为正（spec 须先通过 validate_spec）")
    exacts = [trial_count * w / total for w in combo_weights]
    floors = [math.floor(exact) for exact in exacts]
    remainder = trial_count - sum(floors)
    if remainder > 0:
        order = sorted(
            range(len(exacts)),
            key=lambda i: (-(exacts[i] - floors[i]), i),
        )
        for i in order[:remainder]:
            floors[i] += 1
    return floors


def allocation_has_rounding(trial_count: int, combo_weights: list[float]) -> bool:
    """RATIO_ROUNDED 判定：任一组合的 exact 值非整数（容差内视为整数，防浮点噪声）。"""
    total = sum(combo_weights)
    if total <= 0.0:
        return False
    for weight in combo_weights:
        exact = trial_count * weight / total
        if abs(exact - round(exact)) > _FLOAT_EPSILON:
            return True
    return False


def block_allocation(
    spec: ExperimentSpec,
    block: BlockSpec,
    combos: list[tuple[str, ...]],
    weights: dict[str, dict[str, float]],
) -> list[tuple[tuple[str, ...], int]]:
    """单 block 的分配结果：[(组合, 分配数)]，仅含分配数 > 0 的组合，组合保持声明序。

    输入 combos 应为该 block 经 factor_filter 与互斥剔除后的可用组合。
    """
    available = filter_block(spec, block, combos)
    positive = positive_weight_combos(spec, available, weights)
    counts = largest_remainder_counts(
        block.trial_count, [combo_weight(spec, combo, weights) for combo in positive]
    )
    return [(combo, count) for combo, count in zip(positive, counts) if count > 0]


def compute_frequency(spec: ExperimentSpec, trials: list[Trial]) -> dict[str, dict[str, int]]:
    """频数统计（契约 §3.3 第 9 步）：遍历 trials 对每因素每水平计数（构造序 = 声明序）。"""
    frequency: dict[str, dict[str, int]] = {
        factor.name: {level.name: 0 for level in factor.levels} for factor in spec.factors
    }
    for trial in trials:
        for factor_name, level_name in trial.factors.items():
            if factor_name in frequency and level_name in frequency[factor_name]:
                frequency[factor_name][level_name] += 1
    return frequency


def generate_trials(spec: ExperimentSpec, max_attempts: int = 100) -> GeneratedExperiment:
    """纯函数生成（契约 §3.5 冻结签名）。

    同 spec（含同 seed）→ 返回值 canonical JSON 逐字节相同。
    前置条件：spec 已通过 validate_spec（工具层保证先验证后生成）。
    max_attempts：SEARCH_EXHAUSTED 框架能力参数——Phase A 约束集无搜索路径，
    本参数当前不被消费，签名保留以为 Phase B 序列约束预留。
    """
    # 第 1 步：组合展开（factors 声明序笛卡尔积）
    combos = spec.expanded_combinations()
    # 第 2 步：互斥静态过滤
    combos = filter_mutex(combos, mutex_pairs(spec))
    # 第 3 步：有效权重
    weights = effective_weights(spec)

    trials: list[Trial] = []
    # 第 4~8 步：逐 block 切分、分配、物化、排序、index 分配
    for block in spec.blocks:
        allocation = block_allocation(spec, block, combos, weights)
        block_trials: list[dict[str, str]] = []
        for combo, count in allocation:
            factors_map = {
                factor.name: combo[i] for i, factor in enumerate(spec.factors)
            }
            block_trials.extend([factors_map] * count)
        # 第 7 步：排序（shuffle_within=true → 每 block 恰一次 shuffle 调用）
        if block.shuffle_within:
            rng = random.Random(derive_block_seed(spec.seed, block.name))
            rng.shuffle(block_trials)
        for factors_map in block_trials:
            trials.append(
                Trial(
                    index=len(trials),
                    block=block.name,
                    factors=dict(factors_map),
                    stimulus={},
                    derived={},
                    timing=spec.timing,
                )
            )

    config_fingerprint = sha256_hex(canonical_json(spec.model_dump()))
    trials_fingerprint = sha256_hex(canonical_json([trial.model_dump() for trial in trials]))
    return GeneratedExperiment(
        config_fingerprint=config_fingerprint,
        trials_fingerprint=trials_fingerprint,
        engine_spec_version=ENGINE_SPEC_VERSION,
        plugin_used=None,
        trials=trials,
    )
