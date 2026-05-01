from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
import json

from app.shared.json_store import JSONStore


@dataclass
class LifecycleEvent:
    """生命周期事件记录"""

    timestamp: str
    agent_id: str
    task_id: str
    signal: str
    feature_id: str = ""
    role: str = ""
    pool: str = ""
    message: str = ""
    artifact_root: str = ""
    source: str = ""
    pid: int = 0
    from_state: str = ""
    to_state: str = ""
    is_terminal: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in asdict(self).items()
            if value not in ("", {}) and value is not False
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "LifecycleEvent":
        return LifecycleEvent(**data)


class EventStore:
    """Append-only 事件存储"""

    def __init__(self, store_dir: Path | str, index_limit: int = 1000):
        self._store_dir = Path(store_dir)
        self._store_dir.mkdir(parents=True, exist_ok=True)
        self._index_limit = index_limit
        self._index_store = JSONStore(
            self._store_dir / "events_index.json",
            default_factory=lambda: {"events": []},
        )
        self._ensure_index()

    def _ensure_index(self):
        self._index_store.ensure_initialized()

    def append(self, event: LifecycleEvent) -> dict[str, Any]:
        """追加事件，返回事件记录"""
        record = event.to_dict()

        ts_safe = event.timestamp.replace(":", "-").replace(".", "-")
        event_file = self._store_dir / f"evt_{ts_safe}_{event.agent_id}_{event.signal}.json"

        JSONStore(
            event_file,
            default_factory=lambda: record,
        ).write(record)

        def update_index(idx: dict) -> dict:
            events = idx.get("events", [])
            events.append({
                "file": str(event_file),
                "timestamp": event.timestamp,
                "agent_id": event.agent_id,
                "task_id": event.task_id,
                "signal": event.signal,
            })
            # Enforce index limit
            if len(events) > self._index_limit:
                events = events[-self._index_limit:]
            return {**idx, "events": events}

        self._index_store.update(update_index)

        return record

    def get_events(
        self,
        agent_id: str | None = None,
        task_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """查询事件"""
        index = self._index_store.read()
        events = index.get("events", [])

        if agent_id:
            events = [event for event in events if event.get("agent_id") == agent_id]
        if task_id:
            events = [event for event in events if event.get("task_id") == task_id]

        events = events[-limit:]

        result: list[dict[str, Any]] = []
        for event in events:
            try:
                with open(event["file"], encoding="utf-8") as f:
                    result.append(json.load(f))
            except (OSError, json.JSONDecodeError):
                continue

        return result

    def get_index_stats(self) -> dict[str, int]:
        """Return simple index health stats."""
        index = self._index_store.read()
        events = index.get("events", [])
        corrupt_files = 0

        for event in events:
            try:
                with open(event["file"], encoding="utf-8") as f:
                    json.load(f)
            except (OSError, json.JSONDecodeError):
                corrupt_files += 1

        return {
            "total_events": len(events),
            "corrupt_files": corrupt_files,
        }

    def get_current_state(self, agent_id: str, task_id: str | None = None) -> str | None:
        """获取指定 agent/task 最近一次事件后的状态"""
        events = self.get_events(agent_id=agent_id, task_id=task_id, limit=10)
        if not events:
            return None
        last = events[-1]
        return last.get("to_state")
