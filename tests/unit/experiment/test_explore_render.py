"""M2-D Phase 1 tests: the explore-and-encounter v2 layout renderer (plan, HTML, dispatch).

Covers the data plane (build_explore_plan invariants), the rendered HTML (structure,
security, determinism, embedded integrity anchors) and the layout dispatch in
render_game_html (v1/classic path untouched; explore layout routed to the v2 renderer).

The interactive state machine itself (navigation, cursor, events) is driven under node
with a DOM stub in test_explore_runtime.py.
"""

from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest

from src.experiment.canonical import sha256_hex
from src.experiment.game_render import render_game_html
from src.experiment.explore_render import build_explore_plan, render_explore_html
from src.experiment.game_schemas import GameSpec, validate_game

PROJECT_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures" / "manor-case"
GOLDEN_BUNDLE_PATH = PROJECT_ROOT / "tests" / "golden" / "generic-2x2-seed7.json"
GOLDEN_HTML_PATH = PROJECT_ROOT / "tests" / "golden" / "game-generic-demo.html"

_TEMPLATE_SCRIPT_TAGS = 2  # one pair for the data block, one for the engine block


def _load_manor() -> tuple[dict[str, object], dict[str, object]]:
    bundle = json.loads((FIXTURE_DIR / "bundle.json").read_text(encoding="utf-8"))
    gamespec = json.loads((FIXTURE_DIR / "gamespec.json").read_text(encoding="utf-8"))
    return bundle, gamespec


def _validated_manor_spec():
    bundle, gamespec = _load_manor()
    result = validate_game(gamespec, bundle)
    assert result.valid is True, result.errors
    assert result.game_spec is not None
    return bundle, result.game_spec


def _render_manor() -> str:
    bundle, game_spec = _validated_manor_spec()
    return render_game_html(bundle, game_spec)


# ---------------------------------------------------------------------------
# Plan invariants (the data plane the engine consumes)
# ---------------------------------------------------------------------------

def test_plan_world_rooms_reachable() -> None:
    """Every room is reachable from start_room (navigation is never a dead end)."""
    bundle, game_spec = _validated_manor_spec()
    plan = build_explore_plan(bundle, game_spec)
    world = cast(dict[str, object], plan["world"])
    rooms = cast(dict[str, object], world["rooms"])
    start = cast(str, world["start_room"])
    assert start in rooms
    seen = {start}
    frontier = [start]
    while frontier:
        room = cast(dict[str, object], rooms[frontier.pop()])
        for target in cast(dict[str, str], room["exits"]):
            assert target in rooms, f"exit target {target!r} missing from world"
            if target not in seen:
                seen.add(target)
                frontier.append(target)
    assert seen == set(rooms), f"unreachable rooms: {set(rooms) - seen}"
    assert len(rooms) >= 2  # the vertical slice requires connected rooms


def test_plan_encounters_match_mapping() -> None:
    """The plan carries the mapping's encounter list verbatim (order, membership)."""
    bundle, gamespec = _load_manor()
    plan = build_explore_plan(bundle, cast(object, validate_game(gamespec, bundle).game_spec))
    mapping = cast(dict[str, object], gamespec["mapping"])
    assert plan["encounters"] == mapping["encounter_objects"]

    world = cast(dict[str, object], plan["world"])
    rooms = cast(dict[str, object], world["rooms"])
    all_objects: dict[str, str] = {}
    for room in cast(dict[str, object], rooms).values():
        for obj in cast(list[object], cast(dict[str, object], room)["objects"]):
            o = cast(dict[str, object], obj)
            all_objects[cast(str, o["object_id"])] = cast(str, o["role"])
    for oid in cast(list[object], plan["encounters"]):
        assert all_objects.get(oid) == "encounter"
    # encounter supply >= trial demand (the G8 shortfall guard's premise)
    assert len(cast(list[object], plan["encounters"])) >= len(cast(list[object], plan["trials"]))


