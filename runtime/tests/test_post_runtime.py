from pathlib import Path

from app.runtimes.post_runtime import PostRuntime
from app.services.post_registry import PostRegistry


def test_scan_blocks_project_when_txt_payload_is_present_instead_of_directory(tmp_path: Path):
    registry = PostRegistry(root_dir=tmp_path)
    registry.register_project(
        project_key="SignalOfBridge-v1-Build",
        from_pool="task",
        to_pool="thinking",
        route=["task", "thinking"],
    )

    outbox_dir = tmp_path / "pools" / "task" / "Outbox"
    outbox_dir.mkdir(parents=True, exist_ok=True)
    (outbox_dir / "SignalOfBridge-v1-Build.txt").write_text("not a directory", encoding="utf-8")

    runtime = PostRuntime(root_dir=tmp_path, scan_interval_seconds=60)
    runtime.scan_once()

    project = registry.get_project("SignalOfBridge-v1-Build")
    assert project["status"] == "blocked"
    assert project["blocked_reason"]
    assert "txt" in project["blocked_reason"].lower()


def test_scan_blocks_project_when_directory_name_does_not_match_project_key(tmp_path: Path):
    registry = PostRegistry(root_dir=tmp_path)
    registry.register_project(
        project_key="SignalOfBridge-v1-Build",
        from_pool="task",
        to_pool="thinking",
        route=["task", "thinking"],
    )

    outbox_dir = tmp_path / "pools" / "task" / "Outbox"
    payload_dir = outbox_dir / "SignalOfBridge-v1-Build-conflict"
    payload_dir.mkdir(parents=True, exist_ok=True)
    (payload_dir / "main.py").write_text("print('x')", encoding="utf-8")

    runtime = PostRuntime(root_dir=tmp_path, scan_interval_seconds=60)
    runtime.scan_once()

    project = registry.get_project("SignalOfBridge-v1-Build")
    assert project["status"] == "blocked"
    assert project["blocked_reason"]
    assert "match" in project["blocked_reason"].lower()


def test_scan_delivers_project_directory_to_next_queue(tmp_path: Path):
    registry = PostRegistry(root_dir=tmp_path)
    registry.register_project(
        project_key="SignalOfBridge-v1-Build",
        from_pool="thinking",
        to_pool="construct",
        route=["thinking", "construct"],
    )

    outbox_dir = tmp_path / "pools" / "thinking" / "Outbox"
    payload_dir = outbox_dir / "SignalOfBridge-v1-Build"
    payload_dir.mkdir(parents=True, exist_ok=True)
    (payload_dir / "controller.py").write_text("print('controller')", encoding="utf-8")

    runtime = PostRuntime(root_dir=tmp_path, scan_interval_seconds=60)
    runtime.scan_once()

    delivered_dir = tmp_path / "pools" / "construct" / "Queue" / "SignalOfBridge-v1-Build"
    assert delivered_dir.exists()
    assert delivered_dir.is_dir()
    assert (delivered_dir / "controller.py").exists()

    project = registry.get_project("SignalOfBridge-v1-Build")
    assert project["status"] == "delivered"

    deliveries = registry.list_deliveries(project_key="SignalOfBridge-v1-Build")
    assert len(deliveries) == 1
    assert deliveries[0]["status"] == "delivered"
    assert deliveries[0]["payload_name"] == "SignalOfBridge-v1-Build"
    assert deliveries[0]["delivery_address"] == str(delivered_dir)


