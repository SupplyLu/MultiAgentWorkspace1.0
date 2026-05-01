"""Unit tests for WorkRuntime orchestrator."""

from pathlib import Path
import pytest

from app.runtimes.work_runtime import WorkRuntime, WorkerSlot


def test_get_next_idle_slot_uses_lowest_available(tmp_path):
    """Test that the lowest numbered idle slot is returned first."""
    # Create the directory structure
    (tmp_path / "pools" / "work" / "Queue").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "worker_01" / "workspace").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "worker_02" / "workspace").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "Outbox").mkdir(parents=True)

    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    for f in ["Online.bat", "StartWriting.bat", "Done.bat", "signal_bridge.py", "WORK_BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")


    runtime = WorkRuntime(root_dir=tmp_path, signal_port=18770)

    # First call should return worker_01
    slot1 = runtime.get_next_idle_slot()
    assert slot1 is not None
    assert slot1.slot_id == "worker_01"
    assert slot1.busy is False

    # Mark worker_01 as busy
    slot1.busy = True

    # Second call should return worker_02
    slot2 = runtime.get_next_idle_slot()
    assert slot2 is not None
    assert slot2.slot_id == "worker_02"
    assert slot2.busy is False

    # Mark both as busy
    slot2.busy = True

    # Third call should return None
    slot3 = runtime.get_next_idle_slot()
    assert slot3 is None


def test_list_queue_tasks_ignores_hidden_files(tmp_path):
    """Test that list_queue_tasks returns only visible .txt files."""
    # Create the directory structure
    queue_dir = tmp_path / "pools" / "work" / "Queue"
    queue_dir.mkdir(parents=True)
    (tmp_path / "pools" / "work" / "worker_01" / "workspace").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "worker_02" / "workspace").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "Outbox").mkdir(parents=True)

    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    for f in ["Online.bat", "StartWriting.bat", "Done.bat", "signal_bridge.py", "WORK_BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")


    # Create some files
    (queue_dir / "task_001.txt").write_text("content1")
    (queue_dir / "task_002.txt").write_text("content2")
    (queue_dir / ".hidden.txt").write_text("hidden")
    (queue_dir / "temp.md").write_text("markdown")

    runtime = WorkRuntime(root_dir=tmp_path, signal_port=18771)
    tasks = runtime.list_queue_tasks()

    assert len(tasks) == 2
    assert any(t.name == "task_001.txt" for t in tasks)
    assert any(t.name == "task_002.txt" for t in tasks)
    assert not any(t.name.startswith(".") for t in tasks)
    assert not any(t.suffix != ".txt" for t in tasks)


def test_dispatch_next_copies_task_to_worker_slot_and_marks_busy(tmp_path):
    """Test that dispatch_next copies task to worker slot and marks it busy."""
    # Create the directory structure
    queue_dir = tmp_path / "pools" / "work" / "Queue"
    queue_dir.mkdir(parents=True)
    worker1_dir = tmp_path / "pools" / "work" / "worker_01"
    worker1_dir.mkdir(parents=True)
    (worker1_dir / "workspace").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "worker_02" / "workspace").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "Outbox").mkdir(parents=True)

    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    for f in ["Online.bat", "StartWriting.bat", "Done.bat", "signal_bridge.py", "WORK_BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")


    # Create a task file
    task_file = queue_dir / "task_001.txt"
    task_content = """FROM: runtime
TO: worker_01
PROJECT_KEY: SignalBridge-v1-Build

Please implement the login page.
"""
    task_file.write_text(task_content, encoding="utf-8")

    runtime = WorkRuntime(root_dir=tmp_path, signal_port=18772)

    # Mock LaunchManager.launch to return a fake result
    fake_launch_result = {
        "launched": True,
        "dry_run": True,
        "command": ["cmd"],
        "cwd": str(worker1_dir),
        "pid": 1234,
        "job_handle": None,
    }

    import app.shared.launch_manager as lm_module
    original_launch = lm_module.LaunchManager.launch

    def mock_launch(self, request, dry_run=True):
        return fake_launch_result

    lm_module.LaunchManager.launch = mock_launch

    try:
        # Dispatch the task
        result = runtime.dispatch_next(dry_run=True)

        # Verify result
        assert result["dispatched"] is True
        assert result["slot_id"] == "worker_01"
        assert result["task_id"] == "SignalBridge-v1-Build"
        assert "task_file" in result
        assert "worker_task_file" in result
        assert result["launch"] == fake_launch_result

        # Verify task was copied to worker slot directory (Runtime 搬运)
        worker_task_file = worker1_dir / "task_001.txt"
        assert worker_task_file.exists()
        assert worker_task_file.read_text() == task_content

        # Verify task was removed from queue to avoid duplicate dispatch
        assert not task_file.exists()

        # Verify slot is marked busy
        slot = runtime.get_slot("worker_01")
        assert slot is not None
        assert slot.busy is True
        assert slot.assigned_task_id == "SignalBridge-v1-Build"

        # Verify launch bat file was created
        launch_bat = worker1_dir / "launch_worker_01.bat"
        assert launch_bat.exists()
        bat_content = launch_bat.read_text(encoding="utf-8")
        assert "worker_01" in bat_content
        assert "SignalBridge-v1-Build" in bat_content

    finally:
        lm_module.LaunchManager.launch = original_launch


