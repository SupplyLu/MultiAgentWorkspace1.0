"""
Test Work Runtime can dispatch atomic workorder directories from POST.

POST delivers atomic workorder directories (e.g., E2ETest-v1-Build-001/)
to Work Queue. Work Runtime must recognize and dispatch these directories.
"""

import pytest
import tempfile
from pathlib import Path

from app.runtimes.work_runtime import WorkRuntime


@pytest.mark.skip(reason="Work Runtime atomic workorder directory dispatch not yet implemented")
def test_work_runtime_dispatches_atomic_workorder_directory():
    """
    When POST delivers an atomic workorder directory to Work Queue,
    Work Runtime should recognize it and dispatch the task inside.

    This ensures the Gate → Work handoff works end-to-end.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        work_pool = root / "pools" / "work"
        queue_dir = work_pool / "Queue"
        queue_dir.mkdir(parents=True)

        outbox_dir = work_pool / "Outbox"
        outbox_dir.mkdir(parents=True)

        worker_dir = work_pool / "worker_01"
        workspace_dir = worker_dir / "workspace"
        workspace_dir.mkdir(parents=True)

        tools_dir = root / "runtime" / "tools"
        tools_dir.mkdir(parents=True)
        for f in ["Online.bat", "StartWriting.bat", "Done.bat", "signal_bridge.py", "WORK_BOOTSTRAP.txt"]:
            (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")

        # POST delivers atomic workorder directory with task file inside
        workorder_dir = queue_dir / "E2ETest-v1-Build-001"
        workorder_dir.mkdir()
        (workorder_dir / "task_001.txt").write_text(
            "FROM: gate\nTO: work\nPROJECT_KEY: SignalBridge-v1-Build-Task001\n---\nApproved work task 1",
            encoding="utf-8"
        )

        runtime = WorkRuntime(root_dir=root, signal_port=19299)

        # Work Runtime should recognize the directory as a dispatchable task
        tasks = runtime.list_queue_tasks()
        assert len(tasks) > 0, "Work Runtime should recognize atomic workorder directory in Queue"

        # Mock launch to avoid actual process spawn
        import app.shared.launch_manager as lm_module
        original_launch = lm_module.LaunchManager.launch

        def mock_launch(self, request, dry_run=True):
            return {
                "launched": True,
                "dry_run": True,
                "command": ["cmd"],
                "cwd": str(worker_dir),
                "pid": 9999,
                "job_handle": None,
            }

        lm_module.LaunchManager.launch = mock_launch

        try:
            # Dispatch should succeed
            result = runtime.dispatch_next(dry_run=True)

            assert result["dispatched"] is True, f"Expected dispatch to succeed, got: {result}"
            assert result["slot_id"] == "worker_01"
            assert result["task_id"] == "SignalBridge-v1-Build-Task001"

            # Verify task file was copied to worker slot
            worker_task = worker_dir / "task_001.txt"
            assert worker_task.exists(), "Task file should be copied to worker slot"

            # Verify workorder directory was removed from queue
            assert not workorder_dir.exists(), "Workorder directory should be removed from Queue after dispatch"

        finally:
            lm_module.LaunchManager.launch = original_launch
