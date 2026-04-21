from pathlib import Path


def test_verify_worker_lifecycle_uses_task_prefixed_filename():
    script_path = Path("C:/Users/lenovo/Desktop/MultiAgentWorkspace1.0/runtime/verify_worker_lifecycle.py")
    content = script_path.read_text(encoding="utf-8")

    assert 'task_file = queue_dir / "task_lifecycle_check.txt"' in content
    assert 'task_file = queue_dir / "lifecycle_check.txt"' not in content

def test_verify_worker_lifecycle_uses_unique_task_id_per_run():
    script_path = Path("C:/Users/lenovo/Desktop/MultiAgentWorkspace1.0/runtime/verify_worker_lifecycle.py")
    content = script_path.read_text(encoding="utf-8")

    assert "from datetime import datetime, timezone" in content
    assert 'task_id = f"t_lifecycle_{datetime.now(timezone.utc).strftime(' in content
    assert '"TASK_ID: t_lifecycle_001\n"' not in content
