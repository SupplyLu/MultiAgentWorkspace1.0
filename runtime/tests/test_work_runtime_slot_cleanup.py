"""Regression tests for WorkRuntime stale slot cleanup.

These tests verify that reused worker slots do not retain stale task files
from previous assignments, regardless of filename pattern.
"""

from pathlib import Path

from app.runtimes.work_runtime import WorkRuntime


def test_dispatch_next_removes_stale_fix_critical_task_files(tmp_path):
    """Test that dispatch_next cleans stale fix_critical_*.txt files from reused slots."""
    queue_dir = tmp_path / "pools" / "work" / "Queue"
    queue_dir.mkdir(parents=True)
    worker1_dir = tmp_path / "pools" / "work" / "worker_01"
    worker1_dir.mkdir(parents=True)
    (worker1_dir / "workspace").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "Outbox").mkdir(parents=True)

    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    for f in ["Online.bat", "StartWriting.bat", "Done.bat", "signal_bridge.py", "WORK_BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")

    stale_file = worker1_dir / "fix_critical_001_path_injection.txt"
    stale_file.write_text("old task", encoding="utf-8")
    stale_summary = worker1_dir / "fix_critical_001_summary.md"
    stale_summary.write_text("old summary", encoding="utf-8")
    hidden_file = worker1_dir / ".keep"
    hidden_file.write_text("keep", encoding="utf-8")

    task_file = queue_dir / "fix_critical_002_concurrent_registry.txt"
    task_content = "PROJECT_KEY: SignalBridge-v1-ConcurrencyFix\n\nbody"
    task_file.write_text(task_content, encoding="utf-8")

    runtime = WorkRuntime(root_dir=tmp_path, signal_port=18772)

    import app.shared.launch_manager as lm_module
    original_launch = lm_module.LaunchManager.launch

    def mock_launch(self, request, dry_run=True):
        return {"launched": True, "dry_run": True, "job_handle": None}

    lm_module.LaunchManager.launch = mock_launch

    try:
        result = runtime.dispatch_next(dry_run=True)

        assert result["dispatched"] is True
        assert not stale_file.exists(), "stale task txt should be removed before dispatch"
        assert not stale_summary.exists(), "stale non-workspace artifact should be removed before dispatch"
        assert hidden_file.exists(), "hidden files should be preserved"

        new_task_file = worker1_dir / "fix_critical_002_concurrent_registry.txt"
        assert new_task_file.exists(), "new task file should be copied into slot"
        assert new_task_file.read_text(encoding="utf-8") == task_content
    finally:
        lm_module.LaunchManager.launch = original_launch
