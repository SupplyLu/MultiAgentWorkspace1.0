"""POST Runtime - Scan-based orchestrator for cross-pool batch delivery."""

import time
from pathlib import Path

from app.services.post_registry import PostRegistry


class PostRuntime:
    """POST Runtime scans registry and filesystem to deliver completed batches."""

    def __init__(self, root_dir: Path | str, scan_interval_seconds: int = 60):
        self.root_dir = Path(root_dir)
        self.scan_interval_seconds = scan_interval_seconds
        self._registry = PostRegistry(root_dir=self.root_dir)

    def scan_once(self):
        """Perform one scan cycle: check branch completion, dependencies, and deliver."""
        batch_ids = self._registry.list_batches()

        for batch_id in batch_ids:
            batch = self._registry.get_batch(batch_id)
            if batch is None:
                continue

            if batch["status"] == "blocked":
                continue

            branches = self._registry.get_branches(batch_id)

            for branch in branches:
                if branch["status"] == "pending":
                    outbox_path = Path(branch["outbox_path"])
                    if outbox_path.exists():
                        # Branch is done if there is any .txt file OR any directory
                        has_txt = bool(list(outbox_path.glob("*.txt")))
                        has_dir = any(item.is_dir() for item in outbox_path.iterdir())

                        if has_txt or has_dir:
                            self._registry.update_branch(
                                batch_id=batch_id,
                                branch_id=branch["branch_id"],
                                updates={
                                    "status": "done",
                                    "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                },
                            )

            batch = self._registry.get_batch(batch_id)
            branches = self._registry.get_branches(batch_id)
            if self._batch_ready(batch, branches):
                if not self._dependencies_satisfied(batch_id):
                    if batch["status"] != "waiting":
                        self._registry.update_batch(batch_id, {"status": "waiting"})
                    continue

                for branch in branches:
                    self._deliver_branch_to_queue(batch, branch)
                self._registry.update_batch(batch_id, {"status": "delivered"})

    def _dependencies_satisfied(self, batch_id: str) -> bool:
        deps = self._registry.get_dependencies(batch_id)
        for dep in deps:
            source_batch = self._registry.get_batch(dep["source_batch_id"])
            if not source_batch:
                return False
            if dep["rule"] == "after_delivered" and source_batch["status"] != "delivered":
                return False
        return True

    def _batch_ready(self, batch: dict, branches: list[dict]) -> bool:
        return batch.get("status") != "delivered" and all(branch.get("status") == "done" for branch in branches)

    def _deliver_branch_to_queue(self, batch: dict, branch: dict) -> Path:
        import shutil

        queue_dir = self.root_dir / "pools" / batch["to_pool"] / "Queue"
        queue_dir.mkdir(parents=True, exist_ok=True)

        outbox_path = Path(branch["outbox_path"])

        # Check if there's a directory payload first (higher priority)
        dir_payloads = [item for item in outbox_path.iterdir() if item.is_dir()] if outbox_path.exists() else []

        if dir_payloads:
            # Deliver the first directory payload
            source_dir = dir_payloads[0]
            # Use branch_id prefix to ensure unique naming in queue
            delivery_path = queue_dir / f"{branch['branch_id']}_{source_dir.name}"

            # Remove if exists (to handle retries safely)
            if delivery_path.exists():
                shutil.rmtree(delivery_path)

            shutil.copytree(source_dir, delivery_path)
        else:
            # Fallback to .txt delivery
            delivery_path = queue_dir / f"task_{branch['branch_id']}.txt"
            delivery_path.write_text(branch.get("task_body", ""), encoding="utf-8")

        self._registry.record_transfer(
            batch_id=batch["batch_id"],
            branch_id=branch["branch_id"],
            from_pool=batch["from_pool"],
            to_pool=batch["to_pool"],
            delivery_address=str(delivery_path),
            status="delivered",
        )
        return delivery_path