def test_scan_requeues_gate_rejectbox_project_directory_to_construct_queue(tmp_path: Path):
    registry = PostRegistry(root_dir=tmp_path)
    registry.register_project(
        project_key="SignalOfBridge-v1-Build",
        from_pool="construct",
        to_pool="gate",
        route=["construct", "gate", "work"],
    )
    registry.update_project(
        "SignalOfBridge-v1-Build",
        {"cursor": 1, "current_pool": "gate", "next_pool": "work", "status": "in_progress"},
    )

    rejectbox_dir = tmp_path / "pools" / "gate" / "Rejectbox"
    payload_dir = rejectbox_dir / "SignalOfBridge-v1-Build"
    payload_dir.mkdir(parents=True, exist_ok=True)
    (payload_dir / "reject_note.txt").write_text("needs fixes", encoding="utf-8")

    runtime = PostRuntime(root_dir=tmp_path, scan_interval_seconds=60)
    runtime.scan_once()

    requeued_dir = tmp_path / "pools" / "construct" / "Queue" / "SignalOfBridge-v1-Build"
    assert requeued_dir.exists()
    assert (requeued_dir / "reject_note.txt").exists()

    project = registry.get_project("SignalOfBridge-v1-Build")
    assert project["status"] == "in_progress"
    assert project["current_pool"] == "construct"
    assert project["next_pool"] == "gate"

    deliveries = registry.list_deliveries(project_key="SignalOfBridge-v1-Build")
    assert len(deliveries) == 1
    assert deliveries[0]["to_pool"] == "construct"
    assert deliveries[0]["payload_name"] == "SignalOfBridge-v1-Build"


def test_scan_delivers_atomic_workorders_from_gate_outbox(tmp_path: Path):
    registry = PostRegistry(root_dir=tmp_path)
    registry.register_project(
        project_key="SignalOfBridge-v1-Build",
        from_pool="construct",
        to_pool="gate",
        route=["construct", "gate", "work"],
    )
    registry.update_project(
        "SignalOfBridge-v1-Build",
        {"cursor": 1, "current_pool": "gate", "next_pool": "work", "status": "in_progress"},
    )

    outbox_dir = tmp_path / "pools" / "gate" / "Outbox"
    workorder_1 = outbox_dir / "SignalOfBridge-v1-Build-UIupgrade001"
    workorder_2 = outbox_dir / "SignalOfBridge-v1-Build-BackendPatch002"
    workorder_1.mkdir(parents=True, exist_ok=True)
    workorder_2.mkdir(parents=True, exist_ok=True)
    (workorder_1 / "task.txt").write_text("task 1", encoding="utf-8")
    (workorder_2 / "task.txt").write_text("task 2", encoding="utf-8")

    runtime = PostRuntime(root_dir=tmp_path, scan_interval_seconds=60)
    runtime.scan_once()

    delivered_1 = tmp_path / "pools" / "work" / "Queue" / "SignalOfBridge-v1-Build-UIupgrade001"
    delivered_2 = tmp_path / "pools" / "work" / "Queue" / "SignalOfBridge-v1-Build-BackendPatch002"
    assert delivered_1.exists()
    assert delivered_2.exists()
    assert (delivered_1 / "task.txt").exists()
    assert (delivered_2 / "task.txt").exists()

    project = registry.get_project("SignalOfBridge-v1-Build")
    assert project["status"] == "delivered"

    deliveries = registry.list_deliveries(project_key="SignalOfBridge-v1-Build")
    assert len(deliveries) == 2
    assert {delivery["payload_name"] for delivery in deliveries} == {
        "SignalOfBridge-v1-Build-UIupgrade001",
        "SignalOfBridge-v1-Build-BackendPatch002",
    }


