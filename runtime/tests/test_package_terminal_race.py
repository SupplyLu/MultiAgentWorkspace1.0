"""Test PackageRuntime terminal signal race conditions (Group B security hardening).

验证 done/denied 信号竞态时，只有一条终态路径能赢得清理权。
"""

from pathlib import Path
import threading
import time

from app.runtimes.package_runtime import PackageDeniedError, PackageRuntime, PackageTask


def test_package_done_denied_race_only_one_wins(tmp_path):
    """When done and denied arrive concurrently, only one terminal path should win."""
    package_pool = tmp_path / "pools" / "package"
    (package_pool / "Queue").mkdir(parents=True)
    (package_pool / "Outbox").mkdir(parents=True)
    (package_pool / "Rejectbox").mkdir(parents=True)
    (package_pool / "context").mkdir(parents=True)
    (package_pool / "Release").mkdir(parents=True)

    slot_dir = package_pool / "cutter_01"
    slot_dir.mkdir(parents=True)
    (slot_dir / "workspace").mkdir()

    runtime = PackageRuntime(root_dir=tmp_path, signal_port=19300)

    task = PackageTask(
        task_id="pkg_001",
        project_name="demo_project",
        project_root=tmp_path / "pools" / "work" / "fields" / "demo_project",
        original_task="package demo project",
        context_dir=package_pool / "context" / "demo_project",
        current_stage="cut",
    )
    runtime._tasks[task.task_id] = task

    slot = runtime.get_slot("cutter_01")
    slot.busy = True
    slot.assigned_task_id = task.task_id
    slot.assigned_project_name = task.project_name
    slot.assigned_at_epoch = time.time()
    slot.launch_result = {"launched": True, "job_handle": None}

    release_project_dir = runtime._release_dir / task.project_name
    release_project_dir.mkdir(parents=True, exist_ok=True)
    (release_project_dir / "artifact.txt").write_text("release artifact", encoding="utf-8")

    done_entered = threading.Event()
    denied_entered = threading.Event()
    proceed = threading.Event()

    original_collect = runtime._collect_release_to_outbox
    original_write = runtime._write_rejectbox_marker

    def slow_collect(task_arg):
        done_entered.set()
        proceed.wait(timeout=1)
        return original_collect(task_arg)

    def slow_write(task_arg, stage):
        denied_entered.set()
        proceed.wait(timeout=1)
        return original_write(task_arg, stage)

    runtime._collect_release_to_outbox = slow_collect
    runtime._write_rejectbox_marker = slow_write

    try:
        errors: list[tuple[str, Exception]] = []

        def send_done():
            try:
                runtime.handle_signal({
                    "agent_id": "cutter_01",
                    "task_id": task.task_id,
                    "signal": "done",
                    "to_state": "state_done",
                })
            except Exception as exc:  # pragma: no cover - defensive capture for thread failures
                errors.append(("done", exc))

        def send_denied():
            try:
                runtime.handle_signal({
                    "agent_id": "cutter_01",
                    "task_id": task.task_id,
                    "signal": "denied",
                    "to_state": "state_denied",
                })
            except PackageDeniedError:
                pass
            except Exception as exc:  # pragma: no cover - defensive capture for thread failures
                errors.append(("denied", exc))

        done_thread = threading.Thread(target=send_done)
        denied_thread = threading.Thread(target=send_denied)
        done_thread.start()
        denied_thread.start()

        assert done_entered.wait(timeout=1) or denied_entered.wait(timeout=1), "no terminal path reached its gate"
        proceed.set()

        done_thread.join(timeout=1)
        denied_thread.join(timeout=1)

        assert errors == []
        assert done_entered.is_set() != denied_entered.is_set(), "exactly one terminal path should win"

        outbox_dir = runtime._outbox_dir / task.task_id
        rejectbox_file = runtime._rejectbox_dir / f"{task.project_name}_denied.txt"

        assert outbox_dir.exists() != rejectbox_file.exists(), (
            "Exactly one terminal path should win; done and denied must not both commit side effects"
        )
    finally:
        runtime._collect_release_to_outbox = original_collect
        runtime._write_rejectbox_marker = original_write