def test_dispatch_next_handles_invalid_timeout_safely(tmp_path):
    """Test that dispatch_next does not crash on invalid TIMEOUT and falls back to default."""
    queue_dir = tmp_path / "pools" / "work" / "Queue"
    queue_dir.mkdir(parents=True)
    worker1_dir = tmp_path / "pools" / "work" / "worker_01"
    worker1_dir.mkdir(parents=True)
    (worker1_dir / "workspace").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "worker_02" / "workspace").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "Outbox").mkdir(parents=True)

    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    for f in ["Online.bat", "StartWriting.bat", "Done.bat", "signal_bridge.py", "WORK_BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")

    task_file = queue_dir / "task_invalid_timeout.txt"
    task_file.write_text(
        "PROJECT_KEY: SignalBridge-v1-Build\nTIMEOUT: foo\n\nbody",
        encoding="utf-8",
    )

    runtime = WorkRuntime(root_dir=tmp_path, signal_port=18907)

    import app.shared.launch_manager as lm_module
    original_launch = lm_module.LaunchManager.launch

    def mock_launch(self, request, dry_run=True):
        return {"launched": True, "dry_run": True, "job_handle": None}

    lm_module.LaunchManager.launch = mock_launch

    try:
        result = runtime.dispatch_next(dry_run=True)

        assert result["dispatched"] is True
        assert result["task_id"] == "SignalBridge-v1-Build"

        slot = runtime.get_slot("worker_01")
        assert slot is not None
        assert slot.timeout_seconds == 300
    finally:
        lm_module.LaunchManager.launch = original_launch


def test_dispatch_next_supports_legacy_header_key_shape(tmp_path):
    """Test that dispatch_next can read task_id from legacy 'header' key shape."""
    queue_dir = tmp_path / "pools" / "work" / "Queue"
    queue_dir.mkdir(parents=True)
    worker1_dir = tmp_path / "pools" / "work" / "worker_01"
    worker1_dir.mkdir(parents=True)
    (worker1_dir / "workspace").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "worker_02" / "workspace").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "Outbox").mkdir(parents=True)

    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    for f in ["Online.bat", "StartWriting.bat", "Done.bat", "signal_bridge.py", "WORK_BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")


    task_file = queue_dir / "task_legacy.txt"
    task_file.write_text("PROJECT_KEY: SignalBridge-v1-Build\n\nlegacy body")

    runtime = WorkRuntime(root_dir=tmp_path, signal_port=187731)

    import app.runtimes.work_runtime as wr_module
    original_parse = wr_module.parse_task_file

    def mock_parse_task_file(_path):
        return {
            "header": {"PROJECT_KEY": "SignalBridge-v1-Build"},
            "body": "legacy body",
            "raw": "PROJECT_KEY: SignalBridge-v1-Build\n\nlegacy body",
        }

    wr_module.parse_task_file = mock_parse_task_file

    import app.shared.launch_manager as lm_module
    original_launch = lm_module.LaunchManager.launch

    def mock_launch(self, request, dry_run=True):
        return {
            "launched": True,
            "dry_run": True,
            "command": ["cmd"],
            "cwd": str(worker1_dir),
            "pid": 8888,
            "job_handle": None,
        }

    lm_module.LaunchManager.launch = mock_launch

    try:
        result = runtime.dispatch_next(dry_run=True)
        assert result["dispatched"] is True
        assert result["task_id"] == "SignalBridge-v1-Build"
    finally:
        wr_module.parse_task_file = original_parse
        lm_module.LaunchManager.launch = original_launch


def test_dispatch_next_returns_no_idle_slot_when_all_busy(tmp_path):
    """Test that dispatch_next returns appropriate result when all slots are busy."""
    # Create the directory structure
    queue_dir = tmp_path / "pools" / "work" / "Queue"
    queue_dir.mkdir(parents=True)
    worker1_dir = tmp_path / "pools" / "work" / "worker_01"
    worker1_dir.mkdir(parents=True)
    (worker1_dir / "workspace").mkdir(parents=True)
    worker2_dir = tmp_path / "pools" / "work" / "worker_02"
    worker2_dir.mkdir(parents=True)
    (worker2_dir / "workspace").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "Outbox").mkdir(parents=True)

    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    for f in ["Online.bat", "StartWriting.bat", "Done.bat", "signal_bridge.py", "WORK_BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")


    # Create a task file
    task_file = queue_dir / "task_001.txt"
    task_file.write_text("PROJECT_KEY: SignalBridge-v1-Build\n\ntask body")

    runtime = WorkRuntime(root_dir=tmp_path, signal_port=18773)

    # Mark both slots as busy
    slot1 = runtime.get_slot("worker_01")
    if slot1:
        slot1.busy = True
    slot2 = runtime.get_slot("worker_02")
    if slot2:
        slot2.busy = True

    # Try to dispatch
    result = runtime.dispatch_next(dry_run=True)

    # Verify result
    assert result["dispatched"] is False
    assert "idle slot" in result.get("error", "").lower()


