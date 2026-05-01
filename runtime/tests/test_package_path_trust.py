"""Test PackageRuntime path trust fixes (Group B security hardening).

验证 PackageRuntime 不再信任外部传入的 PROJECT_ROOT，而是从项目标识派生内部路径。
"""

from pathlib import Path

from app.runtimes.package_runtime import PackageRuntime


def test_create_task_context_does_not_trust_external_project_root(tmp_path):
    """PackageRuntime must derive project_root internally instead of trusting PROJECT_ROOT header."""
    package_pool = tmp_path / "pools" / "package"
    (package_pool / "Queue").mkdir(parents=True)
    (package_pool / "Outbox").mkdir(parents=True)
    (package_pool / "Rejectbox").mkdir(parents=True)
    (package_pool / "context").mkdir(parents=True)
    (package_pool / "Release").mkdir(parents=True)

    cutter_dir = package_pool / "cutter_01"
    cutter_dir.mkdir(parents=True)
    (cutter_dir / "workspace").mkdir()

    runtime = PackageRuntime(root_dir=tmp_path, signal_port=19350)

    task_file = package_pool / "Queue" / "task_pkg_001.txt"
    task_data = {
        "headers": {
            "TASK_ID": "pkg_001",
            "PROJECT_NAME": "DemoProject-v1-Build",
            "PROJECT_ROOT": "/etc/passwd",
        },
        "content": "package this project",
    }

    task = runtime._create_task_context(task_data, task_file)

    expected_root = tmp_path / "pools" / "work" / "fields" / "DemoProject-v1-Build"
    assert task.project_root == expected_root
    assert task.project_root != Path("/etc/passwd")

    context_input = (task.context_dir / "input.txt").read_text(encoding="utf-8")
    assert "PROJECT_ROOT: /etc/passwd" not in context_input
    assert f"PROJECT_ROOT: {expected_root}" in context_input
