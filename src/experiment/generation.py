"""Deterministic generation engine (contract §3 nine-step algorithm, frozen).

Trial generation = a pure function: no IO, no time dependency, no hidden state, no global randomness.
The only randomness consumer: the within-block shuffle (exactly one rng.shuffle call per block).
Seed derivation (CR-1): the first 8 bytes of SHA-256(f"{seed}:block:{block.name}") as a big-endian int64.

Determinism guarantees (§3.4): no set construction/iteration; dicts rely on ≥3.7 insertion order;
canonical JSON sort_keys removes key-order differences; no datetime.now / uuid / global state.
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

ENGINE_SPEC_VERSION: str = "1.0"  # must be bumped on any algorithm change (allocation/derivation/shuffle/serialization)

_FLOAT_EPSILON = 1e-9  # integer-decision tolerance (a float representation-noise guard, not an allocation-semantics tolerance)


def derive_block_seed(seed: int, block_name: str) -> int:
    """Per-block independent substream seed (contract §3.1 frozen algorithm: explicit SHA-256 derivation)."""
    digest = hashlib.sha256(f"{seed}:block:{block_name}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")  # unsigned int64


def effective_weights(spec: ExperimentSpec) -> dict[str, dict[str, float]]:
    """C3 effective weights (contract §3.3 step 3).

    - balance=true → 1 / len(levels) per level (equal weight; an explicit weight is ignored after the C2 warning);
    - otherwise → factors declared in ratios use the ratios values (0.0 allowed);
      undeclared factors use Level.weight normalized within the factor.
    Returns: factor name -> (level name -> effective weight), construction order = declaration order.
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
    """Normalize mutex declarations into a list of level-name pairs (declaration order preserved)."""
    return [(pair[0], pair[1]) for pair in spec.constraints.mutually_exclusive]


def filter_mutex(
    combos: list[tuple[str, ...]], pairs: list[tuple[str, str]]
) -> list[tuple[str, ...]]:
    """Static mutex filtering (contract §3.3 step 2 / CR-4): combinations containing a declared pair are removed; order preserves declaration order."""
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
    """factor_filter filtering (contract §3.3 step 4): the factor's level in the combination must be in the allow-list."""
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
    """Combination weight w_c = ∏ effective weights of the factors' levels."""
    value = 1.0
    for i, factor in enumerate(spec.factors):
        value *= weights[factor.name][combo[i]]
    return value


def positive_weight_combos(
    spec: ExperimentSpec, combos: list[tuple[str, ...]], weights: dict[str, dict[str, float]]
) -> list[tuple[str, ...]]:
    """Keep only positive-weight combinations after filtering (weight 0 = explicit exclusion, no allocation)."""
    return [combo for combo in combos if combo_weight(spec, combo, weights) > 0.0]


def largest_remainder_counts(trial_count: int, combo_weights: list[float]) -> list[int]:
    """Largest-remainder integer allocation (contract §3.3 step 5, frozen).

    exact_c = trial_count * w_c / Σw; after the floor, the remaining R units go to the combos with
    the largest fractional parts, ties broken by declaration order (ascending index).
    Precondition: Σw > 0 (the validation layer guarantees a positive-weight combination exists).
    """
    total = sum(combo_weights)
    if total <= 0.0:
        raise ValueError("largest-remainder allocation requires a positive sum of combination weights (the spec must pass validate_spec first)")
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
    """RATIO_ROUNDED decision: any combination has a non-integer exact value (within tolerance counts as integer, guarding float noise)."""
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
    """Allocation result for one block: [(combination, count)] with count > 0 only, combinations in declaration order.

    The input combos should be the block's available combinations after factor_filter and mutex exclusion.
    """
    available = filter_block(spec, block, combos)
    positive = positive_weight_combos(spec, available, weights)
    counts = largest_remainder_counts(
        block.trial_count, [combo_weight(spec, combo, weights) for combo in positive]
    )
    return [(combo, count) for combo, count in zip(positive, counts) if count > 0]


def compute_frequency(spec: ExperimentSpec, trials: list[Trial]) -> dict[str, dict[str, int]]:
    """Frequency statistics (contract §3.3 step 9): iterate the trials and count every factor/level (construction order = declaration order)."""
    frequency: dict[str, dict[str, int]] = {
        factor.name: {level.name: 0 for level in factor.levels} for factor in spec.factors
    }
    for trial in trials:
        for factor_name, level_name in trial.factors.items():
            if factor_name in frequency and level_name in frequency[factor_name]:
                frequency[factor_name][level_name] += 1
    return frequency


def generate_trials(spec: ExperimentSpec, max_attempts: int = 100) -> GeneratedExperiment:
    """Pure-function generation (contract §3.5 frozen signature).

    The same spec (including the same seed) → a return value whose canonical JSON is byte-identical.
    Precondition: the spec has passed validate_spec (the tool layer guarantees validate-before-generate).
    max_attempts: the SEARCH_EXHAUSTED framework capability parameter — the Phase A constraint set has no
    search path, so the parameter is currently unconsumed; the signature keeps it for Phase B sequence constraints.
    """
    # Step 1: combination expansion (Cartesian product in factors declaration order)
    combos = spec.expanded_combinations()
    # Step 2: static mutex filtering
    combos = filter_mutex(combos, mutex_pairs(spec))
    # Step 3: effective weights
    weights = effective_weights(spec)

    trials: list[Trial] = []
    # Steps 4~8: per-block split, allocation, materialization, sorting, index assignment
    for block in spec.blocks:
        allocation = block_allocation(spec, block, combos, weights)
        block_trials: list[dict[str, str]] = []
        for combo, count in allocation:
            factors_map = {
                factor.name: combo[i] for i, factor in enumerate(spec.factors)
            }
            block_trials.extend([factors_map] * count)
        # Step 7: sorting (shuffle_within=true → exactly one shuffle call per block)
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