def test_handle_signal_releases_slot_on_done(tmp_path):
    """Test that handle_signal releases a slot when done signal is received."""
    # Create the directory structure
    (tmp_path / "pools" / "work" / "Queue").mkdir(parents=True)
    worker1_dir = tmp_path / "pools" / "work" / "worker_01"
    worker1_dir.mkdir(parents=True)
    (worker1_dir / "workspace").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "worker_02" / "workspace").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "Outbox").mkdir(parents=True)

    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    for f in ["Online.bat", "StartWriting.bat", "Done.bat", "signal_bridge.py", "WORK_BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")


    runtime = WorkRuntime(root_dir=tmp_path, signal_port=18774)

    # Mark worker_01 as busy with a task
    slot1 = runtime.get_slot("worker_01")
    if slot1:
        slot1.busy = True
        slot1.assigned_task_id = "t_001"

    # Send a done signal
    signal_result = {
        "agent_id": "worker_01",
        "task_id": "t_001",
        "signal": "done",
        "is_terminal": True,
    }

    runtime.handle_signal(signal_result)

    # Verify slot is released
    assert slot1.busy is False
    assert slot1.assigned_task_id == ""


def test_handle_signal_releases_slot_on_failed(tmp_path):
    """Test that handle_signal releases a slot when failed signal is received."""
    # Create the directory structure
    (tmp_path / "pools" / "work" / "Queue").mkdir(parents=True)
    worker1_dir = tmp_path / "pools" / "work" / "worker_01"
    worker1_dir.mkdir(parents=True)
    (worker1_dir / "workspace").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "worker_02" / "workspace").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "Outbox").mkdir(parents=True)

    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    for f in ["Online.bat", "StartWriting.bat", "Done.bat", "signal_bridge.py", "WORK_BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")


    runtime = WorkRuntime(root_dir=tmp_path, signal_port=18775)

    # Mark worker_01 as busy with a task
    slot1 = runtime.get_slot("worker_01")
    if slot1:
        slot1.busy = True
        slot1.assigned_task_id = "t_002"

    # Send a failed signal
    signal_result = {
        "agent_id": "worker_01",
        "task_id": "t_002",
        "signal": "failed",
        "is_terminal": True,
    }

    runtime.handle_signal(signal_result)

    # Verify slot is released
    assert slot1.busy is False
    assert slot1.assigned_task_id == ""


def test_handle_signal_releases_slot_on_blocked(tmp_path):
    """Test that handle_signal releases a slot when blocked signal is received."""
    # Create the directory structure
    (tmp_path / "pools" / "work" / "Queue").mkdir(parents=True)
    worker1_dir = tmp_path / "pools" / "work" / "worker_01"
    worker1_dir.mkdir(parents=True)
    (worker1_dir / "workspace").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "worker_02" / "workspace").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "Outbox").mkdir(parents=True)

    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    for f in ["Online.bat", "StartWriting.bat", "Done.bat", "signal_bridge.py", "WORK_BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")


    runtime = WorkRuntime(root_dir=tmp_path, signal_port=18776)

    # Mark worker_01 as busy with a task
    slot1 = runtime.get_slot("worker_01")
    if slot1:
        slot1.busy = True
        slot1.assigned_task_id = "t_003"

    # Send a blocked signal
    signal_result = {
        "agent_id": "worker_01",
        "task_id": "t_003",
        "signal": "blocked",
        "is_terminal": True,
    }

    runtime.handle_signal(signal_result)

    # Verify slot is released
    assert slot1.busy is False
    assert slot1.assigned_task_id == ""


def test_start_and_stop_signal_server(tmp_path):
    """Test that start and stop control the signal server."""
    # Create the directory structure
    (tmp_path / "pools" / "work" / "Queue").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "worker_01" / "workspace").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "worker_02" / "workspace").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "Outbox").mkdir(parents=True)

    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    for f in ["Online.bat", "StartWriting.bat", "Done.bat", "signal_bridge.py", "WORK_BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")


    runtime = WorkRuntime(root_dir=tmp_path, signal_port=18777)

    # Initially not running
    assert runtime._signal_server.is_running is False

    # Start the server
    runtime.start()
    assert runtime._signal_server.is_running is True

    # Stop the server
    runtime.stop()
    assert runtime._signal_server.is_running is False


def test_dispatch_next_with_no_tasks_returns_nothing(tmp_path):
    """Test that dispatch_next returns appropriate result when queue is empty."""
    # Create the directory structure
    queue_dir = tmp_path / "pools" / "work" / "Queue"
    queue_dir.mkdir(parents=True)
    (tmp_path / "pools" / "work" / "worker_01" / "workspace").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "worker_02" / "workspace").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "Outbox").mkdir(parents=True)

    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    for f in ["Online.bat", "StartWriting.bat", "Done.bat", "signal_bridge.py", "WORK_BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")


    runtime = WorkRuntime(root_dir=tmp_path, signal_port=18778)

    # Try to dispatch when queue is empty
    result = runtime.dispatch_next(dry_run=True)

    # Verify result
    assert result["dispatched"] is False
    assert "no tasks" in result.get("error", "").lower()


