"""experiment package: the Phase A generic experiment engine (contract docs/handoff/architect-phaseA-contract.md).

Module composition:
- schemas.py      full-hierarchy Pydantic models for ExperimentSpec (contract §2 field table + V1~V9)
- canonical.py    canonical JSON serialization and SHA-256 fingerprints (contract §6.1/§6.3)
- validation.py   constraint-semantics validation and error-code enums (contract §4)
- generation.py   deterministic generation engine (contract §3 nine-step algorithm)
- export.py       ExperimentBundle assembly (contract §6.2)
- verify.py       generator-free independent verification CLI (contract §6.4)

Layering (contract §8.4): the experiment layer depends only on src/models, src/config and the stdlib;
importing src.agent / src.tools / src.api / src.services / src.storage is forbidden.
The combinator registration entry lives at src/agent/experiment_registry.py (agent layer, contract §5.4).
"""
