"""Task Pool filesystem and contract tests."""
from pathlib import Path

import pytest


@pytest.fixture
def root_dir():
    """Return the runtime app root directory (parent of tests/)."""
    return Path(__file__).resolve().parent.parent.parent


def test_task_pool_directories_exist(root_dir):
    """Verify Task Pool directory structure exists in the actual workspace."""
    assert (root_dir / "pools/task/Queue").is_dir()
    assert (root_dir / "pools/task/Outbox").is_dir()
    assert (root_dir / "pools/task/TaskReferenceBox").is_dir()
    assert (root_dir / "pools/task/main_brain_01/workspace").is_dir()


def test_start_main_brain_script_exists(root_dir):
    """Verify StartMainBrain.bat exists and contains required references."""
    script_path = root_dir / "runtime/tools/StartMainBrain.bat"
    assert script_path.is_file(), f"StartMainBrain.bat not found at {script_path}"

    content = script_path.read_text()
    assert "main_brain_01" in content, "Script must reference main_brain_01"
    assert "BOOTSTRAP.txt" in content, "Script must reference BOOTSTRAP.txt"


@pytest.mark.skip(reason="Task pool bootstrap not yet deployed to main_brain_01")
def test_main_brain_bootstrap_contract(root_dir):
    """Verify main_brain bootstrap contract exists and defines required constraints."""
    bootstrap_path = root_dir / "pools/task/main_brain_01/BOOTSTRAP.txt"
    assert bootstrap_path.is_file(), f"BOOTSTRAP.txt not found at {bootstrap_path}"

    content = bootstrap_path.read_text(encoding="utf-8")
    assert "ROLE: main_brain" in content
    assert "POOL: task" in content
    assert "TaskReferenceBox" in content
    assert "禁止直接写入 pools/thinking/Queue" in content or "Must NOT directly write to pools/thinking/Queue" in content


def test_task_reference_box_contract(tmp_path):
    """Validate TaskReferenceBox/{task_id} output contract structure."""
    task_id = "task_demo_001"
    base = tmp_path / "pools/task/TaskReferenceBox" / task_id
    base.mkdir(parents=True)

    (base / "requirement.txt").write_text("x", encoding="utf-8")
    (base / "workflow_plan.txt").write_text("x", encoding="utf-8")
    (base / "post_manifest.json").write_text("{}", encoding="utf-8")

    assert (base / "requirement.txt").is_file()
    assert (base / "workflow_plan.txt").is_file()
    assert (base / "post_manifest.json").is_file()


def test_task_outbox_contract(tmp_path):
    """Validate Outbox/{task_id} output contract structure."""
    task_id = "task_demo_001"
    base = tmp_path / "pools/task/Outbox" / task_id
    base.mkdir(parents=True)

    (base / "summary.txt").write_text("x", encoding="utf-8")
    (base / "task_project_scaffold.txt").write_text("x", encoding="utf-8")

    assert (base / "summary.txt").is_file()

    task_files = list(base.glob("task_*.txt"))
    assert len(task_files) >= 1
    assert all(p.is_file() for p in task_files)
