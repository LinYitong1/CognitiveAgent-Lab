"""FakeLLM: a duck-typed LLMClientProtocol implementation (contract §3.1; never enters src/)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from src.models.llm import LLMResponse

Message = dict[str, Any]


class FakeLLM:
    """Pops the preset script round by round; records the messages received each round for assertions."""

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
    """chat always raises (simulates SDK retries exhausted)."""

    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, messages: list[Message], tools: list[dict[str, Any]]) -> LLMResponse:
        self.calls += 1
        raise RuntimeError("simulated retries exhausted")
