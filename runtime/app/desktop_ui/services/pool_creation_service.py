"""Pool Creation Service - creates new runtime pools with standard structure.

Generates pool directories, BAT files, bootstrap files, and state machine definitions,
then registers the pool metadata for UI visibility.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from app.desktop_ui.services.pool_registry_service import PoolRegistryService


FLOW_TEMPLATES: dict[str, dict[str, Any]] = {
    "simple_work": {
        "label": "Simple Work",
        "actions": ["working"],
    },
    "review": {
        "label": "Review",
        "actions": ["review"],
    },
    "thinking": {
        "label": "Thinking",
        "actions": ["thinking", "summarizing"],
    },
}


class PoolCreationError(Exception):
    """Raised when pool creation fails validation or execution."""


class PoolCreationService:
    """Creates new runtime pools with standard directory structure and configuration."""

    def __init__(self, root_dir: Path | str):
        self._root_dir = Path(root_dir)
        self._registry_service = PoolRegistryService(root_dir)
        self._runtime_template_dir = self._root_dir / "runtime_template"

    def list_flow_templates(self) -> list[dict[str, str]]:
        return [
            {"id": key, "label": value["label"]}
            for key, value in FLOW_TEMPLATES.items()
        ]

    def build_action_steps_from_template(self, template_id: str) -> list[str]:
        template = FLOW_TEMPLATES.get(template_id)
        if not template:
            raise PoolCreationError(f"Unknown flow template: {template_id}")
        return list(template.get("actions", []))

    def _normalize_action_signal(self, action_text: str, index: int) -> str:
        slug = re.sub(r"[^a-z0-9]+", "_", action_text.strip().lower()).strip("_")
        if not slug:
            slug = f"step_{index:02d}"
        return slug

    def build_stage_signals_from_actions(self, action_steps: list[str]) -> list[str]:
        return [
            self._normalize_action_signal(action_text, index)
            for index, action_text in enumerate(action_steps, start=1)
        ]

    def build_state_machine_from_actions(self, pool_name: str, action_steps: list[str]) -> dict[str, Any]:
        stage_signals = self.build_stage_signals_from_actions(action_steps)
        transitions: list[dict[str, Any]] = [
            {
                "from_state": "state_0",
                "to_state": "state_1",
                "allowed_signals": ["online"],
                "description": "idle -> online",
            }
        ]

        current_state = 1
        if not stage_signals:
            transitions.append(
                {
                    "from_state": "state_1",
                    "to_state": "state_done",
                    "allowed_signals": ["done"],
                    "description": "online -> done",
                }
            )
        else:
            for index, signal in enumerate(stage_signals, start=1):
                transitions.append(
                    {
                        "from_state": f"state_{current_state}",
                        "to_state": f"state_{current_state + 1}",
                        "allowed_signals": [signal],
                        "description": f"step {index}: {action_steps[index - 1]}",
                    }
                )
                current_state += 1

            transitions.append(
                {
                    "from_state": f"state_{current_state}",
                    "to_state": "state_done",
                    "allowed_signals": ["done"],
                    "description": "final -> done",
                }
            )

        return {
            "pool_id": pool_name,
            "initial_state": "state_0",
            "terminal_states": ["state_done"],
            "transitions": transitions,
        }

    def validate_pool_name(self, pool_name: str) -> str:
        """Validate pool name: alphanumeric + underscore only, no conflicts."""
        if not pool_name:
            raise PoolCreationError("Pool name cannot be empty")

        if not re.match(r"^[a-z][a-z0-9_]*$", pool_name):
            raise PoolCreationError(
                "Pool name must start with lowercase letter and contain only lowercase letters, numbers, and underscores"
            )

        if len(pool_name) > 32:
            raise PoolCreationError("Pool name too long (max 32 characters)")

        existing = self._registry_service.get_pool_meta(pool_name)
        if existing:
            raise PoolCreationError(f"Pool already exists: {pool_name}")

        return pool_name

    def validate_slot_prefix(self, slot_prefix: str) -> str:
        """Validate slot prefix: alphanumeric + underscore, must end with underscore."""
        if not slot_prefix:
            raise PoolCreationError("Slot prefix cannot be empty")

        if not re.match(r"^[a-z][a-z0-9_]*_$", slot_prefix):
            raise PoolCreationError(
                "Slot prefix must start with lowercase letter, contain only lowercase letters/numbers/underscores, and end with underscore"
            )

        return slot_prefix

    def create_pool_directories(
        self,
        pool_name: str,
        slot_prefix: str,
        slot_count: int,
        include_rejectbox: bool = False,
    ) -> Path:
        """Create standard pool directory structure."""
        pool_dir = self._root_dir / "pools" / pool_name

        if pool_dir.exists():
            raise PoolCreationError(f"Pool directory already exists: {pool_dir}")

        (pool_dir / "Queue").mkdir(parents=True, exist_ok=True)
        (pool_dir / "Outbox").mkdir(parents=True, exist_ok=True)
        (pool_dir / "fields").mkdir(parents=True, exist_ok=True)

        if include_rejectbox:
            (pool_dir / "Rejectbox").mkdir(parents=True, exist_ok=True)

        for i in range(1, slot_count + 1):
            slot_id = f"{slot_prefix}{i:02d}"
            slot_workspace = pool_dir / slot_id / "workspace"
            slot_workspace.mkdir(parents=True, exist_ok=True)

        return pool_dir

    def generate_bat_files(
        self,
        pool_name: str,
        custom_stage_signals: list[str] | None = None,
    ) -> None:
        """Generate lifecycle BAT files for the pool."""
        tools_dir = self._root_dir / "runtime" / "tools"
        template_dir = self._runtime_template_dir / "tools"

        standard_bats = ["Online", "Done", "Blocked", "Failed"]
        for bat_name in standard_bats:
            template_path = template_dir / f"{bat_name}.bat.template"
            if template_path.exists():
                target_path = tools_dir / f"{bat_name}.bat"
                if not target_path.exists():
                    shutil.copy(template_path, target_path)

        if custom_stage_signals:
            for signal in custom_stage_signals:
                bat_content = f"""@echo off
