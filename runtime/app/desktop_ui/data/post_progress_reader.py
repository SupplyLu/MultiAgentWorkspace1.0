"""Read POST project progress data for the desktop UI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class PostProgressReader:
    def __init__(self, transfers_dir: Path | str):
        self._transfers_dir = Path(transfers_dir)
        self._index_file = self._transfers_dir / "post_index.json"
        self._projects_dir = self._transfers_dir / "projects"

    def get_progress(self) -> dict[str, Any]:
        if not self._index_file.exists():
            return {
                "percentage": 0,
                "completed": 0,
                "total": 0,
                "current_pool": None,
                "stage": "idle",
                "blocked": False,
                "block_reason": None,
                "active_registrations": 0,
                "waiting_payload_registrations": 0,
                "blocked_registrations": 0,
                "delivered_registrations": 0,
            }

        index_data = json.loads(self._index_file.read_text(encoding="utf-8"))
        project_keys = index_data.get("projects", [])

        completed = 0
        total = 0
        current_pool = None
        blocked = False
        block_reason = None
        stage = "idle"
        active_registrations = 0
        waiting_payload_registrations = 0
        blocked_registrations = 0
        delivered_registrations = 0

        for project_key in project_keys:
            project_file = self._projects_dir / f"{project_key}.json"

            if not project_file.exists():
                continue

            project_data = json.loads(project_file.read_text(encoding="utf-8"))

            total += 1
            current_pool = project_data.get("current_pool") or current_pool
            status = project_data.get("status")

            if status == "in_progress":
                stage = "processing"
                active_registrations += 1
            elif status == "waiting":
                stage = "processing"
                waiting_payload_registrations += 1
            elif status == "blocked":
                stage = "blocked"
                blocked = True
                blocked_registrations += 1
                if not block_reason:
                    block_reason = project_data.get("blocked_reason") or "Project processing failed"
            elif status == "delivered":
                completed += 1
                delivered_registrations += 1

        percentage = int((completed / total) * 100) if total else 0

        return {
            "percentage": percentage,
            "completed": completed,
            "total": total,
            "current_pool": current_pool,
            "stage": stage,
            "blocked": blocked,
            "block_reason": block_reason,
            "active_registrations": active_registrations,
            "waiting_payload_registrations": waiting_payload_registrations,
            "blocked_registrations": blocked_registrations,
            "delivered_registrations": delivered_registrations,
        }