def test_get_slot_returns_correct_slot(tmp_path):
    """Test that get_slot returns the correct slot by ID."""
    # Create the directory structure
    (tmp_path / "pools" / "work" / "Queue").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "worker_01" / "workspace").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "worker_02" / "workspace").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "Outbox").mkdir(parents=True)

    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    for f in ["Online.bat", "StartWriting.bat", "Done.bat", "signal_bridge.py", "WORK_BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")


    runtime = WorkRuntime(root_dir=tmp_path, signal_port=18779)

    # Get worker_01
    slot1 = runtime.get_slot("worker_01")
    assert slot1 is not None
    assert slot1.slot_id == "worker_01"

    # Get worker_02
    slot2 = runtime.get_slot("worker_02")
    assert slot2 is not None
    assert slot2.slot_id == "worker_02"

    # Get non-existent slot
    slot3 = runtime.get_slot("worker_03")
    assert slot3 is None


def test_deploy_lifecycle_bats_includes_signal_bridge(tmp_path):
    """Test that _deploy_lifecycle_bats copies signal_bridge.py along with the bats."""
    from app.runtimes.work_runtime import WorkRuntime, WorkerSlot

    tools_dir = tmp_path / "tools"
    tools_dir.mkdir(parents=True)
    for f in ["Online.bat", "StartWriting.bat", "Done.bat", "signal_bridge.py"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")

    (tmp_path / "pools" / "work" / "Queue").mkdir(parents=True)
    worker1_dir = tmp_path / "pools" / "work" / "worker_01"
    worker1_dir.mkdir(parents=True)
    (worker1_dir / "workspace").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "Outbox").mkdir(parents=True)

    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    for f in ["Online.bat", "StartWriting.bat", "Done.bat", "signal_bridge.py", "WORK_BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")


    runtime = WorkRuntime(root_dir=tmp_path, signal_port=18781)
    runtime._lifecycle_tools_dir = tools_dir  # Override for testing

    slot = runtime.get_slot("worker_01")
    assert slot is not None

    runtime._deploy_lifecycle_bats(slot)

    assert (worker1_dir / "Online.bat").exists()
    assert (worker1_dir / "StartWriting.bat").exists()
    assert (worker1_dir / "Done.bat").exists()
    assert (worker1_dir / "signal_bridge.py").exists(), "signal_bridge.py must be deployed to worker slot"


def test_deploy_lifecycle_bats_includes_bootstrap_txt(tmp_path):
    """Test that _deploy_lifecycle_bats copies BOOTSTRAP.txt and fails fast if missing."""
    from app.runtimes.work_runtime import WorkRuntime, WorkerSlot

    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True)
    # create all required files
    for f in ["Online.bat", "StartWriting.bat", "Done.bat", "signal_bridge.py"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")

    # Write specific content to BOOTSTRAP.txt to verify exact match
    bootstrap_content = "Special BOOTSTRAP content with call Online.bat explicit instructions"
    (tools_dir / "WORK_BOOTSTRAP.txt").write_text(bootstrap_content, encoding="utf-8")

    (tmp_path / "pools" / "work" / "Queue").mkdir(parents=True)
    worker1_dir = tmp_path / "pools" / "work" / "worker_01"
    worker1_dir.mkdir(parents=True)
    (worker1_dir / "workspace").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "Outbox").mkdir(parents=True)

    runtime = WorkRuntime(root_dir=tmp_path, signal_port=18782)
    runtime._lifecycle_tools_dir = tools_dir

    slot = runtime.get_slot("worker_01")
    assert slot is not None

    runtime._deploy_lifecycle_bats(slot)

    deployed_bootstrap = worker1_dir / "WORK_BOOTSTRAP.txt"
    assert deployed_bootstrap.exists(), "BOOTSTRAP.txt must be deployed to worker slot"
    assert deployed_bootstrap.read_text(encoding="utf-8") == bootstrap_content, "Deployed BOOTSTRAP.txt must match source exactly"

