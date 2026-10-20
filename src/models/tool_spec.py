"""ToolSpec 工具注册声明（契约 §1.2；ARCHITECTURE §6.4）。

位置说明：契约 §1.2 将 ToolSpec 列于 src/agent/registry.py，但契约 §4 禁止
``src/tools/`` import ``src.agent``（工具模块构造 ToolSpec 必然需要该类型），
且 §4 规定"共享类型一律走 src/models/"——故 ToolSpec 落位于本模块（签名不变），
ToolRegistry 仍在 src/agent/registry.py。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from src.models.tool_result import ToolResult

Idempotency = Literal["idempotent", "non-idempotent"]
RiskLevel = Literal["low", "medium", "high"]


class ToolSpec(BaseModel):
    """工具注册声明（idempotency / risk_level 必填，缺失/非法值构造期即失败）。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    description: str
    input_model: type[BaseModel]  # 参数校验模型（model_json_schema 自动导出）
    idempotency: Idempotency
    risk_level: RiskLevel
    executor: Callable[[BaseModel], Awaitable[ToolResult]]

    def effective_idempotency(self, args: dict[str, Any]) -> Idempotency:
        """调用级有效幂等性（ARCHITECTURE §6.4）：默认返回声明值。

        需要按参数覆写的工具（如 http_request 的 GET）子类化本类并覆写本方法。
        M1 不被 loop 消费，但必须实现并可测（M2 将把生效值快照进 ToolCall 表）。
        """
        return self.idempotency