def test_plan_trials_are_bundle_verbatim() -> None:
    """Every plan trial mirrors its bundle trial exactly: index order, verbatim lines,
    conditions, correct answers (from bundle factors), timing."""
    bundle, game_spec = _validated_manor_spec()
    plan = build_explore_plan(bundle, game_spec)
    plan_trials = cast(list[object], plan["trials"])
    bundle_trials = cast(list[object], bundle["trials"])
    assert len(plan_trials) == len(bundle_trials)

    for step_raw, trial_raw in zip(plan_trials, bundle_trials):
        step = cast(dict[str, object], step_raw)
        trial = cast(dict[str, object], trial_raw)
        assert step["index"] == trial["index"]
        assert step["block"] == trial["block"]
        assert step["conditions"] == trial["factors"]
        assert step["timing"] == trial["timing"]
        stimulus = cast(dict[str, object], trial["stimulus"])
        assert step["lines"] == stimulus["lines"]  # VERBATIM, same list, same order
        # correct answers computed only from the bundle's factors
        factors = cast(dict[str, object], trial["factors"])
        correct = cast(dict[str, object], step["correct"])
        assert correct == {"accuse": factors["true_suspect"]}


def test_plan_bindings_come_from_mapping_surface() -> None:
    """Bindings come strictly from the mapping surface (G8 requires it for the
    explore-encounter trigger; the builder has no silent input-surface fallback)."""
    bundle, game_spec = _validated_manor_spec()
    plan = build_explore_plan(bundle, game_spec)
    meta = cast(dict[str, object], plan["meta"])
    assert cast(dict[str, object], meta["bindings"]) == {"accuse": {"a": "a", "b": "b", "c": "c"}}


def test_plan_rejects_non_choice_responses() -> None:
    """Phase 1 supports choice responses only; anything else fails loudly at plan build."""
    bundle, gamespec = _load_manor()
    spec_part = cast(dict[str, object], bundle["spec"])
    spec_part["responses"] = [
        {"name": "accuse", "kind": "rating", "options": None, "scale": [1, 5],
         "correct_from": None}
    ]
    with pytest.raises(ValueError, match="choice responses only"):
        build_explore_plan(bundle, GameSpec.model_validate(gamespec))


def test_plan_rejects_missing_key_binding() -> None:
    """A GameSpec whose mapping declares no bindings (constructible at the schema
    layer; G8 would reject it at validation) is refused at render time too."""
    bundle, gamespec = _load_manor()
    gamespec2 = copy.deepcopy(gamespec)
    cast(dict[str, object], gamespec2["mapping"])["response_bindings"] = []
    with pytest.raises(ValueError, match="no key binding"):
        build_explore_plan(bundle, GameSpec.model_validate(gamespec2))


def test_plan_rejects_unmaterialized_stimulus() -> None:
    """A v1-shaped bundle (no materialized stimulus.lines) cannot drive the explore layout."""
    bundle, gamespec = _load_manor()
    bundle2 = copy.deepcopy(bundle)
    trials = cast(list[object], bundle2["trials"])
    cast(dict[str, object], trials[0]).pop("stimulus")
    with pytest.raises(ValueError, match="stimulus.lines"):
        build_explore_plan(bundle2, GameSpec.model_validate(gamespec))


def test_plan_requires_world_and_mapping() -> None:
    bundle, gamespec = _load_manor()
    gamespec2 = copy.deepcopy(gamespec)
    gamespec2.pop("mapping")
    with pytest.raises(ValueError, match="world and mapping"):
        build_explore_plan(bundle, GameSpec.model_validate(gamespec2))


# ---------------------------------------------------------------------------
# Rendered HTML: structure, security, integrity anchors, determinism
# ---------------------------------------------------------------------------

def _extract_string_literal(html: str, pattern: str) -> str:
    m = re.search(pattern, html)
    assert m is not None, f"pattern not found: {pattern}"
    return cast(str, json.loads('"' + m.group(1) + '"'))


