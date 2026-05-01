"""Unit tests for ThinkingRuntime orchestrator.

复制自 test_work_runtime.py，针对 Thinking Pool 特化：
- 槽位命名: sub_brain_XX (动态扫描)
- 池目录: pools/thinking/
- 生命周期: online -> start_thinking -> start_summarizing -> done
"""

from pathlib import Path
import pytest

from app.runtimes.thinking_runtime import ThinkingRuntime, ThinkingSlot


def test_init_slots_discovers_sub_brain_directories_dynamically(tmp_path):
    """Test that ThinkingRuntime dynamically discovers sub_brain_* directories."""
    # Create thinking pool structure with 3 sub_brain slots
    thinking_pool = tmp_path / "pools" / "thinking"
    (thinking_pool / "Queue").mkdir(parents=True)
    (thinking_pool / "Outbox").mkdir(parents=True)

    # Create sub_brain slots
    for i in [1, 2, 3]:
        slot_dir = thinking_pool / f"sub_brain_0{i}"
        slot_dir.mkdir(parents=True)
        (slot_dir / "workspace").mkdir()

    runtime = ThinkingRuntime(root_dir=tmp_path, signal_port=19001)

    # Verify all 3 slots discovered
    assert len(runtime._slots) == 3
    assert "sub_brain_01" in runtime._slots
    assert "sub_brain_02" in runtime._slots
    assert "sub_brain_03" in runtime._slots

    # Verify slot structure
    slot1 = runtime.get_slot("sub_brain_01")
    assert slot1 is not None
    assert slot1.slot_id == "sub_brain_01"
    assert slot1.busy is False
    assert slot1.workspace_dir == thinking_pool / "sub_brain_01" / "workspace"


def test_get_next_idle_slot_uses_lowest_available(tmp_path):
    """Test that the lowest numbered idle slot is returned first."""
    thinking_pool = tmp_path / "pools" / "thinking"
    (thinking_pool / "Queue").mkdir(parents=True)
    (thinking_pool / "Outbox").mkdir(parents=True)

    for i in [1, 2]:
        slot_dir = thinking_pool / f"sub_brain_0{i}"
        slot_dir.mkdir(parents=True)
        (slot_dir / "workspace").mkdir()

    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True)
    for f in ["Online.bat", "StartThinking.bat", "StartSummarizing.bat", "Done.bat", "signal_bridge.py", "THINKING_BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")

    runtime = ThinkingRuntime(root_dir=tmp_path, signal_port=19002)

    # First call should return sub_brain_01
    slot1 = runtime.get_next_idle_slot()
    assert slot1 is not None
    assert slot1.slot_id == "sub_brain_01"
    assert slot1.busy is False

    # Mark sub_brain_01 as busy
    slot1.busy = True

    # Second call should return sub_brain_02
    slot2 = runtime.get_next_idle_slot()
    assert slot2 is not None
    assert slot2.slot_id == "sub_brain_02"
    assert slot2.busy is False

    # Mark both as busy
    slot2.busy = True

    # Third call should return None
    slot3 = runtime.get_next_idle_slot()
    assert slot3 is None


def test_list_queue_tasks_ignores_hidden_files(tmp_path):
    """Test that list_queue_tasks returns only visible .txt files."""
    queue_dir = tmp_path / "pools" / "thinking" / "Queue"
    queue_dir.mkdir(parents=True)
    thinking_pool = tmp_path / "pools" / "thinking"
    (thinking_pool / "sub_brain_01" / "workspace").mkdir(parents=True)
    (thinking_pool / "Outbox").mkdir(parents=True)

    # Create some files
    (queue_dir / "task_001.txt").write_text("content1")
    (queue_dir / "task_002.txt").write_text("content2")
    (queue_dir / ".hidden.txt").write_text("hidden")
    (queue_dir / "temp.md").write_text("markdown")

    runtime = ThinkingRuntime(root_dir=tmp_path, signal_port=19003)
    tasks = runtime.list_queue_tasks()

    assert len(tasks) == 2
    assert any(t.name == "task_001.txt" for t in tasks)
    assert any(t.name == "task_002.txt" for t in tasks)
    assert not any(t.name.startswith(".") for t in tasks)
    assert not any(t.suffix != ".txt" for t in tasks)


