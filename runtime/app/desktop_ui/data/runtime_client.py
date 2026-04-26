"""Fetch runtime status data for the desktop UI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen, Request


class RuntimeClient:
    def __init__(self, root_dir: Path | str | None = None):
        """Initialize RuntimeClient with optional root directory for registry lookup."""
        self._root_dir = Path(root_dir) if root_dir else None
        self._registry_cache: dict[str, dict] = {}

    def _load_registry(self) -> dict[str, dict]:
        """Load runtime registry from disk."""
        if not self._root_dir:
            return {}

        registry_file = self._root_dir / "runtime_registry.json"
        if not registry_file.exists():
            return {}

        try:
            return json.loads(registry_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _get_port_for_pool(self, pool: str) -> int | None:
        """Look up port for a pool from registry."""
        registry = self._load_registry()
        pool_info = registry.get(pool)
        if pool_info:
            return pool_info.get("port")
        return None

    def get_status(self, pool: str, port: int) -> dict[str, Any]:
        try:
            with urlopen(f"http://127.0.0.1:{port}/api/status", timeout=1.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
                payload["online"] = True
                return payload
        except (URLError, HTTPError, ValueError, OSError):
            return {
                "pool": pool,
                "online": False,
                "slots": [],
                "queue_count": 0,
            }

    def send_control(self, pool: str, action: str, port: int = None) -> dict[str, Any]:
        """Send control command to runtime."""
        if not port:
            # Auto-discover port from registry
            port = self._get_port_for_pool(pool)
            if not port:
                return {"success": False, "error": f"Port not found for pool '{pool}' in registry"}

        try:
            req = Request(
                f"http://127.0.0.1:{port}/api/control/{action}",
                method="POST"
            )
            with urlopen(req, timeout=2.0) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as e:
            try:
                err_data = json.loads(e.read().decode("utf-8"))
                return {"success": False, "error": err_data.get("error", str(e))}
            except Exception:
                return {"success": False, "error": str(e)}
        except Exception as e:
            return {"success": False, "error": str(e)}
