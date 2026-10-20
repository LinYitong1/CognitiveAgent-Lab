"""LLMClient（openai SDK 封装）与 LLMClientProtocol（FakeLLM 替换点，契约 §1.1）。"""

from __future__ import annotations

import json
from typing import Any, Protocol, cast

from openai import AsyncOpenAI

from src.config import Settings
from src.models.llm import LLMResponse, ToolCallRequest

Message = dict[str, Any]  # OpenAI chat 消息 JSON 格式（system / user / assistant(tool_calls) / tool）


class LLMProtocolError(Exception):
    """供应商响应不符合协议（如 tool_call 参数非合法 JSON）——不可恢复，任务 failed。"""


class LLMClientProtocol(Protocol):
    """AgentLoop 的依赖类型（鸭子类型：任何实现该签名的对象可注入——FakeLLM 替换点）。"""

    async def chat(self, messages: list[Message], tools: list[dict[str, Any]]) -> LLMResponse: ...


class LLMClient:
    """openai.AsyncOpenAI 封装，实现 LLMClientProtocol。"""

    def __init__(self, settings: Settings, timeout: float = 60.0, max_retries: int = 2) -> None:
        """key 为空时不在构造期抛错——由调用方（run_agent / M2 服务层）显式校验。

        timeout 与 max_retries 透传给 SDK（网络错误/超时重试由 openai SDK 承担）。
        """
        self._model = settings.llm_model
        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.llm_base_url or None,  # 兼容端点切换（ADR-002）
            timeout=timeout,
            max_retries=max_retries,
        )

    async def chat(self, messages: list[Message], tools: list[dict[str, Any]]) -> LLMResponse:
        """调用 chat.completions.create 并转为统一 LLMResponse。

        - tool_call 参数 JSON 解析失败 → LLMProtocolError（loop 视为不可恢复）；
        - SDK 重试耗尽后抛出的异常原样上抛，由 loop 捕获终止。
        """
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=cast(Any, messages),
            tools=cast(Any, tools),
        )
        choice = response.choices[0]
        tool_calls: list[ToolCallRequest] = []
        for native in choice.message.tool_calls or []:
            if native.type != "function" or native.function is None:
                raise LLMProtocolError(f"unsupported tool_call type: {native.type!r}")
            try:
                arguments = json.loads(native.function.arguments or "{}")
            except json.JSONDecodeError as exc:
                raise LLMProtocolError(f"invalid tool arguments JSON: {exc}") from exc
            tool_calls.append(
                ToolCallRequest(
                    remote_id=native.id,
                    tool_name=native.function.name,
                    arguments=arguments,
                )
            )
        return LLMResponse(
            content=choice.message.content or "",
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
        )
