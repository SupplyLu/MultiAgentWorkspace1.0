"""Bridge to execute local CLI commands for runtime management."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

from app.services.runtime_registry import RuntimeRegistry
from app.desktop_ui.services.pool_registry_service import PoolRegistryService
from app.shared.windows_process import kill_process


# Built-in pool entrypoint map (fallback when registry is missing)
_BUILTIN_ENTRY_MAP = {
    "work": "main.py",
    "thinking": "main_thinking.py",
    "construct": "main_construct.py",
    "gate": "main_gate.py",
    "post": "main_post.py",
    "package": "main_package.py",
}


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


class RuntimeCommandBridge:
    def __init__(self, root_dir: Path | str | None = None):
        self._root_dir = Path(root_dir) if root_dir else Path(__file__).resolve().parents[4]
        self._registry = RuntimeRegistry(root_dir=self._root_dir)
        self._pool_registry = PoolRegistryService(root_dir=self._root_dir)

    def _get_runtime_entry(self, pool: str) -> str | None:
        """Get runtime entry script for a pool from registry or fallback."""
        meta = self._pool_registry.get_pool_meta(pool)
        if meta:
            entry = meta.get("runtime_entry")
            if entry:
                return entry
        return _BUILTIN_ENTRY_MAP.get(pool)

    def start_pool(self, pool: str) -> dict[str, bool | str]:
        try:
            entry = self._get_runtime_entry(pool)
            if not entry:
                return {"success": False, "error": f"No runtime entry configured for pool: {pool}"}

            existing = self._registry.get(pool)
            if isinstance(existing, dict) and existing.get("status") == "running":
                pid = existing.get("pid")
                if isinstance(pid, int) and _is_pid_alive(pid):
                    return {"success": False, "error": f"Pool already running: {pool}"}
                self._registry.register(pool=pool, pid=0, port=0, status="stopped")

            script = entry
            runtime_dir = self._root_dir / "runtime"
            process = subprocess.Popen(
                ["python", "-m", f"app.{script[:-3]}"],
                cwd=str(runtime_dir),
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(0.5)
            if process.poll() is not None:
                return {"success": False, "error": "Process crashed immediately on startup"}
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def stop_pool(self, pool: str) -> dict[str, bool | str]:
        try:
            existing = self._registry.get(pool)
            if not isinstance(existing, dict) or existing.get("status") != "running":
                return {"success": True}

            pid = existing.get("pid")
            if not isinstance(pid, int) or pid <= 0:
                self._registry.register(pool=pool, pid=0, port=0, status="stopped")
                return {"success": True}

            if not _is_pid_alive(pid):
                self._registry.register(pool=pool, pid=0, port=0, status="stopped")
                return {"success": True}

            stop_result = self._stop_existing_process(pid)
            if not stop_result["success"]:
                return stop_result
            self._wait_until_stopped(pool, pid, timeout_seconds=5.0)
            self._registry.register(pool=pool, pid=pid, port=existing.get("port", 0), status="stopped")
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def restart_pool(self, pool: str) -> dict[str, bool | str]:
        """Restart a specific runtime pool via local script."""
        stop_result = self.stop_pool(pool)
        if not stop_result["success"]:
            return stop_result
        return self.start_pool(pool)

    def _stop_existing_process(self, pid: int) -> dict[str, bool | str]:
        try:
            if os.name == "nt":
                result = kill_process(pid, force=False, dry_run=False, tree=True)
                if result.get("killed"):
                    return {"success": True}
                result = kill_process(pid, force=True, dry_run=False, tree=True)
                if result.get("killed"):
                    return {"success": True}
                if not _is_pid_alive(pid):
                    return {"success": True}
                return {"success": False, "error": f"Failed to stop PID {pid}"}

            os.kill(pid, signal.SIGTERM)
            return {"success": True}
        except ProcessLookupError:
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _wait_until_stopped(self, pool: str, pid: int, timeout_seconds: float) -> None:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            current = self._registry.get(pool)
            if not isinstance(current, dict):
                return
            if current.get("pid") != pid:
                return
            if current.get("status") != "running":
                return
            time.sleep(0.1)
