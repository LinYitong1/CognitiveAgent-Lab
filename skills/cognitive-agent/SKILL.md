---
name: cognitive-agent
description: Design, validate, and render reproducible game-based cognitive experiments as playable single-file HTML using CognitiveAgent Lab. Use when the user wants to create an experiment design (ExperimentSpec), generate deterministic trial sequences, validate an ExperimentSpec or GameSpec, verify an ExperimentBundle integrity, or turn an experiment into a browser-playable HTML game. Runs fully deterministic — no LLM is invoked by default.
---

# CognitiveAgent Lab — deterministic experiment → game pipeline

CognitiveAgent Lab turns experiment designs into validated, reproducible artifacts:
`ExperimentSpec → deterministic trials → ExperimentBundle (JSON, SHA-256 fingerprinted) → GameSpec → single-file playable HTML`.

Every step is deterministic and independently verifiable. **Do not invoke any LLM** for these workflows — the tools below run the deterministic engine directly (`cognitive-agent run` is the real-LLM path and is experimental; see "Boundaries").

## Installation

Requires Python ≥ 3.13.

```bash
# Install the package from GitHub
python3.13 -m venv .venv && .venv/bin/pip install -U pip
.venv/bin/pip install "cognitive-agent-lab @ git+https://github.com/LinYitong1/CognitiveAgent-Lab.git"

# Sanity check (deterministic, no network, no keys)
.venv/bin/cognitive-agent demo --output demo-out
.venv/bin/cognitive-agent verify demo-out/experiments/demo-agent-game.json   # → exit 0
```

If working inside a clone of the repository instead, use `.venv/bin/pip install -e .` — the CLI and API are identical.

## Workflow 1 — Deterministic end-to-end demo (no LLM)

When the user wants to see the full validated pipeline or a working example game:

```bash
.venv/bin/cognitive-agent demo --output demo-out
```

- Produces `demo-out/experiments/demo-agent-game.json` (24-trial bundle) and
  `demo-out/games/demo-agent-game.html` (playable via `file://`, keyboard input).
- The CLI verifies both artifacts itself: bundle dual-fingerprint check + HTML
  byte-identity with a deterministic re-render. Any failure exits non-zero.
- Open the HTML file in a browser and press any key to start.

## Workflow 2 — Custom experiment without an LLM (Python API)

When the user describes a specific experiment design, build the `ExperimentSpec`
dict yourself and drive the engine directly. Pure functions, no network:

```python
import asyncio, json
from pathlib import Path

from src.config import Settings
from src.experiment.export import build_bundle
from src.experiment.game_render import render_game_html
from src.experiment.game_schemas import validate_game
from src.experiment.schemas import ExperimentSpec
from src.experiment.verify import verify_bundle
from src.tools._sandbox_io import validate_sandbox_path, write_sandbox_file

spec_dict = {
    "schema_version": 1,
    "name": "my-experiment",          # lowercase letters, digits, hyphens
    "version": "0.1.0",
    "seed": 42,                        # same spec + seed → identical trials, always
    "factors": [                       # 1+ factors; levels are plain names
        {"name": "difficulty", "levels": [{"name": "easy"}, {"name": "hard"}]},
    ],
    "blocks": [                        # ≥1 block; trial_count per block
        {"name": "practice", "trial_count": 8},
        {"name": "main", "trial_count": 96},
    ],
    "constraints": {"balance": True},  # all factor-level combos equally frequent
    "responses": [                     # kind: "choice" | "text" | "rating"
        {"name": "answer", "kind": "choice",
         "options": ["easy", "hard"], "correct_from": "difficulty"},
    ],
    "timing": {"fixation_ms": 500, "stimulus_ms": None, "isi_ms": 1000},
}

spec = ExperimentSpec.model_validate(spec_dict)   # raises on schema violations

# 1) Build the deterministic bundle and write it into the output sandbox
bundle = build_bundle(spec)
settings = Settings(data_sandbox_dir="out")       # all artifacts confined to out/
sandbox = Path(settings.data_sandbox_dir)
bundle_path = validate_sandbox_path("experiments/my-experiment.json", sandbox)
write_sandbox_file(bundle_path, json.dumps(bundle).encode("utf-8"))

# 2) Build the GameSpec: copy the six experiment_ref values verbatim from the bundle
repro = bundle["reproducibility"]
game_config = {
    "schema_version": 1,
    "game": {"name": "my-experiment", "version": "0.1.0"},
    "experiment_ref": {
        "name": bundle["spec"]["name"],
        "version": bundle["spec"]["version"],
        "seed": bundle["spec"]["seed"],
        "config_fingerprint": repro["config_fingerprint"],
        "trials_fingerprint": repro["trials_fingerprint"],
        "bundle_sha256": bundle["bundle_sha256"],
    },
    "scene": {
        "title": "My Experiment",
        "instructions": "Press [e] for easy or [h] for hard.",
    },
    "input": {"modalities": ["keyboard"],
              "bindings": [{"response_name": "answer", "keys": {"e": "easy", "h": "hard"}}]},
    "feedback": {"on_response": "outcome-text", "duration_ms": 400},
}

# 3) Validate the GameSpec, then render the playable single-file HTML
result = validate_game(game_config, bundle)
if not result.valid:
    for issue in result.errors:
        print(f"{issue.error_code} @ {issue.path}: {issue.message}")
    raise SystemExit(1)
html = render_game_html(bundle, result.game_spec)
html_path = validate_sandbox_path("games/my-experiment.html", sandbox)
write_sandbox_file(html_path, html.encode("utf-8"))

# 4) Independently verify the bundle (recomputes both fingerprints, no generator)
report = verify_bundle(bundle_path)
assert report.ok, report.detail
print(f"OK: {bundle_path} ({len(bundle['trials'])} trials), {html_path}")
```

Key rules for building specs:

- `experiment_ref` values must be copied **exactly** from the bundle —
  `validate_game` rejects any mismatch (anti-tamper design).
- `correct_from` names a factor whose level equals the correct option
  (for choice responses). Use `null` when there is no objectively correct answer.
- `timing.stimulus_ms: null` means "stimulus stays until response".
- The GameSpec presentation layer can never alter trials, conditions, stimuli,
  or correct answers — those come exclusively from the bundle.

## Workflow 3 — Verify an existing bundle

```bash
.venv/bin/cognitive-agent verify <path/to/bundle.json>   # exit 0 = OK, 1 = invalid
```

`verify_bundle` recomputes the config and trials SHA-256 fingerprints without
the generator — use it whenever the user questions an artifact's integrity.
The rendered HTML also self-checks its embedded fingerprints on load and
refuses to start if they do not match.

## Boundaries

- **Never run `cognitive-agent run` or the async `run_task()` API unless the
  user explicitly asks for the real-LLM path.** Real-LLM end-to-end reliability
  is not yet validated (known issue PA-14); the deterministic paths above are
  the verified ones.
- Generated HTML timing is browser-approximate — **not suitable for formal
  data collection**; say so if the user wants research-grade timing.
- Interaction types are limited to keyboard input (choice / text / rating).
- Keep all generated artifacts inside one output directory
  (`--output` / `Settings(data_sandbox_dir=...)`) and report the final
  artifact paths to the user.
- Always surface validation errors (`error_code @ path: message`) — never
  silently drop an invalid spec or a failed verification.
