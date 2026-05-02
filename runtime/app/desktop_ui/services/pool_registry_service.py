"""Pool Registry Service - manages pool metadata for dynamic UI integration.

Provides a unified registry of pool metadata (slot prefixes, bootstrap files, runtime entries)
that replaces hardcoded constants scattered across desktop UI modules.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.shared.json_store import JSONStore


# Built-in pool definitions (fallback when registry file is missing/corrupt)
_BUILTIN_POOLS = [
    {
        "pool_id": "work",
        "display_name": "Work Pool",
        "builtin": True,
        "slot_prefixes": ["worker_"],
        "bootstrap_files": [
            {
                "name": "WORK_BOOTSTRAP",
                "label": "Work 层",
                "file": "WORK_BOOTSTRAP.txt",
            }
        ],
        "runtime_entry": "main.py",
    },
    {
        "pool_id": "thinking",
        "display_name": "Thinking Pool",
        "builtin": True,
        "slot_prefixes": ["sub_brain_"],
        "bootstrap_files": [
            {
                "name": "THINKING_BOOTSTRAP",
                "label": "Thinking 层",
                "file": "THINKING_BOOTSTRAP.txt",
            }
        ],
        "runtime_entry": "main_thinking.py",
    },
    {
        "pool_id": "construct",
        "display_name": "Construct Pool",
        "builtin": True,
        "slot_prefixes": ["constructor_"],
        "bootstrap_files": [
            {
                "name": "CONSTRUCT_BOOTSTRAP",
                "label": "Construct 层",
                "file": "CONSTRUCT_BOOTSTRAP.txt",
            }
        ],
        "runtime_entry": "main_construct.py",
    },
    {
        "pool_id": "gate",
        "display_name": "Gate Pool",
        "builtin": True,
        "slot_prefixes": ["guard_"],
        "bootstrap_files": [
            {
                "name": "GATE_BOOTSTRAP",
                "label": "Gate 层",
                "file": "GATE_BOOTSTRAP.txt",
                "subdir": "gate",
            }
        ],
        "runtime_entry": "main_gate.py",
    },
    {
        "pool_id": "post",
        "display_name": "POST",
        "builtin": True,
        "slot_prefixes": [],
        "bootstrap_files": [],
        "runtime_entry": "main_post.py",
    },
    {
        "pool_id": "package",
        "display_name": "Package Pool",
        "builtin": True,
        "slot_prefixes": ["cutter_", "tester_", "releaser_", "complete_player_"],
        "bootstrap_files": [],
        "runtime_entry": "main_package.py",
    },
]


class PoolRegistryService:
    """Manages pool metadata registry for dynamic UI integration.

    Loads pool definitions from config/pool_registry.json and merges with built-in defaults.
    Provides query/registration interface for desktop UI components.
    """

    def __init__(self, root_dir: Path | str):
        self._root_dir = Path(root_dir)
        self._registry_path = self._root_dir / "runtime" / "config" / "pool_registry.json"
        self._store = JSONStore(
            file_path=self._registry_path,
            default_factory=lambda: {"pools": []},
        )
        self._cache: dict[str, dict[str, Any]] | None = None

    def _load_registry(self) -> dict[str, Any]:
        """Load registry from disk, fallback to empty if missing/corrupt."""
        try:
            self._store.ensure_initialized()
            data = self._store.read()
            if not isinstance(data, dict) or "pools" not in data:
                return {"pools": []}
            return data
        except Exception:
            return {"pools": []}

    def _merge_pools(self) -> dict[str, dict[str, Any]]:
        """Merge built-in and custom pools, indexed by pool_id."""
        registry_data = self._load_registry()
        custom_pools = registry_data.get("pools", [])

        merged = {pool["pool_id"]: pool.copy() for pool in _BUILTIN_POOLS}

        for custom_pool in custom_pools:
            if not isinstance(custom_pool, dict) or "pool_id" not in custom_pool:
                continue
            pool_id = custom_pool["pool_id"]
            merged[pool_id] = custom_pool

        return merged

    def list_all_pools(self) -> list[dict[str, Any]]:
        """List all pools (built-in + custom) sorted by pool_id."""
        if self._cache is None:
            self._cache = self._merge_pools()
        return sorted(self._cache.values(), key=lambda p: p.get("pool_id", ""))

    def get_pool_meta(self, pool_id: str) -> dict[str, Any] | None:
        """Get metadata for a specific pool."""
        if self._cache is None:
            self._cache = self._merge_pools()
        return self._cache.get(pool_id)

    def register_pool(self, pool_meta: dict[str, Any]) -> bool:
        """Register a new pool or update existing pool metadata.

        Returns True on success, False on failure.
        """
        if not isinstance(pool_meta, dict) or "pool_id" not in pool_meta:
            return False

        pool_id = pool_meta["pool_id"]

        def updater(data: dict) -> dict:
            pools = data.get("pools", [])
            pools = [p for p in pools if p.get("pool_id") != pool_id]
            pools.append(pool_meta)
            return {"pools": pools}

        try:
            self._store.update(updater)
            self._cache = None
            return True
        except Exception:
            return False

    def unregister_pool(self, pool_id: str) -> bool:
        """Remove a pool from the registry.

        Returns True on success, False on failure.
        """

        def updater(data: dict) -> dict:
            pools = data.get("pools", [])
            pools = [p for p in pools if p.get("pool_id") != pool_id]
            return {"pools": pools}

        try:
            self._store.update(updater)
            self._cache = None
            return True
        except Exception:
            return False