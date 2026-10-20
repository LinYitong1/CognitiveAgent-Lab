"""B2 最小示例：从零生成一个可直接打开的可玩 HTML 游戏（无 LLM）。

流程（全部确定性）：
  ExperimentSpec → ExperimentBundle（写盘 data/ 沙箱）
  → GameSpec（validate_game 通过）→ render_game_html → data/games/example-game.html

运行：
    .venv/bin/python examples/run_game_render.py

打开游戏：
    用浏览器直接打开输出路径（file:// 直开，无网络、无外部资源）。
    提示：浏览器原型计时为近似值，不用于正式数据收集。

示例刻意通用：因素/水平/响应均为占位语义（item 的 red/blue 判断），
不绑定任何认知实验范式。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import Settings
from src.experiment.export import build_bundle
from src.experiment.game_render import render_game_html
from src.experiment.game_schemas import validate_game
from src.experiment.schemas import ExperimentSpec
from src.tools._sandbox_io import validate_sandbox_path, write_sandbox_file

BUNDLE_REL = "experiments/example-game.json"
HTML_REL = "games/example-game.html"

DEMO_SPEC: dict[str, object] = {
    "schema_version": 1,
    "name": "example-game",
    "version": "0.1.0",
    "seed": 7,
    "factors": [
        {"name": "item", "levels": [{"name": "red"}, {"name": "blue"}]},
    ],
    "blocks": [
        {"name": "practice", "trial_count": 4},
        {"name": "main", "trial_count": 20},
    ],
    "constraints": {"balance": True},
    "responses": [
        {"name": "pick", "kind": "choice", "options": ["red", "blue"],
         "correct_from": "item"}
    ],
    "timing": {"fixation_ms": 400, "stimulus_ms": None, "isi_ms": 800},
}


def main() -> None:
    settings = Settings()
    sandbox = Path(settings.data_sandbox_dir)

    # 1. 生成 ExperimentBundle 并写入 data/ 沙箱
    bundle = build_bundle(ExperimentSpec.model_validate(DEMO_SPEC))
    bundle_target = validate_sandbox_path(BUNDLE_REL, sandbox)
    write_sandbox_file(bundle_target, json.dumps(bundle).encode("utf-8"))
    print(f"bundle written : {bundle_target}")

    # 2. 构造 GameSpec（六项引用直接复制 bundle 实际值）并校验
    spec_part = bundle["spec"]  # type: ignore[index]
    repro = bundle["reproducibility"]  # type: ignore[index]
    game_config: dict[str, object] = {
        "schema_version": 1,
        "game": {"name": "example-game", "version": "0.1.0"},
        "experiment_ref": {
            "name": spec_part["name"],  # type: ignore[index]
            "version": spec_part["version"],  # type: ignore[index]
            "seed": spec_part["seed"],  # type: ignore[index]
            "config_fingerprint": repro["config_fingerprint"],  # type: ignore[index]
            "trials_fingerprint": repro["trials_fingerprint"],  # type: ignore[index]
            "bundle_sha256": bundle["bundle_sha256"],
        },
        "scene": {
            "title": "Item Judgement Game",
            "instructions": (
                "Each trial shows an item color. Press [r] for red or [b] for blue."
            ),
        },
        "input": {
            "modalities": ["keyboard"],
            "bindings": [{"response_name": "pick", "keys": {"r": "red", "b": "blue"}}],
        },
        "feedback": {"on_response": "outcome-text", "duration_ms": 400},
    }
    result = validate_game(game_config, bundle)
    if not result.valid:
        print("GameSpec invalid:")
        for issue in result.errors:
            print(f"  {issue.error_code} @ {issue.path}: {issue.message}")
        raise SystemExit(1)
    assert result.game_spec is not None
    print("gamespec valid : True")

    # 3. 渲染可玩 HTML 并写入 data/ 沙箱
    html = render_game_html(bundle, result.game_spec)
    html_target = validate_sandbox_path(HTML_REL, sandbox)
    write_sandbox_file(html_target, html.encode("utf-8"))
    print(f"game written   : {html_target}")
    print(f"trials         : {len(bundle['trials'])}")  # type: ignore[arg-type]
    print(f"html bytes     : {len(html.encode('utf-8'))}")
    print("\nOpen in a browser (file://) and press any key to start.")
    print("Note: prototype timing is approximate; not for formal data collection.")


if __name__ == "__main__":
    main()
