"""Unit tests for ConstructRuntime orchestrator.

复制自 test_thinking_runtime.py，针对 Construct Pool 特化：
- 槽位命名: constructor_XX (动态扫描)
- 池目录: pools/construct/
- 生命周期: online -> start_architecting -> start_finalizing -> done
"""

from pathlib import Path
import pytest

from app.runtimes.construct_runtime import ConstructRuntime, ConstructorSlot


def test_init_slots_discovers_constructor_directories_dynamically(tmp_path):
    """Test that ConstructRuntime dynamically discovers constructor_* directories."""
    # Create construct pool structure with 3 constructor slots
    construct_pool = tmp_path / "pools" / "construct"
    (construct_pool / "Queue").mkdir(parents=True)
    (construct_pool / "Outbox").mkdir(parents=True)

    # Create constructor slots
    for i in [1, 2, 3]:
        slot_dir = construct_pool / f"constructor_0{i}"
        slot_dir.mkdir(parents=True)
        (slot_dir / "workspace").mkdir()

    runtime = ConstructRuntime(root_dir=tmp_path, signal_port=19021)

    # Verify all 3 slots discovered
    assert len(runtime._slots) == 3
    assert "constructor_01" in runtime._slots
    assert "constructor_02" in runtime._slots
    assert "constructor_03" in runtime._slots

    # Verify slot structure
    slot1 = runtime.get_slot("constructor_01")
    assert slot1 is not None
    assert slot1.slot_id == "constructor_01"
    assert slot1.busy is False
    assert slot1.workspace_dir == construct_pool / "constructor_01" / "workspace"


def test_get_next_idle_slot_uses_lowest_available(tmp_path):
    """Test that the lowest numbered idle slot is returned first."""
    construct_pool = tmp_path / "pools" / "construct"
    (construct_pool / "Queue").mkdir(parents=True)
    (construct_pool / "Outbox").mkdir(parents=True)

    for i in [1, 2]:
        slot_dir = construct_pool / f"constructor_0{i}"
        slot_dir.mkdir(parents=True)
        (slot_dir / "workspace").mkdir()

    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True)
    for f in ["Online.bat", "StartArchitecting.bat", "StartFinalizing.bat", "Done.bat", "signal_bridge.py", "BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")

    runtime = ConstructRuntime(root_dir=tmp_path, signal_port=19022)

    # First call should return constructor_01
    slot1 = runtime.get_next_idle_slot()
    assert slot1 is not None
    assert slot1.slot_id == "constructor_01"
    assert slot1.busy is False

    # Mark constructor_01 as busy
    slot1.busy = True

    # Second call should return constructor_02
    slot2 = runtime.get_next_idle_slot()
    assert slot2 is not None
    assert slot2.slot_id == "constructor_02"
    assert slot2.busy is False

    # Mark both as busy
    slot2.busy = True

    # Third call should return None
    slot3 = runtime.get_next_idle_slot()
    assert slot3 is None


def test_list_queue_tasks_ignores_hidden_files(tmp_path):
    """Test that list_queue_tasks returns only visible .txt files."""
    queue_dir = tmp_path / "pools" / "construct" / "Queue"
    queue_dir.mkdir(parents=True)
    construct_pool = tmp_path / "pools" / "construct"
    (construct_pool / "constructor_01" / "workspace").mkdir(parents=True)
    (construct_pool / "Outbox").mkdir(parents=True)

    # Create some files
    (queue_dir / "task_001.txt").write_text("content1")
    (queue_dir / "task_002.txt").write_text("content2")
    (queue_dir / ".hidden.txt").write_text("hidden")
    (queue_dir / "temp.md").write_text("markdown")

    runtime = ConstructRuntime(root_dir=tmp_path, signal_port=19023)
    tasks = runtime.list_queue_tasks()

    assert len(tasks) == 2
    assert any(t.name == "task_001.txt" for t in tasks)
    assert any(t.name == "task_002.txt" for t in tasks)
    assert not any(t.name.startswith(".") for t in tasks)
    assert not any(t.suffix != ".txt" for t in tasks)