def test_dispatch_next_copies_task_to_slot_and_marks_busy(tmp_path):
    """Test that dispatch_next copies task to thinking slot and marks it busy."""
    queue_dir = tmp_path / "pools" / "thinking" / "Queue"
    queue_dir.mkdir(parents=True)
    thinking_pool = tmp_path / "pools" / "thinking"
    slot1_dir = thinking_pool / "sub_brain_01"
    slot1_dir.mkdir(parents=True)
    (slot1_dir / "workspace").mkdir(parents=True)
    (thinking_pool / "Outbox").mkdir(parents=True)

    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True)
    for f in ["Online.bat", "StartThinking.bat", "StartSummarizing.bat", "Done.bat", "signal_bridge.py", "THINKING_BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")

    # Create a task file
    task_file = queue_dir / "task_001.txt"
    task_content = """FROM: runtime
TO: sub_brain_01
PROJECT_KEY: SignalBridge-v1-Build

Please analyze the requirements.
"""
    task_file.write_text(task_content, encoding="utf-8")

    runtime = ThinkingRuntime(root_dir=tmp_path, signal_port=19004)

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
        assert result["slot_id"] == "sub_brain_01"
        assert result["task_id"] == "SignalBridge-v1-Build"
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
        slot = runtime.get_slot("sub_brain_01")
        assert slot is not None
        assert slot.busy is True
        assert slot.assigned_task_id == "SignalBridge-v1-Build"

        # Verify launch bat file was created
        launch_bat = slot1_dir / "launch_sub_brain_01.bat"
        assert launch_bat.exists()
        bat_content = launch_bat.read_text(encoding="utf-8")
        assert "sub_brain_01" in bat_content
        assert "SignalBridge-v1-Build" in bat_content
        assert "POOL=thinking" in bat_content

    finally:
        lm_module.LaunchManager.launch = original_launch


def test_dispatch_next_returns_no_idle_slot_when_all_busy(tmp_path):
    """Test that dispatch_next returns appropriate result when all slots are busy."""
    queue_dir = tmp_path / "pools" / "thinking" / "Queue"
    queue_dir.mkdir(parents=True)
    thinking_pool = tmp_path / "pools" / "thinking"

    for i in [1, 2]:
        slot_dir = thinking_pool / f"sub_brain_0{i}"
        slot_dir.mkdir(parents=True)
        (slot_dir / "workspace").mkdir(parents=True)

    (thinking_pool / "Outbox").mkdir(parents=True)

    # Create a task file
    task_file = queue_dir / "task_001.txt"
    task_file.write_text("PROJECT_KEY: SignalBridge-v1-Build\n\ntask body")

    runtime = ThinkingRuntime(root_dir=tmp_path, signal_port=19005)

    # Mark all slots as busy
    for slot_id in ["sub_brain_01", "sub_brain_02"]:
        slot = runtime.get_slot(slot_id)
        if slot:
            slot.busy = True

    # Try to dispatch
    result = runtime.dispatch_next(dry_run=True)

    # Verify result
    assert result["dispatched"] is False
    assert "idle slot" in result.get("error", "").lower()


def test_handle_signal_releases_slot_on_done(tmp_path):
    """Test that handle_signal releases a slot when done signal is received."""
    thinking_pool = tmp_path / "pools" / "thinking"
    (thinking_pool / "Queue").mkdir(parents=True)
    slot1_dir = thinking_pool / "sub_brain_01"
    slot1_dir.mkdir(parents=True)
    (slot1_dir / "workspace").mkdir(parents=True)
    (thinking_pool / "Outbox").mkdir(parents=True)

    runtime = ThinkingRuntime(root_dir=tmp_path, signal_port=19006)

    # Mark sub_brain_01 as busy with a task
    slot1 = runtime.get_slot("sub_brain_01")
    if slot1:
        slot1.busy = True
        slot1.assigned_task_id = "SignalBridge-v1-Build"

    # Send a done signal
    signal_result = {
        "agent_id": "sub_brain_01",
        "task_id": "SignalBridge-v1-Build",
        "signal": "done",
        "is_terminal": True,
    }

    runtime.handle_signal(signal_result)

    # Verify slot is released
    assert slot1.busy is False
    assert slot1.assigned_task_id == ""


