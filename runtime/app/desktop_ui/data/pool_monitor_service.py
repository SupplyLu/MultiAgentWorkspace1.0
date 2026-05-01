"""Pool monitoring service - aggregates runtime and slot status for all pools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.desktop_ui.data.post_progress_reader import PostProgressReader
from app.desktop_ui.data.registry_reader import RegistryReader
from app.desktop_ui.data.runtime_client import RuntimeClient
from app.services.timeout_defaults_store import TimeoutDefaultsStore


class PoolMonitorService:
    """Aggregates runtime and slot status from all pools for dashboard monitoring."""

    SLOT_PREFIXES = {
        "work": ("worker_",),
        "thinking": ("sub_brain_",),
        "construct": ("constructor_",),
        "gate": ("guard_",),
        "package": ("cutter_", "tester_", "releaser_", "complete_player_"),
    }

    def __init__(self, root_dir: Path | str):
        self._root_dir = Path(root_dir)
        self._registry_reader = RegistryReader(root_dir=self._root_dir)
        self._runtime_client = RuntimeClient(root_dir=self._root_dir)
        self._post_progress_reader = PostProgressReader(self._root_dir / "transfers")
        self._timeout_defaults = TimeoutDefaultsStore(root_dir=self._root_dir)

    def _scan_slot_directories(self, pool_name: str) -> list[dict[str, Any]]:
        prefixes = self.SLOT_PREFIXES.get(pool_name)
        if not prefixes:
            return []
        pool_dir = self._root_dir / "pools" / pool_name
        if not pool_dir.exists():
            return []

        slots = []
        for item in sorted(pool_dir.iterdir()):
            if not item.is_dir():
                continue
            if not any(item.name.startswith(prefix) for prefix in prefixes):
                continue
            slots.append(
                {
                    "slot_id": item.name,
                    "busy": False,
                    "enabled": False,
                    "assigned_task_id": "",
                    "assigned_project_name": "",
                    "current_state": "offline",
                    "current_stage": "",
                }
            )
        return slots

    def get_all_pool_status(self) -> list[dict[str, Any]]:
        """Fetch status from all pools and return aggregated data."""
        all_pools = self._registry_reader.list_all_pools()
        results = []

        for pool_entry in all_pools:
            pool_name = pool_entry.get("pool", "unknown")
            port = pool_entry.get("port") or 0
            status_value = pool_entry.get("status", "stopped")
            runtime_online = status_value == "running"
            default_timeout_seconds = None
            if pool_name in self.SLOT_PREFIXES:
                default_timeout_seconds = self._timeout_defaults.get(pool_name)

            if pool_name == "post":
                progress = self._post_progress_reader.get_progress()
                paused = False
                if runtime_online and port:
                    control_state = self._runtime_client.get_control_state(pool_name, port)
                    paused = control_state.get("paused", False)
                results.append(
                    {
                        "pool": pool_name,
                        "runtime": {
                            "online": runtime_online,
                            "pid": pool_entry.get("pid"),
                            "port": port,
                            "paused": paused,
                            "queue_count": 0,
                            "slot_total": 0,
                            "slot_enabled": 0,
                            "slot_busy": 0,
                            "default_timeout_seconds": default_timeout_seconds,
                            "active_registrations": progress.get("active_registrations", 0),
                            "waiting_payload_registrations": progress.get("waiting_payload_registrations", 0),
                            "blocked_registrations": progress.get("blocked_registrations", 0),
                            "delivered_registrations": progress.get("delivered_registrations", 0),
                            "block_reason": progress.get("block_reason"),
                        },
                        "slots": [],
                    }
                )
                continue

            status = {"slots": [], "queue_count": 0, "paused": False, "online": False}
            if runtime_online and port:
                status = self._runtime_client.get_status(pool=pool_name, port=port)
                control_state = self._runtime_client.get_control_state(pool_name, port=port)
                status["paused"] = control_state.get("paused", False)

            slots = []
            enabled_count = 0
            busy_count = 0
            source_slots = status.get("slots", []) or self._scan_slot_directories(pool_name)
            for slot in source_slots:
                enabled = slot.get("enabled", runtime_online)
                busy = slot.get("busy", False)
                if enabled:
                    enabled_count += 1
                if busy:
                    busy_count += 1
                slots.append(
                    {
                        "slot_id": slot.get("slot_id", "unknown"),
                        "busy": busy,
                        "enabled": enabled,
                        "assigned_task_id": slot.get("assigned_task_id", ""),
                        "assigned_project_name": slot.get("assigned_project_name", ""),
                        "current_state": slot.get("current_state", "unknown"),
                        "current_stage": slot.get("current_stage", ""),
                    }
                )

            results.append(
                {
                    "pool": pool_name,
                    "runtime": {
                        "online": runtime_online,
                        "pid": pool_entry.get("pid"),
                        "port": port,
                        "paused": status.get("paused", False),
                        "queue_count": status.get("queue_count", 0),
                        "slot_total": len(slots),
                        "slot_enabled": enabled_count,
                        "slot_busy": busy_count,
                        "default_timeout_seconds": default_timeout_seconds,
                    },
                    "slots": slots,
                }
            )

        return results
