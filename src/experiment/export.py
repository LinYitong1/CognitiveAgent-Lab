"""ExperimentBundle assembly (contract §6.2/§6.3, frozen).

- The bundle is self-contained: normalized spec (spec_dump after Pydantic parse — defaults filled,
  UNSET v2 fields removed, M2-B D-M2-1 §1.1) + full trials + reproducibility (incl. effective_weights /
  allocation per-block) + summary;
- bundle_sha256 = SHA-256(canonical JSON(bundle with the "bundle_sha256" and "generated_at" keys stripped));
  generated_at participates in no fingerprint (a timestamp is not a deterministic input);
- allocation records only combinations actually allocated a non-zero count (filtered combos are absent);
- the on-disk file itself = single-line canonical JSON (UTF-8, no BOM) — serialization is done by the caller.
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
from src.experiment.schemas import ExperimentSpec, spec_dump, trial_dump


def _now_utc_iso_z() -> str:
    """Current UTC time as an ISO-8601 second-precision Z string (only for the generated_at meta field; part of no fingerprint)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def combo_key(combo: tuple[str, ...]) -> str:
    """allocation combo key: level names joined with | in factor declaration order (contract §6.2; the combo tuple is that order)."""
    return "|".join(combo)


def build_bundle(spec: ExperimentSpec, *, generated_at: str | None = None) -> dict[str, object]:
    """Assemble an ExperimentBundle (pure computation + one time meta field).

    generated_at: None → current UTC time; a fixed value is injected for golden files (PA-13).
    bundle_sha256 is computed over the dict with bundle_sha256 and generated_at stripped.
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
        "spec": spec_dump(spec),
        "reproducibility": {
            "engine_spec_version": ENGINE_SPEC_VERSION,
            "config_fingerprint": generated.config_fingerprint,
            "trials_fingerprint": generated.trials_fingerprint,
            "plugin_used": None,
            "effective_weights": weights,
            "allocation": allocation,
        },
        "trials": [trial_dump(trial) for trial in generated.trials],
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
    """Canonical JSON text of the bundle (the unified form for on-disk writes and byte comparisons)."""
    return canonical_json(bundle)
