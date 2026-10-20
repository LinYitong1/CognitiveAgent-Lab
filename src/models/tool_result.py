"""工具执行统一返回（契约 §1.0；工具异常不抛出到 loop 外，M1-3）。"""

from __future__ import annotations

from pydantic import BaseModel


class ToolResult(BaseModel):
    """工具执行结果。"""

    ok: bool
    result: str = ""  # 成功时的结果文本（回传 LLM）
    error: str = ""  # 失败原因（回传 LLM）；安全拒绝统一前缀 "BLOCKED: "
