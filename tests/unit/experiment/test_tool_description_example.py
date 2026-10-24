"""R2 revision (diagnostic fix F1) consistency tests: the example embedded in the description matches the real schema field for field.

Assertion groups (contract §5.1 R2 revision constraints):
1. the example itself validates against the real ExperimentSpec Pydantic model, and validate_spec → valid=true
   with zero errors and zero warnings (executable evidence of a "validated example");
2. the description really contains that example (module-level constant as the single source, preventing drift);
3. that description appears verbatim in the tools schema sent to the LLM (registry.get_schemas());
4. the description is pure ASCII (the R2 core: eliminating the escape-dense schema form);
5. length budget: soft ≤700 / hard ≤900 characters (the R2 thresholds, replacing R1's 1600/2400);
6. the structure summary covers all required top-level keys (required fields must not be dropped for the character budget).

The filename contains "tool_" so PA-7's -k "tool_" filter also picks it up.
"""

from __future__ import annotations

import json

from src.agent.registry import ToolRegistry
from src.config import Settings
from src.experiment.schemas import ExperimentSpec
from src.experiment.validation import validate_spec
from src.tools import experiment_tools

DESCRIPTION_SOFT_BUDGET = 700
DESCRIPTION_HARD_BUDGET = 900
REQUIRED_TOP_KEYS = ("schema_version", "name", "seed", "factors", "blocks", "responses")


def test_description_example_validates_against_real_schema() -> None:
    """The example passes json.loads → ExperimentSpec.model_validate → validate_spec in full."""
    example = json.loads(experiment_tools._SPEC_EXAMPLE_JSON)
    # Pydantic structural validation (V1~V9 all present)
    ExperimentSpec.model_validate(example)
    # validation-layer semantic checks (C1~C3 etc.)
    result = validate_spec(example)
    assert result.valid is True
    assert result.errors == []
    assert result.warnings == []


def test_description_contains_example_constant() -> None:
    """The description embeds the module-level constant example (single source, not two hand copies)."""
    spec = experiment_tools.build_validate_spec(Settings())
    assert experiment_tools._SPEC_EXAMPLE_JSON in spec.description
# the anti-wrapper instruction is present (the direct counter-text to PA-14 failure mode B, English R2 version)
    assert "no wrapper" in spec.description


def test_description_reaches_llm_tools_schema() -> None:
    """The example and the anti-wrapper instruction really enter the tools schema sent to the LLM."""
    registry = ToolRegistry()
    registry.register(experiment_tools.build_validate_spec(Settings()))
    registry.register(experiment_tools.build_generate_spec(Settings()))
    registry.register(experiment_tools.build_export_spec(Settings()))

    schemas = {s["function"]["name"]: s["function"]["description"] for s in registry.get_schemas()}
    assert set(schemas) == {"validate_experiment", "generate_trials", "export_experiment"}
    validate_description = schemas["validate_experiment"]
    assert experiment_tools._SPEC_EXAMPLE_JSON in validate_description
    assert "no wrapper" in validate_description


def test_description_is_pure_ascii() -> None:
    """R2 core: the description is pure ASCII (ord(c) < 128, eliminating the \\uXXXX escape-dense form)."""
    spec = experiment_tools.build_validate_spec(Settings())
    non_ascii = [c for c in spec.description if ord(c) >= 128]
    assert not non_ascii, f"description contains non-ASCII characters: {non_ascii[:10]}"


def test_description_length_budget() -> None:
    """Token-budget guard: soft ≤700 (warning threshold), hard ≤900 (rejection threshold)."""
    spec = experiment_tools.build_validate_spec(Settings())
    length = len(spec.description)
    assert length <= DESCRIPTION_HARD_BUDGET, f"description exceeds the hard budget: {length} chars"
    assert length <= DESCRIPTION_SOFT_BUDGET, (
        f"description exceeds the soft budget: {length} chars (the Architect must review the example for brevity)"
    )


def test_description_covers_required_top_keys() -> None:
    """The structure summary must not drop required top-level keys for the character budget (contract R2 constraint 5)."""
    spec = experiment_tools.build_validate_spec(Settings())
    for key in REQUIRED_TOP_KEYS:
        assert key in spec.description, f"structure summary is missing a required key: {key}"


# ---------------------------------------------------------------------------
# Expressiveness Stage 1: the composition recipes live in the config FIELD
# description (the established v2 documentation surface) while the ToolSpec-level
# description stays within its budget. Same ASCII discipline as the R2 core.
# ---------------------------------------------------------------------------

_RECIPE_MARKERS = (
    "Composition recipes",
    "copy_from",   # recipe 1: relational content via reuse
    "exclude",     # recipe 1: guaranteed-different draw
    "when={factor:level}",  # recipe 1/2 guard syntax
    "withhold_option",  # recipe 4: no-press as a correct answer
    "count={factor,levels",  # recipe 3: per-level element-count maps
)


def test_field_description_is_pure_ascii() -> None:
    """The config field description (the v2 documentation surface) is pure ASCII."""
    field = experiment_tools.ValidateExperimentInput.model_fields["config"]
    non_ascii = [c for c in (field.description or "") if ord(c) >= 128]
    assert not non_ascii, f"field description contains non-ASCII characters: {non_ascii[:10]}"


def test_field_description_contains_composition_recipes() -> None:
    """The when+copy_from+exclude composition pattern (audit T1-2) is documented
    for the LLM in the config field description, paradigm-name-free."""
    field = experiment_tools.ValidateExperimentInput.model_fields["config"]
    description = field.description or ""
    for marker in _RECIPE_MARKERS:
        assert marker in description, f"composition recipe marker missing: {marker!r}"


def test_toolspec_description_budget_unchanged_by_recipes() -> None:
    """Recipes are documented in the FIELD description; the ToolSpec-level
    description keeps the R2 budgets (soft 700 / hard 900)."""
    spec = experiment_tools.build_validate_spec(Settings())
    assert len(spec.description) <= DESCRIPTION_HARD_BUDGET
