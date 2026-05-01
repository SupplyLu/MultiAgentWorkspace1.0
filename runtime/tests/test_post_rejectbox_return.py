import json
from pathlib import Path

from app.runtimes.post_runtime import PostRuntime
from app.services.post_registry import PostRegistry


def test_post_runtime_returns_gate_rejectbox_to_construct_queue(tmp_path: Path):
    gate_rejectbox = tmp_path / "pools" / "gate" / "Rejectbox"
    construct_queue = tmp_path / "pools" / "construct" / "Queue"
    gate_rejectbox.mkdir(parents=True)
    construct_queue.mkdir(parents=True)

    rejected_dir = gate_rejectbox / "Demo-v1-Build"
    rejected_dir.mkdir()
    (rejected_dir / "task_001.txt").write_text("rejected payload", encoding="utf-8")

    registry = PostRegistry(root_dir=tmp_path)
    registry.register_project(
        project_key="Demo-v1-Build",
        from_pool="task",
        to_pool="work",
        route=["task", "thinking", "construct", "gate", "work"],
    )
    registry.update_project(
        "Demo-v1-Build",
        {
            "cursor": 3,
            "current_pool": "gate",
            "next_pool": "work",
            "status": "in_progress",
        },
    )

    runtime = PostRuntime(root_dir=tmp_path)
    runtime.scan_once()

    returned_dir = construct_queue / "Demo-v1-Build"
    assert returned_dir.exists()
    assert (returned_dir / "task_001.txt").read_text(encoding="utf-8") == "rejected payload"

    project = registry.get_project("Demo-v1-Build")
    assert project["cursor"] == 2
    assert project["current_pool"] == "construct"
    assert project["next_pool"] == "gate"
    assert project["status"] == "in_progress"

    assert not rejected_dir.exists()
