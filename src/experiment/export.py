"""ExperimentBundle 组装（契约 §6.2/§6.3，冻结）。

- Bundle 自包含：规范化 spec（Pydantic 解析后 model_dump，默认值补全）+ 全量 trials
  + reproducibility（含 effective_weights / allocation per-block 口径）+ summary；
- bundle_sha256 = SHA-256(canonical JSON(bundle 剥离 "bundle_sha256" 与 "generated_at" 两键))；
  generated_at 不参与任何指纹（时间戳非确定性输入）；
- allocation 只记录实际分配非 0 的组合（被过滤组合不出现）；
- 落盘文件本身 = canonical JSON 单行（UTF-8，无 BOM）——序列化由调用方执行。
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.experiment.canonical import canonical_json, sha256_hex
from src.experiment.generation import (
    ENGINE_SPEC_VERSION,
    block_allocation,
    compute_frequency,
    effective_weights,
    filter_mutex,
    generate_trials,
    mutex_pairs,
)
from src.experiment.schemas import ExperimentSpec


def _now_utc_iso_z() -> str:
    """当前 UTC 时间的 ISO-8601 秒精度 Z 格式（仅用于 generated_at 元字段，不参与指纹）。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def combo_key(combo: tuple[str, ...]) -> str:
    """allocation 组合键：按因素声明序以 | 连接水平名（契约 §6.2；combo 元组即声明序）。"""
    return "|".join(combo)


def build_bundle(spec: ExperimentSpec, *, generated_at: str | None = None) -> dict[str, object]:
    """组装 ExperimentBundle（纯计算 + 唯一时间元字段）。

    generated_at：None → 当前 UTC 时间；固定值注入用于黄金文件（PA-13）。
    bundle_sha256 对剥离 bundle_sha256 与 generated_at 两键后的 dict 计算。
    """
    generated = generate_trials(spec)
    weights = effective_weights(spec)
    combos = filter_mutex(spec.expanded_combinations(), mutex_pairs(spec))

    allocation: dict[str, dict[str, int]] = {}
    for block in spec.blocks:
        block_alloc = block_allocation(spec, block, combos, weights)
        allocation[block.name] = {
            combo_key(combo): count for combo, count in block_alloc
        }

    bundle: dict[str, object] = {
        "schema_version": 1,
        "generated_at": generated_at if generated_at is not None else _now_utc_iso_z(),
        "spec": spec.model_dump(),
        "reproducibility": {
            "engine_spec_version": ENGINE_SPEC_VERSION,
            "config_fingerprint": generated.config_fingerprint,
            "trials_fingerprint": generated.trials_fingerprint,
            "plugin_used": None,
            "effective_weights": weights,
            "allocation": allocation,
        },
        "trials": [trial.model_dump() for trial in generated.trials],
        "summary": {
            "trial_count": len(generated.trials),
            "blocks": [block.name for block in spec.blocks],
            "frequency": compute_frequency(spec, generated.trials),
        },
    }
    stripped = {key: value for key, value in bundle.items() if key not in ("bundle_sha256", "generated_at")}
    bundle["bundle_sha256"] = sha256_hex(canonical_json(stripped))
    return bundle


def bundle_canonical_text(bundle: dict[str, object]) -> str:
    """Bundle 的 canonical JSON 文本（落盘与逐字节比对的统一形态）。"""
    return canonical_json(bundle)
