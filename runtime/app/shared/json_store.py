"""Shared JSON persistence helpers."""

from collections.abc import Callable
from pathlib import Path
from typing import Any
import json
import threading


class JSONStore:
    """Simple JSON file store with initialize, read, and update helpers."""

    def __init__(self, file_path: Path | str, default_factory: Callable[[], Any]):
        self._file_path = Path(file_path)
        self._default_factory = default_factory
        self._lock = threading.RLock()

    def ensure_initialized(self) -> None:
        with self._lock:
            if self._file_path.exists():
                return
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._file_path, "w", encoding="utf-8") as f:
                json.dump(self._default_factory(), f, ensure_ascii=False, indent=2)

    def read(self) -> Any:
        with self._lock:
            self.ensure_initialized()
            with open(self._file_path, encoding="utf-8") as f:
                return json.load(f)

    def write(self, data: Any) -> None:
        with self._lock:
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    def update(self, updater: Callable[[Any], Any]) -> Any:
        with self._lock:
            current = self.read()
            updated = updater(current)
            self.write(updated)
            return updated


def ensure_json_file(file_path: Path | str, default_factory: Callable[[], Any]) -> JSONStore:
    store = JSONStore(file_path=file_path, default_factory=default_factory)
    store.ensure_initialized()
    return store
