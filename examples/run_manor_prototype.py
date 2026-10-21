"""M2-D Phase 1 example: render the Manor Case fixture as a playable explore-and-encounter HTML.

Flow (fully deterministic):
  tests/fixtures/manor-case/{bundle.json, gamespec.json} (read-only)
  → validate_game → render_game_html (v2 explore layout via the layout registry)
  → data/m2d-prototype/manor-case.html

Run:
    .venv/bin/python examples/run_manor_prototype.py

Open the game:
    open the output path directly in a browser (file://, no network, no external resources).
    Keyboard only: numbers inspect objects / move between rooms, a/b/c answer encounters,
    x concludes the session once every trial has been consumed.
    Note: browser prototype timing is approximate; not for formal data collection;
    nothing is persisted — export the event log at the end.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.experiment.canonical import sha256_hex
from src.experiment.game_render import render_game_html
from src.experiment.game_schemas import validate_game

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "manor-case"
HTML_REL = "m2d-prototype/manor-case.html"


def main() -> None:
    bundle = json.loads((FIXTURE_DIR / "bundle.json").read_text(encoding="utf-8"))
    game_config = json.loads((FIXTURE_DIR / "gamespec.json").read_text(encoding="utf-8"))

    result = validate_game(game_config, bundle)
    if not result.valid:
        print("GameSpec invalid:")
        for issue in result.errors:
            print(f"  {issue.error_code} @ {issue.path}: {issue.message}")
        raise SystemExit(1)
    assert result.game_spec is not None
    print("gamespec valid : True")

    # render through the public entry point — the v2 layout registry dispatches
    # mechanics.layout=explore-and-encounter to the explore renderer
    html_text = render_game_html(bundle, result.game_spec)

    out_dir = Path(__file__).resolve().parents[1] / "data" / "m2d-prototype"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "manor-case.html"
    target.write_text(html_text, encoding="utf-8")

    print(f"game written   : {target}")
    print(f"trials         : {len(bundle['trials'])}")  # type: ignore[arg-type]
    print(f"html bytes     : {len(html_text.encode('utf-8'))}")
    print(f"html sha256    : {sha256_hex(html_text)}")
    print("\nOpen in a browser (file://). Keys: numbers = inspect/move, a/b/c = answer,")
    print("x = conclude (once all trials are consumed). Single-file, no network.")
    print("Note: prototype timing is approximate; not for formal data collection.")


if __name__ == "__main__":
    main()