def _extract_plan(html: str) -> dict[str, object]:
    text = _extract_string_literal(html, r'const PLAN = JSON\.parse\("(.*?)(?<!\\)"\);')
    return cast(dict[str, object], json.loads(text))


def test_html_shape_and_mode_distinction() -> None:
    html = _render_manor()
    assert html.startswith("<!DOCTYPE html>")
    assert html.count("<script>") == _TEMPLATE_SCRIPT_TAGS
    assert html.count("</script>") == _TEMPLATE_SCRIPT_TAGS
    assert 'class="theme-neutral-light layout-explore-and-encounter"' in html
    # the exploration/experiment visual distinction is a first-class styling surface
    assert "mode-experiment" in html
    assert "controlled trial" in html  # the trial banner label (engine JS)


def test_html_embedded_plan_matches_builder() -> None:
    bundle, game_spec = _validated_manor_spec()
    html = render_game_html(bundle, game_spec)
    assert _extract_plan(html) == build_explore_plan(bundle, game_spec)


def test_html_embedded_integrity_anchors() -> None:
    bundle, game_spec = _validated_manor_spec()
    html = render_game_html(bundle, game_spec)
    repro = cast(dict[str, object], bundle["reproducibility"])
    trials_text = _extract_string_literal(html, r'const TRIALS_CANONICAL = "(.*?)(?<!\\)";')
    assert sha256_hex(trials_text) == repro["trials_fingerprint"]
    assert json.loads(trials_text) == bundle["trials"]
    bundle_text = _extract_string_literal(html, r'const BUNDLE_CANONICAL = "(.*?)(?<!\\)";')
    assert sha256_hex(bundle_text) == bundle["bundle_sha256"]


def test_html_security_escapes_malicious_text() -> None:
    bundle, gamespec = _load_manor()
    malicious = copy.deepcopy(gamespec)
    scene = cast(dict[str, object], malicious["scene"])
    scene["title"] = "</script><script>alert(1)</script>"
    world = cast(dict[str, object], malicious["world"])
    rooms = cast(dict[str, object], world["rooms"])
    hall = cast(dict[str, object], rooms["hall"])
    objects = cast(list[object], hall["objects"])
    cast(dict[str, object], objects[0])["inspect_text"] = '<img src=x onerror="alert(2)"> "q" \\'
    result = validate_game(malicious, bundle)
    assert result.valid is True, result.errors  # legal presentation text at the schema layer
    assert result.game_spec is not None
    html = render_game_html(bundle, result.game_spec)

    assert html.count("<script>") == _TEMPLATE_SCRIPT_TAGS
    assert "<script>alert" not in html
    assert "&lt;/script&gt;" in html  # title escaped in <title>
    plan = _extract_plan(html)
    world2 = cast(dict[str, object], plan["world"])
    rooms2 = cast(dict[str, object], world2["rooms"])
    hall2 = cast(dict[str, object], rooms2["hall"])
    objects2 = cast(list[object], hall2["objects"])
    assert cast(dict[str, object], plan["meta"])["title"] == "</script><script>alert(1)</script>"
    assert cast(str, cast(dict[str, object], objects2[0])["inspect_text"]).startswith("<img src=x")
    for banned in ("innerHTML", "insertAdjacentHTML", "document.write", "eval("):
        assert banned not in html, f"banned API {banned!r} present in rendered HTML"


def test_render_is_deterministic_and_hashseed_independent() -> None:
    assert _render_manor() == _render_manor()

    snippet = (
        "import json, sys; sys.path.insert(0, '.');\n"
        "from src.experiment.game_schemas import validate_game\n"
        "from src.experiment.game_render import render_game_html\n"
        "from src.experiment.canonical import sha256_hex\n"
        "b = json.load(open('tests/fixtures/manor-case/bundle.json'))\n"
        "g = json.load(open('tests/fixtures/manor-case/gamespec.json'))\n"
        "r = validate_game(g, b)\n"
        "print(sha256_hex(render_game_html(b, r.game_spec)))\n"
    )
    hashes = []
    for seed in ("1", "2"):
        proc = subprocess.run(
            [sys.executable, "-c", snippet],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT),
            env={"PYTHONHASHSEED": seed, "PATH": ""},
            timeout=120,
        )
        assert proc.returncode == 0, proc.stderr
        hashes.append(proc.stdout.strip())
    assert hashes[0] == hashes[1]


