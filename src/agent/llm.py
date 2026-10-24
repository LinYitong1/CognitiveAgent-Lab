"""LLMClient (openai SDK wrapper) and LLMClientProtocol (the FakeLLM swap point, contract §1.1)."""

from __future__ import annotations

import json
from typing import Any, Protocol, cast

from openai import AsyncOpenAI

from src.config import Settings
from src.models.llm import LLMResponse, ToolCallRequest

Message = dict[str, Any]  # OpenAI chat message JSON shape (system / user / assistant(tool_calls) / tool)

# E1-B budget support: a per-call output-token ceiling and a per-request input
# byte ceiling. Both default to None (= the historical behavior, byte-identical
# request payloads); when set, the per-call worst-case cost becomes bounded
# pre-call (input bytes + max output tokens), which is what lets the E1 run
# protocol state a genuine per-call cost bound instead of relying only on the
# request-count cap.
DEFAULT_E1_MAX_TOKENS = 8192
DEFAULT_E1_MAX_INPUT_BYTES = 96 * 1024


class LLMProtocolError(Exception):
    """Provider response violates the protocol (e.g. tool_call arguments not valid JSON) — unrecoverable, task failed."""


class LLMInputTooLarge(Exception):
    """Serialized request payload exceeds the configured input ceiling — refused BEFORE any network call."""


class LLMClientProtocol(Protocol):
    """Dependency type of AgentLoop (duck typing: any object implementing this signature can be injected — the FakeLLM swap point)."""

    async def chat(self, messages: list[Message], tools: list[dict[str, Any]]) -> LLMResponse: ...


class LLMClient:
    """openai.AsyncOpenAI wrapper implementing LLMClientProtocol."""

    def __init__(
        self,
        settings: Settings,
        timeout: float = 60.0,
        max_retries: int = 2,
        max_tokens: int | None = None,
        max_input_bytes: int | None = None,
    ) -> None:
        """An empty key does not raise at construction — callers (run_agent / the M2 service layer) check explicitly.

        timeout and max_retries are passed through to the SDK (network error/timeout retries handled by the openai SDK).
        max_tokens (output-token ceiling) and max_input_bytes (request-payload ceiling) are
        budget guards for authorized evaluation runs; both default to None (absent from the
        request payload — historically byte-identical requests).
        """
        self._model = settings.llm_model
        self._max_tokens = max_tokens
        self._max_input_bytes = max_input_bytes
        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.llm_base_url or None,  # compatible-endpoint switching (ADR-002)
            timeout=timeout,
            max_retries=max_retries,
        )

    def _request_payload_bytes(self, messages: list[Message], tools: list[dict[str, Any]]) -> int:
        try:
            return len(json.dumps({"messages": messages, "tools": tools},
                                  ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        except (TypeError, ValueError):
            return 0  # non-serializable payloads fail in the SDK anyway; never refuse for this reason

    async def chat(self, messages: list[Message], tools: list[dict[str, Any]]) -> LLMResponse:
        """Call chat.completions.create and convert to the unified LLMResponse.

        - payload over max_input_bytes → LLMInputTooLarge (raised BEFORE the request;
          the loop treats it as an unrecoverable failure — a budget stop, not a retry);
        - tool_call arguments failing JSON parse → LLMProtocolError (treated as unrecoverable by the loop);
        - exceptions raised by the SDK after retries are exhausted propagate as-is; the loop catches them and terminates.
        """
        if self._max_input_bytes is not None:
            if self._request_payload_bytes(messages, tools) > self._max_input_bytes:
                raise LLMInputTooLarge(
                    f"request payload exceeds the configured input ceiling "
                    f"({self._max_input_bytes} bytes); refusing before the call"
                )
        kwargs: dict[str, Any] = {}
        if self._max_tokens is not None:
            kwargs["max_tokens"] = self._max_tokens
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=cast(Any, messages),
            tools=cast(Any, tools),
            **kwargs,
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
