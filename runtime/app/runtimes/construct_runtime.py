"""ConstructRuntime - Orchestrator for the Construct Pool.

复制自 ThinkingRuntime 验证过的稳定闭环架构，做以下 Construct Pool 特化：
- 槽位命名: constructor_* (可扩展)
- 池目录: pools/construct/
- 生命周期: online -> start_architecting -> start_finalizing -> done
- 与 WorkRuntime/ThinkingRuntime 完全独立运行，不共享运行态对象

核心职责：
- 读取 Thinking Outbox 的拆解结果（方向性任务）
- 为每个原子任务补全强约束（路径、变量名、接口定义）
- 在 pools/work/fields/ 创建或识别项目根
- 在 workspace/ 中生成规划与工单产物，并由 Runtime 收口到 Construct Outbox
- 由 POST Runtime 继续扫描 Construct Outbox 推进到 Gate
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import shutil
import time
import threading
import fnmatch

from app.services.signal_server import RuntimeSignalServer
from app.services.slot_governance_store import SlotGovernanceStore
from app.services.timeout_defaults_store import TimeoutDefaultsStore
from app.shared.launch_manager import LaunchManager, LaunchRequest
from app.shared.shutdown_manager import ShutdownManager
from app.shared.file_queue import parse_task_file
from app.shared.json_store import JSONStore
import re


def _escape_bat_var(s: str) -> str:
    """
    对 Windows batch 变量值做转义，防止命令注入。
    转义规则（按优先级）：
      %  -> %%
      ^  -> ^^
      &  -> ^&
      |  -> ^|
      <  -> ^<
      >  -> ^>
      "  -> ^"
      !  -> ^^!
    """
    result = s.replace("%", "%%")
    result = result.replace("^", "^^")
    result = result.replace("&", "^&")
    result = result.replace("|", "^|")
    result = result.replace("<", "^<")
    result = result.replace(">", "^>")
    result = result.replace('"', '^"')
    result = result.replace("!", "^^!")
    return result


def _validate_id(value: str, field_name: str) -> str:
    """
    验证 ID 字段（TASK_ID / FEATURE_ID / BATCH_ID）是否符合白名单规则。
    允许: 字母、数字、下划线、连字符
    不允许: 路径分隔符、特殊字符
    """
    if not value:
        raise ValueError(f"{field_name} cannot be empty")
    if not re.match(r'^[a-zA-Z0-9_.-]+$', value):
        raise ValueError(
            f"{field_name} contains invalid characters: {value!r}. "
            "Only alphanumeric, dot, underscore, and hyphen are allowed."
        )
    return value


@dataclass
class ConstructorSlot:
    slot_id: str
    slot_dir: Path
    workspace_dir: Path
    busy: bool = False
    finalizing: bool = False
    assigned_task_id: str = ""
    launch_result: dict[str, Any] | None = None
    assigned_at_epoch: float = 0.0
    timeout_seconds: int = 1800
    last_known_state: str = "state_0"
    enabled: bool = True


class ConstructRuntime:
    def __init__(
        self,
        root_dir: Path | str,
        signal_port: int = 19020,
    ):
        self._root_dir = Path(root_dir)
        self._timeout_defaults = TimeoutDefaultsStore(root_dir=self._root_dir)

        # Core paths - pools/construct/
        self._construct_pool_dir = self._root_dir / "pools" / "construct"
        self._queue_dir = self._construct_pool_dir / "Queue"
        self._outbox_dir = self._construct_pool_dir / "Outbox"

        # Construct fields directory for batch processing
        self._construct_fields_dir = self._construct_pool_dir / "fields"
        self._construct_fields_dir.mkdir(parents=True, exist_ok=True)

        # Work Pool paths for task dispatching
        self._work_queue_dir = self._root_dir / "pools" / "work" / "Queue"
        self._fields_dir = self._root_dir / "pools" / "work" / "fields"

        # Dynamic slot discovery: scan constructor_*
        self._slots: dict[str, ConstructorSlot] = {}
        self._governance_store = SlotGovernanceStore(root_dir=self._root_dir)
        self._init_slots()

        # Signal server - 每个 Runtime 有自己的独立实例
        self._signal_server = RuntimeSignalServer(
            port=signal_port,
            event_store_dir=self._root_dir / "events" / "construct",
        )
        self._signal_server.on_signal = self.handle_signal
        self._signal_server.on_api_request = self.handle_api_request

        # Managers - 独立实例，不共享
        self._launch_manager = LaunchManager()

        # Lifecycle tools directory
        self._lifecycle_tools_dir = self._root_dir / "runtime" / "tools"

        # Lock to protect slot state from concurrent access
        self._lock = threading.RLock()

        # Pause control state
        self._paused = False

    def _init_slots(self) -> None:
        """Initialize constructor slots by dynamically scanning constructor_* directories."""
        if not self._construct_pool_dir.exists():
            return

        constructor_dirs = sorted(
            d for d in self._construct_pool_dir.iterdir()
            if d.is_dir() and fnmatch.fnmatch(d.name, "constructor_*")
        )
        for slot_dir in constructor_dirs:
            slot_id = slot_dir.name
            workspace_dir = slot_dir / "workspace"
            if not workspace_dir.exists() or not workspace_dir.is_dir():
                continue
            enabled = self._governance_store.is_enabled("construct", slot_id)
            self._slots[slot_id] = ConstructorSlot(
                slot_id=slot_id,
                slot_dir=slot_dir,
                workspace_dir=workspace_dir,
                busy=False,
                assigned_task_id="",
                launch_result=None,
                enabled=enabled,
            )

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
        # Fallback: use folder name
        return folder.name

    def _build_project_task_txt(self, project_key: str, field_dir: Path) -> str:
        """Build the reference txt content for a project task."""
        return f"""FROM: thinking_pool