def test_genre_vocabulary_absent_from_renderer_source() -> None:
    """Shared runtime logic must not hard-code Manor Case (or any genre) content."""
    source = (PROJECT_ROOT / "src" / "experiment" / "explore_render.py").read_text(
        encoding="utf-8"
    ).lower()
    for token in ("manor", "suspect", "detective", "evidence", "noir", "clue", "mystery"):
        assert token not in source, f"genre word {token!r} hardcoded in explore_render.py"


# ---------------------------------------------------------------------------
# Layout dispatch in render_game_html (legacy compatibility)
# ---------------------------------------------------------------------------

def _demo_v1_spec(bundle: dict[str, object]) -> dict[str, object]:
    """The classic demo GameSpec (mirrors tests/unit/experiment/test_game_render.py)."""
    spec_part = cast(dict[str, object], bundle["spec"])
    repro = cast(dict[str, object], bundle["reproducibility"])
    responses = cast(list[object], spec_part["responses"])
    choice = cast(dict[str, object], next(r for r in responses if cast(dict[str, object], r)["kind"] == "choice"))
    options = cast(list[str], choice["options"])
    return {
        "schema_version": 1,
        "game": {"name": "generic-demo", "version": "0.1.0"},
        "experiment_ref": {
            "name": spec_part["name"],
            "version": spec_part["version"],
            "seed": spec_part["seed"],
            "config_fingerprint": repro["config_fingerprint"],
            "trials_fingerprint": repro["trials_fingerprint"],
            "bundle_sha256": bundle["bundle_sha256"],
        },
        "scene": {
            "title": "Condition Judgement Demo",
            "instructions": "Watch each trial and press the key matching your answer.",
        },
        "input": {
            "modalities": ["keyboard"],
            "bindings": [{"response_name": choice["name"], "keys": {o[:1]: o for o in options}}],
        },
        "feedback": {"on_response": "outcome-text", "duration_ms": 400},
    }


def test_dispatch_v1_golden_html_unchanged() -> None:
    """A v1 spec still renders byte-identically through the classic pipeline (golden)."""
    bundle = json.loads(GOLDEN_BUNDLE_PATH.read_text(encoding="utf-8"))
    result = validate_game(_demo_v1_spec(bundle), bundle)
    assert result.valid is True and result.game_spec is not None
    assert render_game_html(bundle, result.game_spec) == GOLDEN_HTML_PATH.read_text(
        encoding="utf-8"
    )


def test_dispatch_routes_explore_layout_to_v2_renderer() -> None:
    bundle, game_spec = _validated_manor_spec()
    assert render_game_html(bundle, game_spec) == render_explore_html(bundle, game_spec)
    # and the dispatched output IS the explore plan (not the classic steps plan)
    plan = _extract_plan(render_game_html(bundle, game_spec))
    assert "world" in plan
    assert "steps" not in plan


def test_dispatch_v2_sequential_spec_uses_classic_path() -> None:
    """A schema_version 2 spec WITHOUT a registered v2 layout (sequential trigger,
    no mechanics) renders through the unchanged classic pipeline."""
    bundle, gamespec = _load_manor()
    gamespec2 = copy.deepcopy(gamespec)
    for section in ("world", "narrative", "mechanics", "mapping"):
        gamespec2.pop(section)
    result = validate_game(gamespec2, bundle)
    assert result.valid is True, result.errors
    assert result.game_spec is not None
    html = render_game_html(bundle, result.game_spec)
    plan = _extract_plan(html)
    assert "steps" in plan  # classic run-plan structure
    assert "world" not in plan
