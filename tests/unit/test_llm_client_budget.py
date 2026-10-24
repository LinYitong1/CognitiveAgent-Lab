"""LLMClient budget-parameter tests (E1-B preflight, zero paid calls).

The openai SDK client is replaced by an in-process fake; no network request is
ever made. Pins:
  - max_tokens is forwarded to chat.completions.create (and absent when None);
  - the input-byte ceiling refuses BEFORE the request (create never invoked);
  - thought_signature-style provider_extra still round-trips (budget params
    must not disturb the byte-exact history echo);
  - usage extraction (incl. reasoning_tokens detail) unchanged.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import src.agent.llm as llm_module
from src.agent.llm import LLMClient, LLMInputTooLarge
from src.config import Settings


class _FakeCreate:
    """Captures create() kwargs; returns a canned chat-completion response."""

    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.response


def _tool_call_response(extra_content: dict[str, Any] | None = None) -> Any:
    native = SimpleNamespace(
        id="call-1",
        type="function",
        function=SimpleNamespace(name="calc", arguments='{"expression": "1+1"}'),
        model_extra={"extra_content": extra_content} if extra_content is not None else None,
    )
    message = SimpleNamespace(content="", tool_calls=[native])
    choice = SimpleNamespace(message=message, finish_reason="tool_calls")
    usage = SimpleNamespace(
        prompt_tokens=100,
        completion_tokens=20,
        total_tokens=120,
        completion_tokens_details=SimpleNamespace(reasoning_tokens=5),
        prompt_tokens_details=SimpleNamespace(cached_tokens=3),
    )
    return SimpleNamespace(choices=[choice], usage=usage)


def _make_client(monkeypatch: pytest.MonkeyPatch, response: Any, **client_kwargs: Any) -> tuple[LLMClient, _FakeCreate]:
    create = _FakeCreate(response)

    class _FakeAsyncOpenAI:
        def __init__(self, **kwargs: Any) -> None:
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))

    monkeypatch.setattr(llm_module, "AsyncOpenAI", _FakeAsyncOpenAI)
    settings = Settings(openai_api_key="", llm_model="gemini-3.8-flash")
    return LLMClient(settings, **client_kwargs), create


@pytest.mark.asyncio
async def test_max_tokens_forwarded_to_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    client, create = _make_client(monkeypatch, _tool_call_response(), max_tokens=8192)
    await client.chat([{"role": "user", "content": "hi"}], [])
    assert create.calls, "create was not invoked"
    assert create.calls[0]["max_tokens"] == 8192
    assert create.calls[0]["model"] == client._model


@pytest.mark.asyncio
async def test_max_tokens_absent_when_none(monkeypatch: pytest.MonkeyPatch) -> None:
    client, create = _make_client(monkeypatch, _tool_call_response())
    await client.chat([{"role": "user", "content": "hi"}], [])
    assert "max_tokens" not in create.calls[0], (
        "the default request payload must stay byte-identical to the historical behavior"
    )


@pytest.mark.asyncio
async def test_input_ceiling_refuses_before_request(monkeypatch: pytest.MonkeyPatch) -> None:
    client, create = _make_client(monkeypatch, _tool_call_response(), max_input_bytes=128)
    big_messages = [{"role": "user", "content": "x" * 512}]
    with pytest.raises(LLMInputTooLarge):
        await client.chat(big_messages, [])
    assert not create.calls, "the request must NOT reach the SDK when the input ceiling is exceeded"


@pytest.mark.asyncio
async def test_input_ceiling_passes_small_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    client, create = _make_client(monkeypatch, _tool_call_response(), max_input_bytes=64 * 1024)
    await client.chat([{"role": "user", "content": "hi"}], [])
    assert len(create.calls) == 1


@pytest.mark.asyncio
async def test_provider_extra_round_trip_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    signature = {"google": {"thought_signature": "sig-abc"}}
    client, _ = _make_client(
        monkeypatch, _tool_call_response(extra_content=signature), max_tokens=8192
    )
    response = await client.chat([{"role": "user", "content": "hi"}], [])
    assert response.tool_calls[0].provider_extra == signature, (
        "budget parameters must not disturb the thought_signature round trip"
    )


@pytest.mark.asyncio
async def test_usage_extraction_with_details(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _make_client(monkeypatch, _tool_call_response(), max_tokens=1024)
    response = await client.chat([{"role": "user", "content": "hi"}], [])
    assert response.usage == {
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "total_tokens": 120,
        "reasoning_tokens": 5,
        "cached_tokens": 3,
    }
