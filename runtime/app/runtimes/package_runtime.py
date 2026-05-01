"""PackageRuntime - Orchestrator for the Package Pool.

Package Pool 职责：
- 4 阶段串行验收：Cut → Test → Release → CompletePlayer
- 槽位命名: cutter_01, tester_01, releaser_01, complete_player_01
- 池目录: pools/package/
- 生命周期: online → start_cut → cut_passed → start_test → test_passed
             → start_release → release_passed → start_complete_player → done
- Outbox: 存放 completed 的产物（最终 Release 目录）
- Rejectbox: 存放 denied 的任务（任一阶段失败）
- timeout: 杀进程，任务重新放回 Queue
- denied: 统一拒绝信号，写入 Rejectbox

状态流转：
state_0            idle
state_1            online
state_2            cutting
state_3            testing
state_4            releasing
state_5            completing
state_6_done       completed
state_6_rejected   denied
state_timeout      timeout
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import fnmatch
import json
import shutil
import threading
import time

from app.services.signal_server import RuntimeSignalServer
from app.services.slot_governance_store import SlotGovernanceStore
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
class PackageSlot:
    """Package 槽位定义"""
    slot_id: str
    slot_dir: Path
    workspace_dir: Path
    slot_type: str = ""  # cutter/tester/releaser/complete_player
    busy: bool = False
    finalizing: bool = False
    assigned_task_id: str = ""
    assigned_project_name: str = ""
    launch_result: dict[str, Any] | None = None
    assigned_at_epoch: float = 0.0
    timeout_seconds: int = 1800
    last_known_state: str = "state_0"
    enabled: bool = True


@dataclass
class PackageTask:
    """Package 任务跟踪"""
    task_id: str
    project_name: str
    project_root: Path
    original_task: str
    context_dir: Path
    current_stage: str = "idle"  # idle/cut/test/release/complete/done/denied
    stage_results: dict[str, dict] = field(default_factory=dict)
    assigned_slots: dict[str, str] = field(default_factory=dict)  # stage -> slot_id


class PackageDeniedError(Exception):
    """Package 阶段被拒绝"""
    pass


class PackageRuntime:
    """Package Pool Runtime 编排器"""

    # 阶段定义：顺序执行
    STAGES = ["cut", "test", "release", "complete"]
    STAGE_TO_SLOT_TYPE = {
        "cut": "cutter",
        "test": "tester",
        "release": "releaser",
        "complete": "complete_player",
    }
    STAGE_SIGNALS = {
        "cut": ("start_cut", "cut_passed"),
        "test": ("start_test", "test_passed"),
        "release": ("start_release", "release_passed"),
        "complete": ("start_complete_player", "done"),
    }

    def __init__(
        self,
        root_dir: Path | str,
        signal_port: int = 19300,
    ):
        self._root_dir = Path(root_dir)
        self._signal_port = signal_port

        # 池目录
        self._package_pool_dir = self._root_dir / "pools" / "package"
        self._queue_dir = self._package_pool_dir / "Queue"
        self._outbox_dir = self._package_pool_dir / "Outbox"
        self._rejectbox_dir = self._package_pool_dir / "Rejectbox"
        self._context_dir = self._package_pool_dir / "context"
        self._release_dir = self._package_pool_dir / "Release"

        # 槽位
        self._slots: dict[str, PackageSlot] = {}
        self._governance_store = SlotGovernanceStore(root_dir=self._root_dir)
        self._init_slots()

        # 任务跟踪
        self._tasks: dict[str, PackageTask] = {}

        # 信号服务器
        self._signal_server = RuntimeSignalServer(
            port=signal_port,
            event_store_dir=self._root_dir / "events" / "package",
        )
        self._signal_server.on_signal = self.handle_signal

        # 管理器
        self._launch_manager = LaunchManager()
        self._lifecycle_tools_dir = self._root_dir / "runtime" / "tools"
        self._lock = threading.RLock()
        self._paused = False

    def _init_slots(self) -> None:
        """动态扫描 cutter_*, tester_*, releaser_*, complete_player_* 槽位"""
        if not self._package_pool_dir.exists():
            return

        slot_patterns = ["cutter_*", "tester_*", "releaser_*", "complete_player_*"]

        for sub_dir in self._package_pool_dir.iterdir():
            if not sub_dir.is_dir():
                continue

            for pattern in slot_patterns:
                if fnmatch.fnmatch(sub_dir.name, pattern):
                    workspace_dir = sub_dir / "workspace"
                    if not workspace_dir.exists() or not workspace_dir.is_dir():
                        continue

                    # 提取槽位类型
                    slot_type = pattern.replace("_*", "")

                    self._slots[sub_dir.name] = PackageSlot(
                        slot_id=sub_dir.name,
                        slot_dir=sub_dir,
                        workspace_dir=workspace_dir,
                        slot_type=slot_type,
                        enabled=self._governance_store.is_enabled("package", sub_dir.name),
                    )
                    break

    def get_slot(self, slot_id: str) -> PackageSlot | None:
        """获取槽位"""
        return self._slots.get(slot_id)

    def list_queue_tasks(self) -> list[Path]:
        """列出 Queue 中的任务文件"""
        if not self._queue_dir.exists():
            return []
        return sorted(
            f for f in self._queue_dir.iterdir()
            if f.is_file() and f.suffix == ".txt" and not f.name.startswith(".")
        )

    def find_idle_slot_by_type(self, slot_type: str) -> PackageSlot | None:
        """按类型查找空闲槽位"""
        with self._lock:
            for slot_id in sorted(self._slots.keys()):
                slot = self._slots[slot_id]
                if slot.enabled and slot.slot_type == slot_type and not slot.busy and not slot.finalizing:
                    return slot
        return None

    def _deploy_lifecycle_bats(self, slot: PackageSlot) -> None:
        """部署生命周期工具到槽位"""
        tools_dir = self._lifecycle_tools_dir
        lifecycle_files = [
            "Online.bat",
            "StartCut.bat",
            "StartTest.bat",
            "StartRelease.bat",
            "StartCompletePlayer.bat",
            "Reject.bat",
            "signal_bridge.py",
            "BOOTSTRAP.txt",
        ]
        for file_name in lifecycle_files:
            src = tools_dir / file_name
            if not src.exists():
                raise FileNotFoundError(f"Missing required lifecycle tool: {src}")
            dst = slot.slot_dir / file_name
            dst.write_bytes(src.read_bytes())

    def _parse_timeout_seconds(self, headers: dict[str, Any]) -> int:
        """安全解析超时时间"""
        raw_timeout = headers.get("TIMEOUT", 1800)
        try:
            timeout_seconds = int(raw_timeout)
        except (TypeError, ValueError):
            return 1800
        if timeout_seconds <= 0:
            return 1800
        return timeout_seconds

    def _create_task_context(self, task_data: dict, task_file: Path) -> PackageTask:
        """创建任务上下文"""
        headers = task_data.get("headers", {})
        task_id = headers.get("TASK_ID", task_file.stem)
        project_name = headers.get("PROJECT_NAME", task_id)
        project_root = self._root_dir / "pools" / "work" / "fields" / project_name
        original_task = headers.get("ORIGINAL_TASK", task_data.get("content", ""))

        # 创建共享上下文目录
        context_dir = self._context_dir / project_name
        context_dir.mkdir(parents=True, exist_ok=True)

        # 保存输入到上下文
        (context_dir / "input.txt").write_text(
            f"TASK_ID: {task_id}\n"
            f"PROJECT_NAME: {project_name}\n"
            f"PROJECT_ROOT: {project_root}\n"
            f"ORIGINAL_TASK:\n{original_task}",
            encoding="utf-8"
        )

        task = PackageTask(
            task_id=task_id,
            project_name=project_name,
            project_root=project_root,
            original_task=original_task,
            context_dir=context_dir,
            current_stage="idle",
        )

        self._tasks[task_id] = task
        return task

    def _deploy_to_stage(self, task: PackageTask, stage: str, dry_run: bool = True) -> dict[str, Any]:
        """部署任务到指定阶段槽位"""
        slot_type = self.STAGE_TO_SLOT_TYPE[stage]
        start_signal, _ = self.STAGE_SIGNALS[stage]

        slot = self.find_idle_slot_by_type(slot_type)
        if slot is None:
            return {"dispatched": False, "error": f"No idle {slot_type} slot available"}

        # 标记槽位忙碌
        with self._lock:
            slot.busy = True
            slot.assigned_task_id = task.task_id
            slot.assigned_project_name = task.project_name
            slot.assigned_at_epoch = time.time()

        # 复制任务文件到槽位
        task_file_name = f"{task.task_id}.txt"
        task_content = f"""FROM: package_runtime
