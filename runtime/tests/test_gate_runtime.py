"""Unit tests for GateRuntime orchestrator.

Gate Pool 职责：
- 槽位命名: guard_01, guard_02
- 池目录: pools/gate/
- 生命周期: online -> start_review -> approved/rejected
- Outbox: 存放 accepted 的产物
- Rejectbox: 存放 denied 的产物
- timeout: 杀进程，任务重新放回 Queue
"""

from pathlib import Path
import pytest

from app.runtimes.gate_runtime import GateRuntime, GuardSlot


def test_init_slots_discovers_guard_directories(tmp_path):
    """Test that GateRuntime discovers guard_01 and guard_02 slots."""
    # Create gate pool structure with 2 guard slots
    gate_pool = tmp_path / "pools" / "gate"
    (gate_pool / "Queue").mkdir(parents=True)
    (gate_pool / "Outbox").mkdir(parents=True)
    (gate_pool / "Rejectbox").mkdir(parents=True)

    # Create guard slots
    for i in [1, 2]:
        slot_dir = gate_pool / f"guard_0{i}"
        slot_dir.mkdir(parents=True)
        (slot_dir / "workspace").mkdir()

    runtime = GateRuntime(root_dir=tmp_path, signal_port=19200)

    # Verify both slots discovered
    assert len(runtime._slots) == 2
    assert "guard_01" in runtime._slots
    assert "guard_02" in runtime._slots

    # Verify slot structure
    slot1 = runtime.get_slot("guard_01")
    assert slot1 is not None
    assert slot1.slot_id == "guard_01"
    assert slot1.busy is False
    assert slot1.workspace_dir == gate_pool / "guard_01" / "workspace"


def test_approved_signal_moves_artifacts_to_outbox(tmp_path):
    """Test that approved signal collects workspace artifacts to Outbox."""
    gate_pool = tmp_path / "pools" / "gate"
    (gate_pool / "Queue").mkdir(parents=True)
    (gate_pool / "Outbox").mkdir(parents=True)
    (gate_pool / "Rejectbox").mkdir(parents=True)

    slot_dir = gate_pool / "guard_01"
    slot_dir.mkdir(parents=True)
    workspace_dir = slot_dir / "workspace"
    workspace_dir.mkdir()

    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True)
    for f in ["Online.bat", "StartReview.bat", "Accepted.bat", "Denied.bat", "signal_bridge.py", "BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")

    runtime = GateRuntime(root_dir=tmp_path, signal_port=19201)

    # Simulate a guard working on a task
    slot = runtime.get_slot("guard_01")
    slot.busy = True
    slot.assigned_task_id = "review_001"

    # Create some artifacts in workspace
    (workspace_dir / "review_result.txt").write_text("approved", encoding="utf-8")
    (workspace_dir / "notes.txt").write_text("looks good", encoding="utf-8")

    # Simulate approved signal
    signal_result = {
        "agent_id": "guard_01",
        "task_id": "review_001",
        "signal": "approved",
        "is_terminal": True,
        "to_state": "state_3_approved",
    }

    runtime.handle_signal(signal_result)

    # Verify artifacts moved to Outbox
    outbox_task_dir = gate_pool / "Outbox" / "review_001"
    assert outbox_task_dir.exists()
    assert (outbox_task_dir / "review_result.txt").exists()
    assert (outbox_task_dir / "notes.txt").exists()

    # Verify slot released
    assert slot.busy is False
    assert slot.assigned_task_id == ""


def test_rejected_signal_moves_artifacts_to_rejectbox(tmp_path):
    """Test that rejected signal collects workspace artifacts to Rejectbox."""
    gate_pool = tmp_path / "pools" / "gate"
    (gate_pool / "Queue").mkdir(parents=True)
    (gate_pool / "Outbox").mkdir(parents=True)
    (gate_pool / "Rejectbox").mkdir(parents=True)

    slot_dir = gate_pool / "guard_02"
    slot_dir.mkdir(parents=True)
    workspace_dir = slot_dir / "workspace"
    workspace_dir.mkdir()

    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True)
    for f in ["Online.bat", "StartReview.bat", "Accepted.bat", "Denied.bat", "signal_bridge.py", "BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")

    runtime = GateRuntime(root_dir=tmp_path, signal_port=19202)

    # Simulate a guard working on a task
    slot = runtime.get_slot("guard_02")
    slot.busy = True
    slot.assigned_task_id = "review_002"

    # Create some artifacts in workspace
    (workspace_dir / "review_result.txt").write_text("rejected", encoding="utf-8")
    (workspace_dir / "feedback.txt").write_text("needs work", encoding="utf-8")

    # Simulate rejected signal
    signal_result = {
        "agent_id": "guard_02",
        "task_id": "review_002",
        "signal": "rejected",
        "is_terminal": True,
        "to_state": "state_3_rejected",
    }

    runtime.handle_signal(signal_result)

    # Verify artifacts moved to Rejectbox
    rejectbox_task_dir = gate_pool / "Rejectbox" / "review_002"
    assert rejectbox_task_dir.exists()
    assert (rejectbox_task_dir / "review_result.txt").exists()
    assert (rejectbox_task_dir / "feedback.txt").exists()

    # Verify Outbox is empty for this task
    assert not (gate_pool / "Outbox" / "review_002").exists()

    # Verify slot released
    assert slot.busy is False
    assert slot.assigned_task_id == ""


