"""Read recent event snapshots for the desktop UI."""

from __future__ import annotations

from pathlib import Path

from app.services.event_store import EventStore


class EventSnapshotReader:
    def __init__(self, root_dir: Path | str):
        self._root_dir = Path(root_dir)

    def get_recent_events(self, pool: str, agent_id: str | None = None, limit: int = 20) -> list[dict]:
        pool_event_dir = self._root_dir / "events"
        if not pool_event_dir.exists():
            return []

        store = EventStore(pool_event_dir)
        return store.get_events(agent_id=agent_id, limit=limit)
