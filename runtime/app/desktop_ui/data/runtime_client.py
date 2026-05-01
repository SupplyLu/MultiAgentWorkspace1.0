"""Fetch runtime status data for the desktop UI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen, Request

from app.services.runtime_registry import RuntimeRegistry


class RuntimeClient:
    def __init__(self, root_dir: Path | str | None = None):
        """Initialize RuntimeClient with optional root directory for registry lookup."""
        self._root_dir = Path(root_dir) if root_dir else None
        self._registry: RuntimeRegistry | None = None
        if self._root_dir:
            self._registry = RuntimeRegistry(root_dir=self._root_dir)

    def _get_port_for_pool(self, pool: str) -> int | None:
        """Look up port for a pool from registry."""
        if not self._registry:
            return None
        pool_info = self._registry.get(pool)
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
                "paused": False,
            }

    def get_control_state(self, pool: str, port: int = None) -> dict[str, Any]:
        if not port:
            port = self._get_port_for_pool(pool)
            if not port:
                return {"paused": False, "pool": pool, "online": False}

        try:
            with urlopen(f"http://127.0.0.1:{port}/api/control/state", timeout=1.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
                payload["online"] = True
                return payload
        except (URLError, HTTPError, ValueError, OSError):
            return {"paused": False, "pool": pool, "online": False}

    def send_control(self, pool: str, action: str, port: int = None) -> dict[str, Any]:
        """Send control command to runtime."""
        if not port:
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

    def send_slot_control(self, pool: str, action: str, slot_id: str, port: int = None) -> dict[str, Any]:
        """Send slot-level online/offline control command to runtime."""
        if not port:
            port = self._get_port_for_pool(pool)
            if not port:
                return {"success": False, "error": f"Port not found for pool '{pool}' in registry"}

        try:
            body = json.dumps({"slot_id": slot_id}).encode("utf-8")
            req = Request(
                f"http://127.0.0.1:{port}/api/control/slot/{action}",
                data=body,
                headers={"Content-Type": "application/json"},
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
