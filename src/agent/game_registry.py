"""Game combinator registration (Phase B contract §10/§11): the experiment three tools + validate_game + render_game.

Copies the build_experiment_registry combinator pattern; build_registry (M1 assembly) stays untouched.
"""

from __future__ import annotations

from src.agent import build_registry
from src.agent.registry import ToolRegistry
from src.config import Settings
from src.tools import experiment_tools, game_tools


def build_game_registry(settings: Settings) -> ToolRegistry:
    """M1 three tools + experiment three tools + validate_game + render_game (combinator registration: build_registry untouched)."""
    registry = build_registry(settings)
    registry.register(experiment_tools.build_validate_spec(settings))
    registry.register(experiment_tools.build_generate_spec(settings))
    registry.register(experiment_tools.build_export_spec(settings))
    registry.register(game_tools.build_validate_game_spec(settings))
    registry.register(game_tools.build_render_game_spec(settings))
    return registry
