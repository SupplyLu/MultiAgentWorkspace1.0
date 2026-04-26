"""POST Runtime - Scan-based orchestrator for project-centric cross-pool delivery."""

import shutil
from pathlib import Path
from typing import Any

from app.services.flow_policy import FlowPolicy
from app.services.post_naming import is_valid_atomic_workorder
from app.services.post_registry import PostRegistry


class PostRuntime:
    """POST Runtime scans registry and filesystem to deliver completed projects."""

    def __init__(self, root_dir: Path | str, scan_interval_seconds: int = 60, policy_file: Path | str | None = None):
        self.root_dir = Path(root_dir)
        self.scan_interval_seconds = scan_interval_seconds
        self._registry = PostRegistry(root_dir=self.root_dir)

        if policy_file is None:
            policy_file = self.root_dir / "config" / "flow_policy.json"
        self._policy = FlowPolicy(policy_file)

    def get_policy_route(self) -> list[str]:
        return self._policy.get_active_route()

    def scan_once(self):
        """Perform one scan cycle for all registered POST projects."""
        for project_key in self._registry.list_projects():
            project = self._registry.get_project(project_key)
            if project is None:
                continue

            if project.get("status") in {"blocked", "delivered", "skipped"}:
                continue

            if not self._dependencies_satisfied(project_key):
                if project.get("status") != "waiting":
                    self._registry.update_project(project_key, {"status": "waiting"})
                continue

            current_pool = project.get("current_pool", project.get("from_pool"))
            next_pool = project.get("next_pool")
            if next_pool is None:
                self._registry.update_project(project_key, {"status": "delivered"})
                continue

            if current_pool == "gate":
                if self._handle_gate_reject(project):
                    continue
                self._handle_gate_accept(project)
                continue

            self._handle_project_stage(project)

    def _dependencies_satisfied(self, project_key: str) -> bool:
        for dependency in self._registry.get_dependencies(project_key):
            source_project = self._registry.get_project(dependency["source_project_key"])
            if source_project is None:
                return False
            if dependency["rule"] == "after_delivered" and source_project.get("status") != "delivered":
                return False
        return True

    def _handle_project_stage(self, project: dict[str, Any]) -> None:
        project_key = project["project_key"]
        current_pool = project["current_pool"]
        next_pool = project["next_pool"]
        outbox_dir = self.root_dir / "pools" / current_pool / "Outbox"

        txt_payload = outbox_dir / f"{project_key}.txt"
        if txt_payload.exists():
            self._block_project(project_key, f"Expected project directory '{project_key}', found txt payload '{txt_payload.name}'")
            return

        exact_payload = outbox_dir / project_key
        if exact_payload.exists():
            if not exact_payload.is_dir():
                self._block_project(project_key, f"Expected project directory '{project_key}', found file payload")
                return
            self._deliver_payload(project, exact_payload, next_pool)
            self._advance_project(project)
            return

        conflicting_dirs = [
            entry
            for entry in self._iter_directory_entries(outbox_dir)
            if entry.name.startswith(f"{project_key}-") or entry.name.startswith(f"{project_key}.")
        ]
        if conflicting_dirs:
            self._block_project(
                project_key,
                f"Project directory name must match project_key '{project_key}', found '{conflicting_dirs[0].name}'",
            )

    def _handle_gate_reject(self, project: dict[str, Any]) -> bool:
        project_key = project["project_key"]
        rejectbox_dir = self.root_dir / "pools" / "gate" / "Rejectbox"
        reject_payload = rejectbox_dir / project_key
        if not reject_payload.exists():
            return False

        if not reject_payload.is_dir():
            self._block_project(project_key, f"Gate Rejectbox payload '{reject_payload.name}' must be a directory")
            return True

        target_pool = self._previous_pool(project)
        self._deliver_payload(project, reject_payload, target_pool)

        # Clean up reject payload after successful delivery
        shutil.rmtree(reject_payload)

        route = project.get("route", [project["from_pool"], project["to_pool"]])
        new_cursor = max(project.get("cursor", 0) - 1, 0)
        current_pool = route[new_cursor]
        next_pool = route[new_cursor + 1] if new_cursor + 1 < len(route) else None
        self._registry.update_project(
            project_key,
            {
                "cursor": new_cursor,
                "current_pool": current_pool,
                "next_pool": next_pool,
                "status": "in_progress" if next_pool is not None else "delivered",
            },
        )
        return True

    def _handle_gate_accept(self, project: dict[str, Any]) -> None:
        project_key = project["project_key"]
        next_pool = project["next_pool"]
        outbox_dir = self.root_dir / "pools" / "gate" / "Outbox"

        if (outbox_dir / project_key).exists():
            self._block_project(project_key, "Gate Outbox must contain atomic workorder directories, not the project directory")
            return

        workorders = [
            entry for entry in self._iter_directory_entries(outbox_dir)
            if is_valid_atomic_workorder(entry.name) and entry.name.startswith(f"{project_key}-")
        ]
        if not workorders:
            return

        for workorder in workorders:
            self._deliver_payload(project, workorder, next_pool)

        self._advance_project(project)

    def _advance_project(self, project: dict[str, Any]) -> None:
        route = project.get("route", [project["from_pool"], project["to_pool"]])
        current_cursor = project.get("cursor", 0)
        new_cursor = min(current_cursor + 1, len(route) - 1)
        current_pool = route[new_cursor]
        next_pool = route[new_cursor + 1] if new_cursor + 1 < len(route) else None
        new_status = "in_progress" if next_pool is not None else "delivered"
        self._registry.update_project(
            project["project_key"],
            {
                "cursor": new_cursor,
                "current_pool": current_pool,
                "next_pool": next_pool,
                "status": new_status,
            },
        )

    def _previous_pool(self, project: dict[str, Any]) -> str:
        route = project.get("route", [project["from_pool"], project["to_pool"]])
        cursor = max(project.get("cursor", 0) - 1, 0)
        return route[cursor]

    def _active_project_keys_for_pool(self, pool_name: str) -> set[str]:
        project_keys: set[str] = set()
        for project_key in self._registry.list_projects():
            project = self._registry.get_project(project_key)
            if project is None:
                continue
            if project.get("status") in {"blocked", "delivered", "skipped"}:
                continue
            if project.get("current_pool") == pool_name:
                project_keys.add(project_key)
        return project_keys

    def _iter_directory_entries(self, directory: Path) -> list[Path]:
        if not directory.exists():
            return []
        return sorted((entry for entry in directory.iterdir() if entry.is_dir()), key=lambda entry: entry.name)

    def _block_project(self, project_key: str, reason: str) -> None:
        self._registry.update_project(
            project_key,
            {
                "status": "blocked",
                "blocked_reason": reason,
            },
        )
        self._registry.record_manager_action(
            project_key=project_key,
            action_type="blocked",
            detail=reason,
        )

    def _deliver_payload(self, project: dict[str, Any], payload_path: Path, target_pool: str) -> Path:
        queue_dir = self.root_dir / "pools" / target_pool / "Queue"
        queue_dir.mkdir(parents=True, exist_ok=True)

        delivery_path = queue_dir / payload_path.name
        if delivery_path.exists():
            if delivery_path.is_dir():
                shutil.rmtree(delivery_path)
            else:
                delivery_path.unlink()

        if payload_path.is_dir():
            shutil.copytree(payload_path, delivery_path)
        else:
            shutil.copy2(payload_path, delivery_path)

        self._registry.record_delivery(
            project_key=project["project_key"],
            payload_name=payload_path.name,
            from_pool=project["current_pool"],
            to_pool=target_pool,
            delivery_address=str(delivery_path),
            status="delivered",
            reason="post runtime delivery",
        )
        return delivery_path

    def handle_api_request(self, method: str, path: str, payload: dict | None) -> dict[str, Any]:
        """Handle API requests for runtime status and health."""
        if method == "GET" and path == "/api/status":
            return self._get_status()
        elif method == "GET" and path == "/api/health":
            return self._get_health()
        else:
            return {"error": "unknown endpoint"}

    def _get_status(self) -> dict[str, Any]:
        """Return current runtime status with project registration counts."""
        active_registrations = 0
        waiting_payload_registrations = 0
        blocked_registrations = 0
        delivered_registrations = 0
        recent_blocked_reason: str | None = None

        for project_key in self._registry.list_projects():
            project = self._registry.get_project(project_key)
            if project is None:
                continue

            status = project.get("status", "registered")
            if status == "in_progress":
                active_registrations += 1
            elif status == "waiting":
                waiting_payload_registrations += 1
            elif status == "blocked":
                blocked_registrations += 1
                # Capture blocked reason from most recently updated blocked project
                if project.get("blocked_reason"):
                    recent_blocked_reason = project["blocked_reason"]
            elif status == "delivered":
                delivered_registrations += 1

        return {
            "pool": "post",
            "signal_port": 0,
            "is_running": False,
            "queue_count": 0,
            "slots": [],
            "active_registrations": active_registrations,
            "waiting_payload_registrations": waiting_payload_registrations,
            "blocked_registrations": blocked_registrations,
            "delivered_registrations": delivered_registrations,
            "recent_blocked_reason": recent_blocked_reason,
        }

    def _get_health(self) -> dict[str, Any]:
        """Return basic health check information."""
        return {
            "ok": True,
            "pool": "post",
            "uptime_seconds": 0,
        }
