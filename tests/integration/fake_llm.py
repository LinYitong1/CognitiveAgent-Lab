"""FakeLLM：LLMClientProtocol 的鸭子类型实现（契约 §3.1，不进 src/）。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from src.models.llm import LLMResponse

Message = dict[str, Any]


class FakeLLM:
    """按轮次弹出预设脚本，记录每轮收到的 messages 供断言。"""

    def __init__(self, script: Sequence[LLMResponse]) -> None:
        self._script: list[LLMResponse] = list(script)
        self.received_messages: list[list[Message]] = []
        self.calls = 0

    async def chat(self, messages: list[Message], tools: list[dict[str, Any]]) -> LLMResponse:
        self.received_messages.append([dict(m) for m in messages])
        self.calls += 1
        if self.calls > len(self._script):
            raise AssertionError("FakeLLM script exhausted")
        return self._script[self.calls - 1]


class ExplodingLLM:
    """chat 恒抛异常（模拟 SDK 重试耗尽）。"""

    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, messages: list[Message], tools: list[dict[str, Any]]) -> LLMResponse:
        self.calls += 1
        raise RuntimeError("simulated retries exhausted")
