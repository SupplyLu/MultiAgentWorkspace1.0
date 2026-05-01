"""ThinkingRuntime - Orchestrator for the Thinking Pool.

复制自 WorkRuntime 验证过的稳定闭环架构，做以下 Thinking Pool 特化：
- 槽位命名: sub_brain_XX (可扩展)
- 池目录: pools/thinking/
- 生命周期: online -> start_thinking -> start_summarizing -> done
- 与 WorkRuntime 完全独立运行，不共享运行态对象
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import shutil
import time
import threading
import fnmatch
import re

from app.services.signal_server import RuntimeSignalServer
from app.services.slot_governance_store import SlotGovernanceStore
from app.services.timeout_defaults_store import TimeoutDefaultsStore
from app.shared.launch_manager import LaunchManager, LaunchRequest
from app.shared.shutdown_manager import ShutdownManager
from app.shared.file_queue import parse_task_file, parse_task_header, split_task_file_content
from app.shared.json_store import JSONStore

# ---------------------------------------------------------------------------
# 输入校验与转义
# ---------------------------------------------------------------------------

# 允许的字符集：字母、数字、下划线、连字符、点（支持版本号如 1.0.2）
_TASK_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")

# Timeout 边界（秒）
_MIN_TIMEOUT = 60      # 最少 60 秒（防止误配）
_MAX_TIMEOUT = 86400  # 最多 24 小时

def _validate_task_id(task_id: str) -> str:
    """校验 task_id 格式，只允许 [A-Za-z0-9_.-]，非法时抛出 ValueError。"""
    if not task_id:
        raise ValueError("task_id cannot be empty")
    if not _TASK_ID_PATTERN.match(task_id):
        raise ValueError(
            f"Invalid task_id format: '{task_id}'. "
            f"Only [A-Za-z0-9_.-] allowed."
        )
    return task_id

def _validate_timeout(timeout_seconds: int) -> int:
    """校验并规范化 timeout 值，超出边界时 clip 到边界。"""
    if timeout_seconds < _MIN_TIMEOUT:
        return _MIN_TIMEOUT
    if timeout_seconds > _MAX_TIMEOUT:
        return _MAX_TIMEOUT
    return timeout_seconds

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
      空格 -> ^  (保持参数边界)
    """
    result = s.replace("%", "%%")
    result = result.replace("^", "^^")
    result = result.replace("&", "^&")
    result = result.replace("|", "^|")
    result = result.replace("<", "^<")
    result = result.replace(">", "^>")
    result = result.replace('"', '^"')
    result = result.replace("!", "^^!")  # Delayed expansion: !VAR! -> ^!VAR^! in set "VAR=..."
    return result


@dataclass
class ThinkingSlot:
    slot_id: str
    slot_dir: Path
    workspace_dir: Path
    busy: bool = False
    assigned_task_id: str = ""
    launch_result: dict[str, Any] | None = None
    assigned_at_epoch: float = 0.0
    timeout_seconds: int = 300
    # [Fix P2] Record last known state for accurate timeout events
    last_known_state: str = "state_0"
    enabled: bool = True


