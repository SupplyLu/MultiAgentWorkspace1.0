"""WorkRuntime - Minimal orchestrator for the Work Pool."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import shutil
import time
import threading

from app.services.signal_server import RuntimeSignalServer
from app.services.slot_governance_store import SlotGovernanceStore
from app.shared.launch_manager import LaunchManager, LaunchRequest
from app.shared.shutdown_manager import ShutdownManager
from app.shared.file_queue import parse_task_file
from app.shared.json_store import JSONStore

PROJECT_MODE_LEGACY = "legacy"
PROJECT_MODE_STANDARD = "standard"
PROJECT_MODE_FREE = "free"
SUPPORTED_PROJECT_MODES = {
    PROJECT_MODE_LEGACY,
    PROJECT_MODE_STANDARD,
    PROJECT_MODE_FREE,
}

@dataclass(frozen=True)
class ProjectRootIndex:
    project_key: str
    project_root: Path

    def render_txt(self) -> str:
        return f"{self.project_root}\n"


@dataclass
class WorkerSlot:
    slot_id: str
    slot_dir: Path
    workspace_dir: Path
    busy: bool = False
    finalizing: bool = False
    assigned_task_id: str = ""
    launch_result: dict[str, Any] | None = None
    assigned_at_epoch: float = 0.0
    timeout_seconds: int = 300
    project_mode: str = PROJECT_MODE_LEGACY
    project_root: Path | None = None
    enabled: bool = True


def _escape_bat_var(s: str) -> str:
    """Escape Windows batch variable values to prevent command injection."""
    result = s.replace("%", "%%")
    result = result.replace("^", "^^")
    result = result.replace("&", "^&")
    result = result.replace("|", "^|")
    result = result.replace("<", "^<")
    result = result.replace(">", "^>")
    result = result.replace('"', '^"')
    result = result.replace("!", "^^!")
    return result


class WorkRuntime:
    def __init__(
        self,
        root_dir: Path | str,
        signal_port: int = 18765,
    ):
        self._root_dir = Path(root_dir)
        self._signal_port = signal_port

        # Core paths
        self._work_pool_dir = self._root_dir / "pools" / "work"
        self._queue_dir = self._work_pool_dir / "Queue"
        self._outbox_dir = self._work_pool_dir / "Outbox"

        # Worker slots
        self._slots: dict[str, WorkerSlot] = {}
        self._governance_store = SlotGovernanceStore(root_dir=self._root_dir)
        self._init_slots()

        # Signal server
        self._signal_server = RuntimeSignalServer(
            port=signal_port,
            event_store_dir=self._root_dir / "events",
        )
        self._signal_server.on_signal = self.handle_signal
        self._signal_server.on_api_request = self.handle_api_request

        # Managers and builders
        self._launch_manager = LaunchManager()

        # Lifecycle tools directory (can be overridden for testing)
        self._lifecycle_tools_dir = self._root_dir / "runtime" / "tools"

        # Lock to protect slot state from concurrent access
        self._lock = threading.RLock()

        # Pause control state
        self._paused = False

    def _init_slots(self) -> None:
        """Initialize worker slots from the pool directory structure.
        Any directory under work pool containing a 'workspace' subdirectory is considered a slot.
        """
        if not self._work_pool_dir.exists():
            return

        for slot_dir in self._work_pool_dir.iterdir():
            if not slot_dir.is_dir():
                continue

            # A slot must have a workspace directory
            workspace_dir = slot_dir / "workspace"
            if not workspace_dir.exists() or not workspace_dir.is_dir():
                continue

            slot_id = slot_dir.name
            enabled = self._governance_store.is_enabled("work", slot_id)
            self._slots[slot_id] = WorkerSlot(
                slot_id=slot_id,
                slot_dir=slot_dir,
                workspace_dir=workspace_dir,
                busy=False,
                assigned_task_id="",
                launch_result=None,
                enabled=enabled,
            )

    def _deploy_lifecycle_bats(self, slot: WorkerSlot) -> None:
        """Copy lifecycle bats and signal bridge into worker slot directory."""
        tools_dir = self._lifecycle_tools_dir
        if not tools_dir.exists():
            raise FileNotFoundError(f"Missing lifecycle tools directory: {tools_dir}")

        lifecycle_files = [
            "Online.bat",
            "StartWriting.bat",
            "Done.bat",
            "signal_bridge.py",
            "WORK_BOOTSTRAP.txt",
        ]
        for file_name in lifecycle_files:
            src = tools_dir / file_name
            if not src.exists():
                raise FileNotFoundError(f"Missing required lifecycle tool: {src}")
            dst = slot.slot_dir / file_name
            dst.write_bytes(src.read_bytes())

    def get_next_idle_slot(self) -> WorkerSlot | None:
        """Return the lowest-numbered idle slot, or None if all are busy."""
        with self._lock:
            worker_ids = sorted(self._slots.keys())
            for worker_id in worker_ids:
                slot = self._slots[worker_id]
                if slot.enabled and not slot.busy and not slot.finalizing:
                    return slot
            return None

    def get_slot(self, slot_id: str) -> WorkerSlot | None:
        """Get a specific slot by ID."""
        return self._slots.get(slot_id)

    def list_queue_tasks(self) -> list[Path]:
        """List all .txt files in the Queue directory, ignoring hidden files."""
        if not self._queue_dir.exists():
            return []

        tasks = []
        for f in self._queue_dir.iterdir():
            if f.is_file() and f.suffix == ".txt" and not f.name.startswith("."):
                tasks.append(f)
        return sorted(tasks)

    def _rollback_dispatch(
        self,
        slot: WorkerSlot,
        task_file: Path,
        original_name: str,
        raw_content: str,
    ) -> None:
        """
        Roll back a failed dispatch: restore queue task file and reset slot.

        Called when _deploy_lifecycle_bats() or LaunchManager.launch() raises.
        The task file has been renamed to .processing; this renames it back.
        """
        # Restore task to queue
        queue_dir = self._queue_dir
        restored = queue_dir / original_name
        try:
            task_file.rename(restored)
        except OSError:
            # If rename back fails, write the content directly
            restored.write_text(raw_content, encoding="utf-8")

        # Remove any worker task file that was copied
        worker_task = slot.slot_dir / original_name
        if worker_task.exists():
            worker_task.unlink()

        # Clean all deployed files from slot, keep workspace
        self._clean_slot_dir(slot)

        # Reset slot fields
        slot.busy = False
        slot.finalizing = False
        slot.assigned_task_id = ""
        slot.launch_result = None
        slot.assigned_at_epoch = 0.0
        slot.timeout_seconds = 300
        slot.project_mode = PROJECT_MODE_LEGACY
        slot.project_root = None

    def _parse_timeout_seconds(self, headers: dict[str, Any]) -> int:
        """Parse TIMEOUT header safely with 300-second default and boundary limits."""
        raw_timeout = headers.get("TIMEOUT", 300)
        try:
            timeout_seconds = int(raw_timeout)
        except (TypeError, ValueError):
            return 300

        # Enforce boundaries (min 60s, max 24h)
        if timeout_seconds < 60:
            return 60
        if timeout_seconds > 86400:
            return 86400
        return timeout_seconds

    def _resolve_project_execution_context(self, headers: dict[str, Any]) -> tuple[str, Path | None]:
        raw_mode = str(headers.get("PROJECT_MODE", "")).strip().lower()
        if not raw_mode:
            return PROJECT_MODE_LEGACY, None
        if raw_mode not in SUPPORTED_PROJECT_MODES:
            raise ValueError(f"Invalid PROJECT_MODE: {raw_mode}")
        if raw_mode == PROJECT_MODE_STANDARD:
            raw_root = str(headers.get("PROJECT_ROOT", "")).strip()
            if not raw_root:
                raise ValueError("PROJECT_ROOT is required when PROJECT_MODE=standard")
            project_root = Path(raw_root)
            if not project_root.is_absolute():
                raise ValueError("PROJECT_ROOT must be an absolute path when PROJECT_MODE=standard")
            return PROJECT_MODE_STANDARD, project_root
        if raw_mode == PROJECT_MODE_FREE:
            return PROJECT_MODE_FREE, None
        return PROJECT_MODE_LEGACY, None

    def write_project_root_index(self, project_key: str, project_root: Path) -> dict[str, Any]:
        if not project_root.exists():
            return {"written": False, "reason": "project_root_not_found", "project_root": str(project_root)}
        index = ProjectRootIndex(project_key=project_key, project_root=project_root)
        index_file = self._outbox_dir / f"{project_key}.txt"
        index_file.parent.mkdir(parents=True, exist_ok=True)
        index_file.write_text(index.render_txt(), encoding="utf-8")
        return {
            "written": True,
            "project_key": project_key,
            "index_file": str(index_file),
            "project_root": str(project_root),
        }

    def _finalize_done_payload(self, slot: WorkerSlot, task_id: str) -> dict[str, Any]:
        if slot.project_mode == PROJECT_MODE_STANDARD:
            if slot.project_root is None:
                return {"written": False, "reason": "project_root_missing"}
            return self.write_project_root_index(task_id, slot.project_root)
        if slot.project_mode == PROJECT_MODE_FREE:
            return {"skipped": True, "reason": "no_artifacts_for_free_mode", "project_mode": slot.project_mode}
        return self.collect_artifacts_to_outbox(slot.slot_id, task_id)

    def dispatch_next(self, dry_run: bool = True) -> dict[str, Any]:
        """Dispatch the next task to an idle worker slot."""
        if self._paused:
            return {"dispatched": False, "error": "Runtime is paused"}

        # Find next idle slot and mark it busy immediately under lock
        slot = None
        task_file = None
        original_name = ""
        raw_content = ""
        with self._lock:
            worker_ids = sorted(self._slots.keys())
            for worker_id in worker_ids:
                candidate = self._slots[worker_id]
                if candidate.enabled and not candidate.busy:
                    candidate.busy = True
                    slot = candidate
                    break

            if slot is not None:
                # Find next task in queue and claim it under the same lock
                tasks = self.list_queue_tasks()
                if not tasks:
                    slot.busy = False
                    slot = None
                else:
                    task_file = tasks[0]
                    # Claim by renaming to .processing; keep reference for rollback
                    processing_file = task_file.with_name(task_file.name + ".processing")
                    try:
                        task_file.rename(processing_file)
                        task_file = processing_file
                    except OSError:
                        # Fallback if rename fails
                        slot.busy = False
                        slot = None

        if slot is None:
            if not self.list_queue_tasks():
                return {"dispatched": False, "error": "No tasks in queue"}
            return {"dispatched": False, "error": "No idle slot available"}

        # Parse task file to get headers
        task_data = parse_task_file(task_file)
        headers = task_data.get("headers") or task_data.get("header") or {}
        project_key = headers.get("PROJECT_KEY", "")
        if not project_key:
            self._rollback_dispatch(slot, task_file, task_file.name[:-11] if task_file.name.endswith(".processing") else task_file.name, task_data.get("raw", ""))
            raise ValueError("PROJECT_KEY is required")
        task_id = project_key
        raw_content = task_data.get("raw", "")
        original_name = task_file.name[:-11] if task_file.name.endswith(".processing") else task_file.name
        try:
            project_mode, project_root = self._resolve_project_execution_context(headers)
        except Exception:
            self._rollback_dispatch(slot, task_file, original_name, raw_content)
            raise
        timeout_seconds = self._parse_timeout_seconds(headers)

        # Clear workspace to prevent task A artifacts from leaking into task B
        workspace_dir = slot.workspace_dir
        if workspace_dir.exists():
            for item in workspace_dir.iterdir():
                try:
                    if item.is_file():
                        item.unlink()
                    elif item.is_dir():
                        shutil.rmtree(item)
                except OSError:
                    continue

        # Clean up any stale files in the worker slot root except workspace and hidden files
        for item in slot.slot_dir.iterdir():
            if item.name == "workspace" or item.name.startswith("."):
                continue
            try:
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item)
            except OSError:
                continue

        # Copy task to worker slot directory
        worker_task_file = slot.slot_dir / original_name
        worker_task_file.write_text(raw_content, encoding="utf-8")

        try:
            # Deploy lifecycle bats — may raise FileNotFoundError
            self._deploy_lifecycle_bats(slot)

            # Generate launch bat with fallback done signal.
            bat_lines = [
                "@echo off",
                f"REM Agent launch: {slot.slot_id} for task {task_id}",
                "REM Pool: work",
                "",
                f'set "AGENT_ID={_escape_bat_var(slot.slot_id)}"',
                f'set "TASK_ID={_escape_bat_var(task_id)}"',
                f'set "PROJECT_KEY={_escape_bat_var(task_id)}"',
                f'set "PROJECT_MODE={_escape_bat_var(project_mode)}"',
                "set ROLE=worker",
                "set POOL=work",
                f"set SIGNAL_SERVER_PORT={self._signal_port}",
                "",
                "cd /d \"%~dp0\"",
                "",
            ]
            if project_root is not None:
                bat_lines.append(f'set "PROJECT_ROOT={_escape_bat_var(project_root.as_posix())}"')
                bat_lines.append("")

            bat_lines.extend([
                'powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$env:CLAUDECODE = $null; & \'claude.cmd\' --dangerously-skip-permissions \'Read and strictly follow all instructions in WORK_BOOTSTRAP.txt in the current directory.\'"',
                "",
                "REM Fallback: if Claude exits without calling Done.bat (e.g. end_turn stop_reason),",
                "REM this ensures the terminal signal is sent so the slot is released without timeout.",
                'python "%~dp0signal_bridge.py" --agent-id %AGENT_ID% --task-id %TASK_ID% --signal done --pool work --message "fallback_done"',
                "",
                "exit /b %ERRORLEVEL%",
            ])
            bat_content = "\n".join(bat_lines)
            launch_bat_path = slot.slot_dir / f"launch_{slot.slot_id}.bat"
            launch_bat_path.write_text(bat_content, encoding="utf-8")

            # Create launch request
            launch_request = LaunchRequest(
                bat_path=launch_bat_path,
                working_dir=slot.slot_dir,
                bootstrap_path=None,
                use_job_object=True,
                create_new_console=True,
            )

            # Launch — may raise
            launch_result = self._launch_manager.launch(launch_request, dry_run=dry_run)

        except Exception:
            self._rollback_dispatch(slot, task_file, original_name, raw_content)
            raise

        # Success: remove .processing file from queue
        try:
            task_file.unlink()
        except OSError:
            pass

        with self._lock:
            slot.assigned_task_id = task_id
            slot.launch_result = launch_result
            slot.assigned_at_epoch = time.time()
            slot.timeout_seconds = timeout_seconds
            slot.project_mode = project_mode
            slot.project_root = project_root

        return {
            "dispatched": True,
            "slot_id": slot.slot_id,
            "task_id": task_id,
            "task_file": str(task_file),
            "worker_task_file": str(worker_task_file),
            "launch": launch_result,
        }

    def _clean_slot_dir(self, slot: WorkerSlot) -> None:
        """Clean deployed files in slot directory, keeping only workspace/ intact."""
        if not slot.slot_dir.exists():
            return

        for item in slot.slot_dir.iterdir():
            if item.is_dir() and item.name == "workspace":
                continue
            try:
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item)
            except OSError:
                continue

    def _finalize_slot_terminal(
        self,
        slot: WorkerSlot,
        *,
        signal: str,
        task_id: str,
        is_timeout: bool = False,
        collect_artifacts: bool = False,
    ) -> dict[str, Any]:
        """
        Unified terminal state convergence for done/failed/blocked/timeout.

        Execution order:
        1. Claim finalization atomically under lock (back off if already claimed)
        2. Write terminal event (timeout must write)
        3. cleanup_launch (kill process) - outside lock
        4. collect_artifacts (done only, after process is dead) - outside lock
        5. clean_slot_dir - outside lock
        6. reset slot fields under lock
        """
        # Step 1: Atomic claim under lock
        with self._lock:
            # Re-verify slot is still busy with matching task_id and not already finalizing
            if not slot.busy or slot.finalizing or slot.assigned_task_id != task_id:
                return {"finalized": False, "reason": "slot_already_finalized"}

            # Claim finalization while keeping slot unavailable for dispatch
            slot.finalizing = True
            claimed_launch_result = slot.launch_result
            slot.launch_result = None

        result = {"finalized": True, "slot_id": slot.slot_id, "task_id": task_id, "signal": signal}

        # Step 2: Write terminal event (timeout must write, done/failed/blocked already written by signal server)
        if is_timeout:
            from app.services.event_store import LifecycleEvent
            from datetime import datetime

            # Read current state as from_state
            current_state = self._signal_server.event_store.get_current_state(
                slot.slot_id, task_id
            ) or "state_2"

            self._signal_server.event_store.append(LifecycleEvent(
                timestamp=datetime.now().isoformat() + "Z",
                agent_id=slot.slot_id,
                task_id=task_id,
                signal="timeout",
                pool="work",
                from_state=current_state,
                to_state="state_timeout",
                is_terminal=True,
            ))

        # Step 3: cleanup_launch (kill process first) - outside lock
        if claimed_launch_result is not None:
            cleanup_result = self._launch_manager.cleanup_launch(claimed_launch_result)
            result["cleanup"] = cleanup_result

        # Step 4: finalize done payload (after process is dead) - outside lock
        if collect_artifacts:
            payload_result = self._finalize_done_payload(slot, task_id)
            result["payload"] = payload_result

        # Step 5: clean_slot_dir - outside lock
        self._clean_slot_dir(slot)

        # Step 6: reset slot fields under lock
        with self._lock:
            slot.busy = False
            slot.finalizing = False
            slot.assigned_task_id = ""
            slot.launch_result = None
            slot.assigned_at_epoch = 0.0
            slot.timeout_seconds = 300
            slot.project_mode = PROJECT_MODE_LEGACY
            slot.project_root = None

        return result

    def handle_signal(self, signal_result: dict[str, Any]) -> None:
        """Handle lifecycle signals from workers, releasing slots and cleaning up workers on terminal signals."""
        agent_id = signal_result.get("agent_id", "")
        task_id = signal_result.get("task_id", "")
        signal = signal_result.get("signal", "")
        is_terminal = signal_result.get("is_terminal", False)

        # Quick validation under lock
        with self._lock:
            slot = self._slots.get(agent_id)
            if slot is None:
                return

            # Guard: only process terminal signals if slot is busy and task_id matches
            if not slot.busy:
                return

            if slot.assigned_task_id != task_id:
                return  # Stale or mismatched signal, ignore

            # Release slot and kill worker process for terminal signals
            terminal_signals = {"done", "failed", "blocked"}
            if signal not in terminal_signals and not is_terminal:
                return

        # Heavy finalization outside lock
        self._finalize_slot_terminal(
            slot,
            signal=signal,
            task_id=task_id,
            is_timeout=False,
            collect_artifacts=(signal == "done"),
        )


    def check_timeouts(self) -> list[dict[str, Any]]:
        """Kill and release workers whose runtime exceeds TIMEOUT."""
        timed_out_slots = []

        # Collect timed out slots under lock
        with self._lock:
            now = time.time()
            for slot in self._slots.values():
                if not slot.busy or not slot.assigned_task_id:
                    continue
                if slot.assigned_at_epoch <= 0:
                    continue
                if now - slot.assigned_at_epoch < slot.timeout_seconds:
                    continue

                timed_out_slots.append({
                    "slot": slot,
                    "task_id": slot.assigned_task_id,
                    "timeout_seconds": slot.timeout_seconds,
                })

        # Finalize each timed out slot outside lock
        results = []
        for item in timed_out_slots:
            finalize_result = self._finalize_slot_terminal(
                item["slot"],
                signal="timeout",
                task_id=item["task_id"],
                is_timeout=True,
                collect_artifacts=False,
            )
            if finalize_result.get("finalized"):
                results.append({
                    "slot_id": item["slot"].slot_id,
                    "task_id": item["task_id"],
                    "timeout_seconds": item["timeout_seconds"],
                })

        return results

    def collect_artifacts_to_outbox(self, slot_id: str, task_id: str) -> dict[str, Any]:
        """Copy workspace artifacts into Outbox/task_id/ directory."""
        slot = self._slots.get(slot_id)
        if slot is None:
            return {"collected": False, "reason": "slot_not_found"}
        if not slot.workspace_dir.exists():
            return {"collected": False, "reason": "workspace_missing"}

        out_dir = self._outbox_dir / task_id
        out_dir.mkdir(parents=True, exist_ok=True)

        copied_files: list[str] = []
        for item in slot.workspace_dir.rglob("*"):
            if not item.is_file():
                continue
            rel = item.relative_to(slot.workspace_dir)
            dst = out_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dst)
            copied_files.append(str(rel))

        return {
            "collected": True,
            "task_id": task_id,
            "outbox_dir": str(out_dir),
            "files": copied_files,
        }

    def start(self) -> None:
        """Start the signal server."""
        self._signal_server.start()

    def stop(self) -> None:
        """Stop the signal server."""
        self._signal_server.stop()

    def handle_api_request(self, method: str, path: str, payload: dict | None) -> dict[str, Any]:
        """Handle API requests for runtime status and control."""
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
        elif method == "POST" and path == "/api/control/slot/offline":
            return self._slot_offline(payload)
        elif method == "POST" and path == "/api/control/slot/online":
            return self._slot_online(payload)
        else:
            return {"error": "unknown endpoint"}

    def _get_status(self) -> dict[str, Any]:
        """Return current runtime status with pool info and slot states."""
        with self._lock:
            slots_data = []
            for slot_id in sorted(self._slots.keys()):
                slot = self._slots[slot_id]
                current_state = "state_2" if slot.busy else "idle"
                slots_data.append({
                    "slot_id": slot.slot_id,
                    "busy": slot.busy,
                    "assigned_task_id": slot.assigned_task_id,
                    "current_state": current_state,
                    "enabled": slot.enabled,
                })

            queue_count = len(self.list_queue_tasks())

            return {
                "pool": "work",
                "signal_port": self._signal_port,
                "is_running": self._signal_server.is_running,
                "queue_count": queue_count,
                "slots": slots_data,
            }

    def _get_health(self) -> dict[str, Any]:
        """Return basic health check information."""
        return {
            "ok": True,
            "pool": "work",
            "uptime_seconds": 0,  # TODO: track actual uptime
        }

    def _pause(self) -> dict[str, Any]:
        """Pause runtime task dispatch."""
        self._paused = True
        return self._get_control_state()

    def _resume(self) -> dict[str, Any]:
        """Resume runtime task dispatch."""
        self._paused = False
        return self._get_control_state()

    def _get_control_state(self) -> dict[str, Any]:
        """Return control state for pause/resume."""
        return {
            "paused": self._paused,
            "pool": "work",
        }

    def _slot_offline(self, payload: dict | None) -> dict[str, Any]:
        """Take a slot offline (disable it from accepting new tasks)."""
        if not payload or "slot_id" not in payload:
            return {"success": False, "error": "slot_id required"}

        slot_id = payload["slot_id"]
        slot = self.get_slot(slot_id)
        if slot is None:
            return {"success": False, "error": f"slot not found: {slot_id}"}

        with self._lock:
            slot.enabled = False
            self._governance_store.set_enabled("work", slot_id, False)

        return {
            "success": True,
            "pool": "work",
            "slot_id": slot_id,
            "enabled": False,
            "busy": slot.busy,
        }

    def _slot_online(self, payload: dict | None) -> dict[str, Any]:
        """Bring a slot online (enable it to accept new tasks)."""
        if not payload or "slot_id" not in payload:
            return {"success": False, "error": "slot_id required"}

        slot_id = payload["slot_id"]
        slot = self.get_slot(slot_id)
        if slot is None:
            return {"success": False, "error": f"slot not found: {slot_id}"}

        with self._lock:
            slot.enabled = True
            self._governance_store.set_enabled("work", slot_id, True)

        return {
            "success": True,
            "pool": "work",
            "slot_id": slot_id,
            "enabled": True,
            "busy": slot.busy,
        }