TO: constructor_01
PROJECT_KEY: {project_key}
TIMEOUT: 1800
INPUT_MODE: batch_dir
BATCH_FIELD: {str(field_dir).replace(chr(92), '/')}
PROJECT_ROOT: {str(self._work_queue_dir.parent / "fields").replace(chr(92), '/')}
---

[Construct Task: Process Thinking batch from field directory]

Read all thinking task files from:
  BATCH_FIELD/input/

Analyze and generate strong-constrained work tasks for Work Pool:
  1. Read summary.txt for overall architecture
  2. Read each task_*.txt for individual components
  3. Identify dependencies between tasks
  4. Create work tasks with:
     - TARGET_FILE paths
     - class and method signatures
     - exact test targets
     - acceptance checklists
     - PROJECT_ROOT pointing to the Work field project root when needed
  5. Write all generated deliverables, including every Work task file, into workspace/
  6. Runtime will collect every file from workspace/ into Construct Outbox on terminal convergence
  7. Do NOT write final deliverables to BATCH_FIELD/output/ or any location outside workspace/
  8. Do NOT write any task file to downstream Queue; Construct only plans and specifies project roots
  9. Call Done.bat when complete
"""

    def _preprocess_queue_folders(self) -> None:
        """Convert each folder in Queue to a reference txt and move content to field."""
        import json
        from datetime import datetime

        for item in self._queue_dir.iterdir():
            if not item.is_dir():
                continue
            if item.name.startswith("."):
                continue

            project_key = self._extract_project_key(item)
            field_dir = self._construct_fields_dir / project_key
            input_dir = field_dir / "input"
            input_dir.mkdir(parents=True, exist_ok=True)

            # Move folder content to input/
            for sub_item in list(item.iterdir()):
                dst = input_dir / sub_item.name
                try:
                    if sub_item.is_dir():
                        shutil.move(str(sub_item), str(dst))
                    else:
                        shutil.move(str(sub_item), str(dst))
                except OSError:
                    # Skip if already moved or locked
                    pass

            # Remove empty original folder
            try:
                if item.exists() and not any(item.iterdir()):
                    item.rmdir()
            except OSError:
                pass

            # Generate reference txt
            ref_txt = self._queue_dir / f"task_{project_key}.txt"
            if not ref_txt.exists():
                ref_txt.write_text(
                    self._build_project_task_txt(project_key, field_dir),
                    encoding="utf-8"
                )

            # Write batch meta
            meta_dir = field_dir / "meta"
            meta_dir.mkdir(parents=True, exist_ok=True)
            (meta_dir / "batch_info.json").write_text(
                json.dumps({
                    "batch_id": project_key,
                    "field_dir": str(field_dir),
                    "created_at": datetime.now().isoformat(),
                }, indent=2),
                encoding="utf-8"
            )

    def _deploy_lifecycle_bats(self, slot: ConstructorSlot) -> None:
        """Copy lifecycle bats and signal bridge into constructor slot directory."""
        tools_dir = self._lifecycle_tools_dir
        if not tools_dir.exists():
            raise FileNotFoundError(f"Missing lifecycle tools directory: {tools_dir}")

        # Construct Pool lifecycle bats
        lifecycle_files = [
            "Online.bat",
            "StartArchitecting.bat",
            "StartFinalizing.bat",
            "Done.bat",
            "signal_bridge.py",
        ]
        for file_name in lifecycle_files:
            src = tools_dir / file_name
            if not src.exists():
                raise FileNotFoundError(f"Missing required lifecycle tool: {src}")
            dst = slot.slot_dir / file_name
            dst.write_bytes(src.read_bytes())

        construct_bootstrap = tools_dir / "CONSTRUCT_BOOTSTRAP.txt"
        legacy_bootstrap = tools_dir / "BOOTSTRAP.txt"
        if construct_bootstrap.exists():
            bootstrap_src = construct_bootstrap
        elif legacy_bootstrap.exists():
            bootstrap_src = legacy_bootstrap
        else:
            raise FileNotFoundError(
                f"Missing required lifecycle tool: {construct_bootstrap}"
            )
        (slot.slot_dir / "CONSTRUCT_BOOTSTRAP.txt").write_bytes(bootstrap_src.read_bytes())

    def _parse_timeout_seconds(self, headers: dict[str, Any]) -> int:
        """Parse TIMEOUT header safely with configurable default."""
        raw_timeout = headers.get("TIMEOUT", None)
        if raw_timeout is None:
            return self._timeout_defaults.get("construct")
        try:
            timeout_seconds = int(raw_timeout)
        except (TypeError, ValueError):
            return self._timeout_defaults.get("construct")
        if timeout_seconds <= 0:
            return self._timeout_defaults.get("construct")
        return timeout_seconds

    def get_next_idle_slot(self) -> ConstructorSlot | None:
        """Return the lowest-numbered idle slot, or None if all are busy."""
        with self._lock:
            slot_ids = sorted(self._slots.keys())
            for slot_id in slot_ids:
                slot = self._slots[slot_id]
                if slot.enabled and not slot.busy and not slot.finalizing:
                    return slot
            return None

    def get_slot(self, slot_id: str) -> ConstructorSlot | None:
        """Get a specific slot by ID."""
        return self._slots.get(slot_id)

    def list_queue_tasks(self) -> list[Path]:
        """List all .txt files in the Queue directory, ignoring hidden files.

        Also preprocesses any folders in Queue by moving them to fields/
        and generating reference txt files.
        """
        if not self._queue_dir.exists():
            return []

        self._preprocess_queue_folders()

        tasks = []
        for f in self._queue_dir.iterdir():
            if f.is_file() and f.suffix == ".txt" and not f.name.startswith("."):
                tasks.append(f)
        return sorted(tasks)

    def _rollback_dispatch(
        self,
        slot: ConstructorSlot,
        task_file: Path,
        original_name: str,
        raw_content: str,
    ) -> None:
        """Roll back a failed dispatch: restore queue task file and reset slot."""
        # Restore task to queue
        queue_dir = self._queue_dir
        restored = queue_dir / original_name
        try:
            task_file.rename(restored)
        except OSError:
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
        slot.timeout_seconds = self._timeout_defaults.get("construct")

    def dispatch_next(self, dry_run: bool = True) -> dict[str, Any]:
        """Dispatch the next task to an idle constructor slot."""
        if self._paused:
            return {"dispatched": False, "error": "Runtime is paused"}

        slot = None
        task_file = None
        original_name = ""
        raw_content = ""
        with self._lock:
            slot_ids = sorted(self._slots.keys())
            for slot_id in slot_ids:
                candidate = self._slots[slot_id]
                if candidate.enabled and not candidate.busy and not candidate.finalizing:
                    candidate.busy = True
                    slot = candidate
                    break

            if slot is not None:
                tasks = self.list_queue_tasks()
                if not tasks:
                    slot.busy = False
                    slot = None
                else:
                    task_file = tasks[0]
                    processing_file = task_file.with_name(task_file.name + ".processing")
                    try:
                        task_file.rename(processing_file)
                        task_file = processing_file
                    except OSError:
                        slot.busy = False
                        slot = None

        if slot is None:
            if not self.list_queue_tasks():
                return {"dispatched": False, "error": "No tasks in queue"}
            return {"dispatched": False, "error": "No idle slot available"}

        original_name = task_file.name[:-11] if task_file.name.endswith(".processing") else task_file.name
        try:
            raw_content = task_file.read_text(encoding="utf-8")
        except OSError:
            raw_content = ""

        # Parse task file to get headers
        task_data = parse_task_file(task_file)
        if task_data is None:
            self._rollback_dispatch(slot, task_file, original_name, raw_content)
            return {"dispatched": False, "error": "Failed to parse task file (invalid or disappeared)"}
        headers = task_data.get("headers") or task_data.get("header") or {}
        project_key = headers.get("PROJECT_KEY", "")
        # Support legacy TASK_ID fallback for backward compatibility with existing tasks
        if not project_key:
            project_key = headers.get("TASK_ID", "")
        if not project_key:
            self._rollback_dispatch(slot, task_file, original_name, raw_content)
            return {"dispatched": False, "error": "PROJECT_KEY is required"}
        task_id = project_key
        timeout_seconds = self._parse_timeout_seconds(headers)
        raw_content = task_data.get("raw", raw_content)

        # Validate IDs
        try:
            task_id = _validate_id(task_id, "TASK_ID")
        except ValueError as e:
            self._rollback_dispatch(slot, task_file, original_name, raw_content)
            return {"dispatched": False, "error": f"ID validation failed: {e}"}

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

        # Clean up any stale task files in the slot root
        for f in slot.slot_dir.glob("*.txt"):
            if f.name.startswith("task_") or f.name.startswith("demo_task") or f.name.startswith("lifecycle_"):
                f.unlink()

        # Copy task to slot directory
        worker_task_file = slot.slot_dir / original_name
        worker_task_file.write_text(raw_content, encoding="utf-8")

        controlled_batch_field_dir = self._construct_fields_dir / task_id
        workspace_batch_dir: Path | None = None
        controlled_input_dir = controlled_batch_field_dir / "input"
        if controlled_input_dir.exists() and controlled_input_dir.is_dir():
            workspace_batch_dir = workspace_dir / controlled_batch_field_dir.name
            if workspace_batch_dir.exists():
                shutil.rmtree(workspace_batch_dir)
            shutil.copytree(controlled_input_dir, workspace_batch_dir)

        try:
            # Deploy lifecycle bats
            self._deploy_lifecycle_bats(slot)

            # Generate launch bat with fallback done signal (escape all variables)
            bat_content = f"""@echo off
