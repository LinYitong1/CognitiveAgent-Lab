"""AgentLoop 主循环：plan → act → observe（契约 §1.3；ARCHITECTURE §4）。"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from src.agent.events import EventLog
from src.agent.llm import LLMClientProtocol, Message
from src.agent.registry import ToolRegistry
from src.config import Settings
from src.models.agent_result import AgentResult
from src.models.events import AgentEvent, AgentEventType

_SYSTEM_PROMPT = (
    "你是多步任务执行 Agent。可用工具以 tools 参数提供。需要外部能力时调用工具。"
    "工具失败时会收到 ERROR: 前缀的 tool 结果，应换参数重试或改变策略。"
    "目标达成后直接给出最终答案文本、不再调用工具。"
)

_SUMMARY_LIMIT = 512


class AgentLoop:
    """单任务主循环（M1：无持久化、无恢复语义，事件落 JSONL）。"""

    def __init__(
        self,
        client: LLMClientProtocol,
        registry: ToolRegistry,
        settings: Settings,
        on_event: Callable[[AgentEvent], None] | None = None,
        task_id: str | None = None,
    ) -> None:
        """task_id 可由调用方（CLI）预生成，保证 stdout 提前打印与事件文件同名。"""
        self._client = client
        self._registry = registry
        self._settings = settings
        self._on_event = on_event
        self._task_id = task_id if task_id is not None else f"task-{uuid4().hex[:12]}"

    async def run_task(self, goal: str) -> AgentResult:
        """执行任务，返回完整结果（事件先落 JSONL 再继续）。"""
        log = EventLog(self._task_id)
        events: list[AgentEvent] = []
        seq = 0

        def emit(event_type: AgentEventType, payload: dict[str, object]) -> AgentEvent:
            nonlocal seq
            seq += 1
            event = AgentEvent(
                type=event_type,
                seq=seq,
                ts=datetime.now(timezone.utc),
                payload=payload,
            )
            log.append(event)  # 事件先落盘再继续（契约 §1.3.6）
            events.append(event)
            if self._on_event is not None:
                self._on_event(event)
            return event

        emit(AgentEventType.status, {"status": "running", "reason": "task started"})

        messages: list[Message] = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": goal},
        ]
        steps = 0
        status = "completed"
        result_text = ""

        while True:
            if steps >= self._settings.calc_agent_max_steps:
                status = "failed"
                result_text = "max steps exceeded"
                emit(AgentEventType.error, {"message": "max steps exceeded"})
                break
            try:
                response = await self._client.chat(messages, self._registry.get_schemas())
            except (AssertionError, KeyboardInterrupt, SystemExit):
                # 测试断言与中断信号穿透，不被吞成 failed
                raise
            except Exception as exc:  # 重试耗尽 / LLMProtocolError → 不可恢复
                status = "failed"
                result_text = f"llm error: {type(exc).__name__}: {exc}"
                emit(AgentEventType.error, {"message": result_text[:_SUMMARY_LIMIT]})
                break

            steps += 1

            if not response.tool_calls:
                # 模型给出最终答案；content 不产出任何事件（ADR-006）
                status = "completed"
                result_text = response.content
                break

            native_calls: list[dict[str, Any]] = [
                {
                    "id": call.remote_id,
                    "type": "function",
                    "function": {
                        "name": call.tool_name,
                        "arguments": json.dumps(call.arguments, ensure_ascii=False),
                    },
                }
                for call in response.tool_calls
            ]
            messages.append(
                {"role": "assistant", "content": response.content, "tool_calls": native_calls}
            )

            for call in response.tool_calls:
                # tool_call_id = 该 tool_call 事件的 seq（契约 §1.3.2，事件序号方案）
                next_seq = seq + 1
                tool_call_id = f"call_{next_seq:04d}"
                args_summary = json.dumps(call.arguments, ensure_ascii=False)
                emit(
                    AgentEventType.tool_call,
                    {
                        "tool_call_id": tool_call_id,
                        "tool_name": call.tool_name,
                        "args_summary": args_summary[:_SUMMARY_LIMIT],
                    },
                )
                tool_result = await self._registry.execute(call.tool_name, call.arguments)
                summary = tool_result.result if tool_result.ok else tool_result.error
                emit(
                    AgentEventType.tool_result,
                    {
                        "tool_call_id": tool_call_id,
                        "ok": tool_result.ok,
                        "result_summary": summary[:_SUMMARY_LIMIT],
                    },
                )
                tool_content = (
                    tool_result.result if tool_result.ok else f"ERROR: {tool_result.error}"
                )
                messages.append(
                    {"role": "tool", "tool_call_id": call.remote_id, "content": tool_content}
                )

        # final 必发（任何终止路径）
        emit(
            AgentEventType.final,
            {"status": status, "result_summary": result_text[:_SUMMARY_LIMIT]},
        )
        return AgentResult(
            task_id=self._task_id,
            status=status,
            result=result_text,
            steps=steps,
            events=events,
        )