def test_deploy_lifecycle_bats_raises_if_source_missing(tmp_path):
    """Test that deployment fails fast if required files are missing."""
    from app.runtimes.work_runtime import WorkRuntime, WorkerSlot
    import pytest

    tools_dir = tmp_path / "tools"
    tools_dir.mkdir(parents=True)
    # create all required files EXCEPT BOOTSTRAP.txt
    for f in ["Online.bat", "StartWriting.bat", "Done.bat", "signal_bridge.py"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")

    (tmp_path / "pools" / "work" / "Queue").mkdir(parents=True)
    worker1_dir = tmp_path / "pools" / "work" / "worker_01"
    worker1_dir.mkdir(parents=True)
    # worker must have workspace directory to be recognized as a slot
    (worker1_dir / "workspace").mkdir(parents=True)

    runtime = WorkRuntime(root_dir=tmp_path, signal_port=18782)
    runtime._lifecycle_tools_dir = tools_dir

    slot = runtime.get_slot("worker_01")
    assert slot is not None, "worker_01 must be auto-detected as a slot"

    with pytest.raises(FileNotFoundError, match="Missing required lifecycle tool"):
        runtime._deploy_lifecycle_bats(slot)


def test_launch_bat_does_not_call_online_bat(tmp_path):
    """Test that launch bat does NOT call Online.bat — Online is worker's own responsibility."""
    from app.runtimes.work_runtime import WorkRuntime

    queue_dir = tmp_path / "pools" / "work" / "Queue"
    queue_dir.mkdir(parents=True)
    worker1_dir = tmp_path / "pools" / "work" / "worker_01"
    worker1_dir.mkdir(parents=True)
    (worker1_dir / "workspace").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "worker_02" / "workspace").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "Outbox").mkdir(parents=True)

    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    for f in ["Online.bat", "StartWriting.bat", "Done.bat", "signal_bridge.py", "WORK_BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")


    task_file = queue_dir / "task_001.txt"
    task_file.write_text("PROJECT_KEY: SignalBridge-v1-Nocall\n\ntask body", encoding="utf-8")

    runtime = WorkRuntime(root_dir=tmp_path, signal_port=18783)

    import app.shared.launch_manager as lm_module
    original_launch = lm_module.LaunchManager.launch

    def mock_launch(self, request, dry_run=True):
        return {"launched": True, "dry_run": True, "command": ["cmd"], "cwd": str(worker1_dir), "pid": 1234, "job_handle": None}

    lm_module.LaunchManager.launch = mock_launch

    try:
        runtime.dispatch_next(dry_run=True)

        launch_bat = worker1_dir / "launch_worker_01.bat"
        assert launch_bat.exists()
        bat_content = launch_bat.read_text(encoding="utf-8")

        # Online.bat should NOT be called in launch bat — worker calls it itself
        assert "call Online.bat" not in bat_content, (
            "launch bat should NOT call Online.bat; Online is worker's own responsibility"
        )
        # But BOOTSTRAP.txt prompt should still be there
        assert "WORK_BOOTSTRAP.txt" in bat_content
    finally:
        lm_module.LaunchManager.launch = original_launch


def test_handle_signal_ignores_unknown_agent(tmp_path):
    """Test that handle_signal gracefully handles unknown agent IDs."""
    # Create the directory structure
    (tmp_path / "pools" / "work" / "Queue").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "worker_01" / "workspace").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "worker_02" / "workspace").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "Outbox").mkdir(parents=True)

    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    for f in ["Online.bat", "StartWriting.bat", "Done.bat", "signal_bridge.py", "WORK_BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")


    runtime = WorkRuntime(root_dir=tmp_path, signal_port=18780)

    # Send signal for unknown agent
    signal_result = {
        "agent_id": "worker_99",
        "task_id": "t_999",
        "signal": "done",
        "is_terminal": True,
    }

    # Should not raise an exception
    runtime.handle_signal(signal_result)

    # Slots should remain unchanged
    slot1 = runtime.get_slot("worker_01")
    assert slot1 is not None
    assert slot1.busy is False

def test_dispatch_next_clears_stale_task_files_from_slot_before_copying(tmp_path):
    """Test that dispatch_next removes old task_*.txt files from a slot so workers don't read stale instructions."""
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

    # Inject a STALE task file into the slot
    stale_file = worker1_dir / "task_stale_001.txt"
    stale_file.write_text("STALE CONTENT")

    # Put a NEW task in the Queue
    task_file = queue_dir / "task_new_002.txt"
    task_file.write_text("PROJECT_KEY: SignalBridge-v2-Build\n\nFRESH CONTENT", encoding="utf-8")

    runtime = WorkRuntime(root_dir=tmp_path, signal_port=18774)

    import app.shared.launch_manager as lm_module
    original_launch = lm_module.LaunchManager.launch

    def mock_launch(self, request, dry_run=True):
        return {"launched": True, "dry_run": True, "pid": 1234, "job_handle": None}

    lm_module.LaunchManager.launch = mock_launch

    try:
        result = runtime.dispatch_next(dry_run=True)
        assert result["dispatched"] is True

        # Verify the stale file was removed from the slot
        assert not stale_file.exists(), "Stale task files were not cleaned up from the slot before copying the new task"

        # Verify the new file is present
        assert (worker1_dir / "task_new_002.txt").exists()

    finally:
        lm_module.LaunchManager.launch = original_launch


def test_dispatch_next_rolls_back_when_deploy_lifecycle_bats_fails(tmp_path):
    """Test that dispatch_next restores queue and slot state if lifecycle deployment fails."""
    queue_dir = tmp_path / "pools" / "work" / "Queue"
    queue_dir.mkdir(parents=True)
    worker1_dir = tmp_path / "pools" / "work" / "worker_01"
    worker1_dir.mkdir(parents=True)
    (worker1_dir / "workspace").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "worker_02" / "workspace").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "Outbox").mkdir(parents=True)

    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    for f in ["Online.bat", "StartWriting.bat", "Done.bat", "signal_bridge.py", "WORK_BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")

    task_file = queue_dir / "task_rollback_001.txt"
    task_content = "PROJECT_KEY: SignalBridge-v1-Rollback\n\nbody"
    task_file.write_text(task_content, encoding="utf-8")

    runtime = WorkRuntime(root_dir=tmp_path, signal_port=18784)

    original_deploy = runtime._deploy_lifecycle_bats

    def mock_deploy(_slot):
        raise FileNotFoundError("boom deploy")

    runtime._deploy_lifecycle_bats = mock_deploy

    try:
        with pytest.raises(FileNotFoundError, match="boom deploy"):
            runtime.dispatch_next(dry_run=True)

        slot = runtime.get_slot("worker_01")
        assert slot is not None
        assert slot.busy is False
        assert slot.assigned_task_id == ""
        assert slot.launch_result is None

        assert task_file.exists(), "queue task file should be restored after rollback"
        assert not (queue_dir / "task_rollback_001.txt.processing").exists(), "processing file should not remain after rollback"
        assert not (worker1_dir / "task_rollback_001.txt").exists(), "worker task copy should be removed after rollback"
        assert sorted(p.name for p in worker1_dir.iterdir()) == ["workspace"]
    finally:
        runtime._deploy_lifecycle_bats = original_deploy