def test_handle_signal_releases_slot_on_failed(tmp_path):
    """Test that handle_signal releases a slot when failed signal is received."""
    thinking_pool = tmp_path / "pools" / "thinking"
    (thinking_pool / "Queue").mkdir(parents=True)
    slot1_dir = thinking_pool / "sub_brain_01"
    slot1_dir.mkdir(parents=True)
    (slot1_dir / "workspace").mkdir(parents=True)
    (thinking_pool / "Outbox").mkdir(parents=True)

    runtime = ThinkingRuntime(root_dir=tmp_path, signal_port=19007)

    # Mark sub_brain_01 as busy with a task
    slot1 = runtime.get_slot("sub_brain_01")
    if slot1:
        slot1.busy = True
        slot1.assigned_task_id = "SignalBridge-v2-Build"

    # Send a failed signal
    signal_result = {
        "agent_id": "sub_brain_01",
        "task_id": "SignalBridge-v2-Build",
        "signal": "failed",
        "is_terminal": True,
    }

    runtime.handle_signal(signal_result)

    # Verify slot is released
    assert slot1.busy is False
    assert slot1.assigned_task_id == ""


def test_handle_signal_releases_slot_on_blocked(tmp_path):
    """Test that handle_signal releases a slot when blocked signal is received."""
    thinking_pool = tmp_path / "pools" / "thinking"
    (thinking_pool / "Queue").mkdir(parents=True)
    slot1_dir = thinking_pool / "sub_brain_01"
    slot1_dir.mkdir(parents=True)
    (slot1_dir / "workspace").mkdir(parents=True)
    (thinking_pool / "Outbox").mkdir(parents=True)

    runtime = ThinkingRuntime(root_dir=tmp_path, signal_port=19008)

    # Mark sub_brain_01 as busy with a task
    slot1 = runtime.get_slot("sub_brain_01")
    if slot1:
        slot1.busy = True
        slot1.assigned_task_id = "SignalBridge-v3-Build"

    # Send a blocked signal
    signal_result = {
        "agent_id": "sub_brain_01",
        "task_id": "SignalBridge-v3-Build",
        "signal": "blocked",
        "is_terminal": True,
    }

    runtime.handle_signal(signal_result)

    # Verify slot is released
    assert slot1.busy is False
    assert slot1.assigned_task_id == ""


def test_deploy_lifecycle_bats_includes_thinking_specific_bats(tmp_path):
    """Test that _deploy_lifecycle_bats copies Thinking Pool specific bats."""
    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True)
    for f in ["Online.bat", "StartThinking.bat", "StartSummarizing.bat", "Done.bat", "signal_bridge.py", "THINKING_BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")

    thinking_pool = tmp_path / "pools" / "thinking"
    slot1_dir = thinking_pool / "sub_brain_01"
    slot1_dir.mkdir(parents=True)
    (slot1_dir / "workspace").mkdir(parents=True)
    (thinking_pool / "Outbox").mkdir(parents=True)

    runtime = ThinkingRuntime(root_dir=tmp_path, signal_port=19009)
    runtime._lifecycle_tools_dir = tools_dir

    slot = runtime.get_slot("sub_brain_01")
    assert slot is not None

    runtime._deploy_lifecycle_bats(slot)

    assert (slot1_dir / "Online.bat").exists()
    assert (slot1_dir / "StartThinking.bat").exists()
    assert (slot1_dir / "StartSummarizing.bat").exists()
    assert (slot1_dir / "Done.bat").exists()
    assert (slot1_dir / "signal_bridge.py").exists()
    assert (slot1_dir / "THINKING_BOOTSTRAP.txt").exists()


