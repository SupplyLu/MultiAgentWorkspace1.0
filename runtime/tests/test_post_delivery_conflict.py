"""Regression tests for POST Runtime delivery conflict detection.

验证 POST 不再静默覆盖目标 Queue 中已有对象，冲突时标记项目为 blocked。
"""
from pathlib import Path

from app.runtimes.post_runtime import PostRuntime
from app.services.post_registry import PostRegistry


def test_delivery_blocks_when_target_queue_has_existing_directory(tmp_path: Path):
    """当目标 Queue 已有同名目录时，POST 不覆盖而标记 blocked。"""
    registry = PostRegistry(root_dir=tmp_path)
    registry.register_project(
        project_key="TestProject-v1-Build",
        from_pool="thinking",
        to_pool="construct",
        route=["thinking", "construct"],
    )

    # Thinking Outbox has valid payload
    outbox_dir = tmp_path / "pools" / "thinking" / "Outbox"
    payload_dir = outbox_dir / "TestProject-v1-Build"
    payload_dir.mkdir(parents=True, exist_ok=True)
    (payload_dir / "file.py").write_text("print('x')", encoding="utf-8")

    # Construct Queue already has the same name
    construct_queue = tmp_path / "pools" / "construct" / "Queue"
    construct_queue.mkdir(parents=True, exist_ok=True)
    existing = construct_queue / "TestProject-v1-Build"
    existing.mkdir(parents=True, exist_ok=True)
    (existing / "old.py").write_text("print('old')", encoding="utf-8")

    runtime = PostRuntime(root_dir=tmp_path, scan_interval_seconds=60)
    runtime.scan_once()

    project = registry.get_project("TestProject-v1-Build")
    assert project["status"] == "blocked"
    assert "already exists" in project["blocked_reason"]
    assert "Delivery conflict" in project["blocked_reason"]

    # Original directory is intact
    assert (existing / "old.py").exists(), "existing queue object must not be overwritten"


def test_delivery_blocks_when_target_queue_has_existing_file(tmp_path: Path):
    """当目标 Queue 已有同名文件时，POST 不覆盖而标记 blocked。"""
    registry = PostRegistry(root_dir=tmp_path)
    registry.register_project(
        project_key="TestProject-v1-Build",
        from_pool="thinking",
        to_pool="construct",
        route=["thinking", "construct"],
    )

    outbox_dir = tmp_path / "pools" / "thinking" / "Outbox"
    payload_dir = outbox_dir / "TestProject-v1-Build"
    payload_dir.mkdir(parents=True, exist_ok=True)
    (payload_dir / "new.py").write_text("print('new')", encoding="utf-8")

    construct_queue = tmp_path / "pools" / "construct" / "Queue"
    construct_queue.mkdir(parents=True, exist_ok=True)
    existing = construct_queue / "TestProject-v1-Build"
    existing.write_text("print('existing file')", encoding="utf-8")

    runtime = PostRuntime(root_dir=tmp_path, scan_interval_seconds=60)
    runtime.scan_once()

    project = registry.get_project("TestProject-v1-Build")
    assert project["status"] == "blocked"
    assert "already exists" in project["blocked_reason"]

    # Original file is intact
    assert existing.read_text(encoding="utf-8") == "print('existing file')"


def test_delivery_blocks_when_workorder_collides_in_work_queue(tmp_path: Path):
    """Gate accept 路径投递 workorder 时若目标 Queue 已有同名目录，也应 blocked。"""
    registry = PostRegistry(root_dir=tmp_path)
    registry.register_project(
        project_key="TestProject-v1-Build",
        from_pool="construct",
        to_pool="gate",
        route=["construct", "gate", "work"],
    )
    registry.update_project(
        "TestProject-v1-Build",
        {"cursor": 1, "current_pool": "gate", "next_pool": "work", "status": "in_progress"},
    )

    # Gate Outbox has valid workorders
    gate_outbox = tmp_path / "pools" / "gate" / "Outbox"
    workorder = gate_outbox / "TestProject-v1-Build-001"
    workorder.mkdir(parents=True, exist_ok=True)
    (workorder / "task.txt").write_text("task content", encoding="utf-8")

    # Work Queue already has the same workorder directory
    work_queue = tmp_path / "pools" / "work" / "Queue"
    work_queue.mkdir(parents=True, exist_ok=True)
    collision = work_queue / "TestProject-v1-Build-001"
    collision.mkdir(parents=True, exist_ok=True)
    (collision / "existing.txt").write_text("old content", encoding="utf-8")

    runtime = PostRuntime(root_dir=tmp_path, scan_interval_seconds=60)
    runtime.scan_once()

    project = registry.get_project("TestProject-v1-Build")
    assert project["status"] == "blocked"
    assert "already exists" in project["blocked_reason"]

    # Original workorder directory is intact
    assert (collision / "existing.txt").exists()