def test_dispatch_next_rolls_back_when_launch_fails(tmp_path):
    """Test that dispatch_next restores queue and slot state if process launch fails."""
    queue_dir = tmp_path / "pools" / "work" / "Queue"
    queue_dir.mkdir(parents=True)
    worker1_dir = tmp_path / "pools" / "work" / "worker_01"
    worker1_dir.mkdir(parents=True)
    (worker1_dir / "workspace").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "worker_02" / "workspace").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "Outbox").mkdir(parents=True)

    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    for f in ["Online.bat", "StartWriting.bat", "Done.bat", "signal_bridge.py", "WORK_BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")

    task_file = queue_dir / "task_launch_fail_001.txt"
    task_content = "PROJECT_KEY: SignalBridge-v1-Launch\n\nbody"
    task_file.write_text(task_content, encoding="utf-8")

    runtime = WorkRuntime(root_dir=tmp_path, signal_port=18785)

    import app.shared.launch_manager as lm_module
    original_launch = lm_module.LaunchManager.launch

    def mock_launch(self, request, dry_run=True):
        raise RuntimeError("boom launch")

    lm_module.LaunchManager.launch = mock_launch

    try:
        with pytest.raises(RuntimeError, match="boom launch"):
            runtime.dispatch_next(dry_run=True)

        slot = runtime.get_slot("worker_01")
        assert slot is not None
        assert slot.busy is False
        assert slot.assigned_task_id == ""
        assert slot.launch_result is None

        assert task_file.exists(), "queue task file should be restored after rollback"
        assert not (queue_dir / "task_launch_fail_001.txt.processing").exists(), "processing file should not remain after rollback"
        assert not (worker1_dir / "task_launch_fail_001.txt").exists(), "worker task copy should be removed after rollback"
        assert sorted(p.name for p in worker1_dir.iterdir()) == ["workspace"]
    finally:
        lm_module.LaunchManager.launch = original_launch


def test_workspace_isolation_prevents_artifact_leak_between_tasks(tmp_path):
    """Test that task B outbox does not include task A leftovers from the same workspace."""
    (tmp_path / "pools" / "work" / "Queue").mkdir(parents=True)
    worker1_dir = tmp_path / "pools" / "work" / "worker_01"
    worker1_dir.mkdir(parents=True)
    workspace_dir = worker1_dir / "workspace"
    workspace_dir.mkdir(parents=True)
    (tmp_path / "pools" / "work" / "worker_02" / "workspace").mkdir(parents=True)
    outbox_dir = tmp_path / "pools" / "work" / "Outbox"
    outbox_dir.mkdir(parents=True)

    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    for f in ["Online.bat", "StartWriting.bat", "Done.bat", "signal_bridge.py", "WORK_BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")

    runtime = WorkRuntime(root_dir=tmp_path, signal_port=18786)

    import app.shared.launch_manager as lm_module
    original_launch = lm_module.LaunchManager.launch

    def mock_launch(self, request, dry_run=True):
        return {"launched": True, "dry_run": True, "pid": 1234, "job_handle": None}

    lm_module.LaunchManager.launch = mock_launch

    try:
        # Task A completes and leaves artifact in workspace
        queue_a = tmp_path / "pools" / "work" / "Queue" / "task_a.txt"
        queue_a.write_text("PROJECT_KEY: SignalBridge-v1-TaskA\n\nTask A", encoding="utf-8")
        runtime.dispatch_next(dry_run=True)
        (workspace_dir / "artifact_a.txt").write_text("artifact A", encoding="utf-8")
        runtime.handle_signal({
            "agent_id": "worker_01",
            "task_id": "SignalBridge-v1-TaskA",
            "signal": "done",
            "is_terminal": True,
        })
        assert (outbox_dir / "SignalBridge-v1-TaskA" / "artifact_a.txt").exists()

        # Simulate leftover artifact reappearing before task B dispatch
        (workspace_dir / "artifact_a.txt").write_text("stale artifact A", encoding="utf-8")

        # Task B dispatch should clear workspace before execution
        queue_b = tmp_path / "pools" / "work" / "Queue" / "task_b.txt"
        queue_b.write_text("PROJECT_KEY: SignalBridge-v1-TaskB\n\nTask B", encoding="utf-8")
        runtime.dispatch_next(dry_run=True)
        assert not (workspace_dir / "artifact_a.txt").exists(), "workspace should be cleared before task B starts"

        (workspace_dir / "artifact_b.txt").write_text("artifact B", encoding="utf-8")
        runtime.handle_signal({
            "agent_id": "worker_01",
            "task_id": "SignalBridge-v1-TaskB",
            "signal": "done",
            "is_terminal": True,
        })

        assert (outbox_dir / "SignalBridge-v1-TaskB" / "artifact_b.txt").exists()
        assert not (outbox_dir / "SignalBridge-v1-TaskB" / "artifact_a.txt").exists(), "task B outbox must not contain task A leftovers"
    finally:
        lm_module.LaunchManager.launch = original_launch


