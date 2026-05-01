"""Test PackageRuntime Queue atomic claim with .processing pattern.

验证 PackageRuntime 使用 .processing 文件重命名实现原子 claim，防止并发重复派发。
"""

from pathlib import Path
import threading

from app.runtimes.package_runtime import PackageRuntime


def test_package_dispatch_uses_processing_claim_to_prevent_duplicate_dispatch(tmp_path):
    """PackageRuntime should use .processing rename to atomically claim queue files."""
    package_pool = tmp_path / "pools" / "package"
    (package_pool / "Queue").mkdir(parents=True)
    (package_pool / "Outbox").mkdir(parents=True)
    (package_pool / "Rejectbox").mkdir(parents=True)
    (package_pool / "context").mkdir(parents=True)
    (package_pool / "Release").mkdir(parents=True)

    # Create two cutter slots
    for i in [1, 2]:
        slot_dir = package_pool / f"cutter_0{i}"
        slot_dir.mkdir(parents=True)
        (slot_dir / "workspace").mkdir()

    # Create a single task file
    task_file = package_pool / "Queue" / "task_pkg_001.txt"
    task_file.write_text(
        "FROM: work\nTO: package\nTASK_ID: pkg_001\nPROJECT_NAME: demo_project\n\n---\nPackage this project",
        encoding="utf-8"
    )

    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True)
    for f in ["Online.bat", "StartCut.bat", "StartTest.bat", "StartRelease.bat",
              "StartCompletePlayer.bat", "Reject.bat", "signal_bridge.py", "BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")

    runtime = PackageRuntime(root_dir=tmp_path, signal_port=19300)

    # Simulate concurrent dispatch from two threads
    results = []
    errors = []

    def dispatch_task():
        try:
            result = runtime.dispatch_next(dry_run=True)
            results.append(result)
        except Exception as exc:
            errors.append(exc)

    t1 = threading.Thread(target=dispatch_task)
    t2 = threading.Thread(target=dispatch_task)
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert errors == []
    assert len(results) == 2

    # Only ONE should succeed (atomic claim via .processing)
    dispatched_count = sum(1 for r in results if r.get("dispatched"))
    assert dispatched_count == 1, f"Expected 1 dispatch, got {dispatched_count}. Both threads claimed the same file!"

    # The other should fail with "No tasks in queue"
    failed_count = sum(1 for r in results if not r.get("dispatched"))
    assert failed_count == 1

    # No .processing file should remain in Queue
    queue_dir = package_pool / "Queue"
    processing_files = list(queue_dir.glob("*.processing"))
    assert len(processing_files) == 0, "Leftover .processing file indicates incomplete cleanup"
