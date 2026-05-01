"""Slot governance store - persistent slot online/offline state across runtimes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.shared.json_store import JSONStore


class SlotGovernanceStore:
    """Manages slot enabled/disabled state across all pool runtimes.

    Provides persistent storage for slot governance decisions so UI and Runtime
    can coordinate slot online/offline operations across process boundaries.
    """

    def __init__(self, root_dir: Path | str):
        self._root_dir = Path(root_dir)
        self._governance_file = self._root_dir / "runtime_slot_governance.json"
        self._store = JSONStore(
            self._governance_file,
            default_factory=lambda: {},
        )
        self._store.ensure_initialized()

    def is_enabled(self, pool: str, slot_id: str) -> bool:
        """Check if a slot is enabled (online). Returns True if not explicitly disabled."""
        data = self._store.read()
        if not isinstance(data, dict):
            return True
        pool_data = data.get(pool, {})
        if not isinstance(pool_data, dict):
            return True
        slot_data = pool_data.get(slot_id, {})
        if not isinstance(slot_data, dict):
            return True
        return slot_data.get("enabled", True)

    def set_enabled(self, pool: str, slot_id: str, enabled: bool) -> None:
        """Set slot enabled state (True=online, False=offline)."""
        def updater(data: dict[str, Any]) -> dict[str, Any]:
            if not isinstance(data, dict):
                data = {}
            if pool not in data:
                data[pool] = {}
            if not isinstance(data[pool], dict):
                data[pool] = {}
            data[pool][slot_id] = {"enabled": enabled}
            return data

        self._store.update(updater)

    def list_pool_slots(self, pool: str) -> dict[str, bool]:
        """List all slots for a pool with their enabled state."""
        data = self._store.read()
        if not isinstance(data, dict):
            return {}
        pool_data = data.get(pool, {})
        if not isinstance(pool_data, dict):
            return {}

        result = {}
        for slot_id, slot_data in pool_data.items():
            if isinstance(slot_data, dict):
                result[slot_id] = slot_data.get("enabled", True)
        return result

    def get_pool_snapshot(self, pool: str) -> dict[str, dict[str, Any]]:
        """Get full governance snapshot for a pool."""
        data = self._store.read()
        if not isinstance(data, dict):
            return {}
        pool_data = data.get(pool, {})
        if not isinstance(pool_data, dict):
            return {}
        return pool_data
