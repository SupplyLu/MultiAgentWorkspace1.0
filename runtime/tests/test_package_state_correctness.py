"""Regression tests for PackageRuntime terminal state correctness.

验证 Package Runtime denied 阶段记录、timeout 状态复位、pause/resume API。
"""
from pathlib import Path
import time

from app.runtimes.package_runtime import PackageRuntime, PackageTask


def test_denied_records_actual_stage_not_denied_string(tmp_path: Path):
    """DENIED_AT_STAGE 必须是真实拒绝阶段（如 cut/test/release），而不是 "denied"。"""
    package_pool = tmp_path / "pools" / "package"
    (package_pool / "Queue").mkdir(parents=True)
    (package_pool / "Outbox").mkdir(parents=True)
    (package_pool / "Rejectbox").mkdir(parents=True)
    (package_pool / "context").mkdir(parents=True)
    (package_pool / "Release").mkdir(parents=True)

    cutter_dir = package_pool / "cutter_01"
    cutter_dir.mkdir(parents=True)
    (cutter_dir / "workspace").mkdir()

    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True)
    for f in ["Online.bat", "StartCut.bat", "StartTest.bat", "StartRelease.bat",
              "StartCompletePlayer.bat", "Reject.bat", "signal_bridge.py", "BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")

    runtime = PackageRuntime(root_dir=tmp_path, signal_port=19310)
    runtime._slots.clear()
    from app.runtimes.package_runtime import PackageSlot
    runtime._slots["cutter_01"] = PackageSlot(
        slot_id="cutter_01",
        slot_dir=cutter_dir,
        workspace_dir=cutter_dir / "workspace",
        slot_type="cutter",
    )

    task = PackageTask(
        task_id="pkg_001",
        project_name="demo_project",
        project_root=tmp_path / "pools" / "work" / "fields" / "demo_project",
        original_task="package demo project",
        context_dir=package_pool / "context" / "demo_project",
        current_stage="cut",
    )
    runtime._tasks[task.task_id] = task

    slot = runtime.get_slot("cutter_01")
    slot.busy = True
    slot.assigned_task_id = task.task_id
    slot.assigned_project_name = task.project_name
    slot.assigned_at_epoch = time.time()
    slot.launch_result = {"launched": True, "job_handle": None}
    task.assigned_slots["cut"] = "cutter_01"

    try:
        runtime.handle_signal({
            "agent_id": "cutter_01",
            "task_id": task.task_id,
            "signal": "denied",
            "to_state": "state_denied",
        })
    except Exception:
        pass

    reject_file = package_pool / "Rejectbox" / f"{task.project_name}_denied.txt"
    assert reject_file.exists(), "Rejectbox marker must exist"
    content = reject_file.read_text(encoding="utf-8")
    assert "DENIED_AT_STAGE: cut" in content, "DENIED_AT_STAGE must be the actual stage, not 'denied'"
    assert "DENIED_AT_STAGE: denied" not in content, "DENIED_AT_STAGE must NOT be the string 'denied'"


def test_timeout_resets_all_slot_fields(tmp_path: Path):
    """timeout 后槽位所有字段回到初始值，包括 finalizing/assigned_project_name/last_known_state。"""
    package_pool = tmp_path / "pools" / "package"
    (package_pool / "Queue").mkdir(parents=True)
    (package_pool / "Outbox").mkdir(parents=True)
    (package_pool / "Rejectbox").mkdir(parents=True)
    (package_pool / "context").mkdir(parents=True)
    (package_pool / "Release").mkdir(parents=True)

    slot_dir = package_pool / "cutter_01"
    slot_dir.mkdir(parents=True)
    (slot_dir / "workspace").mkdir()

    from app.runtimes.package_runtime import PackageSlot
    runtime = PackageRuntime(root_dir=tmp_path, signal_port=19311)
    runtime._slots.clear()
    runtime._slots["cutter_01"] = PackageSlot(
        slot_id="cutter_01",
        slot_dir=slot_dir,
        workspace_dir=slot_dir / "workspace",
        slot_type="cutter",
    )

    task = PackageTask(
        task_id="pkg_002",
        project_name="test_project",
        project_root=tmp_path / "pools" / "work" / "fields" / "test_project",
        original_task="test",
        context_dir=package_pool / "context" / "test_project",
        current_stage="cut",
    )
    runtime._tasks[task.task_id] = task

    slot = runtime.get_slot("cutter_01")
    slot.busy = True
    slot.finalizing = False
    slot.assigned_task_id = task.task_id
    slot.assigned_project_name = task.project_name
    slot.launch_result = {"launched": True, "job_handle": None}
    slot.assigned_at_epoch = time.time() - 2000  # already timed out
    slot.last_known_state = "state_cut"

    # Make cleanup_launch a no-op
    original_cleanup = runtime._launch_manager.cleanup_launch
    runtime._launch_manager.cleanup_launch = lambda r: {"cleaned": True}

    try:
        timed_out = runtime.check_timeouts()
        assert len(timed_out) == 1
    finally:
        runtime._launch_manager.cleanup_launch = original_cleanup

    # All fields reset
    assert slot.busy is False
    assert slot.finalizing is False, "finalizing must be reset after timeout"
    assert slot.assigned_task_id == ""
    assert slot.assigned_project_name == "", "assigned_project_name must be reset after timeout"
    assert slot.launch_result is None
    assert slot.assigned_at_epoch == 0.0
    assert slot.last_known_state == "state_0", "last_known_state must be reset after timeout"

    # Task is removed
    assert task.task_id not in runtime._tasks


def test_package_runtime_pause_resume_control(tmp_path: Path):
    """PackageRuntime 支持 pause/resume 控制面，与其他 runtime 行为一致。"""
    package_pool = tmp_path / "pools" / "package"
    (package_pool / "Queue").mkdir(parents=True)
    (package_pool / "Outbox").mkdir(parents=True)
    (package_pool / "Rejectbox").mkdir(parents=True)
    (package_pool / "context").mkdir(parents=True)
    (package_pool / "Release").mkdir(parents=True)

    runtime = PackageRuntime(root_dir=tmp_path, signal_port=19312)
    assert runtime._paused is False

    # Pause
    result = runtime.handle_api_request("POST", "/api/control/pause", None)
    assert result["paused"] is True
    assert result["pool"] == "package"
    assert runtime._paused is True

    # State check
    result = runtime.handle_api_request("GET", "/api/control/state", None)
    assert result["paused"] is True
    assert result["pool"] == "package"

    # Resume
    result = runtime.handle_api_request("POST", "/api/control/resume", None)
    assert result["paused"] is False
    assert result["pool"] == "package"
    assert runtime._paused is False
