"""Single-instance guard using file locks to prevent duplicate process launches."""

import os
import json
from pathlib import Path
from filelock import FileLock, Timeout


class SingleInstanceGuard:
    """Ensures only one instance of a given process type can run per root directory.

    Uses file locks for cross-process coordination. Lock files are stored in
    `<root>/.runtime_locks/<instance_key>.lock` and automatically released on exit.
    """

    def __init__(self, root_dir: Path | str, instance_key: str):
        """
        Args:
            root_dir: Project root directory (scopes the lock to this workspace)
            instance_key: Unique identifier for this process type (e.g., "work", "desktop_ui")
        """
        self._root_dir = Path(root_dir)
        self._instance_key = instance_key
        self._lock_dir = self._root_dir / ".runtime_locks"
        self._lock_file = self._lock_dir / f"{instance_key}.lock"
        self._meta_file = self._lock_dir / f"{instance_key}.meta.json"
        self._lock: FileLock | None = None

    def try_acquire(self, timeout: float = 0.1) -> tuple[bool, str]:
        """Try to acquire the single-instance lock.

        Args:
            timeout: Seconds to wait for lock (default 0.1 for fast-fail)

        Returns:
            (success: bool, message: str)
            - (True, "acquired") if lock obtained
            - (False, "already running: PID=...") if another instance holds the lock
            - (False, "stale lock cleared, retry") if zombie lock was cleaned
        """
        self._lock_dir.mkdir(parents=True, exist_ok=True)

        lock = FileLock(self._lock_file, timeout=timeout)

        try:
            lock.acquire()
            # Lock acquired - write metadata
            self._lock = lock
            self._write_metadata()
            return (True, "acquired")

        except Timeout:
            # Lock held by another process - check if it's alive
            if self._meta_file.exists():
                try:
                    with open(self._meta_file, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                    pid = meta.get("pid")

                    if pid and self._is_process_alive(pid):
                        return (False, f"already running: PID={pid}, instance_key={self._instance_key}")
                    else:
                        # Stale lock - holder is dead
                        return (False, "stale lock detected, will be cleared on next acquire attempt")
                except Exception:
                    pass

            return (False, f"lock held by unknown process (instance_key={self._instance_key})")

    def release(self) -> None:
        """Release the lock and clean up metadata."""
        if self._lock and self._lock.is_locked:
            self._lock.release()
            self._lock = None

        # Clean up metadata file
        if self._meta_file.exists():
            try:
                self._meta_file.unlink()
            except OSError:
                pass

    def _write_metadata(self) -> None:
        """Write metadata file with current PID for diagnostics."""
        meta = {
            "pid": os.getpid(),
            "instance_key": self._instance_key,
        }
        with open(self._meta_file, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

    def _is_process_alive(self, pid: int) -> bool:
        """Check if a process with given PID is alive.

        Uses os.kill(pid, 0) on Unix, or checks if PID exists on Windows.
        """
        try:
            if os.name == "nt":
                # Windows: check if process exists
                import ctypes
                kernel32 = ctypes.windll.kernel32
                PROCESS_QUERY_INFORMATION = 0x0400
                handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)
                if handle:
                    kernel32.CloseHandle(handle)
                    return True
                return False
            else:
                # Unix: send signal 0 (no-op, just checks existence)
                os.kill(pid, 0)
                return True
        except (OSError, AttributeError):
            return False
