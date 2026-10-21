"""One-shot generator for the Manor Case fixture (tests/fixtures/manor-case/).

Run from the repo root:
    .venv/bin/python tests/fixtures/manor-case/generate.py

Produces (deterministic; fixed generated_at):
- spec.json      the schema_version 2 ExperimentSpec (minimal core, PROTOTYPE_SPEC §7)
- bundle.json    the exported ExperimentBundle (canonical JSON)
- gamespec.json  the GameSpec v2 with world/narrative/mechanics/mapping
- README.md      the research-game mapping walkthrough

The generator is committed for provenance/reproducibility; rerunning it must
reproduce byte-identical files (asserted by test_manor_fixture.py).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from src.experiment.canonical import canonical_json  # noqa: E402
from src.experiment.export import build_bundle  # noqa: E402
from src.experiment.game_schemas import validate_game  # noqa: E402
from src.experiment.schemas import ExperimentSpec  # noqa: E402

FIXED_GENERATED_AT = "2026-10-21T00:00:00Z"

SPEC: dict[str, object] = {
    "schema_version": 2,
    "name": "manor-case",
    "version": "0.1.0",
    "seed": 20261021,
    "factors": [
        {"name": "salience", "levels": [{"name": "salient"}, {"name": "embedded"}]},
        {"name": "true_suspect", "levels": [{"name": "a"}, {"name": "b"}, {"name": "c"}]},
    ],
    "blocks": [
        {"name": "practice", "trial_count": 6},
        {"name": "investigation", "trial_count": 20},
    ],
    "constraints": {"balance": True},
    "responses": [
        {"name": "accuse", "kind": "choice", "options": ["a", "b", "c"], "correct_from": "true_suspect"}
    ],
    "timing": {"fixation_ms": 300, "stimulus_ms": None, "isi_ms": 500},
    "stimulus_spec": {
        "factors": {
            "salience": {
                "levels": {
                    "salient": [
                        [
                            "A clear record: payments traced to suspect {true_suspect}.",
                            "The page is otherwise clean.",
                            "The ink is fresh.",
                            "Nothing distracts the eye.",
                        ]
                    ],
                    "embedded": [
                        [
                            "Shelves of unrelated ledgers crowd the desk.",
                            "A torn receipt mentions suspect {true_suspect}.",
                            "Frost obscures half the margin.",
                            "Someone has dog-eared every page.",
                        ]
                    ],
                },
                "match_line_count": True,
            },
        },
        "pools": {},
    },
    "derived_spec": [{"name": "trial_number", "op": "trial_number"}],
    "measures": [
        {"name": "accuracy", "source": "response.correct", "notes": "per-condition accuracy"},
        {"name": "rt", "source": "response.rt_ms", "notes": "demo-grade browser timing"},
    ],
}


def _encounter(object_id: str, label: str, inspect_text: str) -> dict[str, object]:
    return {
        "object_id": object_id,
        "label": label,
        "inspect_text": inspect_text,
        "role": "encounter",
    }


def _flavour(object_id: str, label: str, inspect_text: str) -> dict[str, object]:
    return {
        "object_id": object_id,
        "label": label,
        "inspect_text": inspect_text,
        "role": "flavour",
    }


WORLD: dict[str, object] = {
    "rooms": {
        "hall": {
            "title": "Entrance Hall",
            "description": "A drafty hall; coats on pegs, a clock that lost interest in time.",
            "exits": {"study": "a heavy oak door", "library": "a creaking passage"},
            "objects": [
                _flavour("dusty-clock", "dusty clock", "It stopped at 3:14. Nobody remembers why."),
                _encounter("calling-card", "calling card", "A card left face-down on the hall table."),
                _encounter("torn-invitation", "torn invitation", "Half an invitation, torn diagonally."),
            ],
        },
        "study": {
            "title": "The Study",
            "description": "Books stacked spine-inward; a desk that has seen arguments.",
            "exits": {"hall": "back to the hall", "parlour": "through the side door"},
            "objects": [
                _encounter("desk-ledger", "desk ledger", "A ledger lies open at the centre page."),
                _encounter("hearth-ash", "hearth ash", "Something was burned here, recently."),
                _encounter("portrait-x", "marked portrait", "A portrait with a scratched corner."),
                _encounter("letter-rack", "letter rack", "Letters sorted by no visible system."),
                _encounter("wax-seal", "wax seal", "A seal stamped with an unfamiliar crest."),
                _encounter("inkwell", "inkwell", "Ink still wet around the rim."),
            ],
        },
        "library": {
            "title": "The Library",
            "description": "Two floors of books and one ladder that complains.",
            "exits": {"hall": "back to the hall", "parlour": "past the atlas shelf"},
            "objects": [
                _encounter("wine-ledger", "wine ledger", "A heavy ledger records the cellar stores."),
                _encounter("atlas-margin", "atlas margin", "Notes crowd the margin of one map."),
                _encounter("lamp-oil", "lamp oil", "Oil bought in an unusual quantity."),
                _encounter("reading-list", "reading list", "A list in a careful hand."),
                _encounter("book-plate", "book plate", "A bookplate peeled half away."),
                _encounter("index-card", "index card", "One card misfiled on purpose?"),
            ],
        },
        "parlour": {
            "title": "The Parlour",
            "description": "Where the household performed its evenings.",
            "exits": {"study": "back to the study", "library": "back to the library", "cellar": "down the cellar stairs"},
            "objects": [
                _encounter("tea-cup", "tea cup", "Two cups, one guest."),
                _encounter("piano-key", "piano key", "One key is freshly chipped."),
                _encounter("card-table", "card table", "Cards dealt but never played."),
                _encounter("window-frost", "frost on the window", "A patch melted from the inside."),
                _encounter("coat-check", "coat peg", "One coat heavier than it should be."),
                _encounter("mirror-crack", "cracked mirror", "The crack follows a deliberate line."),
            ],
        },
        "cellar": {
            "title": "The Cellar",
            "description": "Cold, exact, and honest about what the house stores.",
            "exits": {"parlour": "up the stairs"},
            "objects": [
                _encounter("crate-label", "crate label", "A label rewritten twice."),
                _encounter("barrel-mark", "barrel mark", "Chalk marks count the withdrawals."),
                _encounter("tool-rack", "tool rack", "One tool cleaned, the others not."),
                _encounter("cobweb-corner", "cobweb corner", "A web broken in one straight line."),
                _encounter("stair-scuff", "stair scuff", "Scuffs that match no current shoe."),
                _encounter("box-lid", "box lid", "A lid that no longer sits flush."),
            ],
        },
    },
    "start_room": "hall",
}

ENCOUNTER_IDS = [
    "calling-card", "torn-invitation",
    "desk-ledger", "hearth-ash", "portrait-x", "letter-rack", "wax-seal", "inkwell",
    "wine-ledger", "atlas-margin", "lamp-oil", "reading-list", "book-plate", "index-card",
    "tea-cup", "piano-key", "card-table", "window-frost", "coat-check", "mirror-crack",
    "crate-label", "barrel-mark", "tool-rack", "cobweb-corner", "stair-scuff", "box-lid",
]


def build_gamespec(bundle: dict[str, object]) -> dict[str, object]:
    spec_part = bundle["spec"]  # type: ignore[index]
    repro = bundle["reproducibility"]  # type: ignore[index]
    return {
        "schema_version": 2,
        "game": {"name": "manor-case", "version": "0.1.0"},
        "experiment_ref": {
            "name": spec_part["name"],  # type: ignore[index]
            "version": spec_part["version"],  # type: ignore[index]
            "seed": spec_part["seed"],  # type: ignore[index]
            "config_fingerprint": repro["config_fingerprint"],  # type: ignore[index]
            "trials_fingerprint": repro["trials_fingerprint"],  # type: ignore[index]
            "bundle_sha256": bundle["bundle_sha256"],
        },
        "scene": {
            "title": "The Manor Case",
            "instructions": (
                "Re-examine the closed case. Explore the manor, examine what you find, and "
                "judge which suspect each piece of evidence supports. Keys: a / b / c."
            ),
        },
        "input": {
            "modalities": ["keyboard"],
            "bindings": [{"response_name": "accuse", "keys": {"a": "a", "b": "b", "c": "c"}}],
        },
        "feedback": {"on_response": "none", "duration_ms": 0},
        "world": WORLD,
        "narrative": {
            "intro": (
                "The case was closed in a hurry. You have one evening in the manor to "
                "re-examine what remains."
            ),
            "block_briefings": {
                "practice": "A short warm-up round: examine the first pieces of evidence.",
                "investigation": "The re-examination begins in earnest. Trust the record, not the story.",
            },
            "ending_bands": [
                {"min_accuracy": 0.0, "text": "The file returns to the shelf, unread."},
                {"min_accuracy": 0.5, "text": "Some threads hold. The report is amended with care."},
                {"min_accuracy": 0.8, "text": "The record speaks plainly. The case is reopened."},
            ],
        },
        "mechanics": {
            "layout": "explore-and-encounter",
            "inspect_objects": True,
            "trial_trigger": "explore-encounter",
        },
        "mapping": {
            "trial_trigger": "explore-encounter",
            "encounter_objects": ENCOUNTER_IDS,
            "response_bindings": [{"response_name": "accuse", "keys": {"a": "a", "b": "b", "c": "c"}}],
            "creative_freedom": [
                "theme", "room_labels", "object_labels", "narrative_text", "feedback_style",
            ],
            "controlled_invariants": [
                "trial_order", "conditions", "stimulus_content", "correct_answers", "timing",
            ],
        },
    }


README = """# Manor Case fixture (M2-C)

