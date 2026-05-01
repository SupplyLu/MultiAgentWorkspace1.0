"""Manage cross-pool project registration and dependencies.

Provides PostRegistry for tracking project state, dependencies, deliveries,
and manager actions with project-centric naming and unified JSONStore-based
storage for cross-process safety.
"""

import json
import time
import uuid
from pathlib import Path
from typing import Any

from app.shared.json_store import JSONStore


class PostRegistry:
    """Project-centric registry for cross-pool task management.

    Uses JSONStore for all storage operations to ensure cross-process
    safety and consistent file locking protocol.

    Attributes:
        _root_dir: Root directory for transfers
        _transfers_dir: Transfers subdirectory
        _projects_dir: Directory for project files
        _dependencies_dir: Directory for dependency files
        _deliveries_dir: Directory for delivery files
        _actions_dir: Directory for manager action files
        _index_store: JSONStore for post_index.json
    """

    def __init__(self, root_dir: Path | str):
        self._root_dir = Path(root_dir)
        self._transfers_dir = self._root_dir / "transfers"
        self._projects_dir = self._transfers_dir / "projects"
        self._dependencies_dir = self._transfers_dir / "dependencies"
        self._deliveries_dir = self._transfers_dir / "deliveries"
        self._actions_dir = self._transfers_dir / "manager_actions"

        for path in (
            self._projects_dir,
            self._dependencies_dir,
            self._deliveries_dir,
            self._actions_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

        self._index_store = JSONStore(
            self._transfers_dir / "post_index.json",
            default_factory=lambda: {
                "projects": [],
                "dependencies": [],
                "deliveries": [],
                "manager_actions": [],
            },
        )
        self._index_store.ensure_initialized()
        self._migrate_index_schema()

    def _migrate_index_schema(self) -> None:
        """Migrate legacy post_index.json schema to the project-centric format."""
        def migrate(data: Any) -> dict[str, Any]:
            if not isinstance(data, dict):
                data = {}

            projects = data.get("projects")
            if not isinstance(projects, list):
                projects = []

            dependencies = data.get("dependencies")
            if not isinstance(dependencies, list):
                dependencies = []

            deliveries = data.get("deliveries")
            if not isinstance(deliveries, list):
                legacy_deliveries = data.get("transfers")
                deliveries = legacy_deliveries if isinstance(legacy_deliveries, list) else []

            manager_actions = data.get("manager_actions")
            if not isinstance(manager_actions, list):
                manager_actions = []

            return {
                "projects": projects,
                "dependencies": dependencies,
                "deliveries": deliveries,
                "manager_actions": manager_actions,
            }

        self._index_store.update(migrate)

    def _project_file(self, project_key: str) -> Path:
        return self._projects_dir / f"{project_key}.json"

    def _dependencies_file(self, target_project_key: str) -> Path:
        return self._dependencies_dir / f"{target_project_key}.json"

    def _delivery_file(self, delivery_id: str) -> Path:
        return self._deliveries_dir / f"{delivery_id}.json"

    def _manager_action_file(self, action_id: str) -> Path:
        return self._actions_dir / f"{action_id}.json"

    def _safe_read_json_file(self, file_path: Path) -> Any:
        """Safely read a JSON file, returning None if file is corrupted or missing.

        Uses JSONStore internally for consistent file locking.

        Args:
            file_path: Path to JSON file

        Returns:
            Parsed JSON data or None if corrupted/missing
        """
        if not file_path.exists():
            return None

        # Use JSONStore for cross-process safe read with corruption fallback
        store = JSONStore(
            file_path,
            default_factory=lambda: None,
        )
        data = store.read()
        # JSONStore returns default_factory() on corruption, which is None here
        return data

    def _safe_read_json_list(self, file_path: Path) -> list:
        """Safely read a JSON file that should contain a list.

        Args:
            file_path: Path to JSON file

        Returns:
            List from file, or empty list if corrupted/missing
        """
        data = self._safe_read_json_file(file_path)
        if isinstance(data, list):
            return data
        return []

    def register_project(
        self,
        project_key: str,
        from_pool: str,
        to_pool: str,
        route: list[str] | None = None,
    ) -> dict[str, Any]:
        """Register a new project. Idempotent - returns existing project if already registered."""
        # Check if project already exists
        existing_project = self.get_project(project_key)
        if existing_project is not None:
            return existing_project

        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        # Determine route and calculate route metadata
        if route is None:
            route = [from_pool, to_pool]
        elif len(route) == 0:
            raise ValueError("route cannot be empty if provided")

        cursor = 0
        current_pool = route[cursor]
        next_pool = route[cursor + 1] if cursor + 1 < len(route) else None
        route_version = 1

        # Prepare project data
        project_data = {
            "project_key": project_key,
            "from_pool": from_pool,
            "to_pool": to_pool,
            "status": "registered",
            "route": route,
            "cursor": cursor,
            "current_pool": current_pool,
            "next_pool": next_pool,
            "route_version": route_version,
            "created_at": now,
            "updated_at": now,
        }

        # Write to file using JSONStore for atomic writes with cross-process locking
        project_store = JSONStore(
            self._project_file(project_key),
            default_factory=lambda: project_data,
        )
        project_store.write(project_data)

        # Update index
        def update_index(data):
            if project_key not in data["projects"]:
                data["projects"].append(project_key)
            return data

        self._index_store.update(update_index)

        return project_data

    def get_project(self, project_key: str) -> dict[str, Any] | None:
        """Get project data by key. Returns None if missing or corrupted."""
        return self._safe_read_json_file(self._project_file(project_key))

    def update_project(
        self, project_key: str, updates: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Update specific fields of a project."""
        project = self.get_project(project_key)
        if project is None:
            return None
        project.update(updates)
        project["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        # Write using JSONStore for cross-process safe atomic write
        project_store = JSONStore(
            self._project_file(project_key), default_factory=lambda: project
        )
        project_store.write(project)
        return project

    def list_projects(self) -> list[str]:
        """List all registered project keys."""
        index_data = self._index_store.read()
        return index_data.get("projects", [])

    def add_dependency(
        self,
        source_project_key: str,
        target_project_key: str,
        rule: str,
    ) -> dict[str, Any]:
        """Add a dependency record. Target project depends on source project."""
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        dependency_data = {
            "source_project_key": source_project_key,
            "target_project_key": target_project_key,
            "rule": rule,
            "satisfied": False,
            "satisfied_at": "",
            "created_at": now,
        }

        # Use JSONStore.update() for atomic read-modify-write
        dep_store = JSONStore(
            self._dependencies_file(target_project_key),
            default_factory=lambda: []
        )

        def append_dependency(existing_deps: Any) -> list:
            if not isinstance(existing_deps, list):
                existing_deps = []
            existing_deps.append(dependency_data)
            return existing_deps

        dep_store.update(append_dependency)

        # Update index
        def update_index(data):
            dep_key = f"{source_project_key}->{target_project_key}"
            if dep_key not in data["dependencies"]:
                data["dependencies"].append(dep_key)
            return data

        self._index_store.update(update_index)

        return dependency_data

    def get_dependencies(self, target_project_key: str) -> list[dict[str, Any]]:
        """Get all dependencies for a target project. Returns empty list if corrupted/missing."""
        return self._safe_read_json_list(self._dependencies_file(target_project_key))

    def record_delivery(
        self,
        project_key: str,
        payload_name: str,
        from_pool: str,
        to_pool: str,
        delivery_address: str,
        status: str,
        reason: str = "",
    ) -> dict[str, Any]:
        """Record a delivery event for a project."""
        delivery_id = str(uuid.uuid4())
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        delivery_data = {
            "delivery_id": delivery_id,
            "project_key": project_key,
            "payload_name": payload_name,
            "from_pool": from_pool,
            "to_pool": to_pool,
            "delivery_address": delivery_address,
            "status": status,
            "reason": reason,
            "created_at": now,
        }

        # Write delivery file using JSONStore for cross-process safety
        delivery_store = JSONStore(
            self._delivery_file(delivery_id), default_factory=lambda: delivery_data
        )
        delivery_store.write(delivery_data)

        # Update index
        def update_index(data):
            data["deliveries"].append(delivery_id)
            return data

        self._index_store.update(update_index)

        return delivery_data

    def list_deliveries(self, project_key: str | None = None) -> list[dict[str, Any]]:
        """List all deliveries, optionally filtered by project_key.

        Skips corrupted delivery files and returns successfully parsed ones.
        """
        index_data = self._index_store.read()
        delivery_ids = index_data.get("deliveries", [])

        deliveries = []
        for delivery_id in delivery_ids:
            delivery_data = self._safe_read_json_file(self._delivery_file(delivery_id))
            if delivery_data is None:
                # File missing or corrupted - skip silently
                continue
            if project_key is None or delivery_data.get("project_key") == project_key:
                deliveries.append(delivery_data)

        return deliveries

    def record_manager_action(
        self,
        project_key: str,
        action_type: str,
        detail: str,
    ) -> dict[str, Any]:
        """Record a manager action (hold, resume, merge, etc.)."""
        action_id = str(uuid.uuid4())
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        action_data = {
            "action_id": action_id,
            "project_key": project_key,
            "action_type": action_type,
            "detail": detail,
            "created_at": now,
        }

        # Write action file using JSONStore for cross-process safety
        action_store = JSONStore(
            self._manager_action_file(action_id), default_factory=lambda: action_data
        )
        action_store.write(action_data)

        # Update index
        def update_index(data):
            data["manager_actions"].append(action_id)
            return data

        self._index_store.update(update_index)

        return action_data

    def list_manager_actions(
        self, project_key: str | None = None
    ) -> list[dict[str, Any]]:
        """List all manager actions, optionally filtered by project_key.

        Skips corrupted action files and returns successfully parsed ones.
        """
        index_data = self._index_store.read()
        action_ids = index_data.get("manager_actions", [])

        actions = []
        for action_id in action_ids:
            action_data = self._safe_read_json_file(self._manager_action_file(action_id))
            if action_data is None:
                # File missing or corrupted - skip silently
                continue
            if project_key is None or action_data.get("project_key") == project_key:
                actions.append(action_data)

        return actions

    def update_remaining_route(
        self,
        project_key: str,
        remaining_route: list[str],
        operator: str,
        reason: str,
    ) -> dict[str, Any]:
        """Update the remaining route for a project. Validates and records audit trail."""
        project = self.get_project(project_key)
        if project is None:
            raise ValueError(f"Project {project_key} not found")

        # Validation
        if not remaining_route:
            raise ValueError("remaining_route cannot be empty")

        cursor = project.get("cursor", 0)
        current_pool = project.get("current_pool")

        if remaining_route[0] != current_pool:
            raise ValueError(
                f"remaining_route must start with current_pool '{current_pool}', got '{remaining_route[0]}'"
            )

        # Store before state for audit
        old_route = project.get("route", [])
        old_route_version = project.get("route_version", 1)

        # Calculate skipped stages only within remaining tail after current cursor
        old_tail = old_route[cursor + 1 :]
        new_tail = remaining_route[1:]
        skipped_stages = [stage for stage in old_tail if stage not in new_tail]

        # Mutate only tail from cursor onward
        new_route = old_route[:cursor] + remaining_route

        # Increment route_version
        new_route_version = old_route_version + 1

        # Recalculate next_pool
        next_pool = new_route[cursor + 1] if cursor + 1 < len(new_route) else None

        # Update project
        updates = {
            "route": new_route,
            "next_pool": next_pool,
            "route_version": new_route_version,
            "skipped_stages": skipped_stages,
        }
        updated_project = self.update_project(project_key, updates)

        # Record manager action
        self.record_manager_action(
            project_key=project_key,
            action_type="route_update",
            detail=json.dumps(
                {
                    "operator": operator,
                    "reason": reason,
                    "before": {
                        "route": old_route,
                        "route_version": old_route_version,
                    },
                    "after": {
                        "route": new_route,
                        "route_version": new_route_version,
                    },
                }
            ),
        )

        return updated_project
