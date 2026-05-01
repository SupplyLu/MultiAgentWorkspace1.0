"""Tests for Runtime status API endpoints."""

import json
from pathlib import Path

import pytest

from app.runtimes.work_runtime import WorkRuntime
from app.runtimes.thinking_runtime import ThinkingRuntime
from app.runtimes.construct_runtime import ConstructRuntime
from app.runtimes.gate_runtime import GateRuntime
from app.runtimes.post_runtime import PostRuntime
from app.runtimes.package_runtime import PackageRuntime


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
    assert "current_state" in slot


@pytest.mark.parametrize(
    ("runtime_cls", "pool_name", "slot_prefix", "port"),
    [
        (ThinkingRuntime, "thinking", "sub_brain_", 18910),
        (ConstructRuntime, "construct", "constructor_", 18920),
        (GateRuntime, "gate", "guard_", 18930),
    ],
)
def test_runtime_status_api_exposes_current_state_for_slot_based_pools(
    tmp_path, runtime_cls, pool_name, slot_prefix, port
):
    root_dir = tmp_path / "test_root"
    pool_dir = root_dir / "pools" / pool_name

    for i in [1, 2]:
        slot_dir = pool_dir / f"{slot_prefix}0{i}"
        workspace = slot_dir / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)

    runtime = runtime_cls(root_dir=root_dir, signal_port=port)
    result = runtime.handle_api_request("GET", "/api/status", None)

    assert result["pool"] == pool_name
    assert result["signal_port"] == port
    assert len(result["slots"]) == 2
    assert "current_state" in result["slots"][0]


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




def test_package_runtime_status_api_returns_slot_task_and_stage_details(tmp_path):
    """Test that package runtime exposes slot task and stage details in GET /api/status."""
    from app.runtimes.package_runtime import PackageTask

    root_dir = tmp_path / "test_root"
    package_pool = root_dir / "pools" / "package"

    for slot_name in ["cutter_01", "tester_01", "releaser_01", "complete_player_01"]:
        workspace = package_pool / slot_name / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)

    runtime = PackageRuntime(root_dir=root_dir, signal_port=19300)

    with runtime._lock:
        slot = runtime._slots["cutter_01"]
        slot.busy = True
        slot.assigned_task_id = "pkg_task_1"
        slot.assigned_project_name = "demo_project"
        slot.last_known_state = "state_2"
        runtime._tasks["pkg_task_1"] = PackageTask(
            task_id="pkg_task_1",
            project_name="demo_project",
            project_root=root_dir / "pools" / "work" / "fields" / "demo_project",
            original_task="test task",
            context_dir=package_pool / "context" / "demo_project",
            current_stage="cut",
        )

    result = runtime.handle_api_request("GET", "/api/status", None)

    assert result["pool"] == "package"
    assert result["signal_port"] == 19300
    assert result["is_running"] is False
    assert result["queue_count"] == 0
    assert len(result["slots"]) == 4

    slot_result = result["slots"][0]
    assert "slot_id" in slot_result
    assert "busy" in slot_result
    assert "assigned_task_id" in slot_result
    assert "assigned_project_name" in slot_result
    assert "current_state" in slot_result
    assert "current_stage" in slot_result

    cutter_slot = next(slot for slot in result["slots"] if slot["slot_id"] == "cutter_01")
    assert cutter_slot["busy"] is True
    assert cutter_slot["assigned_task_id"] == "pkg_task_1"
    assert cutter_slot["assigned_project_name"] == "demo_project"
    assert cutter_slot["current_state"] == "state_2"
    assert cutter_slot["current_stage"] == "cut"


def test_package_runtime_health_api_returns_ok_and_pool_info(tmp_path):
    """Test that package runtime exposes GET /api/health with standard schema."""
    runtime = PackageRuntime(root_dir=tmp_path, signal_port=19301)

    result = runtime.handle_api_request("GET", "/api/health", None)

    assert result["ok"] is True
    assert result["pool"] == "package"
    assert "uptime_seconds" in result