Minimal-core prototype data (PROTOTYPE_SPEC §7): single-factor load manipulation
(`salience`: salient vs embedded clue lines), ground truth `true_suspect` (a/b/c),
6 practice + 20 investigation trials, seed 20261021. All files are deterministic
(fixed `generated_at`); `generate.py` reproduces them byte-identically.

## Research-game mapping walkthrough (one interaction)

1. Player moves hall → library: `game: room_enter` (logged, NOT reconciled).
2. Player inspects the dusty clock (flavour): `game: object_inspect` (no trial).
3. Player examines the **wine ledger** (role=encounter): `game: encounter_trigger`;
   the runtime pulls the NEXT unconsumed bundle trial in index order (monotonic
   cursor — no skip, no reorder; 26 encounter objects ≥ 26 trials).
4. The encounter renders `trial.stimulus["lines"]` VERBATIM (M2-B materialization;
   the GameSpec has no field that can alter, filter or reorder lines).
   Event: `measurement: trial_start` (index, block, conditions).
5. Player presses `b` → mapping binding resolves to value "b"; the renderer
   computes `correct = (trial.factors["true_suspect"] == "b")` FROM THE BUNDLE.
   Event: `measurement: response` (value, correct, rt_ms).
6. No feedback (investigation, `feedback.on_response=none`); return to exploration.
7. Post-session (M2-E, not yet implemented): `verify_game_events` reconciles every
   measurement event against the bundle — order, conditions, correctness.

