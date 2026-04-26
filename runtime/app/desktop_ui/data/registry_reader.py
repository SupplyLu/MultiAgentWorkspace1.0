"""Read runtime registry information for the desktop UI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class RegistryReader:
    def __init__(self, root_dir: Path | str):
        self._root_dir = Path(root_dir)
        self._registry_file = self._root_dir / "runtime_registry.json"

    def list_running_pools(self) -> list[dict[str, Any]]:
        if not self._registry_file.exists():
            return []

        with open(self._registry_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        pools = [entry for entry in data.values() if entry.get("status") == "running"]
        return sorted(pools, key=lambda entry: entry.get("started_at", 0))
