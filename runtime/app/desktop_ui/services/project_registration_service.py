"""Service for project registration and Queue file generation."""

import re
from pathlib import Path

from app.services.flow_policy import FlowPolicy
from app.services.post_naming import is_valid_project_key


class InvalidInputError(Exception):
    """Raised when input validation fails."""


class ProjectRegistrationService:
    """Handle project registration and Queue file generation."""

    def __init__(self, root_dir: Path | str):
        self._root_dir = Path(root_dir)
        self._policy = FlowPolicy(self._root_dir / "config" / "flow_policy.json")

    def build_project_key(self, project_name: str, version: str, mode: str) -> str:
        """Assemble project_key from components.

        Supports flexible version formats: v1, v2, 0.1.2, 1.3, 2.0.1, etc.
        """
        # Validate version: non-empty, alphanumeric + dots only, no path separators
        if not version or not re.match(r"^[A-Za-z0-9.]+$", version):
            raise InvalidInputError(
                f"Invalid version format: {version}. "
                "Version must be non-empty and contain only letters, numbers, and dots."
            )

        return f"{project_name}-{version}-{mode}"

    def validate_project_key(self, project_key: str) -> bool:
        """Validate project_key format."""
        return is_valid_project_key(project_key)

    def list_available_pools(self) -> list[str]:
        pools_dir = self._root_dir / "pools"
        if not pools_dir.exists():
            return []

        available: list[str] = []
        for entry in sorted(pools_dir.iterdir(), key=lambda item: item.name):
            if not entry.is_dir():
                continue
            if any((entry / box_name).is_dir() for box_name in ("Queue", "Outbox", "Rejectbox")):
                available.append(entry.name)
        return available

    def get_default_route(self) -> list[str]:
        return self._policy.get_active_route()

    def list_available_modes(self) -> list[str]:
        return self._policy.list_modes()

    def get_default_mode(self) -> str:
        return self._policy.get_default_mode()

    def get_pool_description(self, pool_name: str) -> str:
        return self._policy.get_pool_description(pool_name)

    def validate_target_pool(self, target_pool: str) -> str:
        """Validate if the target pool exists in the workspace."""
        if not target_pool:
            raise InvalidInputError("Target pool cannot be empty")

        available_pools = self.list_available_pools()
        if target_pool not in available_pools:
            raise InvalidInputError(
                f"Invalid target pool: '{target_pool}'. Available pools are: {', '.join(available_pools)}"
            )
        return target_pool

    def parse_route(self, route: list[str] | None, target_pool: str) -> list[str]:
        if route:
            parsed_route = [segment.strip() for segment in route if segment and segment.strip()]
        else:
            validated_target_pool = self.validate_target_pool(target_pool)
            parsed_route = ["task", validated_target_pool]

        if len(parsed_route) < 2:
            raise InvalidInputError("Route must contain at least two pools")
        if parsed_route[0] != "task":
            raise InvalidInputError("UI registration route must start from 'task'")

        available_pools = set(self.list_available_pools())
        invalid_pools = [pool for pool in parsed_route if pool not in available_pools]
        if invalid_pools:
            raise InvalidInputError(
                f"Unknown pool(s) in route: {', '.join(invalid_pools)}. Available pools are: {', '.join(sorted(available_pools))}"
            )

        return parsed_route

    def ensure_queue_directory_ready(self) -> Path:
        """Pre-check that the task Outbox directory is available before registration."""
        queue_dir = self._root_dir / "pools" / "task" / "Outbox"

        try:
            queue_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise InvalidInputError(f"Queue directory is not writable: {queue_dir}") from exc

        if not queue_dir.is_dir():
            raise InvalidInputError(f"Queue path is not a directory: {queue_dir}")

        return queue_dir

    def write_queue_file(self, project_key: str, target_pool: str, mode: str, requirements: str) -> Path:
        """Write a Queue file for the given project registration input."""
        # [Architecture Fix] Write to task/Outbox, name it exactly as project_key.txt
        queue_dir = self._root_dir / "pools" / "task" / "Outbox"
        queue_dir.mkdir(parents=True, exist_ok=True)

        queue_file_path = queue_dir / f"{project_key}.txt"
        content = (
            f"PROJECT_KEY: {project_key}\n"
            "SOURCE_POOL: task\n"
            f"TARGET_POOL: {target_pool}\n"
            f"MODE: {mode}\n"
            "\n"
            f"{requirements}"
        )
        queue_file_path.write_text(content, encoding="utf-8")
        return queue_file_path

    def register(
        self,
        project_name: str,
        version: str,
        mode: str,
        target_pool: str,
        requirements: str,
        route: list[str] | None = None,
    ) -> dict:
        """Execute full registration flow."""
        try:
            project_key = self.build_project_key(project_name, version, mode)
            route = self.parse_route(route, target_pool)
            immediate_target = route[1]

            if not self.validate_project_key(project_key):
                raise InvalidInputError(f"Invalid project_key format: {project_key}")

            from app.services.post_registry import PostRegistry

            registry = PostRegistry(self._root_dir)

            existing_project = registry.get_project(project_key)
            if existing_project is not None:
                raise InvalidInputError(f"Project already exists: {project_key}")

            self.ensure_queue_directory_ready()

            registry.register_project(
                project_key=project_key,
                from_pool=route[0],
                to_pool=immediate_target,
                route=route,
            )

            queue_file = self.write_queue_file(
                project_key=project_key,
                target_pool=immediate_target,
                mode=mode,
                requirements=requirements,
            )

            return {
                "success": True,
                "project_key": project_key,
                "target_pool": immediate_target,
                "route": route,
                "queue_file": str(queue_file),
            }
        except InvalidInputError as exc:
            return {"success": False, "error": str(exc)}
        except Exception as exc:
            return {"success": False, "error": f"Registration failed: {str(exc)}"}