def test_resolve_project_execution_context_default_legacy(tmp_path):
    """Test that PROJECT_MODE defaults to legacy when not specified."""
    (tmp_path / "pools" / "work" / "Queue").mkdir(parents=True)
    runtime = WorkRuntime(root_dir=tmp_path, signal_port=18787)

    mode, root = runtime._resolve_project_execution_context({})
    assert mode == "legacy"
    assert root is None


def test_resolve_project_execution_context_explicit_values(tmp_path):
    """Test that PROJECT_MODE accepts all supported values."""
    (tmp_path / "pools" / "work" / "Queue").mkdir(parents=True)
    runtime = WorkRuntime(root_dir=tmp_path, signal_port=18788)

    mode, root = runtime._resolve_project_execution_context({"PROJECT_MODE": "legacy"})
    assert mode == "legacy"
    assert root is None

    mode, root = runtime._resolve_project_execution_context({"PROJECT_MODE": "free"})
    assert mode == "free"
    assert root is None


def test_resolve_project_execution_context_invalid_value(tmp_path):
    """Test that invalid PROJECT_MODE raises ValueError."""
    (tmp_path / "pools" / "work" / "Queue").mkdir(parents=True)
    runtime = WorkRuntime(root_dir=tmp_path, signal_port=18789)

    with pytest.raises(ValueError, match="Invalid PROJECT_MODE"):
        runtime._resolve_project_execution_context({"PROJECT_MODE": "invalid"})


def test_resolve_project_execution_context_standard_valid(tmp_path):
    """Test that standard mode with valid PROJECT_ROOT succeeds."""
    (tmp_path / "pools" / "work" / "Queue").mkdir(parents=True)
    runtime = WorkRuntime(root_dir=tmp_path, signal_port=18790)

    project_root = tmp_path / "test_project"
    project_root.mkdir()

    mode, root = runtime._resolve_project_execution_context({
        "PROJECT_MODE": "standard",
        "PROJECT_ROOT": str(project_root)
    })
    assert mode == "standard"
    assert root == project_root


def test_resolve_project_execution_context_standard_missing_root(tmp_path):
    """Test that standard mode without PROJECT_ROOT raises ValueError."""
    (tmp_path / "pools" / "work" / "Queue").mkdir(parents=True)
    runtime = WorkRuntime(root_dir=tmp_path, signal_port=18791)

    with pytest.raises(ValueError, match="PROJECT_ROOT is required"):
        runtime._resolve_project_execution_context({"PROJECT_MODE": "standard"})


def test_resolve_project_execution_context_standard_relative_path(tmp_path):
    """Test that standard mode with relative PROJECT_ROOT raises ValueError."""
    (tmp_path / "pools" / "work" / "Queue").mkdir(parents=True)
    runtime = WorkRuntime(root_dir=tmp_path, signal_port=18792)

    with pytest.raises(ValueError, match="PROJECT_ROOT must be an absolute path"):
        runtime._resolve_project_execution_context({
            "PROJECT_MODE": "standard",
            "PROJECT_ROOT": "relative/path"
        })


def test_finalize_done_payload_legacy_mode(tmp_path):
    """Test that legacy mode copies workspace to Outbox."""
    (tmp_path / "pools" / "work" / "Queue").mkdir(parents=True)
    worker_dir = tmp_path / "pools" / "work" / "worker_01"
    worker_dir.mkdir(parents=True)
    workspace_dir = worker_dir / "workspace"
    workspace_dir.mkdir()
    outbox_dir = tmp_path / "pools" / "work" / "Outbox"
    outbox_dir.mkdir()

    runtime = WorkRuntime(root_dir=tmp_path, signal_port=18793)
    slot = runtime._slots["worker_01"]
    slot.project_mode = "legacy"
    slot.project_root = None

    (workspace_dir / "artifact.txt").write_text("test artifact", encoding="utf-8")

    result = runtime._finalize_done_payload(slot, "SignalBridge-v1-Build")

    assert result["collected"] is True
    assert (outbox_dir / "SignalBridge-v1-Build" / "artifact.txt").exists()


