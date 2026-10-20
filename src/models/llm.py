"""LLM 交互共享模型（契约 §1.0）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ToolCallRequest(BaseModel):
    """LLM 返回的一次工具调用（统一结构，隔离供应商格式）。"""

    remote_id: str  # 供应商侧 ID（OpenAI tool_call.id；FakeLLM 自造如 "fake-0"）
    tool_name: str
    arguments: dict[str, object] = Field(default_factory=dict)


class LLMResponse(BaseModel):
    """LLMClient.chat 的统一返回。"""

    content: str = ""  # 模型文本（内部推理——不写入任何事件/JSONL，ADR-006）
    tool_calls: list[ToolCallRequest] = Field(default_factory=list)
    finish_reason: str = "stop"  # "tool_calls" | "stop" | 其他供应商值
