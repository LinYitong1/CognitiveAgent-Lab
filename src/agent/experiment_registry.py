"""实验组合注册（契约 §5.4，冻结）：M1 三工具 + 实验三工具。

不改 src/agent/__init__.py——build_registry（M1 组装）零改动，
本函数在其结果上追加注册实验三工具。
"""

from __future__ import annotations

from src.agent import build_registry
from src.agent.registry import ToolRegistry
from src.config import Settings
from src.tools import experiment_tools


def build_experiment_registry(settings: Settings) -> ToolRegistry:
    """M1 三工具 + 实验三工具（组合注册：build_registry 零改动）。"""
    registry = build_registry(settings)
    registry.register(experiment_tools.build_validate_spec(settings))
    registry.register(experiment_tools.build_generate_spec(settings))
    registry.register(experiment_tools.build_export_spec(settings))
    return registry
