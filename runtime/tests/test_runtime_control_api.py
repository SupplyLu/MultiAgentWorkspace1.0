"""Tests for Runtime control API endpoints (pause/resume)."""

from pathlib import Path
import time

from app.runtimes.work_runtime import WorkRuntime
from app.runtimes.thinking_runtime import ThinkingRuntime
from app.runtimes.construct_runtime import ConstructRuntime
from app.runtimes.gate_runtime import GateRuntime


def test_work_runtime_pause_api_sets_paused_flag(tmp_path):
    """Test that POST /api/control/pause sets paused=True."""
    root_dir = tmp_path / "test_root"
    work_pool = root_dir / "pools" / "work"

    # Create worker slots
    for i in [1, 2]:
        slot_dir = work_pool / f"worker_0{i}"
        workspace = slot_dir / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)

    runtime = WorkRuntime(root_dir=root_dir, signal_port=18950)

    # Call pause API
    result = runtime.handle_api_request("POST", "/api/control/pause", None)

    assert result["paused"] is True
    assert result["pool"] == "work"
    assert runtime._paused is True


def test_work_runtime_resume_api_clears_paused_flag(tmp_path):
    """Test that POST /api/control/resume sets paused=False."""
    root_dir = tmp_path / "test_root"
    work_pool = root_dir / "pools" / "work"

    for i in [1, 2]:
        slot_dir = work_pool / f"worker_0{i}"
        workspace = slot_dir / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)

    runtime = WorkRuntime(root_dir=root_dir, signal_port=18951)

    # Pause first
    runtime.handle_api_request("POST", "/api/control/pause", None)
    assert runtime._paused is True

    # Resume
    result = runtime.handle_api_request("POST", "/api/control/resume", None)

    assert result["paused"] is False
    assert result["pool"] == "work"
    assert runtime._paused is False


def test_work_runtime_control_state_api_returns_paused_status(tmp_path):
    """Test that GET /api/control/state returns current paused status."""
    root_dir = tmp_path / "test_root"
    work_pool = root_dir / "pools" / "work"

    for i in [1, 2]:
        slot_dir = work_pool / f"worker_0{i}"
        workspace = slot_dir / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)

    runtime = WorkRuntime(root_dir=root_dir, signal_port=18952)

    # Initially not paused
    result = runtime.handle_api_request("GET", "/api/control/state", None)
    assert result["paused"] is False
    assert result["pool"] == "work"

    # Pause
    runtime.handle_api_request("POST", "/api/control/pause", None)

    # Check state again
    result = runtime.handle_api_request("GET", "/api/control/state", None)
    assert result["paused"] is True
    assert result["pool"] == "work"


def test_thinking_runtime_pause_resume_control(tmp_path):
    """Test that thinking runtime supports pause/resume control."""
    root_dir = tmp_path / "test_root"
    thinking_pool = root_dir / "pools" / "thinking"

    for i in [1, 2]:
        slot_dir = thinking_pool / f"sub_brain_0{i}"
        workspace = slot_dir / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)

    runtime = ThinkingRuntime(root_dir=root_dir, signal_port=18960)

    # Pause
    result = runtime.handle_api_request("POST", "/api/control/pause", None)
    assert result["paused"] is True
    assert result["pool"] == "thinking"

    # Resume
    result = runtime.handle_api_request("POST", "/api/control/resume", None)
    assert result["paused"] is False
    assert result["pool"] == "thinking"


def test_construct_runtime_pause_resume_control(tmp_path):
    """Test that construct runtime supports pause/resume control."""
    root_dir = tmp_path / "test_root"
    construct_pool = root_dir / "pools" / "construct"

    for i in [1, 2]:
        slot_dir = construct_pool / f"constructor_0{i}"
        workspace = slot_dir / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)

    runtime = ConstructRuntime(root_dir=root_dir, signal_port=18970)

    # Pause
    result = runtime.handle_api_request("POST", "/api/control/pause", None)
    assert result["paused"] is True
    assert result["pool"] == "construct"

    # Resume
    result = runtime.handle_api_request("POST", "/api/control/resume", None)
    assert result["paused"] is False
    assert result["pool"] == "construct"


