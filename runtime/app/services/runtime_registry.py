"""Runtime Registry - tracks running pool runtimes with PID and port info."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from filelock import Timeout

from app.shared.json_store import JSONStore


class RuntimeRegistry:
    """Registry for tracking running pool runtimes with their PID and port information.

    Uses JSONStore for cross-process safe reads and writes so all registry access
    follows the same lock and atomic replace protocol.
    """

    def __init__(self, root_dir: Path | str):
        self._root_dir = Path(root_dir)
        self._registry_file = self._root_dir / "runtime_registry.json"
        self._store = JSONStore(
            self._registry_file,
            default_factory=lambda: {},
        )
        self._store.ensure_initialized()

    def register(
        self,
        pool: str,
        pid: int,
        port: int,
        status: str,
    ) -> None:
        """Register or update a runtime entry."""
        now = time.time()

        def updater(data: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
            if not isinstance(data, dict):
                data = {}
            if pool in data:
                data[pool].update(
                    {
                        "pid": pid,
                        "port": port,
                        "status": status,
                        "last_heartbeat": now,
                    }
                )
            else:
                data[pool] = {
                    "pool": pool,
                    "pid": pid,
                    "port": port,
                    "status": status,
                    "started_at": now,
                    "last_heartbeat": now,
                }
            return data

        try:
            self._store.update(updater)
        except Timeout:
            raise TimeoutError("Timeout acquiring lock for runtime registry")

    def get(self, pool: str) -> dict[str, Any] | None:
        """Get runtime info for a specific pool."""
        try:
            data = self._store.read()
            if not isinstance(data, dict):
                return None
            return data.get(pool)
        except Timeout:
            raise TimeoutError("Timeout acquiring lock for runtime registry")

    def list_all(self) -> list[dict[str, Any]]:
        """List all registered runtimes."""
        try:
            data = self._store.read()
            if not isinstance(data, dict):
                return []
            return [value for value in data.values() if isinstance(value, dict)]
        except Timeout:
            raise TimeoutError("Timeout acquiring lock for runtime registry")

    def unregister(self, pool: str) -> None:
        """Remove a runtime from the registry."""
        def updater(data: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
            if not isinstance(data, dict):
                data = {}
            if pool in data:
                del data[pool]
            return data

        try:
            self._store.update(updater)
        except Timeout:
            raise TimeoutError("Timeout acquiring lock for runtime registry")

    def heartbeat(self, pool: str) -> None:
        """Update the last_heartbeat timestamp for a pool."""
        def updater(data: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
            if not isinstance(data, dict):
                data = {}
            if pool in data:
                data[pool]["last_heartbeat"] = time.time()
            return data

        try:
            self._store.update(updater)
        except Timeout:
            raise TimeoutError("Timeout acquiring lock for runtime registry")
