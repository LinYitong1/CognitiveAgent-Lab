"""Experiment combinator registration (contract §5.4, frozen): the M1 three tools + the three experiment tools.

src/agent/__init__.py is not modified — build_registry (M1 assembly) stays untouched;
this function appends the experiment tools to its result.
"""

from __future__ import annotations

from src.agent import build_registry
from src.agent.registry import ToolRegistry
from src.config import Settings
from src.tools import experiment_tools


def build_experiment_registry(settings: Settings) -> ToolRegistry:
    """M1 three tools + experiment three tools (combinator registration: build_registry untouched)."""
    registry = build_registry(settings)
    registry.register(experiment_tools.build_validate_spec(settings))
    registry.register(experiment_tools.build_generate_spec(settings))
    registry.register(experiment_tools.build_export_spec(settings))
    return registry
