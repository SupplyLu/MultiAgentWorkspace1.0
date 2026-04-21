from pathlib import Path

from app.runtimes.post_runtime import PostRuntime
from app.services.post_registry import PostRegistry


def test_scan_marks_branch_done_when_txt_exists_in_outbox(tmp_path: Path):
    registry = PostRegistry(root_dir=tmp_path)
    registry.register_batch(
        batch_id="feat_001",
        name="login feature",
        from_pool="task",
        to_pool="construct",
        branches=[
            {
                "branch_id": "feat_001_b1",
                "feature_id": "login_ui",
                "task_body": "task one",
                "outbox_path": str(tmp_path / "pools" / "thinking" / "Outbox" / "feat_001_b1"),
            }
        ],
    )
    outbox_dir = tmp_path / "pools" / "thinking" / "Outbox" / "feat_001_b1"
    outbox_dir.mkdir(parents=True, exist_ok=True)
    (outbox_dir / "thinking_result.txt").write_text("done", encoding="utf-8")

    runtime = PostRuntime(root_dir=tmp_path, scan_interval_seconds=60)
    runtime.scan_once()

    branch = registry.get_branches("feat_001")[0]
    assert branch["status"] == "done"


def test_scan_delivers_completed_batch_to_construct_queue(tmp_path: Path):
    registry = PostRegistry(root_dir=tmp_path)
    construct_queue = tmp_path / "pools" / "construct" / "Queue"
    branch_outbox = tmp_path / "pools" / "thinking" / "Outbox" / "feat_001_b1"
    branch_outbox.mkdir(parents=True, exist_ok=True)
    (branch_outbox / "thinking_result.txt").write_text("done", encoding="utf-8")

    registry.register_batch(
        batch_id="feat_001",
        name="login feature",
        from_pool="thinking",
        to_pool="construct",
        branches=[
            {
                "branch_id": "feat_001_b1",
                "feature_id": "login_ui",
                "task_body": "FROM: thinking\nTO: construct\nTASK_ID: feat_001_b1",
                "outbox_path": str(branch_outbox),
            }
        ],
    )

    runtime = PostRuntime(root_dir=tmp_path, scan_interval_seconds=60)
    runtime.scan_once()

    delivered_files = list(construct_queue.glob("*.txt"))
    assert len(delivered_files) == 1
    assert registry.get_batch("feat_001")["status"] == "delivered"
    assert registry.list_transfers(batch_id="feat_001")[0]["status"] == "delivered"


def test_scan_marks_batch_waiting_when_dependency_unsatisfied(tmp_path: Path):
    registry = PostRegistry(root_dir=tmp_path)
    outbox = tmp_path / "pools" / "thinking" / "Outbox" / "feat_002_b1"
    outbox.mkdir(parents=True, exist_ok=True)
    (outbox / "thinking_result.txt").write_text("done", encoding="utf-8")
    registry.register_batch(
        batch_id="feat_002",
        name="construct after prereq",
        from_pool="thinking",
        to_pool="construct",
        branches=[
            {
                "branch_id": "feat_002_b1",
                "feature_id": "construct_step",
                "task_body": "task",
                "outbox_path": str(outbox),
            }
        ],
    )
    registry.add_dependency(
        source_batch_id="feat_001",
        target_batch_id="feat_002",
        rule="after_delivered",
    )

    runtime = PostRuntime(root_dir=tmp_path, scan_interval_seconds=60)
    runtime.scan_once()

    assert registry.get_batch("feat_002")["status"] == "waiting"


def test_scan_skips_blocked_batch(tmp_path: Path):
    registry = PostRegistry(root_dir=tmp_path)
    outbox = tmp_path / "pools" / "thinking" / "Outbox" / "feat_003_b1"
    outbox.mkdir(parents=True, exist_ok=True)
    (outbox / "thinking_result.txt").write_text("done", encoding="utf-8")
    registry.register_batch(
        batch_id="feat_003",
        name="blocked feature",
        from_pool="thinking",
        to_pool="construct",
        branches=[
            {
                "branch_id": "feat_003_b1",
                "feature_id": "blocked_step",
                "task_body": "task",
                "outbox_path": str(outbox),
            }
        ],
    )
    registry.update_batch("feat_003", {"status": "blocked"})

    runtime = PostRuntime(root_dir=tmp_path, scan_interval_seconds=60)
    runtime.scan_once()

    assert not list((tmp_path / "pools" / "construct" / "Queue").glob("*.txt"))


def test_build_runtime_uses_root_dir_and_default_scan_interval(tmp_path):
    from app.main_post import build_runtime
    runtime = build_runtime(str(tmp_path))

    assert runtime.root_dir == tmp_path
    assert runtime.scan_interval_seconds == 60


def test_scan_marks_branch_done_when_directory_exists_in_outbox(tmp_path: Path):
    """Test that a branch is marked done when outbox contains a directory (not just txt files)."""
    registry = PostRegistry(root_dir=tmp_path)
    registry.register_batch(
        batch_id="pid_001",
        name="PID demo project",
        from_pool="thinking",
        to_pool="construct",
        branches=[
            {
                "branch_id": "pid_001_b1",
                "feature_id": "pid_simulink",
                "task_body": "Build PID controller demo",
                "outbox_path": str(tmp_path / "pools" / "thinking" / "Outbox" / "pid_001_b1"),
            }
        ],
    )
    outbox_dir = tmp_path / "pools" / "thinking" / "Outbox" / "pid_001_b1"
    outbox_dir.mkdir(parents=True, exist_ok=True)

    # Create a directory payload instead of txt file
    project_dir = outbox_dir / "pid_simulink_project"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "main.py").write_text("# PID controller", encoding="utf-8")
    (project_dir / "README.md").write_text("# Demo", encoding="utf-8")

    runtime = PostRuntime(root_dir=tmp_path, scan_interval_seconds=60)
    runtime.scan_once()

    branch = registry.get_branches("pid_001")[0]
    assert branch["status"] == "done"


def test_scan_delivers_directory_payload_to_construct_queue(tmp_path: Path):
    """Test that directory payloads are copied to construct queue."""
    registry = PostRegistry(root_dir=tmp_path)
    construct_queue = tmp_path / "pools" / "construct" / "Queue"
    branch_outbox = tmp_path / "pools" / "thinking" / "Outbox" / "pid_002_b1"
    branch_outbox.mkdir(parents=True, exist_ok=True)

    # Create directory payload
    project_dir = branch_outbox / "pid_demo"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "controller.py").write_text("# Controller", encoding="utf-8")
    (project_dir / "plant.py").write_text("# Plant", encoding="utf-8")

    registry.register_batch(
        batch_id="pid_002",
        name="PID feature",
        from_pool="thinking",
        to_pool="construct",
        branches=[
            {
                "branch_id": "pid_002_b1",
                "feature_id": "pid_controller",
                "task_body": "FROM: thinking\nTO: construct\nTASK_ID: pid_002_b1",
                "outbox_path": str(branch_outbox),
            }
        ],
    )

    runtime = PostRuntime(root_dir=tmp_path, scan_interval_seconds=60)
    runtime.scan_once()

    # Check directory was delivered
    delivered_dir = construct_queue / "pid_002_b1_pid_demo"
    assert delivered_dir.exists()
    assert delivered_dir.is_dir()
    assert (delivered_dir / "controller.py").exists()
    assert (delivered_dir / "plant.py").exists()

    assert registry.get_batch("pid_002")["status"] == "delivered"
    assert registry.list_transfers(batch_id="pid_002")[0]["status"] == "delivered"