def test_dispatch_next_clears_workspace_before_task(tmp_path):
    """Test that dispatch_next clears workspace to prevent artifact leak."""
    queue_dir = tmp_path / "pools" / "thinking" / "Queue"
    queue_dir.mkdir(parents=True)
    thinking_pool = tmp_path / "pools" / "thinking"
    slot1_dir = thinking_pool / "sub_brain_01"
    slot1_dir.mkdir(parents=True)
    workspace_dir = slot1_dir / "workspace"
    workspace_dir.mkdir(parents=True)
    (thinking_pool / "Outbox").mkdir(parents=True)

    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True)
    for f in ["Online.bat", "StartThinking.bat", "StartSummarizing.bat", "Done.bat", "signal_bridge.py", "THINKING_BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")

    # Create stale artifact in workspace
    stale_file = workspace_dir / "stale_artifact.txt"
    stale_file.write_text("STALE CONTENT")

    # Create task
    task_file = queue_dir / "task_new.txt"
    task_file.write_text("PROJECT_KEY: SignalBridge-v1-Build\n\nFRESH TASK", encoding="utf-8")

    runtime = ThinkingRuntime(root_dir=tmp_path, signal_port=19010)

    import app.shared.launch_manager as lm_module
    original_launch = lm_module.LaunchManager.launch

    def mock_launch(self, request, dry_run=True):
        return {"launched": True, "dry_run": True, "pid": 1234, "job_handle": None}

    lm_module.LaunchManager.launch = mock_launch

    try:
        result = runtime.dispatch_next(dry_run=True)
        assert result["dispatched"] is True

        # Verify stale file was removed
        assert not stale_file.exists(), "Workspace should be cleared before task dispatch"

    finally:
        lm_module.LaunchManager.launch = original_launch


def test_dispatch_next_rolls_back_when_deploy_fails(tmp_path):
    """Test that dispatch_next restores queue and slot state if lifecycle deployment fails."""
    queue_dir = tmp_path / "pools" / "thinking" / "Queue"
    queue_dir.mkdir(parents=True)
    thinking_pool = tmp_path / "pools" / "thinking"
    slot1_dir = thinking_pool / "sub_brain_01"
    slot1_dir.mkdir(parents=True)
    (slot1_dir / "workspace").mkdir(parents=True)
    (thinking_pool / "Outbox").mkdir(parents=True)

    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True)
    for f in ["Online.bat", "StartThinking.bat", "StartSummarizing.bat", "Done.bat", "signal_bridge.py", "THINKING_BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")

    task_file = queue_dir / "task_rollback.txt"
    task_content = "PROJECT_KEY: SignalBridge-v1-Rollback\n\nbody"
    task_file.write_text(task_content, encoding="utf-8")

    runtime = ThinkingRuntime(root_dir=tmp_path, signal_port=19011)

    original_deploy = runtime._deploy_lifecycle_bats

    def mock_deploy(_slot):
        raise FileNotFoundError("boom deploy")

    runtime._deploy_lifecycle_bats = mock_deploy

    try:
        with pytest.raises(FileNotFoundError, match="boom deploy"):
            runtime.dispatch_next(dry_run=True)

        slot = runtime.get_slot("sub_brain_01")
        assert slot is not None
        assert slot.busy is False
        assert slot.assigned_task_id == ""
        assert slot.launch_result is None

        assert task_file.exists(), "queue task file should be restored after rollback"
        assert not (queue_dir / "task_rollback.txt.processing").exists()
        assert not (slot1_dir / "task_rollback.txt").exists()
    finally:
        runtime._deploy_lifecycle_bats = original_deploy