Controlled invariants (architectural, validated by G8 + schema absence):
trial_order, conditions, stimulus_content, correct_answers, timing.
Creative freedom surfaces: theme, room_labels, object_labels, narrative_text,
feedback_style.
"""


def main() -> None:
    out_dir = Path(__file__).parent
    spec = ExperimentSpec.model_validate(dict(SPEC))
    bundle = build_bundle(spec, generated_at=FIXED_GENERATED_AT)
    gamespec = build_gamespec(bundle)

    result = validate_game(gamespec, bundle)
    if not result.valid:
        for issue in result.errors:
            print(f"{issue.error_code} @ {issue.path}: {issue.message}", file=sys.stderr)
        raise SystemExit("fixture gamespec is invalid — refusing to write")

    (out_dir / "spec.json").write_text(json.dumps(SPEC, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out_dir / "bundle.json").write_text(canonical_json(bundle) + "\n", encoding="utf-8")
    (out_dir / "gamespec.json").write_text(json.dumps(gamespec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out_dir / "README.md").write_text(README, encoding="utf-8")
    trials = bundle["trials"]  # type: ignore[index]
    print(f"fixture written: {len(trials)} trials, "  # type: ignore[arg-type]
          f"bundle_sha256={bundle['bundle_sha256'][:12]}..., "
          f"encounters={len(ENCOUNTER_IDS)}")


if __name__ == "__main__":
    main()
