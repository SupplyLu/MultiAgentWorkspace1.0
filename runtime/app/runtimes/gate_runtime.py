"""GateRuntime - Orchestrator for the Gate Pool."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import fnmatch
import shutil
import threading
import time

from app.services.signal_server import RuntimeSignalServer
from app.shared.file_queue import parse_task_file
from app.shared.launch_manager import LaunchManager, LaunchRequest


@dataclass
class GuardSlot:
    slot_id: str
    slot_dir: Path
    workspace_dir: Path
    busy: bool = False
    assigned_task_id: str = ""
    launch_result: dict[str, Any] | None = None
    assigned_at_epoch: float = 0.0
    timeout_seconds: int = 600
    last_known_state: str = "state_0"


class GateRuntime:
    def __init__(
        self,
        root_dir: Path | str,
        signal_port: int = 19200,
    ):
        self._root_dir = Path(root_dir)
        self._signal_port = signal_port

        self._gate_pool_dir = self._root_dir / "pools" / "gate"
        self._queue_dir = self._gate_pool_dir / "Queue"
        self._outbox_dir = self._gate_pool_dir / "Outbox"
        self._rejectbox_dir = self._gate_pool_dir / "Rejectbox"

        # Gate fields directory for batch processing
        self._gate_fields_dir = self._gate_pool_dir / "fields"
        self._gate_fields_dir.mkdir(parents=True, exist_ok=True)

        self._slots: dict[str, GuardSlot] = {}
        self._init_slots()

        self._signal_server = RuntimeSignalServer(
            port=signal_port,
            event_store_dir=self._root_dir / "events" / "gate",
        )
        self._signal_server.on_signal = self.handle_signal
        self._signal_server.on_api_request = self.handle_api_request

        self._launch_manager = LaunchManager()
        self._lifecycle_tools_dir = self._root_dir / "runtime" / "tools"
        self._lock = threading.RLock()
        self._paused = False

    def _init_slots(self) -> None:
        if not self._gate_pool_dir.exists():
            return

        guard_dirs = sorted(
            d for d in self._gate_pool_dir.iterdir()
            if d.is_dir() and fnmatch.fnmatch(d.name, "guard_*")
        )
        for slot_dir in guard_dirs:
            workspace_dir = slot_dir / "workspace"
            if not workspace_dir.exists() or not workspace_dir.is_dir():
                continue
            self._slots[slot_dir.name] = GuardSlot(
                slot_id=slot_dir.name,
                slot_dir=slot_dir,
                workspace_dir=workspace_dir,
            )

    def get_slot(self, slot_id: str) -> GuardSlot | None:
        return self._slots.get(slot_id)

    def _extract_batch_id(self, folder: Path) -> str:
        """Extract batch id from folder summary.txt, fallback to folder name."""
        summary_file = folder / "summary.txt"
        if summary_file.exists() and summary_file.is_file():
            try:
                content = summary_file.read_text(encoding="utf-8")
                for line in content.splitlines():
                    if line.startswith("TASK_ID:"):
                        batch_id = line.split(":", 1)[1].strip()
                        if batch_id:
                            return batch_id
            except (OSError, UnicodeDecodeError):
                pass
        return folder.name

    def _build_batch_task_txt(self, batch_id: str, field_dir: Path) -> str:
        """Build the reference txt content for a gate batch review task."""
        return f"""FROM: construct_pool
TO: guard_01
TASK_ID: {batch_id}
TIMEOUT: 600
INPUT_MODE: batch_dir
BATCH_FIELD: {str(field_dir).replace(chr(92), '/')}
---

[Gate Task: Review Construct batch from field directory]

Review all files in:
  BATCH_FIELD/input/

Instructions:
  1. Read summary.txt for the batch-level architecture and shared constraints
  2. Review each task_*.txt against the batch summary and sibling tasks
  3. Validate cross-task consistency, interfaces, naming, and dependency constraints
  4. If approved, write the approved work task .txt files into workspace/
  5. Runtime will collect files from workspace/ into Gate Outbox on terminal convergence
  6. On approval call Accepted.bat
  7. On rejection write review notes into workspace/ and call Denied.bat