def test_dispatch_next_uses_20_minute_default_timeout_when_header_missing(tmp_path):
    """Test that dispatch_next falls back to 20 minutes when TIMEOUT header is absent."""
    queue_dir = tmp_path / "pools" / "construct" / "Queue"
    queue_dir.mkdir(parents=True)
    construct_pool = tmp_path / "pools" / "construct"
    slot1_dir = construct_pool / "constructor_01"
    slot1_dir.mkdir(parents=True)
    (slot1_dir / "workspace").mkdir(parents=True)
    (construct_pool / "Outbox").mkdir(parents=True)

    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True)
    for f in ["Online.bat", "StartArchitecting.bat", "StartFinalizing.bat", "Done.bat", "signal_bridge.py", "BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")

    task_file = queue_dir / "task_001.txt"
    task_file.write_text(
        """FROM: runtime
TO: constructor_01
TASK_ID: c_001
FEATURE_ID: feature_build

Please construct the project root.
""",
        encoding="utf-8",
    )

    runtime = ConstructRuntime(root_dir=tmp_path, signal_port=19024)

    fake_launch_result = {
        "launched": True,
        "dry_run": True,
        "command": ["cmd"],
        "cwd": str(slot1_dir),
        "pid": 1234,
        "job_handle": None,
    }

    import app.shared.launch_manager as lm_module
    original_launch = lm_module.LaunchManager.launch

    def mock_launch(self, request, dry_run=True):
        return fake_launch_result

    lm_module.LaunchManager.launch = mock_launch

    try:
        result = runtime.dispatch_next(dry_run=True)
        assert result["dispatched"] is True
        slot = runtime.get_slot("constructor_01")
        assert slot is not None
        assert slot.timeout_seconds == 1200
    finally:
        lm_module.LaunchManager.launch = original_launch



def test_dispatch_next_rejects_invalid_timeout_header_and_uses_default(tmp_path):
    """Test that invalid TIMEOUT headers do not crash dispatch and fall back to default."""
    queue_dir = tmp_path / "pools" / "construct" / "Queue"
    queue_dir.mkdir(parents=True)
    construct_pool = tmp_path / "pools" / "construct"
    slot1_dir = construct_pool / "constructor_01"
    slot1_dir.mkdir(parents=True)
    (slot1_dir / "workspace").mkdir(parents=True)
    (construct_pool / "Outbox").mkdir(parents=True)

    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True)
    for f in ["Online.bat", "StartArchitecting.bat", "StartFinalizing.bat", "Done.bat", "signal_bridge.py", "BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")

    task_file = queue_dir / "task_bad_timeout.txt"
    task_file.write_text(
        """FROM: runtime
TO: constructor_01
TASK_ID: c_bad_timeout
FEATURE_ID: feature_build
TIMEOUT: abc

Please construct the project root.
""",
        encoding="utf-8",
    )

    runtime = ConstructRuntime(root_dir=tmp_path, signal_port=19024)

    fake_launch_result = {
        "launched": True,
        "dry_run": True,
        "command": ["cmd"],
        "cwd": str(slot1_dir),
        "pid": 1234,
        "job_handle": None,
    }

    import app.shared.launch_manager as lm_module
    original_launch = lm_module.LaunchManager.launch

    def mock_launch(self, request, dry_run=True):
        return fake_launch_result

    lm_module.LaunchManager.launch = mock_launch

    try:
        result = runtime.dispatch_next(dry_run=True)
        assert result["dispatched"] is True
        slot = runtime.get_slot("constructor_01")
        assert slot is not None
        assert slot.timeout_seconds == 1200
    finally:
        lm_module.LaunchManager.launch = original_launch



