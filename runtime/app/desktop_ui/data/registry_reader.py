"""Read runtime registry information for the desktop UI."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from app.services.runtime_registry import RuntimeRegistry


def _is_pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is alive."""
    try:
        if os.name == "nt":
            import ctypes
            kernel32 = ctypes.windll.kernel32
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        else:
            os.kill(pid, 0)
            return True
    except (OSError, ProcessLookupError, PermissionError):
        return False
    except Exception:
        return False


class RegistryReader:
    ALL_POOLS = ["work", "thinking", "construct", "gate", "post", "package"]

    def __init__(self, root_dir: Path | str):
        self._root_dir = Path(root_dir)
        self._registry = RuntimeRegistry(root_dir=self._root_dir)

    def list_running_pools(self) -> list[dict[str, Any]]:
        all_pools = self._registry.list_all()
        pools = [entry for entry in all_pools if entry.get("status") == "running"]
        return sorted(pools, key=lambda entry: entry.get("started_at", 0))

    def list_all_pools(self) -> list[dict[str, Any]]:
        entries = []
        for pool in self.ALL_POOLS:
            runtime_info = self._registry.get(pool)
            if runtime_info is None:
                entries.append(
                    {
                        "pool": pool,
                        "pid": None,
                        "port": 0,
                        "status": "stopped",
                    }
                )
            else:
                pid = runtime_info.get("pid")
                status = runtime_info.get("status", "stopped")
                if status == "running" and isinstance(pid, int) and pid > 0:
                    if not _is_pid_alive(pid):
                        status = "stopped"
                entries.append({**runtime_info, "status": status})
        return entries
