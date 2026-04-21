import json
import time
import uuid
from pathlib import Path
from typing import Any

from app.shared.json_store import JSONStore


class PostRegistry:
    def __init__(self, root_dir: Path | str):
        self._root_dir = Path(root_dir)
        self._transfers_dir = self._root_dir / "transfers"
        self._batches_dir = self._transfers_dir / "batches"
        self._dependencies_dir = self._transfers_dir / "dependencies"
        self._records_dir = self._transfers_dir / "transfers"
        self._actions_dir = self._transfers_dir / "manager_actions"

        for path in (
            self._batches_dir,
            self._dependencies_dir,
            self._records_dir,
            self._actions_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

        self._index_store = JSONStore(
            self._transfers_dir / "post_index.json",
            default_factory=lambda: {
                "batches": [],
                "dependencies": [],
                "transfers": [],
                "manager_actions": [],
            },
        )
        self._index_store.ensure_initialized()

    def _batch_file(self, batch_id: str) -> Path:
        return self._batches_dir / f"{batch_id}.json"

    def _branches_file(self, batch_id: str) -> Path:
        return self._batches_dir / f"{batch_id}_branches.json"

    def _dependencies_file(self, target_batch_id: str) -> Path:
        return self._dependencies_dir / f"{target_batch_id}.json"

    def _transfer_file(self, transfer_id: str) -> Path:
        return self._records_dir / f"{transfer_id}.json"

    def _manager_action_file(self, action_id: str) -> Path:
        return self._actions_dir / f"{action_id}.json"

    def register_batch(
        self,
        batch_id: str,
        name: str,
        from_pool: str,
        to_pool: str,
        branches: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Register a new batch and its branches. Idempotent - returns existing batch if already registered."""
        # Check if batch already exists
        existing_batch = self.get_batch(batch_id)
        if existing_batch is not None:
            return existing_batch

        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        # Prepare batch data
        batch_data = {
            "batch_id": batch_id,
            "name": name,
            "from_pool": from_pool,
            "to_pool": to_pool,
            "status": "registered",
            "branches": [b["branch_id"] for b in branches],
            "created_at": now,
            "updated_at": now,
        }

        # Prepare branch data
        branch_data_list = []
        for b in branches:
            branch_data = {
                "branch_id": b["branch_id"],
                "batch_id": batch_id,
                "feature_id": b.get("feature_id", ""),
                "from_pool": b.get("from_pool", from_pool),
                "to_pool": b.get("to_pool", to_pool),
                "task_body": b.get("task_body", ""),
                "status": "pending",
                "outbox_path": b.get("outbox_path", ""),
                "outbox_checked_at": None,
                "created_at": now,
                "completed_at": None,
            }
            branch_data_list.append(branch_data)

        # Write to files using JSONStore for atomic writes
        batch_store = JSONStore(self._batch_file(batch_id), default_factory=lambda: batch_data)
        batch_store.ensure_initialized()
        batch_store.write(batch_data)

        branches_store = JSONStore(self._branches_file(batch_id), default_factory=lambda: branch_data_list)
        branches_store.ensure_initialized()
        branches_store.write(branch_data_list)

        # Update index
        def update_index(data):
            if batch_id not in data["batches"]:
                data["batches"].append(batch_id)
            return data
        self._index_store.update(update_index)

        return batch_data

    def get_batch(self, batch_id: str) -> dict[str, Any] | None:
        """Get batch data by ID."""
        file_path = self._batch_file(batch_id)
        if not file_path.exists():
            return None
        return json.loads(file_path.read_text(encoding="utf-8"))

    def get_branches(self, batch_id: str) -> list[dict[str, Any]]:
        """Get all branches for a batch."""
        file_path = self._branches_file(batch_id)
        if not file_path.exists():
            return []
        return json.loads(file_path.read_text(encoding="utf-8"))

    def list_batches(self) -> list[str]:
        """List all registered batch IDs."""
        index_data = self._index_store.read()
        return index_data.get("batches", [])

    def add_dependency(
        self,
        source_batch_id: str,
        target_batch_id: str,
        rule: str,
    ) -> dict[str, Any]:
        """Add a dependency record. Target batch depends on source batch."""
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        dependency_data = {
            "source_batch_id": source_batch_id,
            "target_batch_id": target_batch_id,
            "rule": rule,
            "satisfied": False,
            "satisfied_at": "",
            "created_at": now,
        }

        # Load existing dependencies for target batch
        dep_file = self._dependencies_file(target_batch_id)
        if dep_file.exists():
            existing_deps = json.loads(dep_file.read_text(encoding="utf-8"))
        else:
            existing_deps = []

        # Append new dependency
        existing_deps.append(dependency_data)

        # Write back
        dep_store = JSONStore(dep_file, default_factory=lambda: existing_deps)
        dep_store.ensure_initialized()
        dep_store.write(existing_deps)

        # Update index
        def update_index(data):
            dep_key = f"{source_batch_id}->{target_batch_id}"
            if dep_key not in data["dependencies"]:
                data["dependencies"].append(dep_key)
            return data
        self._index_store.update(update_index)

        return dependency_data

    def get_dependencies(self, target_batch_id: str) -> list[dict[str, Any]]:
        """Get all dependencies for a target batch."""
        dep_file = self._dependencies_file(target_batch_id)
        if not dep_file.exists():
            return []
        return json.loads(dep_file.read_text(encoding="utf-8"))

    def record_transfer(
        self,
        batch_id: str,
        branch_id: str,
        from_pool: str,
        to_pool: str,
        delivery_address: str,
        status: str,
    ) -> dict[str, Any]:
        """Record a transfer/delivery event."""
        transfer_id = str(uuid.uuid4())
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        transfer_data = {
            "transfer_id": transfer_id,
            "batch_id": batch_id,
            "branch_id": branch_id,
            "from_pool": from_pool,
            "to_pool": to_pool,
            "delivery_address": delivery_address,
            "status": status,
            "created_at": now,
        }

        # Write transfer file
        transfer_store = JSONStore(self._transfer_file(transfer_id), default_factory=lambda: transfer_data)
        transfer_store.ensure_initialized()
        transfer_store.write(transfer_data)

        # Update index
        def update_index(data):
            data["transfers"].append(transfer_id)
            return data
        self._index_store.update(update_index)

        return transfer_data

    def list_transfers(self, batch_id: str | None = None) -> list[dict[str, Any]]:
        """List all transfers, optionally filtered by batch_id."""
        index_data = self._index_store.read()
        transfer_ids = index_data.get("transfers", [])

        transfers = []
        for transfer_id in transfer_ids:
            transfer_file = self._transfer_file(transfer_id)
            if transfer_file.exists():
                transfer_data = json.loads(transfer_file.read_text(encoding="utf-8"))
                if batch_id is None or transfer_data.get("batch_id") == batch_id:
                    transfers.append(transfer_data)

        return transfers

    def record_manager_action(
        self,
        batch_id: str,
        action_type: str,
        detail: str,
    ) -> dict[str, Any]:
        """Record a manager action (hold, resume, merge, etc.)."""
        action_id = str(uuid.uuid4())
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        action_data = {
            "action_id": action_id,
            "batch_id": batch_id,
            "action_type": action_type,
            "detail": detail,
            "created_at": now,
        }

        # Write action file
        action_store = JSONStore(self._manager_action_file(action_id), default_factory=lambda: action_data)
        action_store.ensure_initialized()
        action_store.write(action_data)

        # Update index
        def update_index(data):
            data["manager_actions"].append(action_id)
            return data
        self._index_store.update(update_index)

        return action_data

    def list_manager_actions(self, batch_id: str | None = None) -> list[dict[str, Any]]:
        """List all manager actions, optionally filtered by batch_id."""
        index_data = self._index_store.read()
        action_ids = index_data.get("manager_actions", [])

        actions = []
        for action_id in action_ids:
            action_file = self._manager_action_file(action_id)
            if action_file.exists():
                action_data = json.loads(action_file.read_text(encoding="utf-8"))
                if batch_id is None or action_data.get("batch_id") == batch_id:
                    actions.append(action_data)

        return actions

    def update_branch(self, batch_id: str, branch_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        """Update specific fields of a branch."""
        branches = self.get_branches(batch_id)
        for i, branch in enumerate(branches):
            if branch["branch_id"] == branch_id:
                branches[i].update(updates)
                branches_store = JSONStore(self._branches_file(batch_id), default_factory=lambda: branches)
                branches_store.ensure_initialized()
                branches_store.write(branches)
                return branches[i]
        return None

    def update_batch(self, batch_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        """Update specific fields of a batch."""
        batch = self.get_batch(batch_id)
        if batch is None:
            return None
        batch.update(updates)
        batch_store = JSONStore(self._batch_file(batch_id), default_factory=lambda: batch)
        batch_store.ensure_initialized()
        batch_store.write(batch)
        return batch