REM Agent launch: {slot.slot_id} for task {task_id}
REM Pool: construct

set "AGENT_ID={_escape_bat_var(slot.slot_id)}"
set "TASK_ID={_escape_bat_var(task_id)}"
set "PROJECT_KEY={_escape_bat_var(task_id)}"
set "ROLE=constructor"
set "POOL=construct"
set "SIGNAL_SERVER_PORT={self._signal_port}"

cd /d "%~dp0"

REM Ensure Work Pool fields directory exists
if not exist "{self._fields_dir}" mkdir "{self._fields_dir}"

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$env:CLAUDECODE = $null; & 'claude.cmd' --dangerously-skip-permissions 'Read and strictly follow all instructions in CONSTRUCT_BOOTSTRAP.txt in the current directory.'"

REM Fallback: if Claude exits without calling Done.bat (e.g. end_turn stop_reason),
REM this ensures the terminal signal is sent so the slot is released without timeout.
python "%~dp0signal_bridge.py" --agent-id %AGENT_ID% --task-id %TASK_ID% --signal done --pool construct --message "fallback_done"

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

            # Launch
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

    def _clean_slot_dir(self, slot: ConstructorSlot) -> None:
        """Clean deployed files in slot directory and clear workspace contents."""
        if not slot.slot_dir.exists():
            return

        for item in slot.slot_dir.iterdir():
            if item.is_dir() and item.name == "workspace":
                for workspace_item in item.iterdir():
                    try:
                        if workspace_item.is_file():
                            workspace_item.unlink()
                        elif workspace_item.is_dir():
                            shutil.rmtree(workspace_item)
                    except OSError:
                        continue
                continue
            try:
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item)
            except OSError:
                continue

    def _cleanup_batch_field(self, slot: ConstructorSlot, task_id: str) -> None:
        """Remove batch field directory on task completion."""
        batch_id = task_id
        field_dir = self._construct_fields_dir / batch_id

        if field_dir.exists():
            try:
                shutil.rmtree(field_dir)
            except OSError:
                pass

    def _finalize_slot_terminal(
        self,
        slot: ConstructorSlot,
        *,
        signal: str,
        task_id: str,
        is_timeout: bool = False,
        collect_artifacts: bool = False,
    ) -> dict[str, Any]:
        """Unified terminal state convergence for done/failed/blocked/timeout."""
        result = {"finalized": True, "slot_id": slot.slot_id, "task_id": task_id, "signal": signal}

        # Step 1: Write terminal event (timeout must write)
        if is_timeout:
            from app.services.event_store import LifecycleEvent
            from datetime import datetime

            current_state = self._signal_server.event_store.get_current_state(
                slot.slot_id, task_id
            )
            if current_state is None:
                current_state = slot.last_known_state if slot.last_known_state != "state_0" else "state_unknown"

            self._signal_server.event_store.append(LifecycleEvent(
                timestamp=datetime.now().isoformat() + "Z",
                agent_id=slot.slot_id,
                task_id=task_id,
                signal="timeout",
                pool="construct",
                from_state=current_state,
                to_state="state_timeout",
                is_terminal=True,
            ))

        # Step 2: cleanup_launch (kill process first)
        if slot.launch_result is not None:
            cleanup_result = self._launch_manager.cleanup_launch(slot.launch_result)
            result["cleanup"] = cleanup_result

        # Step 3: collect_artifacts
        if collect_artifacts:
            artifact_result = self.collect_artifacts_to_outbox(slot.slot_id, task_id)
            result["artifacts"] = artifact_result

        # Step 4: clean_slot_dir
        self._clean_slot_dir(slot)

        # Step 5: reset slot fields
        slot.busy = False
        slot.finalizing = False
        slot.assigned_task_id = ""
        slot.launch_result = None
        slot.assigned_at_epoch = 0.0
        slot.timeout_seconds = self._timeout_defaults.get("construct")
        slot.last_known_state = "state_0"

        return result

    def handle_signal(self, signal_result: dict[str, Any]) -> None:
        """Handle lifecycle signals from constructors."""
        agent_id = signal_result.get("agent_id", "")
        task_id = signal_result.get("task_id", "")
        signal = signal_result.get("signal", "")
        is_terminal = signal_result.get("is_terminal", False)
        to_state = signal_result.get("to_state", "")

        slot: ConstructorSlot | None = None
        should_finalize = False

        # Narrow lock: only validate and decide
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

            terminal_signals = {"done", "failed", "blocked"}
            should_finalize = signal in terminal_signals or is_terminal

        # Heavy I/O outside lock
        if should_finalize and slot is not None:
            with self._lock:
                # Double-check busy to prevent done/timeout race
                if slot.finalizing or not slot.busy or slot.assigned_task_id != task_id:
                    return
                # Mark as finalizing to block timeout and reuse until convergence completes
                slot.finalizing = True

            self._finalize_slot_terminal(
                slot,
                signal=signal,
                task_id=task_id,
                is_timeout=False,
                collect_artifacts=True,
            )
            self._cleanup_batch_field(slot, task_id)

    def check_timeouts(self) -> list[dict[str, Any]]:
        """Kill and release constructors whose runtime exceeds TIMEOUT."""
        now = time.time()
        timed_out_slots: list[tuple[ConstructorSlot, str, int]] = []

        # Narrow lock: only collect timed-out slots and mark finalizing atomically
        with self._lock:
            for slot in self._slots.values():
                if not slot.busy or not slot.assigned_task_id:
                    continue
                if slot.finalizing:
                    continue
                if slot.assigned_at_epoch <= 0:
                    continue
                if now - slot.assigned_at_epoch < slot.timeout_seconds:
                    continue

                task_id = slot.assigned_task_id
                timeout_seconds = slot.timeout_seconds
                slot.finalizing = True
                timed_out_slots.append((slot, task_id, timeout_seconds))

        timed_out: list[dict[str, Any]] = []
        for slot, task_id, timeout_seconds in timed_out_slots:
            finalize_result = self._finalize_slot_terminal(
                slot,
                signal="timeout",
                task_id=task_id,
                is_timeout=True,
                collect_artifacts=True,
            )
            self._cleanup_batch_field(slot, task_id)
            timed_out.append({
                "slot_id": slot.slot_id,
                "task_id": finalize_result["task_id"],
                "timeout_seconds": timeout_seconds,
            })

        return timed_out

    def collect_artifacts_to_outbox(self, slot_id: str, task_id: str) -> dict[str, Any]:
        """Copy workspace artifacts into Outbox/task_id/ directory."""
        slot = self._slots.get(slot_id)
        if slot is None:
            return {"collected": False, "reason": "slot_not_found"}
        if not slot.workspace_dir.exists():
            return {"collected": False, "reason": "workspace_missing"}

        out_dir = self._outbox_dir / task_id
        out_dir.mkdir(parents=True, exist_ok=True)

        source_root = slot.workspace_dir
        workspace_items = list(slot.workspace_dir.iterdir())
        workspace_files = [item for item in workspace_items if item.is_file()]
        workspace_dirs = [item for item in workspace_items if item.is_dir()]

        if not workspace_files and len(workspace_dirs) == 1 and workspace_dirs[0].name == task_id:
            source_root = workspace_dirs[0]

        copied_files: list[str] = []
        for item in source_root.rglob("*"):
            if not item.is_file():
                continue
            rel = item.relative_to(source_root)
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
            "pool": "construct",
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
            self._governance_store.set_enabled("construct", slot_id, False)
        return {"success": True, "pool": "construct", "slot_id": slot_id, "enabled": False, "busy": slot.busy}

    def _slot_online(self, payload: dict | None) -> dict[str, Any]:
        if not payload or "slot_id" not in payload:
            return {"success": False, "error": "slot_id required"}
        slot_id = payload["slot_id"]
        slot = self.get_slot(slot_id)
        if slot is None:
            return {"success": False, "error": f"slot not found: {slot_id}"}
        with self._lock:
            slot.enabled = True
            self._governance_store.set_enabled("construct", slot_id, True)
        return {"success": True, "pool": "construct", "slot_id": slot_id, "enabled": True, "busy": slot.busy}

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
                "pool": "construct",
                "signal_port": self._signal_port,
                "is_running": self._signal_server.is_running,
                "queue_count": queue_count,
                "slots": slots_data,
            }

    def _get_health(self) -> dict[str, Any]:
        """Return basic health check information."""
        return {
            "ok": True,
            "pool": "construct",
            "uptime_seconds": 0,
        }
