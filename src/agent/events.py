"""EventLog: JSONL event log (contract §1.4; the M1 form of ARCHITECTURE §8 — files only, no DB)."""

from __future__ import annotations

from pathlib import Path

from src.models.events import AgentEvent


class EventLog:
    """Append per event with immediate flush, so events already written survive kill -9 (the basis for M2 recovery)."""

    def __init__(self, task_id: str, log_dir: str | Path = "logs") -> None:
        self._path = Path(log_dir) / f"agent-{task_id}.jsonl"
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            if not self._path.parent.is_dir():
                raise  # the host security agent may wrap a cross-process EEXIST into PermissionError

    @property
    def path(self) -> Path:
        """JSONL file path."""
        return self._path

    def append(self, event: AgentEvent) -> None:
        """Append one JSON line in "a" mode and flush."""
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(event.model_dump_json() + "\n")
            fh.flush()