setlocal enabledelayedexpansion

set AGENT_ID=%1
set TASK_ID=%2
set SIGNAL={signal}
set POOL=%3
set MESSAGE=%4

python "%~dp0signal_bridge.py" --agent-id %AGENT_ID% --task-id %TASK_ID% --signal %SIGNAL% --pool %POOL% --message %MESSAGE%

endlocal
"""
                bat_name = "".join(word.capitalize() for word in signal.split("_"))
                if not bat_name.startswith("Start"):
                    bat_name = f"Start{bat_name}"

                bat_path = tools_dir / f"{bat_name}.bat"
                bat_path.write_text(bat_content, encoding="utf-8")

    def generate_bootstrap_file(
        self,
        pool_name: str,
        bootstrap_content: str,
    ) -> Path:
        """Generate bootstrap file for the pool."""
        tools_dir = self._root_dir / "runtime" / "tools"
        bootstrap_name = f"{pool_name.upper()}_BOOTSTRAP.txt"
        bootstrap_path = tools_dir / bootstrap_name

        bootstrap_path.write_text(bootstrap_content, encoding="utf-8")
        return bootstrap_path

    def generate_state_machine_file(
        self,
        pool_name: str,
        state_machine_json: dict[str, Any],
    ) -> Path:
        """Generate state machine definition file for the pool."""
        state_dir = self._root_dir / "runtime" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)

        state_machine_path = state_dir / f"{pool_name}_state_machine.json"
        with open(state_machine_path, "w", encoding="utf-8") as f:
            json.dump(state_machine_json, f, indent=2, ensure_ascii=False)

        return state_machine_path

    def create_pool(
        self,
        pool_name: str,
        display_name: str,
        slot_prefix: str,
        slot_count: int,
        bootstrap_content: str,
        flow_template_id: str,
        action_steps: list[str] | None = None,
        include_rejectbox: bool = False,
    ) -> dict[str, Any]:
        """Create a new pool with all necessary files and metadata.

        Returns:
            {"success": bool, "error": str | None, "pool_id": str | None}
        """
        try:
            pool_name = self.validate_pool_name(pool_name)
            slot_prefix = self.validate_slot_prefix(slot_prefix)

            if slot_count < 1 or slot_count > 99:
                raise PoolCreationError("Slot count must be between 1 and 99")

            if not display_name:
                display_name = pool_name.replace("_", " ").title()

            if action_steps is None:
                action_steps = self.build_action_steps_from_template(flow_template_id)
            action_steps = [step.strip() for step in action_steps if step and step.strip()]
            state_machine_json = self.build_state_machine_from_actions(pool_name, action_steps)
            custom_stage_signals = self.build_stage_signals_from_actions(action_steps)

            pool_dir = self.create_pool_directories(
                pool_name=pool_name,
                slot_prefix=slot_prefix,
                slot_count=slot_count,
                include_rejectbox=include_rejectbox,
            )

            self.generate_bat_files(
                pool_name=pool_name,
                custom_stage_signals=custom_stage_signals,
            )

            bootstrap_path = self.generate_bootstrap_file(
                pool_name=pool_name,
                bootstrap_content=bootstrap_content,
            )

            state_machine_path = self.generate_state_machine_file(
                pool_name=pool_name,
                state_machine_json=state_machine_json,
            )
            state_machine_file = state_machine_path.name

            pool_meta = {
                "pool_id": pool_name,
                "display_name": display_name,
                "builtin": False,
                "slot_prefixes": [slot_prefix],
                "bootstrap_files": [
                    {
                        "name": f"{pool_name.upper()}_BOOTSTRAP",
                        "label": display_name,
                        "file": bootstrap_path.name,
                    }
                ],
            }

            if state_machine_file:
                pool_meta["state_machine_file"] = state_machine_file

            success = self._registry_service.register_pool(pool_meta)
            if not success:
                raise PoolCreationError("Failed to register pool metadata")

            return {
                "success": True,
                "error": None,
                "pool_id": pool_name,
                "pool_dir": str(pool_dir),
            }

        except PoolCreationError as e:
            return {
                "success": False,
                "error": str(e),
                "pool_id": None,
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Unexpected error: {str(e)}",
                "pool_id": None,
            }