class ThinkingRuntime:
    def __init__(
        self,
        root_dir: Path | str,
        signal_port: int = 18765,
    ):
        self._root_dir = Path(root_dir)
        self._timeout_defaults = TimeoutDefaultsStore(root_dir=self._root_dir)

        # Core paths - pools/thinking/
        self._thinking_pool_dir = self._root_dir / "pools" / "thinking"
        self._queue_dir = self._thinking_pool_dir / "Queue"
        self._outbox_dir = self._thinking_pool_dir / "Outbox"

        # Dynamic slot discovery: scan sub_brain_*
        self._slots: dict[str, ThinkingSlot] = {}
        self._governance_store = SlotGovernanceStore(root_dir=self._root_dir)
        self._init_slots()

        # Signal server - 每个 Runtime 有自己的独立实例
        self._signal_server = RuntimeSignalServer(
            port=signal_port,
            event_store_dir=self._root_dir / "events" / "thinking",
        )
        self._signal_server.on_signal = self.handle_signal
        self._signal_server.on_api_request = self.handle_api_request

        # Managers - 独立实例，不共享
        self._launch_manager = LaunchManager()

        # Lifecycle tools directory (can be overridden for testing)
        self._lifecycle_tools_dir = self._root_dir / "runtime" / "tools"

        # Lock to protect slot state from concurrent access
        self._lock = threading.RLock()

        # Pause control state
        self._paused = False

    def _init_slots(self) -> None:
        """Initialize thinking slots by dynamically scanning sub_brain_* directories."""
        if not self._thinking_pool_dir.exists():
            return

        # Sort for deterministic order
        sub_brain_dirs = sorted(
            d for d in self._thinking_pool_dir.iterdir()
            if d.is_dir() and fnmatch.fnmatch(d.name, "sub_brain_*")
        )
        for slot_dir in sub_brain_dirs:
            slot_id = slot_dir.name
            workspace_dir = slot_dir / "workspace"
            if not workspace_dir.exists() or not workspace_dir.is_dir():
                continue
            enabled = self._governance_store.is_enabled("thinking", slot_id)
            self._slots[slot_id] = ThinkingSlot(
                slot_id=slot_id,
                slot_dir=slot_dir,
                workspace_dir=workspace_dir,
                busy=False,
                assigned_task_id="",
                launch_result=None,
                enabled=enabled,
            )

    def _deploy_lifecycle_bats(self, slot: ThinkingSlot) -> None:
        """Copy lifecycle bats and signal bridge into thinking slot directory."""
        tools_dir = self._lifecycle_tools_dir
        if not tools_dir.exists():
            raise FileNotFoundError(f"Missing lifecycle tools directory: {tools_dir}")

        # Thinking Pool lifecycle bats
        lifecycle_files = [
            "Online.bat",
            "StartThinking.bat",
            "StartSummarizing.bat",
            "Done.bat",
            "signal_bridge.py",
            "THINKING_BOOTSTRAP.txt",
        ]
        for file_name in lifecycle_files:
            src = tools_dir / file_name
            if not src.exists():
                raise FileNotFoundError(f"Missing required lifecycle tool: {src}")
            dst = slot.slot_dir / file_name
            dst.write_bytes(src.read_bytes())

    def get_next_idle_slot(self) -> ThinkingSlot | None:
        """Return the lowest-numbered idle slot, or None if all are busy."""
        with self._lock:
            slot_ids = sorted(self._slots.keys())
            for slot_id in slot_ids:
                slot = self._slots[slot_id]
                if slot.enabled and not slot.busy:
                    return slot
            return None

    def get_slot(self, slot_id: str) -> ThinkingSlot | None:
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
        slot: ThinkingSlot,
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
        slot.assigned_task_id = ""
        slot.launch_result = None
        slot.assigned_at_epoch = 0.0
        slot.timeout_seconds = self._timeout_defaults.get("thinking")

    def dispatch_next(self, dry_run: bool = True) -> dict[str, Any]:
        """Dispatch the next task to an idle thinking slot."""
        if self._paused:
            return {"dispatched": False, "error": "Runtime is paused"}

        # [Concurrency Fix] Find next idle slot and mark it busy immediately under lock
        slot = None
        task_file = None
        original_name = ""
        raw_content = ""
        with self._lock:
            slot_ids = sorted(self._slots.keys())
            for slot_id in slot_ids:
                candidate = self._slots[slot_id]
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
        try:
            original_name = task_file.name[:-11] if task_file.name.endswith(".processing") else task_file.name
            raw_content = task_file.read_text(encoding="utf-8")
            header_text, _ = split_task_file_content(raw_content)
            headers = parse_task_header(header_text)

            # [Project-centric] Only accept PROJECT_KEY as task identifier
            project_key = headers.get("PROJECT_KEY", "")
            if not project_key:
                raise ValueError("PROJECT_KEY is required")

            task_id = _validate_task_id(project_key)

            raw_timeout = headers.get("TIMEOUT", None)
            if raw_timeout is None:
                parsed_timeout = self._timeout_defaults.get("thinking")
            else:
                try:
                    parsed_timeout = int(raw_timeout)
                except (TypeError, ValueError) as e:
                    raise ValueError(f"Invalid TIMEOUT value: {raw_timeout}") from e
            timeout_seconds = _validate_timeout(parsed_timeout)
        except Exception:
            if slot is not None and task_file is not None:
                self._rollback_dispatch(slot, task_file, original_name, raw_content)
            raise

        # [Work Pool 踩坑] 派发前必须清空 workspace，防止任务 A 残留污染任务 B
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

        # [Work Pool 踩坑] 清理槽位根目录的旧任务文件
        for f in slot.slot_dir.glob("*.txt"):
            if f.name.startswith("task_") or f.name.startswith("demo_task") or f.name.startswith("lifecycle_"):
                f.unlink()

        # Copy task to slot directory
        worker_task_file = slot.slot_dir / original_name
        worker_task_file.write_text(raw_content, encoding="utf-8")

        try:
            # Deploy lifecycle bats — may raise FileNotFoundError
            self._deploy_lifecycle_bats(slot)

            # [Security Fix] 生成 launch bat，包含 fallback done 信号防止假死
            # 所有环境变量值经过转义，防止命令注入
            bat_content = f"""@echo off
REM Agent launch: {slot.slot_id} for task {task_id}
REM Pool: thinking

set "AGENT_ID={_escape_bat_var(slot.slot_id)}"
set "TASK_ID={_escape_bat_var(task_id)}"
set "PROJECT_KEY={_escape_bat_var(task_id)}"
set "ROLE=thinker"
set "POOL=thinking"
set "SIGNAL_SERVER_PORT={self._signal_port}"

cd /d "%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$env:CLAUDECODE = $null; & 'claude.cmd' --dangerously-skip-permissions 'Read and strictly follow all instructions in THINKING_BOOTSTRAP.txt in the current directory.'"

REM [Work Pool 踩坑] Fallback: if Claude exits without calling Done.bat (e.g. end_turn stop_reason),
REM this ensures the terminal signal is sent so the slot is released without timeout.
python "%~dp0signal_bridge.py" --agent-id %AGENT_ID% --task-id %TASK_ID% --signal done --pool thinking --message "fallback_done"

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

    def _clean_slot_dir(self, slot: ThinkingSlot) -> None:
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
        slot: ThinkingSlot,
        *,
        signal: str,
        task_id: str,
        is_timeout: bool = False,
        collect_artifacts: bool = False,
    ) -> dict[str, Any]:
        """
        Unified terminal state convergence for done/failed/blocked/timeout.

        Must be called within self._lock, and caller must have verified task_id consistency.
        Execution order (from Work Pool verified sequence):
        1. Write terminal event (timeout must write)
        2. cleanup_launch (kill process)
        3. collect_artifacts (done only, after process is dead)
        4. clean_slot_dir
        5. reset slot fields
        """
        result = {"finalized": True, "slot_id": slot.slot_id, "task_id": task_id, "signal": signal}

        # Step 1: Write terminal event (timeout must write, done/failed/blocked already written by signal server)
        if is_timeout:
            from app.services.event_store import LifecycleEvent
            from datetime import datetime

            # [Fix P2] Use slot's last_known_state instead of hardcoded fallback
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
                pool="thinking",
                from_state=current_state,
                to_state="state_timeout",
                is_terminal=True,
            ))

        # Step 2: cleanup_launch (kill process first)
        if slot.launch_result is not None:
            cleanup_result = self._launch_manager.cleanup_launch(slot.launch_result)
            result["cleanup"] = cleanup_result

        # Step 3: collect_artifacts (done only, after process is dead)
        if collect_artifacts:
            artifact_result = self.collect_artifacts_to_outbox(slot.slot_id, task_id)
            result["artifacts"] = artifact_result

        # Step 4: clean_slot_dir
        self._clean_slot_dir(slot)

        # Step 5: reset slot fields
        slot.busy = False
        slot.assigned_task_id = ""
        slot.launch_result = None
        slot.assigned_at_epoch = 0.0
        slot.timeout_seconds = self._timeout_defaults.get("thinking")
        slot.last_known_state = "state_0"

        return result

    def handle_signal(self, signal_result: dict[str, Any]) -> None:
        """Handle lifecycle signals from workers, releasing slots and cleaning up workers on terminal signals."""
        with self._lock:
            agent_id = signal_result.get("agent_id", "")
            task_id = signal_result.get("task_id", "")
            signal = signal_result.get("signal", "")
            is_terminal = signal_result.get("is_terminal", False)
            to_state = signal_result.get("to_state", "")

            slot = self._slots.get(agent_id)
            if slot is None:
                return

            # Guard: only process terminal signals if slot is busy and task_id matches
            if not slot.busy:
                return

            if slot.assigned_task_id != task_id:
                return  # [Work Pool 踩坑] Stale or mismatched signal, ignore

            if to_state:
                slot.last_known_state = to_state

            # Release slot and kill worker process for terminal signals
            terminal_signals = {"done", "failed", "blocked"}
            if signal in terminal_signals or is_terminal:
                self._finalize_slot_terminal(
                    slot,
                    signal=signal,
                    task_id=task_id,
                    is_timeout=False,
                    collect_artifacts=True,  # [Fix] 无论是 done 还是 failed/blocked，都尽力收集残留产物
                )

    def check_timeouts(self) -> list[dict[str, Any]]:
        """Kill and release workers whose runtime exceeds TIMEOUT."""
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

                # Timeout detected, finalize slot
                finalize_result = self._finalize_slot_terminal(
                    slot,
                    signal="timeout",
                    task_id=task_id,
                    is_timeout=True,
                    collect_artifacts=True,  # [Fix] 保留超时遗留产物
                )

                timed_out.append(
                    {
                        "slot_id": slot.slot_id,
                        "task_id": finalize_result["task_id"],
                        "timeout_seconds": timeout_seconds,
                    }
                )

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

        workspace_items = list(slot.workspace_dir.iterdir())
        workspace_files = [item for item in workspace_items if item.is_file()]
        workspace_dirs = [item for item in workspace_items if item.is_dir()]

        source_root = slot.workspace_dir
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
            "pool": "thinking",
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
            self._governance_store.set_enabled("thinking", slot_id, False)
        return {"success": True, "pool": "thinking", "slot_id": slot_id, "enabled": False, "busy": slot.busy}

    def _slot_online(self, payload: dict | None) -> dict[str, Any]:
        if not payload or "slot_id" not in payload:
            return {"success": False, "error": "slot_id required"}
        slot_id = payload["slot_id"]
        slot = self.get_slot(slot_id)
        if slot is None:
            return {"success": False, "error": f"slot not found: {slot_id}"}
        with self._lock:
            slot.enabled = True
            self._governance_store.set_enabled("thinking", slot_id, True)
        return {"success": True, "pool": "thinking", "slot_id": slot_id, "enabled": True, "busy": slot.busy}

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
                "pool": "thinking",
                "signal_port": self._signal_port,
                "is_running": self._signal_server.is_running,
                "queue_count": queue_count,
                "slots": slots_data,
            }

    def _get_health(self) -> dict[str, Any]:
        """Return basic health check information."""
        return {
            "ok": True,
            "pool": "thinking",
            "uptime_seconds": 0,
        }
