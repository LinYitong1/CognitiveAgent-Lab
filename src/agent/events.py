"""EventLog：JSONL 事件日志（契约 §1.4；ARCHITECTURE §8 的 M1 形态，无 DB 仅文件）。"""

from __future__ import annotations

from pathlib import Path

from src.models.events import AgentEvent


class EventLog:
    """逐事件追加 + 即时 flush，保证 kill -9 后已写事件不丢（M2 断点恢复基础）。"""

    def __init__(self, task_id: str, log_dir: str | Path = "logs") -> None:
        self._path = Path(log_dir) / f"agent-{task_id}.jsonl"
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            if not self._path.parent.is_dir():
                raise  # 宿主安全代理可能把跨进程已存在目录的 EEXIST 包成 PermissionError

    @property
    def path(self) -> Path:
        """JSONL 文件路径。"""
        return self._path

    def append(self, event: AgentEvent) -> None:
        """以 "a" 模式追加单条 JSON 行并 flush。"""
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(event.model_dump_json() + "\n")
            fh.flush()