"""

    def _preprocess_queue_folders(self) -> None:
        """Move batch folders from Queue into fields and replace with reference txt tasks."""
        if not self._queue_dir.exists():
            return

        for item in list(self._queue_dir.iterdir()):
            if not item.is_dir() or item.name.startswith("."):
                continue

            batch_id = self._extract_batch_id(item)
            field_dir = self._gate_fields_dir / batch_id
            input_dir = field_dir / "input"
            input_dir.mkdir(parents=True, exist_ok=True)

            for sub_item in list(item.iterdir()):
                dst = input_dir / sub_item.name
                try:
                    shutil.move(str(sub_item), str(dst))
                except OSError:
                    pass

            try:
                if item.exists() and not any(item.iterdir()):
                    item.rmdir()
            except OSError:
                pass

            ref_txt = self._queue_dir / f"task_{batch_id}.txt"
            if not ref_txt.exists():
                ref_txt.write_text(self._build_batch_task_txt(batch_id, field_dir), encoding="utf-8")

    def list_queue_tasks(self) -> list[Path]:
        if not self._queue_dir.exists():
            return []

        batch_dirs = sorted(
            f for f in self._queue_dir.iterdir()
            if f.is_dir() and not f.name.startswith(".")
        )
        if batch_dirs:
            return batch_dirs

        return sorted(
            f for f in self._queue_dir.iterdir()
            if f.is_file() and f.suffix == ".txt" and not f.name.startswith(".")
        )

    def find_idle_slot(self) -> GuardSlot | None:
        with self._lock:
            for slot_id in sorted(self._slots.keys()):
                slot = self._slots[slot_id]
                if not slot.busy:
                    return slot
        return None

    def _deploy_lifecycle_bats(self, slot: GuardSlot) -> None:
        tools_dir = self._lifecycle_tools_dir
        lifecycle_files = [
            "Online.bat",
            "StartReview.bat",
            "Accepted.bat",
            "Denied.bat",
            "signal_bridge.py",
        ]
        for file_name in lifecycle_files:
            src = tools_dir / file_name
            if not src.exists():
                raise FileNotFoundError(f"Missing required lifecycle tool: {src}")
            dst = slot.slot_dir / file_name
            dst.write_bytes(src.read_bytes())

        gate_bootstrap = tools_dir / "gate" / "GATE_BOOTSTRAP.txt"
        if not gate_bootstrap.exists():
            raise FileNotFoundError(f"Missing required lifecycle tool: {gate_bootstrap}")
        (slot.slot_dir / "GATE_BOOTSTRAP.txt").write_bytes(gate_bootstrap.read_bytes())

    def _parse_timeout_seconds(self, headers: dict[str, Any]) -> int:
        raw_timeout = headers.get("TIMEOUT", 600)
        try:
            timeout_seconds = int(raw_timeout)
        except (TypeError, ValueError):
            return 600
        if timeout_seconds <= 0:
            return 600
        return timeout_seconds

    def dispatch_next(self, dry_run: bool = True) -> dict[str, Any]:
        if self._paused:
            return {"dispatched": False, "error": "Runtime is paused"}

        slot = None
        task_file = None
        raw_content = ""
        original_name = ""

        with self._lock:
            slot = self.find_idle_slot()
            if slot is None:
                if not self.list_queue_tasks():
                    return {"dispatched": False, "error": "No tasks in queue"}
                return {"dispatched": False, "error": "No idle slot available"}

            tasks = self.list_queue_tasks()
            if not tasks:
                return {"dispatched": False, "error": "No tasks in queue"}

            if tasks[0].is_dir():
                self._preprocess_queue_folders()
                tasks = sorted(
                    f for f in self._queue_dir.iterdir()
                    if f.is_file() and f.suffix == ".txt" and not f.name.startswith(".")
                )
                if not tasks:
                    return {"dispatched": False, "error": "No tasks in queue"}

            slot.busy = True
            task_file = tasks[0]
            raw_content = task_file.read_text(encoding="utf-8")

        task_data = parse_task_file(task_file)
        headers = task_data.get("headers", {})
        task_id = headers.get("TASK_ID", task_file.stem)
        timeout_seconds = self._parse_timeout_seconds(headers)
        original_name = f"task_{task_id}.txt"

        worker_task_file = slot.slot_dir / original_name
        worker_task_file.write_text(raw_content, encoding="utf-8")

        try:
            if dry_run:
                launch_result = {
                    "dry_run": True,
                    "slot_id": slot.slot_id,
                    "task_id": task_id,
                }
            else:
                self._deploy_lifecycle_bats(slot)

                bat_content = f"""@echo off
REM Agent launch: {slot.slot_id} for task {task_id}
REM Pool: gate

