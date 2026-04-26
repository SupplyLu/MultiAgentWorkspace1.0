"""Runtime Registry - tracks running pool runtimes with PID and port info."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class RuntimeRegistry:
    """Registry for tracking running pool runtimes with their PID and port information."""

    def __init__(self, root_dir: Path | str):
        self._root_dir = Path(root_dir)
        self._registry_file = self._root_dir / "runtime_registry.json"
        self._data: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        """Load registry data from disk."""
        if self._registry_file.exists():
            try:
                with open(self._registry_file, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._data = {}

    def _save(self) -> None:
        """Save registry data to disk."""
        self._registry_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self._registry_file, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2)

    def register(
        self,
        pool: str,
        pid: int,
        port: int,
        status: str,
    ) -> None:
        """Register or update a runtime entry."""
        now = time.time()

        if pool in self._data:
            # Update existing entry
            self._data[pool].update({
                "pid": pid,
                "port": port,
                "status": status,
                "last_heartbeat": now,
            })
        else:
            # Create new entry
            self._data[pool] = {
                "pool": pool,
                "pid": pid,
                "port": port,
                "status": status,
                "started_at": now,
                "last_heartbeat": now,
            }

        self._save()

    def get(self, pool: str) -> dict[str, Any] | None:
        """Get runtime info for a specific pool."""
        return self._data.get(pool)

    def list_all(self) -> list[dict[str, Any]]:
        """List all registered runtimes."""
        return list(self._data.values())

    def unregister(self, pool: str) -> None:
        """Remove a runtime from the registry."""
        if pool in self._data:
            del self._data[pool]
            self._save()

    def heartbeat(self, pool: str) -> None:
        """Update the last_heartbeat timestamp for a pool."""
        if pool in self._data:
            self._data[pool]["last_heartbeat"] = time.time()
            self._save()
