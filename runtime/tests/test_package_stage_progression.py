"""Test PackageRuntime stage progression failure handling.

验证当阶段通过后，下一阶段派发失败时的处理逻辑。
"""

from pathlib import Path
import time

from app.runtimes.package_runtime import PackageRuntime, PackageTask


def test_stage_passed_but_next_stage_has_no_idle_slot(tmp_path):
    """When stage passes but next stage has no idle slot, task should be requeued or marked for retry."""
    package_pool = tmp_path / "pools" / "package"
    (package_pool / "Queue").mkdir(parents=True)
    (package_pool / "Outbox").mkdir(parents=True)
    (package_pool / "Rejectbox").mkdir(parents=True)
    (package_pool / "context").mkdir(parents=True)
    (package_pool / "Release").mkdir(parents=True)

    # Create cutter slot (for cut stage)
    cutter_dir = package_pool / "cutter_01"
    cutter_dir.mkdir(parents=True)
    (cutter_dir / "workspace").mkdir()

    # NO tester slot created - this will cause next stage dispatch to fail

    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True)
    for f in ["Online.bat", "StartCut.bat", "StartTest.bat", "StartRelease.bat",
              "StartCompletePlayer.bat", "Reject.bat", "signal_bridge.py", "BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")

    runtime = PackageRuntime(root_dir=tmp_path, signal_port=19300)

    # Create a task that's currently in cut stage
    task = PackageTask(
        task_id="pkg_001",
        project_name="demo_project",
        project_root=tmp_path / "pools" / "work" / "fields" / "demo_project",
        original_task="package demo project",
        context_dir=package_pool / "context" / "demo_project",
        current_stage="cut",
    )
    runtime._tasks[task.task_id] = task

    # Assign task to cutter slot
    slot = runtime.get_slot("cutter_01")
    slot.busy = True
    slot.assigned_task_id = task.task_id
    slot.assigned_project_name = task.project_name
    slot.assigned_at_epoch = time.time()
    slot.launch_result = {"launched": True, "job_handle": None}

    # Send cut_passed signal - this should try to deploy to test stage
    # But test stage has no idle slot, so deployment will fail
    runtime.handle_signal({
        "agent_id": "cutter_01",
        "task_id": task.task_id,
        "signal": "cut_passed",
        "to_state": "state_cut_passed",
    })

    # After cut_passed handling:
    # 1. Task should have recorded cut stage result
    assert "cut" in task.stage_results
    assert task.stage_results["cut"]["status"] == "passed"

    # 2. Cutter slot should be finalized (cleaned up)
    assert slot.busy is False
    assert slot.assigned_task_id == ""

    # 3. Task should be requeued for retry when next stage has no idle slot
    queue_files = list((package_pool / "Queue").glob("*.txt"))
    assert len(queue_files) == 1, "Task should be requeued when next stage dispatch fails"

    # 4. Requeued task file should contain retry metadata
    requeued_file = queue_files[0]
    requeued_content = requeued_file.read_text(encoding="utf-8")
    assert "REQUEUED: true" in requeued_content
    assert "PREVIOUS_STAGE: cut" in requeued_content
    assert task.task_id in requeued_content
