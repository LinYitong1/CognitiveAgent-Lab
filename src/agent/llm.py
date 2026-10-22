"""LLMClient (openai SDK wrapper) and LLMClientProtocol (the FakeLLM swap point, contract §1.1)."""

from __future__ import annotations

import json
from typing import Any, Protocol, cast

from openai import AsyncOpenAI

from src.config import Settings
from src.models.llm import LLMResponse, ToolCallRequest

Message = dict[str, Any]  # OpenAI chat message JSON shape (system / user / assistant(tool_calls) / tool)


class LLMProtocolError(Exception):
    """Provider response violates the protocol (e.g. tool_call arguments not valid JSON) — unrecoverable, task failed."""


class LLMClientProtocol(Protocol):
    """Dependency type of AgentLoop (duck typing: any object implementing this signature can be injected — the FakeLLM swap point)."""

    async def chat(self, messages: list[Message], tools: list[dict[str, Any]]) -> LLMResponse: ...


class LLMClient:
    """openai.AsyncOpenAI wrapper implementing LLMClientProtocol."""

    def __init__(self, settings: Settings, timeout: float = 60.0, max_retries: int = 2) -> None:
        """An empty key does not raise at construction — callers (run_agent / the M2 service layer) check explicitly.

        timeout and max_retries are passed through to the SDK (network error/timeout retries handled by the openai SDK).
        """
        self._model = settings.llm_model
        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.llm_base_url or None,  # compatible-endpoint switching (ADR-002)
            timeout=timeout,
            max_retries=max_retries,
        )

    async def chat(self, messages: list[Message], tools: list[dict[str, Any]]) -> LLMResponse:
        """Call chat.completions.create and convert to the unified LLMResponse.

        - tool_call arguments failing JSON parse → LLMProtocolError (treated as unrecoverable by the loop);
        - exceptions raised by the SDK after retries are exhausted propagate as-is; the loop catches them and terminates.
        """
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=cast(Any, messages),
            tools=cast(Any, tools),
        )
        choice = response.choices[0]
        usage_obj = getattr(response, "usage", None)
        usage: dict[str, int] | None = None
        if usage_obj is not None:
            usage = {
                "prompt_tokens": int(getattr(usage_obj, "prompt_tokens", 0) or 0),
                "completion_tokens": int(getattr(usage_obj, "completion_tokens", 0) or 0),
                "total_tokens": int(getattr(usage_obj, "total_tokens", 0) or 0),
            }
            # provider detail fields when present (observability only)
            comp_details = getattr(usage_obj, "completion_tokens_details", None)
            if comp_details is not None:
                reasoning = getattr(comp_details, "reasoning_tokens", None)
                if reasoning is not None:
                    usage["reasoning_tokens"] = int(reasoning)
            prompt_details = getattr(usage_obj, "prompt_tokens_details", None)
            if prompt_details is not None:
                cached = getattr(prompt_details, "cached_tokens", None)
                if cached is not None:
                    usage["cached_tokens"] = int(cached)
        tool_calls: list[ToolCallRequest] = []
        for native in choice.message.tool_calls or []:
            if native.type != "function" or native.function is None:
                raise LLMProtocolError(f"unsupported tool_call type: {native.type!r}")
            try:
                arguments = json.loads(native.function.arguments or "{}")
            except json.JSONDecodeError as exc:
                raise LLMProtocolError(f"invalid tool arguments JSON: {exc}") from exc
            # capture opaque provider extensions (e.g. Gemini 3.x thought_signature in
            # extra_content.google) so the loop can round-trip them in the history;
            # providers without such fields yield None and behave exactly as before
            extra = getattr(native, "model_extra", None) or {}
            provider_extra = cast("dict[str, object] | None", extra.get("extra_content"))
            tool_calls.append(
                ToolCallRequest(
                    remote_id=native.id,
                    tool_name=native.function.name,
                    arguments=arguments,
                    provider_extra=provider_extra,
                )
            )
        return LLMResponse(
            content=choice.message.content or "",
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
            usage=usage,
        )
