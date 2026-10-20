"""ToolSpec tool registration declaration (contract §1.2; ARCHITECTURE §6.4).

Placement note: contract §1.2 lists ToolSpec under src/agent/registry.py, but contract §4 forbids
``src/tools/`` importing ``src.agent`` (tool modules building a ToolSpec necessarily need the type),
and §4 rules "shared types always go to src/models/" — so ToolSpec lives in this module (signature unchanged),
and ToolRegistry stays in src/agent/registry.py.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from src.models.tool_result import ToolResult

Idempotency = Literal["idempotent", "non-idempotent"]
RiskLevel = Literal["low", "medium", "high"]


class ToolSpec(BaseModel):
    """Tool registration declaration (idempotency / risk_level required; missing/invalid values fail at construction)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    description: str
    input_model: type[BaseModel]  # parameter validation model (model_json_schema is exported automatically)
    idempotency: Idempotency
    risk_level: RiskLevel
    executor: Callable[[BaseModel], Awaitable[ToolResult]]

    def effective_idempotency(self, args: dict[str, Any]) -> Idempotency:
        """Call-level effective idempotency (ARCHITECTURE §6.4): returns the declared value by default.

        Tools that need per-argument overrides (e.g. http_request GET) subclass and override this method.
        Not consumed by the loop in M1, but must exist and be testable (M2 will snapshot the effective value into the ToolCall table).
        """
        return self.idempotency
