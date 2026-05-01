"""POST Runtime - Scan-based orchestrator for project-centric cross-pool delivery."""

import shutil
from pathlib import Path
from typing import Any

from app.services.flow_policy import FlowPolicy
from app.services.post_naming import extract_project_key
from app.services.post_registry import PostRegistry


class PostRuntime:
    """POST Runtime scans registry and filesystem to deliver completed projects."""

    def __init__(self, root_dir: Path | str, scan_interval_seconds: int = 60, policy_file: Path | str | None = None):
        self.root_dir = Path(root_dir)
        self.scan_interval_seconds = scan_interval_seconds
        self._registry = PostRegistry(root_dir=self.root_dir)
        self._paused = False

        if policy_file is None:
            policy_file = self.root_dir / "config" / "flow_policy.json"
        self._policy = FlowPolicy(policy_file)

    def get_policy_route(self) -> list[str]:
        return self._policy.get_active_route()

    def scan_once(self):
        """Perform one scan cycle for all registered POST projects."""
        if self._paused:
            return
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

            if self._handle_rejectbox_return(project):
                continue

            next_target = self._get_next_target(project)
            if next_target is None:
                self._registry.update_project(project_key, {"status": "delivered"})
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

    def _handle_rejectbox_return(self, project: dict[str, Any]) -> bool:
        """Check if current pool's Rejectbox has rejected payloads and return them to the previous pool's Queue."""
        project_key = project["project_key"]
        current_pool = self._get_current_pool(project)
        if current_pool is None:
            return False

        rejectbox_dir = self.root_dir / "pools" / current_pool / "Rejectbox"
        if not rejectbox_dir.exists():
            return False

        reject_payloads = self._collect_project_payloads(rejectbox_dir, project_key)
        if not reject_payloads:
            return False

        route = project.get("route") or []
        cursor = project.get("cursor", 0)
        if cursor <= 0 or not route:
            self._block_project(project_key, f"Rejected at {current_pool} but no previous pool to return to")
            return True

        previous_pool = route[cursor - 1]
        previous_queue = self.root_dir / "pools" / previous_pool / "Queue"
        previous_queue.mkdir(parents=True, exist_ok=True)

        for payload in reject_payloads:
            dest = previous_queue / payload.name
            if dest.exists():
                shutil.rmtree(dest) if dest.is_dir() else dest.unlink()
            if payload.is_dir():
                shutil.copytree(payload, dest)
            else:
                shutil.copy2(payload, dest)
            if payload.is_dir():
                shutil.rmtree(payload)
            else:
                payload.unlink()

        new_cursor = cursor - 1
        new_current = route[new_cursor]
        new_next = route[new_cursor + 1] if new_cursor + 1 < len(route) else None
        self._registry.update_project(project_key, {
            "cursor": new_cursor,
            "current_pool": new_current,
            "next_pool": new_next,
            "status": "in_progress",
        })

        self._registry.record_manager_action(
            project_key=project_key,
            action_type="rejectbox_return",
            detail=f"Returned from {current_pool}/Rejectbox to {previous_pool}/Queue",
        )
        return True

    def _handle_project_stage(self, project: dict[str, Any]) -> None:
        """Deliver project payload from current Outbox to configured next target Queue."""
        project_key = project["project_key"]
        current_pool = self._get_current_pool(project)
        next_target = self._get_next_target(project)
        if current_pool is None or next_target is None:
            self._registry.update_project(project_key, {"status": "delivered"})
            return

        outbox_dir = self.root_dir / "pools" / current_pool / "Outbox"
        payloads = self._collect_project_payloads(outbox_dir, project_key)
        if not payloads:
            return

        try:
            for payload in payloads:
                self._deliver_payload(project, payload, next_target)
        except FileExistsError as exc:
            self._block_project(project_key, str(exc))
            return

        self._advance_project(project)

    def _get_current_pool(self, project: dict[str, Any]) -> str | None:
        route = project.get("route") or []
        cursor = project.get("cursor", 0)
        if route and 0 <= cursor < len(route):
            return route[cursor]
        return project.get("current_pool") or project.get("from_pool")

    def _get_next_target(self, project: dict[str, Any]) -> str | None:
        route = project.get("route") or []
        cursor = project.get("cursor", 0)
        if route and cursor + 1 < len(route):
            return route[cursor + 1]
        return project.get("next_pool") or project.get("to_pool")

    def _advance_project(self, project: dict[str, Any]) -> None:
        route = project.get("route") or []
        current_cursor = project.get("cursor", 0)
        if route:
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
                    "to_pool": next_pool if next_pool is not None else project.get("to_pool"),
                    "status": new_status,
                },
            )
            return

        self._registry.update_project(
            project["project_key"],
            {
                "status": "delivered",
            },
        )

    def _collect_project_payloads(self, outbox_dir: Path, project_key: str) -> list[Path]:
        if not outbox_dir.exists():
            return []

        exact_dir = outbox_dir / project_key
        exact_txt = outbox_dir / f"{project_key}.txt"
        payloads: list[Path] = []

        if exact_dir.exists():
            payloads.append(exact_dir)
        if exact_txt.exists():
            payloads.append(exact_txt)

        if payloads:
            return payloads

        matched_payloads: list[Path] = []
        for entry in sorted(outbox_dir.iterdir(), key=lambda item: item.name):
            if extract_project_key(entry.name) == project_key:
                matched_payloads.append(entry)
        return matched_payloads

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

        # [Fix] 不再静默覆盖目标 Queue 中已存在的对象。
        # 若目标已有同名文件/目录，报告冲突而不破坏现有对象。
        if delivery_path.exists():
            raise FileExistsError(
                f"Delivery conflict: '{payload_path.name}' already exists in target Queue "
                f"'{target_pool}/Queue/'. Refusing to overwrite to prevent data loss. "
                f"Project '{project['project_key']}' will be blocked."
            )

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
        elif method == "POST" and path == "/api/control/pause":
            return self._pause()
        elif method == "POST" and path == "/api/control/resume":
            return self._resume()
        elif method == "GET" and path == "/api/control/state":
            return self._get_control_state()
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
            "paused": self._paused,
            "queue_count": 0,
            "slots": [],
            "active_registrations": active_registrations,
            "waiting_payload_registrations": waiting_payload_registrations,
            "blocked_registrations": blocked_registrations,
            "delivered_registrations": delivered_registrations,
            "recent_blocked_reason": recent_blocked_reason,
        }

    def _pause(self) -> dict[str, Any]:
        self._paused = True
        return self._get_control_state()

    def _resume(self) -> dict[str, Any]:
        self._paused = False
        return self._get_control_state()

    def _get_control_state(self) -> dict[str, Any]:
        return {
            "paused": self._paused,
            "pool": "post",
        }

    def _get_health(self) -> dict[str, Any]:
        """Return basic health check information."""
        return {
            "ok": True,
            "pool": "post",
            "uptime_seconds": 0,
        }
