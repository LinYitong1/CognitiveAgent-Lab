"""Agent 任务结果模型（契约 §1.0）。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.models.events import AgentEvent


class AgentResult(BaseModel):
    """run_task 的返回。"""

    task_id: str
    status: str  # "completed" | "failed"
    result: str  # 最终答案（completed）或失败原因（failed）
    steps: int  # 实际消耗的 LLM 调用轮数
    events: list[AgentEvent] = Field(default_factory=list)  # 完整事件序列（与 JSONL 一致）
