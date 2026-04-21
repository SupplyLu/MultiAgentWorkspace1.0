from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path



def get_file_mtime(file_path: str | Path) -> datetime:
    path = Path(file_path)
    return datetime.fromtimestamp(path.stat().st_mtime)



def is_stale(last_seen_at: datetime | None, timeout_seconds: float, now: datetime | None = None) -> bool:
    if last_seen_at is None:
        return True
    current = now or datetime.utcnow()
    return current - last_seen_at > timedelta(seconds=timeout_seconds)



def is_file_idle(file_path: str | Path, timeout_seconds: float, now: datetime | None = None) -> bool:
    return is_stale(get_file_mtime(file_path), timeout_seconds, now=now)



def seconds_since_file_update(file_path: str | Path, now: datetime | None = None) -> float:
    current = now or datetime.utcnow()
    return (current - get_file_mtime(file_path)).total_seconds()