set AGENT_ID={slot.slot_id}
set TASK_ID={task_id}
set ROLE=guard
set POOL=gate
set SIGNAL_SERVER_PORT={self._signal_port}

cd /d "%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$env:CLAUDECODE = $null; & 'claude.cmd' --dangerously-skip-permissions 'Read and strictly follow all instructions in GATE_BOOTSTRAP.txt in the current directory.'"

exit /b %ERRORLEVEL%
"""
                launch_bat_path = slot.slot_dir / f"launch_{slot.slot_id}.bat"
                launch_bat_path.write_text(bat_content, encoding="utf-8")

                launch_request = LaunchRequest(
                    bat_path=launch_bat_path,
                    working_dir=slot.slot_dir,
                    bootstrap_path=None,
                    use_job_object=True,
                    create_new_console=True,
                )
                launch_result = self._launch_manager.launch(launch_request, dry_run=dry_run)
        except Exception:
            if worker_task_file.exists():
                worker_task_file.unlink()
            slot.busy = False
            raise

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

    def handle_signal(self, signal_result: dict[str, Any]) -> None:
        """Handle lifecycle signals from guards."""
        agent_id = signal_result.get("agent_id", "")
        task_id = signal_result.get("task_id", "")
        signal = signal_result.get("signal", "")
        to_state = signal_result.get("to_state", "")

        if task_id.startswith("task_"):
            task_id = task_id[5:]

        slot: GuardSlot | None = None
        should_finalize = False
        with self._lock:
            slot = self._slots.get(agent_id)
            if slot is None:
                return
            if not slot.busy:
                return
            if slot.assigned_task_id != task_id:
                return
            if to_state:
                slot.last_known_state = to_state
            should_finalize = signal in {"approved", "rejected"}

        if should_finalize and slot is not None:
            self._finalize_slot_terminal(slot, signal=signal, task_id=task_id)

    def _cleanup_batch_field(self, task_id: str) -> None:
        if not task_id.startswith("batch_"):
            return

        field_dir = self._gate_fields_dir / task_id
        if field_dir.exists():
            try:
                shutil.rmtree(field_dir)
            except OSError:
                pass

    def _finalize_slot_terminal(
        self,
        slot: GuardSlot,
        *,
        signal: str,
        task_id: str,
    ) -> dict[str, Any]:
        result = {"finalized": True, "slot_id": slot.slot_id, "task_id": task_id, "signal": signal}

        if slot.launch_result is not None:
            cleanup_result = self._launch_manager.cleanup_launch(slot.launch_result)
            result["cleanup"] = cleanup_result

        if signal == "approved":
            result["artifacts"] = self.collect_artifacts_to_outbox(slot.slot_id, task_id)
        elif signal == "rejected":
            result["artifacts"] = self.collect_artifacts_to_rejectbox(slot.slot_id, task_id)

        self._clean_slot_dir(slot)
        self._cleanup_batch_field(task_id)

        slot.busy = False
        slot.assigned_task_id = ""
        slot.launch_result = None
        slot.assigned_at_epoch = 0.0
        slot.timeout_seconds = 600
        slot.last_known_state = "state_0"

        return result

    def collect_artifacts_to_outbox(self, slot_id: str, task_id: str) -> dict[str, Any]:
        slot = self._slots.get(slot_id)
        if slot is None:
            return {"collected": False, "reason": "slot_not_found"}
        if not slot.workspace_dir.exists():
            return {"collected": False, "reason": "workspace_missing"}

        self._outbox_dir.mkdir(parents=True, exist_ok=True)

        copied_files: list[str] = []
        if task_id.startswith("batch_"):
            out_dir = self._outbox_dir
        else:
            out_dir = self._outbox_dir / task_id
            out_dir.mkdir(parents=True, exist_ok=True)

        for item in slot.workspace_dir.rglob("*"):
            if not item.is_file():
                continue

            # Batch mode filtering: only collect valid work tasks (task_*.txt)
            if task_id.startswith("batch_"):
                if not item.name.startswith("task_") or not item.name.endswith(".txt"):
                    continue
                dst = out_dir / item.name
            else:
                rel = item.relative_to(slot.workspace_dir)
                dst = out_dir / rel
                dst.parent.mkdir(parents=True, exist_ok=True)

            shutil.copy2(item, dst)
            copied_files.append(str(item.relative_to(slot.workspace_dir)))

        return {
            "collected": True,
            "task_id": task_id,
            "outbox_dir": str(out_dir),
            "files": copied_files,
        }

    def collect_artifacts_to_rejectbox(self, slot_id: str, task_id: str) -> dict[str, Any]:
        slot = self._slots.get(slot_id)
        if slot is None:
            return {"collected": False, "reason": "slot_not_found"}
        if not slot.workspace_dir.exists():
            return {"collected": False, "reason": "workspace_missing"}

        reject_dir = self._rejectbox_dir / task_id
        reject_dir.mkdir(parents=True, exist_ok=True)

        copied_files: list[str] = []

        # Step 1: Copy original batch input folder first (if exists)
        field_input_dir = self._gate_fields_dir / task_id / "input"
        if field_input_dir.exists():
            for item in field_input_dir.rglob("*"):
                if not item.is_file():
                    continue
                rel = item.relative_to(field_input_dir)
                dst = reject_dir / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dst)
                copied_files.append(str(rel))

        # Step 2: Overlay workspace contents (guard's rejection notes and any modifications)
        for item in slot.workspace_dir.rglob("*"):
            if not item.is_file():
                continue
            rel = item.relative_to(slot.workspace_dir)
            dst = reject_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dst)
            if str(rel) not in copied_files:
                copied_files.append(str(rel))

        return {
            "collected": True,
            "task_id": task_id,
            "rejectbox_dir": str(reject_dir),
            "files": copied_files,
        }

    def _clean_workspace_dir(self, workspace_dir: Path) -> None:
        if not workspace_dir.exists():
            return
        for item in workspace_dir.iterdir():
            if item.name == ".gitkeep":
                continue
            try:
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item)
            except OSError:
                continue

    def _clean_slot_dir(self, slot: GuardSlot) -> None:
        if not slot.slot_dir.exists():
            return
        for item in slot.slot_dir.iterdir():
            if item.is_dir() and item.name == "workspace":
                self._clean_workspace_dir(item)
                continue
            try:
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item)
            except OSError:
                continue

    def check_timeouts(self) -> list[dict[str, Any]]:
        """Kill timed-out guards and requeue the original task until approved/rejected."""
        with self._lock:
            now = time.time()
            timed_out: list[dict[str, Any]] = []

            for slot in self._slots.values():
                if not slot.busy or not slot.assigned_task_id:
                    continue
                if slot.assigned_at_epoch <= 0:
                    continue
                if now - slot.assigned_at_epoch < slot.timeout_seconds:
                    continue

                task_id = slot.assigned_task_id
                timeout_seconds = slot.timeout_seconds

                if slot.launch_result is not None:
                    self._launch_manager.cleanup_launch(slot.launch_result)

                worker_task_file = slot.slot_dir / f"task_{task_id}.txt"
                if worker_task_file.exists() and not task_id.startswith("batch_"):
                    requeued_file = self._queue_dir / worker_task_file.name
                    requeued_file.write_text(worker_task_file.read_text(encoding="utf-8"), encoding="utf-8")

                self._clean_slot_dir(slot)
                self._cleanup_batch_field(task_id)

                slot.busy = False
                slot.assigned_task_id = ""
                slot.launch_result = None
                slot.assigned_at_epoch = 0.0
                slot.timeout_seconds = 600
                slot.last_known_state = "state_0"

                timed_out.append({
                    "slot_id": slot.slot_id,
                    "task_id": task_id,
                    "timeout_seconds": timeout_seconds,
                })

            return timed_out

    def start(self) -> None:
        self._signal_server.start()

    def stop(self) -> None:
        self._signal_server.stop()

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
            "pool": "gate",
        }

    def _get_status(self) -> dict[str, Any]:
        """Return current runtime status with pool info and slot states."""
        with self._lock:
            slots_data = []
            for slot_id in sorted(self._slots.keys()):
                slot = self._slots[slot_id]
                slots_data.append({
                    "slot_id": slot.slot_id,
                    "busy": slot.busy,
                    "assigned_task_id": slot.assigned_task_id,
                })

            queue_count = len(self.list_queue_tasks())

            return {
                "pool": "gate",
                "signal_port": self._signal_port,
                "is_running": self._signal_server.is_running,
                "queue_count": queue_count,
                "slots": slots_data,
            }

    def _get_health(self) -> dict[str, Any]:
        """Return basic health check information."""
        return {
            "ok": True,
            "pool": "gate",
            "uptime_seconds": 0,
        }