def test_dispatch_next_copies_task_to_slot_and_marks_busy(tmp_path):
    """Test that dispatch_next copies task to construct slot and marks it busy."""
    queue_dir = tmp_path / "pools" / "construct" / "Queue"
    queue_dir.mkdir(parents=True)
    construct_pool = tmp_path / "pools" / "construct"
    slot1_dir = construct_pool / "constructor_01"
    slot1_dir.mkdir(parents=True)
    (slot1_dir / "workspace").mkdir(parents=True)
    (construct_pool / "Outbox").mkdir(parents=True)

    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True)
    for f in ["Online.bat", "StartArchitecting.bat", "StartFinalizing.bat", "Done.bat", "signal_bridge.py", "BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")

    # Create a task file
    task_file = queue_dir / "task_001.txt"
    task_content = """FROM: runtime
TO: constructor_01
TASK_ID: c_001
FEATURE_ID: feature_build

Please construct the project root.
"""
    task_file.write_text(task_content, encoding="utf-8")

    runtime = ConstructRuntime(root_dir=tmp_path, signal_port=19024)

    # Mock LaunchManager.launch
    fake_launch_result = {
        "launched": True,
        "dry_run": True,
        "command": ["cmd"],
        "cwd": str(slot1_dir),
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
        assert result["slot_id"] == "constructor_01"
        assert result["task_id"] == "c_001"
        assert "task_file" in result
        assert "worker_task_file" in result
        assert result["launch"] == fake_launch_result

        # Verify task was copied to slot directory
        slot_task_file = slot1_dir / "task_001.txt"
        assert slot_task_file.exists()
        assert slot_task_file.read_text(encoding="utf-8") == task_content

        # Verify task was removed from queue
        assert not task_file.exists()

        # Verify slot is marked busy
        slot = runtime.get_slot("constructor_01")
        assert slot is not None
        assert slot.busy is True
        assert slot.assigned_task_id == "c_001"

        # Verify launch bat file was created
        launch_bat = slot1_dir / "launch_constructor_01.bat"
        assert launch_bat.exists()
        bat_content = launch_bat.read_text(encoding="utf-8")
        assert "constructor_01" in bat_content
        assert "c_001" in bat_content
        assert "POOL=construct" in bat_content
        assert "fields" in bat_content  # Should have the fields dir check

    finally:
        lm_module.LaunchManager.launch = original_launch


def test_dispatch_next_returns_no_idle_slot_when_all_busy(tmp_path):
    """Test that dispatch_next returns appropriate result when all slots are busy."""
    queue_dir = tmp_path / "pools" / "construct" / "Queue"
    queue_dir.mkdir(parents=True)
    construct_pool = tmp_path / "pools" / "construct"

    for i in [1, 2]:
        slot_dir = construct_pool / f"constructor_0{i}"
        slot_dir.mkdir(parents=True)
        (slot_dir / "workspace").mkdir(parents=True)

    # Create a task file
    task_file = queue_dir / "task_001.txt"
    task_file.write_text("dummy", encoding="utf-8")

    runtime = ConstructRuntime(root_dir=tmp_path, signal_port=19025)

    # Mark all slots as busy
    for slot in runtime._slots.values():
        slot.busy = True

    result = runtime.dispatch_next(dry_run=True)

    assert result["dispatched"] is False
    assert result["error"] == "No idle slot available"
    assert task_file.exists()  # Task should remain in queue


def test_dispatch_next_returns_no_tasks_when_queue_empty(tmp_path):
    """Test that dispatch_next returns appropriate result when queue is empty."""
    queue_dir = tmp_path / "pools" / "construct" / "Queue"
    queue_dir.mkdir(parents=True)
    construct_pool = tmp_path / "pools" / "construct"
    slot_dir = construct_pool / "constructor_01"
    slot_dir.mkdir(parents=True)
    (slot_dir / "workspace").mkdir(parents=True)

    runtime = ConstructRuntime(root_dir=tmp_path, signal_port=19026)

    result = runtime.dispatch_next(dry_run=True)

    assert result["dispatched"] is False
    assert result["error"] == "No tasks in queue"


def test_handle_signal_kills_worker_on_done(tmp_path):
    """Test that receiving 'done' signal triggers slot cleanup and artifact collection."""
    construct_pool = tmp_path / "pools" / "construct"
    (construct_pool / "Queue").mkdir(parents=True)
    (construct_pool / "Outbox").mkdir(parents=True)
    slot1_dir = construct_pool / "constructor_01"
    slot1_dir.mkdir(parents=True)
    workspace = slot1_dir / "workspace"
    workspace.mkdir(parents=True)

    # Add an artifact to verify collection
    (workspace / "result.txt").write_text("architectural design")

    runtime = ConstructRuntime(root_dir=tmp_path, signal_port=19027)

    # Set up busy slot
    slot = runtime.get_slot("constructor_01")
    slot.busy = True
    slot.assigned_task_id = "c_002"
    slot.launch_result = {"job_handle": "fake_handle"}

    # Mock cleanup_launch
    cleanup_called = False

    def mock_cleanup(launch_res):
        nonlocal cleanup_called
        cleanup_called = True
        return {"killed": True}

    runtime._launch_manager.cleanup_launch = mock_cleanup

    # Send terminal signal
    runtime.handle_signal({
        "agent_id": "constructor_01",
        "task_id": "c_002",
        "signal": "done",
        "is_terminal": True
    })

    assert cleanup_called is True
    assert slot.busy is False
    assert slot.assigned_task_id == ""
    assert slot.launch_result is None

    # Verify artifact collection
    outbox_artifact = construct_pool / "Outbox" / "c_002" / "result.txt"
    assert outbox_artifact.exists()
    assert outbox_artifact.read_text() == "architectural design"


def test_handle_signal_does_not_kill_on_non_terminal_signals(tmp_path):
    """Test that non-terminal signals (online, start_architecting) do not kill worker."""
    construct_pool = tmp_path / "pools" / "construct"
    (construct_pool / "Queue").mkdir(parents=True)
    (construct_pool / "Outbox").mkdir(parents=True)
    slot1_dir = construct_pool / "constructor_01"
    slot1_dir.mkdir(parents=True)
    (slot1_dir / "workspace").mkdir(parents=True)

    runtime = ConstructRuntime(root_dir=tmp_path, signal_port=19028)

    slot = runtime.get_slot("constructor_01")
    slot.busy = True
    slot.assigned_task_id = "c_003"
    slot.launch_result = {"job_handle": "fake_handle"}

    cleanup_called = False

    def mock_cleanup(launch_res):
        nonlocal cleanup_called
        cleanup_called = True
        return {"killed": True}

    runtime._launch_manager.cleanup_launch = mock_cleanup

    runtime.handle_signal({
        "agent_id": "constructor_01",
        "task_id": "c_003",
        "signal": "start_architecting",
        "is_terminal": False,
        "to_state": "state_2"
    })

    assert cleanup_called is False
    assert slot.busy is True
    assert slot.assigned_task_id == "c_003"
    assert slot.last_known_state == "state_2"


def test_check_timeouts_kills_expired_workers(tmp_path):
    """Test that check_timeouts kills workers that have exceeded TIMEOUT."""
    import time

    construct_pool = tmp_path / "pools" / "construct"
    (construct_pool / "Queue").mkdir(parents=True)
    (construct_pool / "Outbox").mkdir(parents=True)
    slot1_dir = construct_pool / "constructor_01"
    slot1_dir.mkdir(parents=True)
    (slot1_dir / "workspace").mkdir(parents=True)

    runtime = ConstructRuntime(root_dir=tmp_path, signal_port=19029)

    slot = runtime.get_slot("constructor_01")
    slot.busy = True
    slot.assigned_task_id = "c_004"
    slot.timeout_seconds = 10
    # Simulate started 20 seconds ago
    slot.assigned_at_epoch = time.time() - 20
    slot.launch_result = {"job_handle": "fake_handle"}

    cleanup_called = False

    def mock_cleanup(launch_res):
        nonlocal cleanup_called
        cleanup_called = True
        return {"killed": True}

    runtime._launch_manager.cleanup_launch = mock_cleanup

    # Run check
    timed_out = runtime.check_timeouts()

    assert len(timed_out) == 1
    assert timed_out[0]["slot_id"] == "constructor_01"
    assert timed_out[0]["task_id"] == "c_004"
    assert cleanup_called is True
    assert slot.busy is False


# =============================================================================
# Folder Intake Tests
# =============================================================================


def test_list_queue_tasks_converts_folder_to_reference_txt(tmp_path):
    """Test that list_queue_tasks converts a folder batch to a reference txt."""
    from app.runtimes.construct_runtime import ConstructRuntime

    construct_pool = tmp_path / "pools" / "construct"
    queue_dir = construct_pool / "Queue"
    queue_dir.mkdir(parents=True)

    # Create a batch folder in Queue (simulating Thinking Pool Outbox deposit)
    batch_folder = queue_dir / "pid_simulink_001"
    batch_folder.mkdir()
    (batch_folder / "summary.txt").write_text("BATCH_ID: pid_simulink_001\n", encoding="utf-8")
    (batch_folder / "task_controller.txt").write_text("Implement PID controller\n", encoding="utf-8")

    runtime = ConstructRuntime(root_dir=tmp_path)

    # list_queue_tasks should convert the folder and return reference txt
    tasks = runtime.list_queue_tasks()
    task_names = [t.name for t in tasks]

    # The folder should be gone, replaced by a reference txt
    assert not batch_folder.exists(), "Batch folder should have been moved"
    assert any("task_batch_pid_simulink_001.txt" in name for name in task_names), \
        f"Expected reference txt, got: {task_names}"

    # The field directory should exist
    field_dir = construct_pool / "fields" / "pid_simulink_001"
    assert field_dir.exists(), "Field directory should exist"
    assert (field_dir / "input" / "summary.txt").exists()
    assert (field_dir / "input" / "task_controller.txt").exists()


def test_extract_batch_id_from_summary_txt(tmp_path):
    """Test that _extract_batch_id reads BATCH_ID from summary.txt."""
    from app.runtimes.construct_runtime import ConstructRuntime

    construct_pool = tmp_path / "pools" / "construct"
    queue_dir = construct_pool / "Queue"
    queue_dir.mkdir(parents=True)

    # Case 1: folder with summary.txt containing BATCH_ID
    batch_folder = queue_dir / "my_batch_001"
    batch_folder.mkdir()
    (batch_folder / "summary.txt").write_text("BATCH_ID: my_batch_001\nContent: some thinking\n", encoding="utf-8")

    runtime = ConstructRuntime(root_dir=tmp_path)
    batch_id = runtime._extract_batch_id(batch_folder)

    assert batch_id == "my_batch_001", f"Expected 'my_batch_001', got '{batch_id}'"


def test_extract_batch_id_fallback_to_folder_name(tmp_path):
    """Test that _extract_batch_id falls back to folder name when no BATCH_ID."""
    from app.runtimes.construct_runtime import ConstructRuntime

    construct_pool = tmp_path / "pools" / "construct"
    queue_dir = construct_pool / "Queue"
    queue_dir.mkdir(parents=True)

    # Case: folder without summary.txt
    batch_folder = queue_dir / "orphan_batch"
    batch_folder.mkdir()
    (batch_folder / "task_x.txt").write_text("some task\n", encoding="utf-8")

    runtime = ConstructRuntime(root_dir=tmp_path)
    batch_id = runtime._extract_batch_id(batch_folder)

    assert batch_id == "orphan_batch", f"Expected 'orphan_batch', got '{batch_id}'"


def test_preprocess_queue_folders_idempotent(tmp_path):
    """Test that folder preprocessing is idempotent (safe to call twice)."""
    from app.runtimes.construct_runtime import ConstructRuntime

    construct_pool = tmp_path / "pools" / "construct"
    queue_dir = construct_pool / "Queue"
    queue_dir.mkdir(parents=True)

    batch_folder = queue_dir / "idempotent_test"
    batch_folder.mkdir()
    (batch_folder / "summary.txt").write_text("BATCH_ID: idempotent_test\n", encoding="utf-8")
    (batch_folder / "task_1.txt").write_text("task 1\n", encoding="utf-8")

    runtime = ConstructRuntime(root_dir=tmp_path)

    # Call preprocessing twice
    runtime._preprocess_queue_folders()
    runtime._preprocess_queue_folders()

    # Should still only have one reference txt
    tasks = runtime.list_queue_tasks()
    batch_refs = [t for t in tasks if "idempotent_test" in t.name]
    assert len(batch_refs) == 1, f"Expected 1 reference txt, got {len(batch_refs)}"

    # And folder should be gone
    assert not batch_folder.exists()


def test_cleanup_batch_field_on_done(tmp_path):
    """Test that Done signal triggers field cleanup for batch tasks."""
    from app.runtimes.construct_runtime import ConstructRuntime

    construct_pool = tmp_path / "pools" / "construct"
    queue_dir = construct_pool / "Queue"
    outbox_dir = construct_pool / "Outbox"
    slot_dir = construct_pool / "constructor_01"
    workspace_dir = slot_dir / "workspace"
    queue_dir.mkdir(parents=True)
    outbox_dir.mkdir(parents=True)
    slot_dir.mkdir(parents=True)
    workspace_dir.mkdir(parents=True)

    # Simulate: queue has a folder, list_queue_tasks preprocesses it
    batch_folder = queue_dir / "batch_cleanup_test"
    batch_folder.mkdir()
    (batch_folder / "summary.txt").write_text("BATCH_ID: batch_cleanup_test\n", encoding="utf-8")

    runtime = ConstructRuntime(root_dir=tmp_path)
    runtime.list_queue_tasks()

    # Verify field was created
    field_dir = construct_pool / "fields" / "batch_cleanup_test"
    assert field_dir.exists(), "Field should exist after preprocessing"

    # Simulate Done signal for a batch task
    slot = runtime.get_slot("constructor_01")
    slot.busy = True
    slot.assigned_task_id = "batch_batch_cleanup_test"

    # Cleanup the field
    runtime._cleanup_batch_field(slot, "batch_batch_cleanup_test")

    # Field should be gone
    assert not field_dir.exists(), "Field should be cleaned up after Done"


def test_mixed_txt_and_folder_queue(tmp_path):
    """Test queue with both .txt files and folders."""
    from app.runtimes.construct_runtime import ConstructRuntime

    construct_pool = tmp_path / "pools" / "construct"
    queue_dir = construct_pool / "Queue"
    queue_dir.mkdir(parents=True)

    # Put a regular .txt in Queue
    (queue_dir / "single_task.txt").write_text(
        "FROM: user\nTO: construct\nTASK_ID: t_single_001\n---\nTask.\n",
        encoding="utf-8"
    )

    # Put a folder batch in Queue
    batch_folder = queue_dir / "mixed_batch"
    batch_folder.mkdir()
    (batch_folder / "summary.txt").write_text("BATCH_ID: mixed_batch\n", encoding="utf-8")
    (batch_folder / "task_x.txt").write_text("x\n", encoding="utf-8")

    runtime = ConstructRuntime(root_dir=tmp_path)
    tasks = runtime.list_queue_tasks()
    task_names = [t.name for t in tasks]

    # Should have both: original txt + converted batch reference
    assert "single_task.txt" in task_names, "Original txt should remain"
    assert any("task_batch_mixed_batch.txt" in name for name in task_names), \
        "Batch should be converted to reference txt"


def test_build_batch_task_txt_format(tmp_path):
    """Test that _build_batch_task_txt produces correctly formatted reference txt."""
    from app.runtimes.construct_runtime import ConstructRuntime

    construct_pool = tmp_path / "pools" / "construct"
    queue_dir = construct_pool / "Queue"
    queue_dir.mkdir(parents=True)

    batch_folder = queue_dir / "format_test"
    batch_folder.mkdir()
    (batch_folder / "summary.txt").write_text("BATCH_ID: format_test\n", encoding="utf-8")

    runtime = ConstructRuntime(root_dir=tmp_path)
    field_dir = construct_pool / "fields" / "format_test"
    field_dir.mkdir(parents=True, exist_ok=True)

    content = runtime._build_batch_task_txt("format_test", field_dir)

    # Verify key fields
    assert "FROM: thinking_pool" in content
    assert "TASK_ID: batch_format_test" in content
    assert "INPUT_MODE: batch_dir" in content
    assert "BATCH_FIELD:" in content
    assert "batch_dir" in content