def test_scan_cleans_gate_reject_payload_and_does_not_retrigger_after_requeue(tmp_path: Path):
    registry = PostRegistry(root_dir=tmp_path)
    registry.register_project(
        project_key="SignalOfBridge-v1-Build",
        from_pool="construct",
        to_pool="gate",
        route=["construct", "gate", "work"],
    )
    registry.update_project(
        "SignalOfBridge-v1-Build",
        {"cursor": 1, "current_pool": "gate", "next_pool": "work", "status": "in_progress"},
    )

    rejectbox_dir = tmp_path / "pools" / "gate" / "Rejectbox"
    payload_dir = rejectbox_dir / "SignalOfBridge-v1-Build"
    payload_dir.mkdir(parents=True, exist_ok=True)
    (payload_dir / "reject_note.txt").write_text("needs fixes", encoding="utf-8")

    runtime = PostRuntime(root_dir=tmp_path, scan_interval_seconds=60)
    runtime.scan_once()

    requeued_dir = tmp_path / "pools" / "construct" / "Queue" / "SignalOfBridge-v1-Build"
    assert requeued_dir.exists()
    assert not payload_dir.exists()

    project = registry.get_project("SignalOfBridge-v1-Build")
    assert project["current_pool"] == "construct"
    assert project["next_pool"] == "gate"

    runtime.scan_once()

    project_after_second_scan = registry.get_project("SignalOfBridge-v1-Build")
    assert project_after_second_scan["current_pool"] == "construct"
    assert project_after_second_scan["next_pool"] == "gate"

    deliveries = registry.list_deliveries(project_key="SignalOfBridge-v1-Build")
    assert len(deliveries) == 1


def test_scan_ignores_unrelated_unknown_directory_when_valid_project_payload_exists(tmp_path: Path):
    registry = PostRegistry(root_dir=tmp_path)
    registry.register_project(
        project_key="SignalOfBridge-v1-Build",
        from_pool="thinking",
        to_pool="construct",
        route=["thinking", "construct"],
    )

    outbox_dir = tmp_path / "pools" / "thinking" / "Outbox"
    valid_payload = outbox_dir / "SignalOfBridge-v1-Build"
    valid_payload.mkdir(parents=True, exist_ok=True)
    (valid_payload / "controller.py").write_text("print('controller')", encoding="utf-8")

    unrelated_payload = outbox_dir / "UnrelatedProject-v1-Plan"
    unrelated_payload.mkdir(parents=True, exist_ok=True)
    (unrelated_payload / "note.txt").write_text("ignore", encoding="utf-8")

    runtime = PostRuntime(root_dir=tmp_path, scan_interval_seconds=60)
    runtime.scan_once()

    delivered_dir = tmp_path / "pools" / "construct" / "Queue" / "SignalOfBridge-v1-Build"
    assert delivered_dir.exists()
    assert (delivered_dir / "controller.py").exists()

    project = registry.get_project("SignalOfBridge-v1-Build")
    assert project["status"] == "delivered"

    deliveries = registry.list_deliveries(project_key="SignalOfBridge-v1-Build")
    assert len(deliveries) == 1
    assert deliveries[0]["payload_name"] == "SignalOfBridge-v1-Build"


def test_build_runtime_uses_root_dir_and_default_scan_interval(tmp_path: Path):
    from app.main_post import build_runtime

    runtime = build_runtime(str(tmp_path))

    assert runtime.root_dir == tmp_path
    assert runtime.scan_interval_seconds == 60


def test_scan_ignores_skipped_projects(tmp_path: Path):
    registry = PostRegistry(root_dir=tmp_path)
    registry.register_project(
        project_key="SignalOfBridge-v1-Build",
        from_pool="thinking",
        to_pool="construct",
        route=["thinking", "construct"],
    )
    registry.update_project(
        "SignalOfBridge-v1-Build",
        {"status": "skipped", "skipped_reason": "operator skipped"},
    )

    outbox_dir = tmp_path / "pools" / "thinking" / "Outbox"
    payload_dir = outbox_dir / "SignalOfBridge-v1-Build"
    payload_dir.mkdir(parents=True, exist_ok=True)
    (payload_dir / "controller.py").write_text("print('controller')", encoding="utf-8")

    runtime = PostRuntime(root_dir=tmp_path, scan_interval_seconds=60)
    runtime.scan_once()

    delivered_dir = tmp_path / "pools" / "construct" / "Queue" / "SignalOfBridge-v1-Build"
    assert not delivered_dir.exists()

    project = registry.get_project("SignalOfBridge-v1-Build")
    assert project["status"] == "skipped"

    deliveries = registry.list_deliveries(project_key="SignalOfBridge-v1-Build")
    assert len(deliveries) == 0