def test_gate_runtime_pause_resume_control(tmp_path):
    """Test that gate runtime supports pause/resume control."""
    root_dir = tmp_path / "test_root"
    gate_pool = root_dir / "pools" / "gate"

    for i in [1, 2]:
        slot_dir = gate_pool / f"guard_0{i}"
        workspace = slot_dir / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)

    runtime = GateRuntime(root_dir=root_dir, signal_port=18980)

    # Pause
    result = runtime.handle_api_request("POST", "/api/control/pause", None)
    assert result["paused"] is True
    assert result["pool"] == "gate"

    # Resume
    result = runtime.handle_api_request("POST", "/api/control/resume", None)
    assert result["paused"] is False
    assert result["pool"] == "gate"


def test_paused_runtime_skips_dispatch(tmp_path):
    """Test that paused runtime does not dispatch tasks."""
    root_dir = tmp_path / "test_root"
    work_pool = root_dir / "pools" / "work"
    queue_dir = work_pool / "Queue"
    queue_dir.mkdir(parents=True, exist_ok=True)

    for i in [1, 2]:
        slot_dir = work_pool / f"worker_0{i}"
        workspace = slot_dir / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)

    (work_pool / "Outbox").mkdir(parents=True, exist_ok=True)

    tools_dir = root_dir / "runtime" / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    for f in ["Online.bat", "StartWriting.bat", "Done.bat", "signal_bridge.py", "WORK_BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")

    # Create a task
    task_file = queue_dir / "task_001.txt"
    task_file.write_text("TASK_ID: t_001\nFEATURE_ID: f_001\n\nTask body", encoding="utf-8")

    runtime = WorkRuntime(root_dir=root_dir, signal_port=18953)

    # Pause runtime
    runtime.handle_api_request("POST", "/api/control/pause", None)

    # Try to dispatch - should be skipped
    result = runtime.dispatch_next(dry_run=True)

    assert result["dispatched"] is False
    assert "paused" in result.get("error", "").lower()

    # Task should still be in queue
    assert task_file.exists()

    # All slots should remain idle
    for slot in runtime._slots.values():
        assert slot.busy is False


def test_resumed_runtime_allows_dispatch(tmp_path):
    """Test that resumed runtime can dispatch tasks normally."""
    root_dir = tmp_path / "test_root"
    work_pool = root_dir / "pools" / "work"
    queue_dir = work_pool / "Queue"
    queue_dir.mkdir(parents=True, exist_ok=True)

    for i in [1, 2]:
        slot_dir = work_pool / f"worker_0{i}"
        workspace = slot_dir / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)

    (work_pool / "Outbox").mkdir(parents=True, exist_ok=True)

    tools_dir = root_dir / "runtime" / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    for f in ["Online.bat", "StartWriting.bat", "Done.bat", "signal_bridge.py", "WORK_BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")

    # Create a task
    task_file = queue_dir / "task_002.txt"
    task_file.write_text("TASK_ID: t_002\nFEATURE_ID: f_002\n\nTask body", encoding="utf-8")

    runtime = WorkRuntime(root_dir=root_dir, signal_port=18954)

    # Pause then resume
    runtime.handle_api_request("POST", "/api/control/pause", None)
    runtime.handle_api_request("POST", "/api/control/resume", None)

    # Mock launch
    import app.shared.launch_manager as lm_module
    original_launch = lm_module.LaunchManager.launch

    def mock_launch(self, request, dry_run=True):
        return {"launched": True, "dry_run": True, "pid": 1234, "job_handle": None}

    lm_module.LaunchManager.launch = mock_launch

    try:
        # Dispatch should succeed
        result = runtime.dispatch_next(dry_run=True)
        assert result["dispatched"] is True
        assert result["task_id"] == "t_002"
    finally:
        lm_module.LaunchManager.launch = original_launch