TO: {slot.slot_id}
TASK_ID: {task.task_id}
PROJECT_NAME: {task.project_name}
PROJECT_ROOT: {task.project_root}
CONTEXT_DIR: {task.context_dir}
PACKAGE_STAGE: {stage}
TIMEOUT: {slot.timeout_seconds}
---
{task.original_task}
"""
        worker_task_file = slot.slot_dir / task_file_name
        worker_task_file.write_text(task_content, encoding="utf-8")

        try:
            self._deploy_lifecycle_bats(slot)

            # 生成启动 bat
            bat_content = f"""@echo off
REM Package Agent launch: {slot.slot_id} for task {task.task_id}
REM Stage: {stage}

set "AGENT_ID={_escape_bat_var(slot.slot_id)}"
set "TASK_ID={_escape_bat_var(task.task_id)}"
set "PROJECT_NAME={_escape_bat_var(task.project_name)}"
set "PROJECT_ROOT={_escape_bat_var(task.project_root.as_posix())}"
set "CONTEXT_DIR={_escape_bat_var(task.context_dir.as_posix())}"
set "PACKAGE_STAGE={_escape_bat_var(stage)}"
set ROLE=packager
set POOL=package
set SIGNAL_SERVER_PORT={self._signal_port}

cd /d "%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$env:CLAUDECODE = $null; & 'claude.cmd' --dangerously-skip-permissions 'Read and strictly follow all instructions in BOOTSTRAP.txt in the current directory.'"

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

        except Exception as e:
            # 回滚
            if worker_task_file.exists():
                worker_task_file.unlink()
            with self._lock:
                slot.busy = False
                slot.assigned_task_id = ""
            raise

        with self._lock:
            slot.launch_result = launch_result
            task.current_stage = stage
            task.assigned_slots[stage] = slot.slot_id

        return {
            "dispatched": True,
            "slot_id": slot.slot_id,
            "task_id": task.task_id,
            "stage": stage,
            "launch": launch_result,
        }

    def dispatch_next(self, dry_run: bool = True) -> dict[str, Any]:
        """派发下一个任务"""
        import logging
        logger = logging.getLogger(__name__)

        if self._paused:
            return {"dispatched": False, "error": "Runtime is paused"}

        original_name = ""
        processing_file = None

        with self._lock:
            tasks = self.list_queue_tasks()
            if not tasks:
                return {"dispatched": False, "error": "No tasks in queue"}

            task_file = tasks[0]
            original_name = task_file.name
            processing_file = task_file.with_name(task_file.name + ".processing")
            try:
                task_file.rename(processing_file)
                task_file = processing_file
            except OSError:
                return {"dispatched": False, "error": "No tasks in queue"}

        task_data = parse_task_file(task_file)
        if task_data is None:
            if original_name:
                restored = task_file.with_name(original_name)
                try:
                    task_file.rename(restored)
                except OSError:
                    pass
            return {"dispatched": False, "error": "Failed to parse task file (invalid or disappeared)"}

        # 创建任务上下文
        task = self._create_task_context(task_data, task_file)

        # 先尝试派发到第一阶段：Cut
        result = self._deploy_to_stage(task, "cut", dry_run=dry_run)

        if result["dispatched"]:
            # 派发成功，删除已 claim 的队列文件
            try:
                task_file.unlink()
            except OSError:
                pass
        else:
            # 派发失败（没有空闲槽位），恢复 Queue 文件，清理任务跟踪
            logger.warning(f"Dispatch failed for task {task.task_id}: {result.get('error', 'Unknown error')}. Keeping queue file for retry.")
            del self._tasks[task.task_id]
            if original_name:
                restored = task_file.with_name(original_name)
                try:
                    task_file.rename(restored)
                except OSError:
                    pass

        return result

    def handle_signal(self, signal_result: dict[str, Any]) -> None:
        """处理生命周期信号"""
        agent_id = signal_result.get("agent_id", "")
        task_id = signal_result.get("task_id", "")
        signal = signal_result.get("signal", "")
        to_state = signal_result.get("to_state", "")

        with self._lock:
            slot = self._slots.get(agent_id)
            if slot is None:
                return

            task = self._tasks.get(task_id)
            if task is None:
                return

            # 验证槽位正在处理该任务
            if slot.assigned_task_id != task_id:
                return

            # 如果槽位已经进入终态收敛，忽略所有后续信号
            if slot.finalizing:
                return

            if to_state:
                slot.last_known_state = to_state

            terminal_signal = signal in ["done", "denied"]
            if terminal_signal:
                slot.finalizing = True

        # 处理通过信号
        if signal in ["cut_passed", "test_passed", "release_passed"]:
            self._handle_stage_passed(task, slot, signal)

        # 处理完成信号
        elif signal == "done":
            self._handle_done(task, slot)

        # 处理拒绝信号
        elif signal == "denied":
            self._handle_denied(task, slot)

    def _handle_stage_passed(self, task: PackageTask, slot: PackageSlot, signal: str) -> None:
        """处理阶段通过信号"""
        # 记录阶段结果
        stage_map = {
            "cut_passed": "cut",
            "test_passed": "test",
            "release_passed": "release",
        }
        current_stage = stage_map[signal]

        task.stage_results[current_stage] = {"status": "passed", "slot_id": slot.slot_id}

        # 清理当前槽位
        self._finalize_slot(slot)

        # 确定下一阶段
        current_index = self.STAGES.index(current_stage)
        if current_index + 1 < len(self.STAGES):
            next_stage = self.STAGES[current_index + 1]
            result = self._deploy_to_stage(task, next_stage, dry_run=False)
            if not result["dispatched"]:
                # 下一阶段无可用槽位，回队等待
                self._requeue_task(task)
        else:
            # 所有阶段完成，不应该到这里（done 信号会处理）
            pass

    def _handle_done(self, task: PackageTask, slot: PackageSlot) -> None:
        """处理完成信号"""
        task.current_stage = "done"
        task.stage_results["complete"] = {"status": "completed", "slot_id": slot.slot_id}

        # 收集产物到 Outbox
        self._collect_release_to_outbox(task)

        # 清理槽位
        self._finalize_slot_claimed(slot)

        # 清理任务跟踪
        self._tasks.pop(task.task_id, None)

    def _handle_denied(self, task: PackageTask, slot: PackageSlot) -> None:
        """处理拒绝信号"""
        # [Fix] 先保存真实拒绝阶段，再改 current_stage
        denied_stage = task.current_stage
        task.current_stage = "denied"

        # 记录拒绝信息
        task.stage_results[denied_stage] = {
            "status": "denied",
            "slot_id": slot.slot_id,
        }

        # 收集拒绝标记到 Rejectbox
        self._write_rejectbox_marker(task, denied_stage)

        # 清理槽位
        self._finalize_slot_claimed(slot)

        # 清理任务跟踪
        self._tasks.pop(task.task_id, None)

        # 抛出异常让 Runtime 主循环知道这是失败完成
        raise PackageDeniedError(
            f"Task {task.task_id} denied at stage {denied_stage} by {slot.slot_id}"
        )

    def _finalize_slot(self, slot: PackageSlot) -> None:
        """终结槽位状态"""
        with self._lock:
            if not slot.busy or slot.finalizing or not slot.assigned_task_id:
                return
            slot.finalizing = True

        self._finalize_slot_claimed(slot)

    def _finalize_slot_claimed(self, slot: PackageSlot) -> None:
        """终结已由调用方 claim 过 finalizing 权限的槽位状态"""
        with self._lock:
            if not slot.busy or not slot.assigned_task_id:
                return
            claimed_launch_result = slot.launch_result
            slot.launch_result = None

        if claimed_launch_result is not None:
            self._launch_manager.cleanup_launch(claimed_launch_result)

        self._clean_slot_dir(slot)

        with self._lock:
            slot.busy = False
            slot.finalizing = False
            slot.assigned_task_id = ""
            slot.assigned_project_name = ""
            slot.launch_result = None
            slot.assigned_at_epoch = 0.0
            slot.last_known_state = "state_0"

    def _clean_slot_dir(self, slot: PackageSlot) -> None:
        """清理槽位目录（保留 workspace）"""
        for item in slot.slot_dir.iterdir():
            if item.name == "workspace":
                continue
            try:
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item)
            except OSError:
                pass

    def _write_rejectbox_marker(self, task: PackageTask, stage: str) -> None:
        """写入拒绝标记到 Rejectbox"""
        reject_file = self._rejectbox_dir / f"{task.project_name}_denied.txt"
        self._rejectbox_dir.mkdir(parents=True, exist_ok=True)

        content = f"""PROJECT_NAME: {task.project_name}
TASK_ID: {task.task_id}
DENIED_AT_STAGE: {stage}
TIMESTAMP: {time.strftime('%Y-%m-%dT%H:%M:%S')}
REJECTED_BY: {task.assigned_slots.get(stage, 'unknown')}
CONTEXT_DIR: {task.context_dir}

STAGE_RESULTS:
{json.dumps(task.stage_results, indent=2, ensure_ascii=False)}
"""
        reject_file.write_text(content, encoding="utf-8")

    def _collect_release_to_outbox(self, task: PackageTask) -> dict[str, Any]:
        """收集 Release 产物到 Outbox"""
        release_project_dir = self._release_dir / task.project_name
        if not release_project_dir.exists():
            return {"collected": False, "reason": "release_dir_not_found"}

        outbox_task_dir = self._outbox_dir / task.task_id
        self._outbox_dir.mkdir(parents=True, exist_ok=True)

        # 创建 manifest
        manifest = {
            "project_name": task.project_name,
            "task_id": task.task_id,
            "packaged_at": time.strftime('%Y-%m-%dT%H:%M:%S'),
            "stages": task.stage_results,
            "original_task_digest": task.original_task[:500] if task.original_task else "",
        }

        manifest_file = release_project_dir / "package_manifest.json"
        manifest_file.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

        # 复制整个 Release 目录到 Outbox
        if outbox_task_dir.exists():
            shutil.rmtree(outbox_task_dir)
        shutil.copytree(release_project_dir, outbox_task_dir)

        return {
            "collected": True,
            "task_id": task.task_id,
            "outbox_dir": str(outbox_task_dir),
            "manifest": manifest,
        }

    def check_timeouts(self) -> list[dict[str, Any]]:
        """检查超时任务"""
        timed_out = []
        current_time = time.time()

        with self._lock:
            for slot in self._slots.values():
                if not slot.busy or slot.finalizing or not slot.assigned_task_id:
                    continue

                elapsed = current_time - slot.assigned_at_epoch
                if elapsed > slot.timeout_seconds:
                    task = self._tasks.get(slot.assigned_task_id)
                    if task:
                        timed_out.append({
                            "slot_id": slot.slot_id,
                            "task_id": slot.assigned_task_id,
                            "timeout_seconds": slot.timeout_seconds,
                            "elapsed_seconds": elapsed,
                        })

                        # 清理进程
                        if slot.launch_result is not None:
                            self._launch_manager.cleanup_launch(slot.launch_result)

                        # 写超时拒绝标记
                        task.current_stage = "timeout"
                        self._write_rejectbox_marker(task, f"{task.current_stage}_timeout")

                        # 重新放回 Queue
                        self._requeue_task(task)

                        # 清理槽位
                        self._clean_slot_dir(slot)
                        slot.busy = False
                        slot.finalizing = False
                        slot.assigned_task_id = ""
                        slot.assigned_project_name = ""
                        slot.launch_result = None
                        slot.assigned_at_epoch = 0.0
                        slot.last_known_state = "state_0"

                        # 清理任务跟踪
                        del self._tasks[task.task_id]

        return timed_out

    def _requeue_task(self, task: PackageTask) -> None:
        """将任务重新放回 Queue"""
        task_file = self._queue_dir / f"{task.task_id}.txt"
        task_content = f"""FROM: package_runtime
TO: package
TASK_ID: {task.task_id}
PROJECT_NAME: {task.project_name}
PROJECT_ROOT: {task.project_root}
REQUEUED: true
PREVIOUS_STAGE: {task.current_stage}
---
{task.original_task}
"""
        task_file.write_text(task_content, encoding="utf-8")

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
            "pool": "package",
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
            self._governance_store.set_enabled("package", slot_id, False)
        return {"success": True, "pool": "package", "slot_id": slot_id, "enabled": False, "busy": slot.busy}

    def _slot_online(self, payload: dict | None) -> dict[str, Any]:
        if not payload or "slot_id" not in payload:
            return {"success": False, "error": "slot_id required"}
        slot_id = payload["slot_id"]
        slot = self.get_slot(slot_id)
        if slot is None:
            return {"success": False, "error": f"slot not found: {slot_id}"}
        with self._lock:
            slot.enabled = True
            self._governance_store.set_enabled("package", slot_id, True)
        return {"success": True, "pool": "package", "slot_id": slot_id, "enabled": True, "busy": slot.busy}

    def _get_status(self) -> dict[str, Any]:
        """Return current runtime status with pool info and slot states."""
        with self._lock:
            slots_data = []
            for slot_id in sorted(self._slots.keys()):
                slot = self._slots[slot_id]

                # Find task for this slot to get current_stage
                task = self._tasks.get(slot.assigned_task_id) if slot.assigned_task_id else None
                current_stage = task.current_stage if task else ""

                # Determine current_state from last_known_state
                current_state = slot.last_known_state if slot.last_known_state != "state_0" else ("state_1" if slot.busy else "idle")

                slots_data.append({
                    "slot_id": slot.slot_id,
                    "busy": slot.busy,
                    "assigned_task_id": slot.assigned_task_id,
                    "assigned_project_name": slot.assigned_project_name,
                    "current_state": current_state,
                    "current_stage": current_stage,
                    "enabled": slot.enabled,
                })

            queue_count = len(self.list_queue_tasks())

            return {
                "pool": "package",
                "signal_port": self._signal_port,
                "is_running": self._signal_server.is_running,
                "queue_count": queue_count,
                "slots": slots_data,
            }

    def _get_health(self) -> dict[str, Any]:
        """Return basic health check information."""
        return {
            "ok": True,
            "pool": "package",
            "uptime_seconds": 0,
        }

    def start(self) -> None:
        """启动 Runtime"""
        self._signal_server.start()

    def stop(self) -> None:
        """停止 Runtime"""
        self._signal_server.stop()
