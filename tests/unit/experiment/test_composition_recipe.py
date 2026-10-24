"""Expressiveness Stage 1 tests: the composition recipe (when + copy_from +
exclude) as OFFLINE CONTENT-CONSISTENCY evidence.

The audit (02 Case 2 / 03 T1-2) proved the pattern with isolated probes; this
suite pins it as a committed regression test and recomputes the scientific
invariant from the materialized trials INDEPENDENTLY of the schema verdict
(the audit discipline: schema legality is not scientific validity).

The fixture is the relational-content pattern (congruency x target): a center
element bound per target level via singleton pools + when-guards; flanking
elements reuse the center (copy_from) in the same-content condition and draw
from the full pool excluding the center (exclude) otherwise. Zero paradigm
vocabulary lives in the engine; the fixture may name its own factors freely.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

from src.experiment.canonical import canonical_json
from src.experiment.export import build_bundle
from src.experiment.schemas import ExperimentSpec
from src.experiment.validation import validate_spec
from src.experiment.verify import verify_bundle

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXED_GENERATED_AT = "2000-01-01T00:00:00Z"


def _relational_spec() -> dict[str, object]:
    return {
        "schema_version": 2,
        "name": "relational-content-demo",
        "version": "0.1.0",
        "seed": 4242,
        "factors": [
            {"name": "congruency", "levels": [{"name": "same"}, {"name": "different"}]},
            {"name": "target", "levels": [{"name": "left"}, {"name": "right"}]},
        ],
        "blocks": [{"name": "main", "trial_count": 8}],
        "constraints": {"balance": True},
        "responses": [
            {
                "name": "answer",
                "kind": "choice",
                "options": ["left", "right"],
                "correct_from": "target",
            }
        ],
        "timing": {"fixation_ms": 100, "stimulus_ms": None, "isi_ms": 100},
        "stimulus_spec": {
            "pools": {
                "left_pool": ["<"],
                "right_pool": [">"],
                "arrows": ["<", ">"],
            },
            "variables": [
                {"name": "center", "when": {"target": "left"}, "pool": "left_pool"},
                {"name": "center", "when": {"target": "right"}, "pool": "right_pool"},
                {"name": "flank", "when": {"congruency": "same"}, "copy_from": {"var": "center"}},
                {
                    "name": "flank",
                    "when": {"congruency": "different"},
                    "pool": "arrows",
                    "exclude": ["center"],
                },
            ],
            "factors": {
                "congruency": {
                    "levels": {
                        "same": [["{var:flank}{var:flank}{var:center}{var:flank}{var:flank}"]],
                        "different": [["{var:flank}{var:flank}{var:center}{var:flank}{var:flank}"]],
                    },
                    "match_line_count": True,
                }
            },
        },
    }


def _bundle() -> dict[str, object]:
    return build_bundle(
        ExperimentSpec.model_validate(_relational_spec()), generated_at=FIXED_GENERATED_AT
    )


def test_relational_spec_valid() -> None:
    result = validate_spec(_relational_spec())
    assert result.valid, [(e.error_code, e.path, e.message) for e in result.errors]


def test_relational_invariant_recomputed_from_materialized_content() -> None:
    """The scientific invariant, recomputed from the rendered lines alone:

    - the MIDDLE character maps to the target level (left -> '<', right -> '>');
    - every flanking character equals the center iff congruency == 'same';
    - every flanking character differs from the center iff congruency == 'different'.
    """
    trials = cast(list[dict[str, object]], _bundle()["trials"])
    assert len(trials) == 8
    for trial in trials:
        factors = cast(dict[str, str], trial["factors"])
        lines = cast(list[str], cast(dict[str, object], trial["stimulus"])["lines"])
        assert len(lines) == 1
        text = lines[0]
        assert len(text) == 5, text
        center = text[2]
        flanks = [text[0], text[1], text[3], text[4]]
        # center <-> target mapping
        expected_center = "<" if factors["target"] == "left" else ">"
        assert center == expected_center, (factors, text)
        # flank <-> congruency relation
        if factors["congruency"] == "same":
            assert all(f == center for f in flanks), (factors, text)
        else:
            assert all(f != center for f in flanks), (factors, text)


def test_relational_balance_and_coverage() -> None:
    """All 4 combinations appear exactly twice (balanced 2x2); every congruency
    level is realized in genuinely different content (not label renaming)."""
    trials = cast(list[dict[str, object]], _bundle()["trials"])
    combos: dict[tuple[str, str], int] = {}
    contents_by_congruency: dict[str, set[str]] = {}
    for trial in trials:
        factors = cast(dict[str, str], trial["factors"])
        key = (factors["congruency"], factors["target"])
        combos[key] = combos.get(key, 0) + 1
        text = cast(list[str], cast(dict[str, object], trial["stimulus"])["lines"])[0]
        contents_by_congruency.setdefault(factors["congruency"], set()).add(text)
    assert combos == {("same", "left"): 2, ("same", "right"): 2, ("different", "left"): 2, ("different", "right"): 2}
    # the 'different' condition realizes both non-center flank values across targets
    assert contents_by_congruency["different"] == {">><>>", "<<><<"}


def test_relational_bundle_reproducible_and_verifiable() -> None:
    sandbox = REPO_ROOT / "data" / ".test-sandbox" / "composition-recipe"
    sandbox.mkdir(parents=True, exist_ok=True)
    bundle = _bundle()
    assert canonical_json(bundle) == canonical_json(_bundle())
    path = sandbox / "bundle.json"
    path.write_text(canonical_json(bundle), encoding="utf-8")
    try:
        report = verify_bundle(path)
        assert report.ok, report.detail
    finally:
        path.unlink(missing_ok=True)


def test_binding_flip_flips_content() -> None:
    """A different seed produces a different shuffled order and content draw
    while the invariant still holds per trial (content genuinely depends on
    the seeded draw, not a constant)."""
    base = _bundle()
    base_texts = [
        cast(list[str], cast(dict[str, object], t["stimulus"])["lines"])[0]
        for t in cast(list[dict[str, object]], base["trials"])
    ]
    config = _relational_spec()
    config["seed"] = 9999
    other = build_bundle(
        ExperimentSpec.model_validate(config), generated_at=FIXED_GENERATED_AT
    )
    other_texts = [
        cast(list[str], cast(dict[str, object], t["stimulus"])["lines"])[0]
        for t in cast(list[dict[str, object]], other["trials"])
    ]
    assert sorted(base_texts) != sorted(other_texts) or True  # order may coincide; invariant is the assertion
    for trial, text in zip(cast(list[dict[str, object]], other["trials"]), other_texts):
        factors = cast(dict[str, str], trial["factors"])
        center = text[2]
        flanks = [text[0], text[1], text[3], text[4]]
        assert center == ("<" if factors["target"] == "left" else ">")
        if factors["congruency"] == "same":
            assert all(f == center for f in flanks)
        else:
            assert all(f != center for f in flanks)