def test_finalize_done_payload_standard_mode(tmp_path):
    """Test that standard mode generates project root index txt."""
    (tmp_path / "pools" / "work" / "Queue").mkdir(parents=True)
    worker_dir = tmp_path / "pools" / "work" / "worker_01"
    worker_dir.mkdir(parents=True)
    (worker_dir / "workspace").mkdir()
    outbox_dir = tmp_path / "pools" / "work" / "Outbox"
    outbox_dir.mkdir()

    project_root = tmp_path / "test_project"
    project_root.mkdir()

    runtime = WorkRuntime(root_dir=tmp_path, signal_port=18794)
    slot = runtime._slots["worker_01"]
    slot.project_mode = "standard"
    slot.project_root = project_root

    result = runtime._finalize_done_payload(slot, "SignalBridge-v1-Build")

    assert result["written"] is True
    index_file = outbox_dir / "SignalBridge-v1-Build.txt"
    assert index_file.exists()

    content = index_file.read_text(encoding="utf-8")
    assert content == f"{project_root}\n"


def test_finalize_done_payload_free_mode(tmp_path):
    """Test that free mode skips artifact collection."""
    (tmp_path / "pools" / "work" / "Queue").mkdir(parents=True)
    worker_dir = tmp_path / "pools" / "work" / "worker_01"
    worker_dir.mkdir(parents=True)
    workspace_dir = worker_dir / "workspace"
    workspace_dir.mkdir()
    outbox_dir = tmp_path / "pools" / "work" / "Outbox"
    outbox_dir.mkdir()

    runtime = WorkRuntime(root_dir=tmp_path, signal_port=18795)
    slot = runtime._slots["worker_01"]
    slot.project_mode = "free"
    slot.project_root = None

    (workspace_dir / "artifact.txt").write_text("test artifact", encoding="utf-8")

    result = runtime._finalize_done_payload(slot, "SignalBridge-v1-Build")

    assert result["skipped"] is True
    assert not (outbox_dir / "SignalBridge-v1-Build").exists()
    assert not (outbox_dir / "SignalBridge-v1-Build.txt").exists()


def test_write_project_root_index_content(tmp_path):
    """Test that project root index contains all required headers."""
    (tmp_path / "pools" / "work" / "Queue").mkdir(parents=True)
    outbox_dir = tmp_path / "pools" / "work" / "Outbox"
    outbox_dir.mkdir()

    project_root = tmp_path / "test_project"
    project_root.mkdir()

    runtime = WorkRuntime(root_dir=tmp_path, signal_port=18796)

    result = runtime.write_project_root_index("SignalBridge-v2-Package", project_root)

    assert result["written"] is True
    index_file = outbox_dir / "SignalBridge-v2-Package.txt"
    assert index_file.exists()

    content = index_file.read_text(encoding="utf-8")
    assert content == f"{project_root}\n"


def test_dispatch_next_with_project_mode_standard(tmp_path):
    """Test that dispatch_next correctly parses PROJECT_MODE and PROJECT_ROOT."""
    (tmp_path / "pools" / "work" / "Queue").mkdir(parents=True)
    worker_dir = tmp_path / "pools" / "work" / "worker_01"
    worker_dir.mkdir(parents=True)
    (worker_dir / "workspace").mkdir()

    project_root = tmp_path / "test_project"
    project_root.mkdir()

    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    for f in ["Online.bat", "StartWriting.bat", "Done.bat", "signal_bridge.py", "WORK_BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")

    runtime = WorkRuntime(root_dir=tmp_path, signal_port=18797)

    import app.shared.launch_manager as lm_module
    original_launch = lm_module.LaunchManager.launch

    def mock_launch(self, request, dry_run=True):
        return {"launched": True, "dry_run": True, "pid": 1234, "job_handle": None}

    lm_module.LaunchManager.launch = mock_launch

    try:
        queue_file = tmp_path / "pools" / "work" / "Queue" / "task.txt"
        queue_file.write_text(
            f"PROJECT_KEY: SignalBridge-v1-Build\n"
            f"PROJECT_MODE: standard\n"
            f"PROJECT_ROOT: {project_root}\n\n"
            f"Build the project",
            encoding="utf-8"
        )

        result = runtime.dispatch_next(dry_run=True)

        assert result["dispatched"] is True
        slot = runtime._slots["worker_01"]
        assert slot.project_mode == "standard"
        assert slot.project_root == project_root
    finally:
        lm_module.LaunchManager.launch = original_launch


def test_dispatch_next_standard_mode_missing_project_root(tmp_path):
    """Test that standard mode without PROJECT_ROOT raises ValueError."""
    (tmp_path / "pools" / "work" / "Queue").mkdir(parents=True)
    worker_dir = tmp_path / "pools" / "work" / "worker_01"
    worker_dir.mkdir(parents=True)
    (worker_dir / "workspace").mkdir()

    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    for f in ["Online.bat", "StartWriting.bat", "Done.bat", "signal_bridge.py", "WORK_BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")

    runtime = WorkRuntime(root_dir=tmp_path, signal_port=18798)

    queue_file = tmp_path / "pools" / "work" / "Queue" / "task.txt"
    queue_file.write_text(
        "PROJECT_KEY: SignalBridge-v1-Build\n"
        "PROJECT_MODE: standard\n\n"
        "Build the project",
        encoding="utf-8"
    )

    with pytest.raises(ValueError, match="PROJECT_ROOT is required"):
        runtime.dispatch_next(dry_run=True)
