"""游戏组合注册（Phase B 契约 §10）：实验三工具 + validate_game。

复制 build_experiment_registry 组合模式；build_registry（M1 组装）零改动。
"""

from __future__ import annotations

from src.agent import build_registry
from src.agent.registry import ToolRegistry
from src.config import Settings
from src.tools import experiment_tools, game_tools


def build_game_registry(settings: Settings) -> ToolRegistry:
    """M1 三工具 + 实验三工具 + validate_game（组合注册：build_registry 零改动）。"""
    registry = build_registry(settings)
    registry.register(experiment_tools.build_validate_spec(settings))
    registry.register(experiment_tools.build_generate_spec(settings))
    registry.register(experiment_tools.build_export_spec(settings))
    registry.register(game_tools.build_validate_game_spec(settings))
    return registry
