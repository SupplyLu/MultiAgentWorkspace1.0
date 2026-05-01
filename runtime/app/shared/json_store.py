"""Shared JSON persistence helpers with cross-process locking.

Provides JSONStore - a cross-process safe JSON file store using filelock
for inter-process synchronization and atomic file writes.
"""

import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any
import json
import threading

from filelock import FileLock, Timeout


class JSONStore:
    """Cross-process safe JSON file store with filelock protection.

    Uses file-level locking to coordinate access across multiple processes,
    and atomic temp-file + replace for safe writes.

    Attributes:
        _file_path: Path to the JSON file
        _default_factory: Factory function for initial data
        _lock: Threading lock for intra-process synchronization
        _file_lock_path: Path to the file lock file
    """

    def __init__(self, file_path: Path | str, default_factory: Callable[[], Any]):
        self._file_path = Path(file_path)
        self._default_factory = default_factory
        self._lock = threading.RLock()
        # Lock file is alongside the data file with .lock suffix
        self._file_lock_path = self._file_path.parent / f"{self._file_path.name}.lock"

    def _acquire_file_lock(self, timeout: float = 10.0) -> FileLock:
        """Acquire cross-process file lock.

        Args:
            timeout: Seconds to wait for lock acquisition

        Returns:
            FileLock context manager

        Raises:
            TimeoutError: If lock cannot be acquired within timeout
        """
        return FileLock(self._file_lock_path, timeout=timeout)

    def ensure_initialized(self) -> None:
        """Ensure the JSON file exists with default data.

        Thread-safe and cross-process safe initialization.
        """
        with self._lock:
            with self._acquire_file_lock():
                if self._file_path.exists():
                    return
                self._file_path.parent.mkdir(parents=True, exist_ok=True)
                # Atomic write for initial data
                self._write_no_lock(self._default_factory())

    def _read_no_lock(self) -> Any:
        """Read JSON data without acquiring locks.

        Must be called with both threading and file locks held.
        Handles corrupted files by falling back to default_factory.

        Returns:
            Parsed JSON data, or default_factory() result if file corrupted
        """
        if not self._file_path.exists():
            return self._default_factory()

        try:
            with open(self._file_path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            # Corrupted file - return default
            return self._default_factory()

    def _write_no_lock(self, data: Any) -> None:
        """Write JSON data atomically without acquiring locks.

        Must be called with both threading and file locks held.
        Uses temp file + os.replace for atomic writes.

        Args:
            data: Data to serialize and write
        """
        self._file_path.parent.mkdir(parents=True, exist_ok=True)

        # Create temp file in same directory for atomic replace
        fd, temp_path = tempfile.mkstemp(
            dir=self._file_path.parent,
            prefix=f".tmp_{self._file_path.stem}_",
            suffix=".json"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            # Atomic replace
            os.replace(temp_path, self._file_path)
        except Exception:
            # Clean up temp file on error
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            raise

    def read(self) -> Any:
        """Read JSON data with cross-process safety.

        Returns:
            Parsed JSON data, or default_factory() result if file corrupted
        """
        with self._lock:
            with self._acquire_file_lock():
                return self._read_no_lock()

    def write(self, data: Any) -> None:
        """Write JSON data atomically with cross-process safety.

        Args:
            data: Data to serialize and write
        """
        with self._lock:
            with self._acquire_file_lock():
                self._write_no_lock(data)

    def update(self, updater: Callable[[Any], Any]) -> Any:
        """Atomically read, modify, and write JSON data.

        The updater function receives the current data and returns the new data.
        The entire read-modify-write cycle is protected by locks.

        Args:
            updater: Function that takes current data and returns updated data

        Returns:
            The updated data
        """
        with self._lock:
            with self._acquire_file_lock():
                current = self._read_no_lock()
                updated = updater(current)
                self._write_no_lock(updated)
                return updated


def ensure_json_file(file_path: Path | str, default_factory: Callable[[], Any]) -> JSONStore:
    """Create and initialize a JSONStore.

    Args:
        file_path: Path to the JSON file
        default_factory: Factory function for initial data

    Returns:
        Initialized JSONStore instance
    """
    store = JSONStore(file_path=file_path, default_factory=default_factory)
    store.ensure_initialized()
    return store
