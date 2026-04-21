from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.shared.windows_process import kill_process, terminate_job


@dataclass(slots=True)
class ShutdownRequest:
    worker_id: str
    pid: int | None = None
    job_handle: Any | None = None
    reason: str = "manual"
    timeout_seconds: float = 5.0


_SHUTDOWN_TASK_TEMPLATE = """\
FROM: runtime
TO: {agent_id}
TASK_ID: shutdown_{agent_id}
TYPE: SHUTDOWN

Graceful shutdown requested by runtime.
"""


class ShutdownManager:
    """Shutdown orchestration manager."""

    def _terminate_job_handle(self, job_handle: Any, dry_run: bool) -> dict[str, Any]:
        if dry_run:
            return {"job_terminated": True, "dry_run": True, "job_handle": job_handle}
        return {
            "job_terminated": terminate_job(job_handle),
            "dry_run": False,
            "job_handle": job_handle,
        }

    def __init__(
        self,
        event_bus: Any | None = None,
        registry_manager: Any | None = None,
        ownership_manager: Any | None = None,
        workspace_root: str | Path | None = None,
    ) -> None:
        self.event_bus = event_bus
        self.registry_manager = registry_manager
        self.ownership_manager = ownership_manager
        self.workspace_root = Path(workspace_root) if workspace_root is not None else None

    def request_shutdown(self, request: ShutdownRequest, dry_run: bool = False) -> dict[str, Any]:
        """
        Perform a graceful shutdown sequence:
        1. Write SHUTDOWN.txt to the agent's queue directory.
        2. Wait up to timeout_seconds for the agent to exit.
        3. Force-kill if not done.
        4. Mark registry status as 'shutdown'.
        5. Remove parent→child ownership link.
        """
        agent_id = request.worker_id

        if self.workspace_root is not None:
            shutdown_file = self.workspace_root / "agents" / agent_id / "queue" / "SHUTDOWN.txt"
            shutdown_file.parent.mkdir(parents=True, exist_ok=True)
            shutdown_file.write_text(
                _SHUTDOWN_TASK_TEMPLATE.format(agent_id=agent_id),
                encoding="utf-8",
            )

        time.sleep(request.timeout_seconds)

        still_running = False
        if self.registry_manager is not None:
            agent = self.registry_manager.get_agent(agent_id)
            if agent is not None:
                still_running = agent.get("status") not in {"shutdown", "completed"}

        termination_result: dict[str, Any] = {
            "job_terminated": False,
            "pid_killed": False,
        }
        if still_running:
            if request.job_handle is not None:
                termination_result = self._terminate_job_handle(request.job_handle, dry_run=dry_run)
            elif request.pid is not None:
                kill_result = kill_process(request.pid, force=True, dry_run=dry_run)
                termination_result = {
                    "job_terminated": False,
                    "pid_killed": kill_result.get("killed", False),
                    "result": kill_result,
                }

        if self.registry_manager is not None:
            try:
                self.registry_manager.update_agent_status(agent_id, "shutdown")
            except Exception:
                pass

        if self.ownership_manager is not None:
            try:
                self.ownership_manager.remove_agent(agent_id)
            except Exception:
                pass

        return {
            "worker_id": agent_id,
            "status": "shutdown",
            "dry_run": dry_run,
            **termination_result,
        }

    def request_soft_shutdown(self, request: ShutdownRequest) -> dict[str, Any]:
        payload = {
            "worker_id": request.worker_id,
            "pid": request.pid,
            "job_handle": request.job_handle,
            "reason": request.reason,
            "timeout_seconds": request.timeout_seconds,
            "mode": "soft",
        }
        if self.event_bus is not None:
            self.event_bus.publish("worker.shutdown_requested", payload, source=self.__class__.__name__)
        return payload

    def force_kill(self, request: ShutdownRequest, dry_run: bool = True) -> dict[str, Any]:
        if request.job_handle is not None:
            result = self._terminate_job_handle(request.job_handle, dry_run=dry_run)
            payload = {
                "worker_id": request.worker_id,
                "pid": request.pid,
                "job_handle": request.job_handle,
                "mode": "hard",
                "result": result,
            }
            if self.event_bus is not None:
                self.event_bus.publish("worker.force_killed", payload, source=self.__class__.__name__)
            return payload
        if request.pid is None:
            return {
                "worker_id": request.worker_id,
                "killed": False,
                "reason": "missing_pid",
                "mode": "hard",
            }
        result = kill_process(request.pid, force=True, dry_run=dry_run)
        payload = {
            "worker_id": request.worker_id,
            "pid": request.pid,
            "job_handle": request.job_handle,
            "mode": "hard",
            "result": result,
        }
        if self.event_bus is not None:
            self.event_bus.publish("worker.force_killed", payload, source=self.__class__.__name__)
        return payload

    def auto_cleanup_completed_worker(
        self,
        worker_id: str,
        pid: int | None,
        job_handle: Any | None = None,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        job_result = None
        pid_result = None

        if job_handle is not None:
            job_result = self._terminate_job_handle(job_handle, dry_run=dry_run)

        if pid is not None:
            pid_result = kill_process(pid, force=True, dry_run=dry_run, tree=True)

        if job_handle is None and pid is None:
            return {
                "worker_id": worker_id,
                "killed": False,
                "reason": "missing_pid",
                "mode": "auto_cleanup",
            }

        primary_result = job_result or pid_result
        return {
            "worker_id": worker_id,
            "pid": pid,
            "job_handle": job_handle,
            "mode": "auto_cleanup",
            "result": primary_result,
            "job_result": job_result,
            "pid_result": pid_result,
        }
