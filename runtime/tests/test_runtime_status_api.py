"""Tests for Runtime status API endpoints."""

import json
from pathlib import Path

from app.runtimes.work_runtime import WorkRuntime
from app.runtimes.thinking_runtime import ThinkingRuntime
from app.runtimes.construct_runtime import ConstructRuntime
from app.runtimes.gate_runtime import GateRuntime
from app.runtimes.post_runtime import PostRuntime


def test_work_runtime_status_api_returns_pool_and_slots(tmp_path):
    """Test that work runtime exposes GET /api/status with pool info and slot states."""
    root_dir = tmp_path / "test_root"
    work_pool = root_dir / "pools" / "work"

    # Create two worker slots
    for i in [1, 2]:
        slot_dir = work_pool / f"worker_0{i}"
        workspace = slot_dir / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)

    runtime = WorkRuntime(root_dir=root_dir, signal_port=18900)

    # Hook up the API handler
    def api_handler(method: str, path: str, payload: dict | None):
        return runtime.handle_api_request(method, path, payload)

    runtime._signal_server.on_api_request = api_handler

    # Call the handler directly (no HTTP needed for unit test)
    result = api_handler("GET", "/api/status", None)

    # Verify schema
    assert result["pool"] == "work"
    assert result["signal_port"] == 18900
    assert result["is_running"] is False  # Not started yet
    assert "queue_count" in result
    assert "slots" in result
    assert len(result["slots"]) == 2

    # Verify slot structure
    slot = result["slots"][0]
    assert "slot_id" in slot
    assert "busy" in slot
    assert "assigned_task_id" in slot


def test_work_runtime_health_api_returns_ok_and_pool_info(tmp_path):
    """Test that work runtime exposes GET /api/health with basic health check."""
    root_dir = tmp_path / "test_root"
    work_pool = root_dir / "pools" / "work"
    work_pool.mkdir(parents=True, exist_ok=True)

    runtime = WorkRuntime(root_dir=root_dir, signal_port=18901)

    def api_handler(method: str, path: str, payload: dict | None):
        return runtime.handle_api_request(method, path, payload)

    runtime._signal_server.on_api_request = api_handler

    result = api_handler("GET", "/api/health", None)

    assert result["ok"] is True
    assert result["pool"] == "work"
    assert "uptime_seconds" in result


def test_thinking_runtime_status_api_returns_pool_and_slots(tmp_path):
    """Test that thinking runtime exposes GET /api/status with standard schema."""
    root_dir = tmp_path / "test_root"
    thinking_pool = root_dir / "pools" / "thinking"

    for i in [1, 2]:
        slot_dir = thinking_pool / f"sub_brain_0{i}"
        workspace = slot_dir / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)

    runtime = ThinkingRuntime(root_dir=root_dir, signal_port=18910)

    result = runtime.handle_api_request("GET", "/api/status", None)

    assert result["pool"] == "thinking"
    assert result["signal_port"] == 18910
    assert result["is_running"] is False
    assert "queue_count" in result
    assert len(result["slots"]) == 2


def test_construct_runtime_status_api_returns_pool_and_slots(tmp_path):
    """Test that construct runtime exposes GET /api/status with standard schema."""
    root_dir = tmp_path / "test_root"
    construct_pool = root_dir / "pools" / "construct"

    for i in [1, 2]:
        slot_dir = construct_pool / f"constructor_0{i}"
        workspace = slot_dir / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)

    runtime = ConstructRuntime(root_dir=root_dir, signal_port=18920)

    result = runtime.handle_api_request("GET", "/api/status", None)

    assert result["pool"] == "construct"
    assert result["signal_port"] == 18920
    assert result["is_running"] is False
    assert "queue_count" in result
    assert len(result["slots"]) == 2


def test_post_runtime_status_api_returns_basic_runtime_info(tmp_path):
    """Test that post runtime exposes GET /api/status with standard schema."""
    runtime = PostRuntime(root_dir=tmp_path, scan_interval_seconds=30)

    result = runtime.handle_api_request("GET", "/api/status", None)

    assert result["pool"] == "post"
    assert result["is_running"] is False
    assert result["queue_count"] == 0
    assert result["slots"] == []


def test_post_runtime_health_api_returns_ok_and_pool_info(tmp_path):
    """Test that post runtime exposes GET /api/health with standard schema."""
    runtime = PostRuntime(root_dir=tmp_path, scan_interval_seconds=30)

    result = runtime.handle_api_request("GET", "/api/health", None)

    assert result["ok"] is True
    assert result["pool"] == "post"
    assert "uptime_seconds" in result


def test_post_runtime_status_returns_real_project_registration_counts(tmp_path):
    """Test that POST runtime status returns accurate counts of project registrations."""
    runtime = PostRuntime(root_dir=tmp_path)

    # Register some projects with various statuses
    runtime._registry.register_project("p1", "pool1", "pool2", route=["pool1", "pool2"])
    runtime._registry.update_project("p1", {"status": "in_progress"})

    runtime._registry.register_project("p2", "pool1", "pool2", route=["pool1", "pool2"])
    runtime._registry.update_project("p2", {"status": "waiting"})

    runtime._registry.register_project("p3", "pool1", "pool2", route=["pool1", "pool2"])
    runtime._registry.update_project("p3", {"status": "blocked", "blocked_reason": "Missing dependency"})

    runtime._registry.register_project("p4", "pool1", "pool2", route=["pool1", "pool2"])
    runtime._registry.update_project("p4", {"status": "delivered"})

    runtime._registry.register_project("p5", "pool1", "pool2", route=["pool1", "pool2"])
    runtime._registry.update_project("p5", {"status": "in_progress"})

    result = runtime.handle_api_request("GET", "/api/status", None)

    # Base schema checks
    assert result["pool"] == "post"
    assert result["is_running"] is False
    assert result["queue_count"] == 0
    assert result["slots"] == []

    # New fields
    assert result["active_registrations"] == 2  # p1, p5
    assert result["waiting_payload_registrations"] == 1  # p2
    assert result["blocked_registrations"] == 1  # p3
    assert result["delivered_registrations"] == 1  # p4
    assert result["recent_blocked_reason"] == "Missing dependency"


def test_gate_runtime_status_api_returns_pool_and_slots(tmp_path):
    """Test that gate runtime exposes GET /api/status with standard schema."""
    root_dir = tmp_path / "test_root"
    gate_pool = root_dir / "pools" / "gate"

    for i in [1, 2]:
        slot_dir = gate_pool / f"guard_0{i}"
        workspace = slot_dir / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)

    runtime = GateRuntime(root_dir=root_dir, signal_port=18930)

    result = runtime.handle_api_request("GET", "/api/status", None)

    assert result["pool"] == "gate"
    assert result["signal_port"] == 18930
    assert result["is_running"] is False
    assert "queue_count" in result
    assert len(result["slots"]) == 2


def test_gate_runtime_health_api_returns_ok_and_pool_info(tmp_path):
    """Test that gate runtime exposes GET /api/health with standard schema."""
    root_dir = tmp_path / "test_root"
    gate_pool = root_dir / "pools" / "gate"
    gate_pool.mkdir(parents=True, exist_ok=True)

    runtime = GateRuntime(root_dir=root_dir, signal_port=18931)

    result = runtime.handle_api_request("GET", "/api/health", None)

    assert result["ok"] is True
    assert result["pool"] == "gate"
    assert "uptime_seconds" in result
