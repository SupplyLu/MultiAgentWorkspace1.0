"""WorkRuntime - Minimal orchestrator for the Work Pool."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import shutil
import time
import threading

from app.services.signal_server import RuntimeSignalServer
from app.services.post_service import PostService
from app.shared.launch_manager import LaunchManager, LaunchRequest
from app.shared.shutdown_manager import ShutdownManager
from app.shared.file_queue import parse_task_file
from app.shared.json_store import JSONStore


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
        self._init_slots()

        # Signal server
        self._signal_server = RuntimeSignalServer(
            port=signal_port,
            event_store_dir=self._root_dir / "events",
        )
        self._signal_server.on_signal = self.handle_signal

        # Managers and builders
        self._launch_manager = LaunchManager()

        # Lifecycle tools directory (can be overridden for testing)
        self._lifecycle_tools_dir = self._root_dir / "runtime" / "tools"

        # Lock to protect slot state from concurrent access
        self._lock = threading.RLock()

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
            self._slots[slot_id] = WorkerSlot(
                slot_id=slot_id,
                slot_dir=slot_dir,
                workspace_dir=workspace_dir,
                busy=False,
                assigned_task_id="",
                launch_result=None,
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
            "BOOTSTRAP.txt",
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
                if not slot.busy and not slot.finalizing:
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

    def dispatch_next(self, dry_run: bool = True) -> dict[str, Any]:
        """Dispatch the next task to an idle worker slot."""
        # Find next idle slot and mark it busy immediately under lock
        slot = None
        task_file = None
        original_name = ""
        raw_content = ""
        with self._lock:
            worker_ids = sorted(self._slots.keys())
            for worker_id in worker_ids:
                candidate = self._slots[worker_id]
                if not candidate.busy:
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
        task_id = headers.get("TASK_ID", "")
        feature_id = headers.get("FEATURE_ID", "")
        timeout_seconds = self._parse_timeout_seconds(headers)
        raw_content = task_data.get("raw", "")
        original_name = task_file.name[:-11] if task_file.name.endswith(".processing") else task_file.name

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

        # Clean up any stale task files in the worker slot root
        for f in slot.slot_dir.glob("*.txt"):
            if f.name.startswith("task_") or f.name.startswith("demo_task") or f.name.startswith("lifecycle_"):
                f.unlink()

        # Copy task to worker slot directory
        worker_task_file = slot.slot_dir / original_name
        worker_task_file.write_text(raw_content, encoding="utf-8")

        try:
            # Deploy lifecycle bats — may raise FileNotFoundError
            self._deploy_lifecycle_bats(slot)

            # Generate launch bat with fallback done signal.
            # After Claude CLI exits (normally, or via end_turn), this bat sends a
            # fallback "done" signal to guarantee slot release. If the worker already
            # sent "done" via Done.bat, the signal is idempotent and safe.
            bat_content = f"""@echo off
REM Agent launch: {slot.slot_id} for task {task_id}
REM Pool: work

set AGENT_ID={slot.slot_id}
set TASK_ID={task_id}
set ROLE=worker
set FEATURE_ID={feature_id}
set POOL=work
set SIGNAL_SERVER_PORT={self._signal_port}

cd /d "%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$env:CLAUDECODE = $null; & 'claude.cmd' --dangerously-skip-permissions 'Read and strictly follow all instructions in BOOTSTRAP.txt in the current directory.'"

REM Fallback: if Claude exits without calling Done.bat (e.g. end_turn stop_reason),
REM this ensures the terminal signal is sent so the slot is released without timeout.
python "%~dp0signal_bridge.py" --agent-id %AGENT_ID% --task-id %TASK_ID% --signal done --pool work --message "fallback_done"

exit /b %ERRORLEVEL%
"""
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

        # Step 4: collect_artifacts (done only, after process is dead) - outside lock
        if collect_artifacts:
            artifact_result = self.collect_artifacts_to_outbox(slot.slot_id, task_id)
            result["artifacts"] = artifact_result

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
