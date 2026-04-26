"""Test auto-detection of worker slots from pool directory structure."""

from pathlib import Path
import pytest

from app.runtimes.work_runtime import WorkRuntime


def _make_tools(tmp_path: Path) -> Path:
    """Create minimal lifecycle tools directory."""
    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    for f in ["Online.bat", "StartWriting.bat", "Done.bat", "signal_bridge.py", "WORK_BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")
    return tools_dir


def _make_pool_structure(tmp_path: Path, slot_names: list[str]) -> None:
    """Create pool directory with given slot names, each containing workspace."""
    pool_dir = tmp_path / "pools" / "work"
    (pool_dir / "Queue").mkdir(parents=True, exist_ok=True)
    (pool_dir / "Outbox").mkdir(parents=True, exist_ok=True)
    for name in slot_names:
        slot_dir = pool_dir / name
        slot_dir.mkdir(parents=True, exist_ok=True)
        (slot_dir / "workspace").mkdir(parents=True, exist_ok=True)


def test_auto_detects_more_than_two_slots(tmp_path):
    """Test that _init_slots discovers all slot directories, not just worker_01/02."""
    # Create 4 worker slots
    _make_pool_structure(tmp_path, ["worker_01", "worker_02", "worker_03", "worker_04"])
    _make_tools(tmp_path)

    runtime = WorkRuntime(root_dir=tmp_path, signal_port=18771)

    # All 4 slots should be discovered
    assert len(runtime._slots) == 4
    slot_ids = sorted(runtime._slots.keys())
    assert slot_ids == ["worker_01", "worker_02", "worker_03", "worker_04"]


def test_auto_detects_non_consecutive_slots(tmp_path):
    """Test that slots with gaps (worker_01, worker_03) are all discovered."""
    _make_pool_structure(tmp_path, ["worker_01", "worker_03"])
    _make_tools(tmp_path)

    runtime = WorkRuntime(root_dir=tmp_path, signal_port=18772)

    assert len(runtime._slots) == 2
    slot_ids = sorted(runtime._slots.keys())
    assert slot_ids == ["worker_01", "worker_03"]


def test_auto_detects_only_directories_with_workspace(tmp_path):
    """Test that subdirectories without a workspace/ subdirectory are ignored."""
    pool_dir = tmp_path / "pools" / "work"
    (pool_dir / "Queue").mkdir(parents=True, exist_ok=True)
    (pool_dir / "Outbox").mkdir(parents=True, exist_ok=True)

    # worker_01 has workspace — should be detected
    (pool_dir / "worker_01" / "workspace").mkdir(parents=True, exist_ok=True)
    # worker_02 has NO workspace — should be ignored
    (pool_dir / "worker_02").mkdir(parents=True, exist_ok=True)
    # logs/ has no workspace — should be ignored
    (pool_dir / "logs").mkdir(parents=True, exist_ok=True)
    # Queue/ has no workspace — should be ignored
    (pool_dir / "Queue").mkdir(parents=True, exist_ok=True)

    _make_tools(tmp_path)
    runtime = WorkRuntime(root_dir=tmp_path, signal_port=18773)

    # Only worker_01 should be discovered
    assert len(runtime._slots) == 1
    assert "worker_01" in runtime._slots


def _make_task(queue_dir: Path, task_name: str, task_id: str) -> Path:
    task_file = queue_dir / task_name
    task_file.write_text(
        f"TASK_ID: {task_id}\nTIMEOUT: 60\n\ntest task\n",
        encoding="utf-8",
    )
    return task_file


def test_dispatch_uses_auto_detected_slots(tmp_path):
    """Test that dispatch_next uses all auto-detected slots, not just first two."""
    # Create 3 slots
    _make_pool_structure(tmp_path, ["worker_01", "worker_02", "worker_03"])
    queue_dir = tmp_path / "pools" / "work" / "Queue"

    _make_tools(tmp_path)
    runtime = WorkRuntime(root_dir=tmp_path, signal_port=18774)

    # First dispatch
    _make_task(queue_dir, "task_auto_001.txt", "t_auto_001")
    r1 = runtime.dispatch_next(dry_run=True)
    assert r1["dispatched"] is True
    assert r1["slot_id"] == "worker_01"

    # Second dispatch
    _make_task(queue_dir, "task_auto_002.txt", "t_auto_002")
    r2 = runtime.dispatch_next(dry_run=True)
    assert r2["dispatched"] is True
    assert r2["slot_id"] == "worker_02"

    # Third dispatch
    _make_task(queue_dir, "task_auto_003.txt", "t_auto_003")
    r3 = runtime.dispatch_next(dry_run=True)
    assert r3["dispatched"] is True
    assert r3["slot_id"] == "worker_03"

    # All 3 busy, fourth dispatch should fail
    _make_task(queue_dir, "task_auto_004.txt", "t_auto_004")
    r4 = runtime.dispatch_next(dry_run=True)
    assert r4["dispatched"] is False
    assert "No idle slot" in r4.get("error", "")