def test_dispatch_next_rolls_back_when_launch_fails(tmp_path):
    """Test that dispatch_next restores queue and slot state if process launch fails."""
    queue_dir = tmp_path / "pools" / "thinking" / "Queue"
    queue_dir.mkdir(parents=True)
    thinking_pool = tmp_path / "pools" / "thinking"
    slot1_dir = thinking_pool / "sub_brain_01"
    slot1_dir.mkdir(parents=True)
    (slot1_dir / "workspace").mkdir(parents=True)
    (thinking_pool / "Outbox").mkdir(parents=True)

    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True)
    for f in ["Online.bat", "StartThinking.bat", "StartSummarizing.bat", "Done.bat", "signal_bridge.py", "THINKING_BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")

    task_file = queue_dir / "task_launch_fail.txt"
    task_content = "PROJECT_KEY: SignalBridge-v1-Launch\n\nbody"
    task_file.write_text(task_content, encoding="utf-8")

    runtime = ThinkingRuntime(root_dir=tmp_path, signal_port=19012)

    import app.shared.launch_manager as lm_module
    original_launch = lm_module.LaunchManager.launch

    def mock_launch(self, request, dry_run=True):
        raise RuntimeError("boom launch")

    lm_module.LaunchManager.launch = mock_launch

    try:
        with pytest.raises(RuntimeError, match="boom launch"):
            runtime.dispatch_next(dry_run=True)

        slot = runtime.get_slot("sub_brain_01")
        assert slot is not None
        assert slot.busy is False
        assert slot.assigned_task_id == ""
        assert slot.launch_result is None

        assert task_file.exists(), "queue task file should be restored after rollback"
    finally:
        lm_module.LaunchManager.launch = original_launch


def test_check_timeouts_kills_and_releases_expired_slots(tmp_path):
    """Test that check_timeouts detects and releases timed-out slots."""
    import time

    thinking_pool = tmp_path / "pools" / "thinking"
    (thinking_pool / "Queue").mkdir(parents=True)
    slot1_dir = thinking_pool / "sub_brain_01"
    slot1_dir.mkdir(parents=True)
    (slot1_dir / "workspace").mkdir(parents=True)
    (thinking_pool / "Outbox").mkdir(parents=True)

    runtime = ThinkingRuntime(root_dir=tmp_path, signal_port=19013)

    # Setup slot with expired timeout
    slot = runtime.get_slot("sub_brain_01")
    assert slot is not None
    slot.busy = True
    slot.assigned_task_id = "SignalBridge-v1-Timeout"
    slot.assigned_at_epoch = time.time() - 400  # Expired (300s timeout)
    slot.timeout_seconds = 300
    slot.launch_result = {"launched": True, "job_handle": 0xBEEF}

    # Check timeouts
    timed_out = runtime.check_timeouts()

    # Verify timeout detected
    assert len(timed_out) == 1
    assert timed_out[0]["slot_id"] == "sub_brain_01"
    assert timed_out[0]["task_id"] == "SignalBridge-v1-Timeout"
    assert timed_out[0]["timeout_seconds"] == 300

    # Verify slot released
    assert slot.busy is False
    assert slot.assigned_task_id == ""


def test_collect_artifacts_to_outbox(tmp_path):
    """Test that collect_artifacts_to_outbox copies workspace to Outbox."""
    thinking_pool = tmp_path / "pools" / "thinking"
    (thinking_pool / "Queue").mkdir(parents=True)
    slot1_dir = thinking_pool / "sub_brain_01"
    slot1_dir.mkdir(parents=True)
    workspace_dir = slot1_dir / "workspace"
    workspace_dir.mkdir(parents=True)
    outbox_dir = thinking_pool / "Outbox"
    outbox_dir.mkdir(parents=True)

    # Create artifacts in workspace
    (workspace_dir / "result.txt").write_text("analysis result", encoding="utf-8")
    (workspace_dir / "subdir").mkdir()
    (workspace_dir / "subdir" / "detail.txt").write_text("detail", encoding="utf-8")

    runtime = ThinkingRuntime(root_dir=tmp_path, signal_port=19014)

    result = runtime.collect_artifacts_to_outbox("sub_brain_01", "SignalBridge-v1-Collect")

    assert result["collected"] is True
    assert result["task_id"] == "SignalBridge-v1-Collect"
    assert len(result["files"]) == 2

    # Verify files copied to Outbox
    assert (outbox_dir / "SignalBridge-v1-Collect" / "result.txt").exists()
    assert (outbox_dir / "SignalBridge-v1-Collect" / "subdir" / "detail.txt").exists()
