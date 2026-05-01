"""Persistent default timeout store for execution pools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.shared.json_store import JSONStore


DEFAULT_TIMEOUTS: dict[str, int] = {
    "work": 300,
    "thinking": 1800,
    "construct": 1800,
    "gate": 600,
    "package": 1800,
}

MIN_TIMEOUT_SECONDS = 60
MAX_TIMEOUT_SECONDS = 86400


class TimeoutDefaultsStore:
    """Manages persistent default timeout settings for execution pools."""

    def __init__(self, root_dir: Path | str):
        self._root_dir = Path(root_dir)
        self._config_file = self._root_dir / "runtime" / "state" / "pool_timeout_config.json"
        self._store = JSONStore(
            self._config_file,
            default_factory=lambda: dict(DEFAULT_TIMEOUTS),
        )
        self._store.ensure_initialized()

    def get(self, pool: str) -> int:
        pool_name = self._validate_pool(pool)
        data = self._store.read()
        if not isinstance(data, dict):
            return DEFAULT_TIMEOUTS[pool_name]
        return self._normalize_timeout(data.get(pool_name), fallback=DEFAULT_TIMEOUTS[pool_name])

    def get_all(self) -> dict[str, int]:
        data = self._store.read()
        if not isinstance(data, dict):
            return dict(DEFAULT_TIMEOUTS)
        result = dict(DEFAULT_TIMEOUTS)
        for pool, default_value in DEFAULT_TIMEOUTS.items():
            result[pool] = self._normalize_timeout(data.get(pool), fallback=default_value)
        return result

    def set(self, pool: str, seconds: int) -> None:
        pool_name = self._validate_pool(pool)
        normalized_seconds = self._normalize_timeout(seconds, fallback=DEFAULT_TIMEOUTS[pool_name])

        def updater(data: dict[str, Any]) -> dict[str, Any]:
            if not isinstance(data, dict):
                data = dict(DEFAULT_TIMEOUTS)
            data[pool_name] = normalized_seconds
            return data

        self._store.update(updater)

    def _validate_pool(self, pool: str) -> str:
        if pool not in DEFAULT_TIMEOUTS:
            raise ValueError(f"Unsupported timeout pool: {pool}")
        return pool

    @staticmethod
    def _normalize_timeout(value: Any, fallback: int) -> int:
        try:
            timeout_seconds = int(value)
        except (TypeError, ValueError):
            timeout_seconds = fallback
        if timeout_seconds < MIN_TIMEOUT_SECONDS:
            return MIN_TIMEOUT_SECONDS
        if timeout_seconds > MAX_TIMEOUT_SECONDS:
            return MAX_TIMEOUT_SECONDS
        return timeout_seconds