def test_check_timeouts_requeues_task_until_guard_confirms_state(tmp_path):
    """Test that timeout kills process and requeues the original task file."""
    gate_pool = tmp_path / "pools" / "gate"
    queue_dir = gate_pool / "Queue"
    queue_dir.mkdir(parents=True)
    (gate_pool / "Outbox").mkdir(parents=True)
    (gate_pool / "Rejectbox").mkdir(parents=True)

    slot_dir = gate_pool / "guard_01"
    slot_dir.mkdir(parents=True)
    (slot_dir / "workspace").mkdir()

    task_file = slot_dir / "task_review_003.txt"
    task_content = """FROM: construct
TO: guard_01
TASK_ID: review_003
FEATURE_ID: feature_gate
TIMEOUT: 1

Review this construct output.
"""
    task_file.write_text(task_content, encoding="utf-8")

    runtime = GateRuntime(root_dir=tmp_path, signal_port=19203)
    slot = runtime.get_slot("guard_01")
    slot.busy = True
    slot.assigned_task_id = "review_003"
    slot.assigned_at_epoch = 1.0
    slot.timeout_seconds = 1
    slot.launch_result = {"pid": 1234, "launched": True}

    cleanup_calls = []
    original_cleanup = runtime._launch_manager.cleanup_launch

    def mock_cleanup(launch_result):
        cleanup_calls.append(launch_result)
        return {"cleaned": True}

    runtime._launch_manager.cleanup_launch = mock_cleanup

    import time as time_module
    original_time = time_module.time
    time_module.time = lambda: 10.0

    try:
        timed_out = runtime.check_timeouts()

        assert len(timed_out) == 1
        assert timed_out[0]["slot_id"] == "guard_01"
        assert timed_out[0]["task_id"] == "review_003"
        assert cleanup_calls == [{"pid": 1234, "launched": True}]

        requeued_file = queue_dir / "task_review_003.txt"
        assert requeued_file.exists()
        assert requeued_file.read_text(encoding="utf-8") == task_content

        assert slot.busy is False
        assert slot.assigned_task_id == ""
        assert slot.launch_result is None
    finally:
        runtime._launch_manager.cleanup_launch = original_cleanup
        time_module.time = original_time


def test_dispatch_next_uses_gate_specific_bootstrap_file(tmp_path):
    """Test that Gate dispatch deploys GATE_BOOTSTRAP.txt and launch script reads it explicitly."""
    gate_pool = tmp_path / "pools" / "gate"
    queue_dir = gate_pool / "Queue"
    queue_dir.mkdir(parents=True)
    (gate_pool / "Outbox").mkdir(parents=True)
    (gate_pool / "Rejectbox").mkdir(parents=True)

    slot_dir = gate_pool / "guard_01"
    slot_dir.mkdir(parents=True)
    (slot_dir / "workspace").mkdir()

    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True)
    for f in ["Online.bat", "StartReview.bat", "Accepted.bat", "Denied.bat", "signal_bridge.py", "BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")
    gate_tools_dir = tools_dir / "gate"
    gate_tools_dir.mkdir()
    (gate_tools_dir / "GATE_BOOTSTRAP.txt").write_text("mock gate bootstrap", encoding="utf-8")

    task_file = queue_dir / "task_review_004.txt"
    task_file.write_text("FROM: construct\nTASK_ID: review_004\n\nContent", encoding="utf-8")

    runtime = GateRuntime(root_dir=tmp_path, signal_port=19204)

    import app.shared.launch_manager as lm_module
    original_launch = lm_module.LaunchManager.launch

    def mock_launch(self, request, dry_run=True):
        return {
            "launched": True,
            "dry_run": dry_run,
            "command": ["cmd"],
            "cwd": str(slot_dir),
            "pid": 5678,
            "job_handle": None,
        }

    lm_module.LaunchManager.launch = mock_launch

    try:
        result = runtime.dispatch_next(dry_run=False)

        assert result["dispatched"] is True
        assert (slot_dir / "GATE_BOOTSTRAP.txt").exists()
        assert not (slot_dir / "BOOTSTRAP.txt").exists()

        launch_bat = slot_dir / "launch_guard_01.bat"
        assert launch_bat.exists()
        launch_content = launch_bat.read_text(encoding="utf-8")
        assert "GATE_BOOTSTRAP.txt" in launch_content
        assert "Read and strictly follow all instructions in BOOTSTRAP.txt in the current directory." not in launch_content
    finally:
        lm_module.LaunchManager.launch = original_launch


