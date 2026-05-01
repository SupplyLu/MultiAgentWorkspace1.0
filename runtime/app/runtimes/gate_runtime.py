"""GateRuntime - Orchestrator for the Gate Pool."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import fnmatch
import re
import shutil
import threading
import time

from app.services.signal_server import RuntimeSignalServer
from app.services.slot_governance_store import SlotGovernanceStore
from app.services.timeout_defaults_store import TimeoutDefaultsStore
from app.shared.file_queue import parse_task_file
from app.shared.launch_manager import LaunchManager, LaunchRequest


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


@dataclass
class GuardSlot:
    slot_id: str
    slot_dir: Path
    workspace_dir: Path
    busy: bool = False
    finalizing: bool = False
    assigned_task_id: str = ""
    launch_result: dict[str, Any] | None = None
    assigned_at_epoch: float = 0.0
    timeout_seconds: int = 600
    last_known_state: str = "state_0"
    enabled: bool = True
class GateRuntime:
    def __init__(
        self,
        root_dir: Path | str,
        signal_port: int = 19200,
    ):
        self._root_dir = Path(root_dir)
        self._timeout_defaults = TimeoutDefaultsStore(root_dir=self._root_dir)

        self._gate_pool_dir = self._root_dir / "pools" / "gate"
        self._queue_dir = self._gate_pool_dir / "Queue"
        self._outbox_dir = self._gate_pool_dir / "Outbox"
        self._rejectbox_dir = self._gate_pool_dir / "Rejectbox"

        # Gate fields directory for batch processing
        self._gate_fields_dir = self._gate_pool_dir / "fields"
        self._gate_fields_dir.mkdir(parents=True, exist_ok=True)

        self._slots: dict[str, GuardSlot] = {}
        self._governance_store = SlotGovernanceStore(root_dir=self._root_dir)
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
                enabled=self._governance_store.is_enabled("gate", slot_dir.name),
            )

    def get_slot(self, slot_id: str) -> GuardSlot | None:
        return self._slots.get(slot_id)

    def _extract_project_key(self, folder: Path) -> str:
        """Extract PROJECT_KEY from folder's summary.txt, fallback to folder name."""
        summary_file = folder / "summary.txt"
        if summary_file.exists() and summary_file.is_file():
            try:
                content = summary_file.read_text(encoding="utf-8")
                for line in content.splitlines():
                    if line.startswith("PROJECT_KEY:"):
                        project_key = line.split(":", 1)[1].strip()
                        if project_key:
                            return project_key
            except (OSError, UnicodeDecodeError):
                pass
        return folder.name

    def _build_project_task_txt(self, project_key: str, field_dir: Path) -> str:
        """Build the reference txt content for a gate batch review task.

        Security: BATCH_FIELD only contains project_key, not absolute paths.
        Runtime derives field_dir internally from task_id.
        """
        return f"""FROM: construct_pool
TO: guard_01
PROJECT_KEY: {project_key}
TIMEOUT: 600
INPUT_MODE: batch_dir
BATCH_FIELD: {project_key}
---

[Gate Task: Review Construct batch from field directory]

Review all files in:
  pools/gate/fields/BATCH_FIELD/input/

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

            project_key = self._extract_project_key(item)
            field_dir = self._gate_fields_dir / project_key
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

            ref_txt = self._queue_dir / f"task_{project_key}.txt"
            if not ref_txt.exists():
                ref_txt.write_text(self._build_project_task_txt(project_key, field_dir), encoding="utf-8")

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
                if slot.enabled and not slot.busy and not slot.finalizing:
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
        raw_timeout = headers.get("TIMEOUT", None)
        if raw_timeout is None:
            return self._timeout_defaults.get("gate")
        try:
            timeout_seconds = int(raw_timeout)
        except (TypeError, ValueError):
            return self._timeout_defaults.get("gate")
        if timeout_seconds <= 0:
            return self._timeout_defaults.get("gate")
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
            processing_file = task_file.with_name(task_file.name + ".processing")
            try:
                task_file.rename(processing_file)
                task_file = processing_file
            except OSError:
                slot.busy = False
                return {"dispatched": False, "error": "Failed to claim task file"}
            raw_content = task_file.read_text(encoding="utf-8")

        task_data = parse_task_file(task_file)
        if task_data is None:
            with self._lock:
                slot.busy = False
            try:
                task_file.unlink()
            except OSError:
                pass
            return {"dispatched": False, "error": "Failed to parse task file (invalid or disappeared)"}
        headers = task_data.get("headers", {})
        project_key = headers.get("PROJECT_KEY", "")
        # Support legacy TASK_ID fallback for backward compatibility with existing tasks
        if not project_key:
            project_key = headers.get("TASK_ID", "")
        if not project_key:
            with self._lock:
                slot.busy = False
            try:
                task_file.unlink()
            except OSError:
                pass
            return {"dispatched": False, "error": "PROJECT_KEY is required"}
        task_id = project_key
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

set "AGENT_ID={_escape_bat_var(slot.slot_id)}"
set "TASK_ID={_escape_bat_var(task_id)}"
set "PROJECT_KEY={_escape_bat_var(task_id)}"
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

        slot: GuardSlot | None = None
        should_finalize = False
        normalized_task_id = task_id
        with self._lock:
            slot = self._slots.get(agent_id)
            if slot is None:
                return
            if not slot.busy or slot.finalizing:
                return
            if slot.assigned_task_id != task_id:
                stripped_task_id = task_id[5:] if task_id.startswith("task_") else task_id
                if slot.assigned_task_id != stripped_task_id:
                    return
                normalized_task_id = stripped_task_id
            if to_state:
                slot.last_known_state = to_state
            should_finalize = signal in {"approved", "rejected"}

        if should_finalize and slot is not None:
            self._finalize_slot_terminal(slot, signal=signal, task_id=normalized_task_id)

    def _cleanup_project_field(self, task_id: str) -> None:
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
        with self._lock:
            if not slot.busy or slot.finalizing or slot.assigned_task_id != task_id:
                return {"finalized": False, "reason": "slot_already_finalized"}
            slot.finalizing = True
            claimed_launch_result = slot.launch_result
            slot.launch_result = None

        result = {"finalized": True, "slot_id": slot.slot_id, "task_id": task_id, "signal": signal}

        if claimed_launch_result is not None:
            cleanup_result = self._launch_manager.cleanup_launch(claimed_launch_result)
            result["cleanup"] = cleanup_result

        if signal == "approved":
            result["artifacts"] = self.collect_artifacts_to_outbox(slot.slot_id, task_id)
        elif signal == "rejected":
            result["artifacts"] = self.collect_artifacts_to_rejectbox(slot.slot_id, task_id)

        self._clean_slot_dir(slot)
        self._cleanup_project_field(task_id)

        with self._lock:
            slot.busy = False
            slot.finalizing = False
            slot.assigned_task_id = ""
            slot.launch_result = None
            slot.assigned_at_epoch = 0.0
            slot.timeout_seconds = self._timeout_defaults.get("gate")
            slot.last_known_state = "state_0"

        return result

    def _sanitize_outbox_suffix(self, value: str) -> str:
        sanitized = re.sub(r'[\\/:*?"<>|]', '_', value).strip()
        sanitized = sanitized.rstrip(". ")
        return sanitized or "task"

    def _build_project_outbox_name(self, task_id: str, task_file: Path) -> str | None:
        task_name = task_file.stem
        match = re.search(r'(\d{3})$', task_name)
        if not match:
            return None
        seq = match.group(1)

        task_data = parse_task_file(task_file)
        headers = task_data.get("headers", {})
        raw_suffix = headers.get("TITLE") or f"task{int(seq)}"
        suffix = self._sanitize_outbox_suffix(str(raw_suffix))
        return f"{task_id}-{seq}-{suffix}.txt"

    def collect_artifacts_to_outbox(self, slot_id: str, task_id: str) -> dict[str, Any]:
        slot = self._slots.get(slot_id)
        if slot is None:
            return {"collected": False, "reason": "slot_not_found"}
        if not slot.workspace_dir.exists():
            return {"collected": False, "reason": "workspace_missing"}

        self._outbox_dir.mkdir(parents=True, exist_ok=True)

        copied_files: list[str] = []
        from app.services.post_naming import is_valid_atomic_workorder, is_valid_project_key

        task_files = sorted(slot.workspace_dir.glob("task_*.txt"))
        if task_files and is_valid_project_key(task_id):
            renamed_task_files = [
                (task_file, self._build_project_outbox_name(task_id, task_file))
                for task_file in task_files
            ]
            for task_file, outbox_name in renamed_task_files:
                if outbox_name is None:
                    continue
                dst = self._outbox_dir / outbox_name
                shutil.copy2(task_file, dst)
                copied_files.append(outbox_name)
        elif task_files and not is_valid_atomic_workorder(task_id):
            for item in task_files:
                dst = self._outbox_dir / item.name
                shutil.copy2(item, dst)
                copied_files.append(str(item.relative_to(slot.workspace_dir)))
        else:
            out_dir = self._outbox_dir / task_id
            out_dir.mkdir(parents=True, exist_ok=True)
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
            "outbox_dir": str(self._outbox_dir),
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
                if not slot.busy or slot.finalizing or not slot.assigned_task_id:
                    continue
                if slot.assigned_at_epoch <= 0:
                    continue
                if now - slot.assigned_at_epoch < slot.timeout_seconds:
                    continue

                task_id = slot.assigned_task_id
                timeout_seconds = slot.timeout_seconds
                claimed_launch_result = slot.launch_result
                slot.finalizing = True
                slot.launch_result = None

                if claimed_launch_result is not None:
                    self._launch_manager.cleanup_launch(claimed_launch_result)

                worker_task_file = slot.slot_dir / f"task_{task_id}.txt"
                field_dir = self._gate_fields_dir / task_id
                if worker_task_file.exists() and not field_dir.exists():
                    requeued_file = self._queue_dir / worker_task_file.name
                    requeued_file.write_text(worker_task_file.read_text(encoding="utf-8"), encoding="utf-8")

                self._clean_slot_dir(slot)
                self._cleanup_project_field(task_id)

                slot.busy = False
                slot.finalizing = False
                slot.assigned_task_id = ""
                slot.launch_result = None
                slot.assigned_at_epoch = 0.0
                slot.timeout_seconds = self._timeout_defaults.get("gate")
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
        elif method == "POST" and path == "/api/control/slot/offline":
            return self._slot_offline(payload)
        elif method == "POST" and path == "/api/control/slot/online":
            return self._slot_online(payload)
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

    def _slot_offline(self, payload: dict | None) -> dict[str, Any]:
        if not payload or "slot_id" not in payload:
            return {"success": False, "error": "slot_id required"}
        slot_id = payload["slot_id"]
        slot = self.get_slot(slot_id)
        if slot is None:
            return {"success": False, "error": f"slot not found: {slot_id}"}
        with self._lock:
            slot.enabled = False
            self._governance_store.set_enabled("gate", slot_id, False)
        return {"success": True, "pool": "gate", "slot_id": slot_id, "enabled": False, "busy": slot.busy}

    def _slot_online(self, payload: dict | None) -> dict[str, Any]:
        if not payload or "slot_id" not in payload:
            return {"success": False, "error": "slot_id required"}
        slot_id = payload["slot_id"]
        slot = self.get_slot(slot_id)
        if slot is None:
            return {"success": False, "error": f"slot not found: {slot_id}"}
        with self._lock:
            slot.enabled = True
            self._governance_store.set_enabled("gate", slot_id, True)
        return {"success": True, "pool": "gate", "slot_id": slot_id, "enabled": True, "busy": slot.busy}

    def _get_status(self) -> dict[str, Any]:
        """Return current runtime status with pool info and slot states."""
        with self._lock:
            slots_data = []
            for slot_id in sorted(self._slots.keys()):
                slot = self._slots[slot_id]
                current_state = slot.last_known_state if slot.last_known_state != "state_0" else ("state_1" if slot.busy else "idle")
                slots_data.append({
                    "slot_id": slot.slot_id,
                    "busy": slot.busy,
                    "assigned_task_id": slot.assigned_task_id,
                    "current_state": current_state,
                    "enabled": slot.enabled,
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
