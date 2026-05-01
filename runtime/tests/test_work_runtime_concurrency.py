"""Concurrency-safety tests for WorkRuntime slot state management."""

from pathlib import Path
import pytest
import threading
import time

from app.runtimes.work_runtime import WorkRuntime


def test_concurrent_dispatch_slot_reservation_race(tmp_path):
    """Test that concurrent dispatch_next calls don't double-assign the same slot."""
    # Setup
    queue_dir = tmp_path / "pools" / "work" / "Queue"
    queue_dir.mkdir(parents=True)
    worker1_dir = tmp_path / "pools" / "work" / "worker_01"
    worker1_dir.mkdir(parents=True)
    (worker1_dir / "workspace").mkdir()
    worker2_dir = tmp_path / "pools" / "work" / "worker_02"
    worker2_dir.mkdir(parents=True)
    (worker2_dir / "workspace").mkdir()
    (tmp_path / "pools" / "work" / "Outbox").mkdir(parents=True)

    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True)
    for f in ["Online.bat", "StartWriting.bat", "Done.bat", "signal_bridge.py", "WORK_BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")

    # Create two tasks
    (queue_dir / "task_001.txt").write_text("PROJECT_KEY: SignalBridge-v1-Build\n\nbody1", encoding="utf-8")
    (queue_dir / "task_002.txt").write_text("PROJECT_KEY: SignalBridge-v2-Build\n\nbody2", encoding="utf-8")

    runtime = WorkRuntime(root_dir=tmp_path, signal_port=18900)

    # Mock launch
    import app.shared.launch_manager as lm_module
    original_launch = lm_module.LaunchManager.launch

    def mock_launch(self, request, dry_run=True):
        # Simulate slow launch to increase race window
        time.sleep(0.01)
        return {"launched": True, "dry_run": True, "job_handle": None}

    lm_module.LaunchManager.launch = mock_launch

    results = []
    errors = []

    def dispatch_worker():
        try:
            result = runtime.dispatch_next(dry_run=True)
            results.append(result)
        except Exception as e:
            errors.append(e)

    try:
        # Launch two concurrent dispatches
        t1 = threading.Thread(target=dispatch_worker)
        t2 = threading.Thread(target=dispatch_worker)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Verify no errors
        assert len(errors) == 0, f"Dispatch errors: {errors}"

        # Verify both dispatched successfully
        assert len(results) == 2
        assert all(r["dispatched"] for r in results)

        # Verify different slots were assigned
        slot_ids = [r["slot_id"] for r in results]
        assert len(set(slot_ids)) == 2, f"Same slot assigned twice: {slot_ids}"

        # Verify both slots are busy
        slot1 = runtime.get_slot("worker_01")
        slot2 = runtime.get_slot("worker_02")
        assert slot1.busy and slot2.busy

    finally:
        lm_module.LaunchManager.launch = original_launch


def test_stale_signal_ignored_after_slot_reuse(tmp_path):
    """Test that stale terminal signals from previous tasks are ignored."""
    # Setup
    (tmp_path / "pools" / "work" / "Queue").mkdir(parents=True)
    worker1_dir = tmp_path / "pools" / "work" / "worker_01"
    worker1_dir.mkdir(parents=True)
    (worker1_dir / "workspace").mkdir()
    (tmp_path / "pools" / "work" / "worker_02" / "workspace").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "Outbox").mkdir(parents=True)

    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True)
    for f in ["Online.bat", "StartWriting.bat", "Done.bat"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")

    runtime = WorkRuntime(root_dir=tmp_path, signal_port=18901)

    # Simulate slot lifecycle: task_old -> done -> task_new
    slot = runtime.get_slot("worker_01")
    slot.busy = True
    slot.assigned_task_id = "t_old"
    slot.launch_result = {"launched": True, "job_handle": 0x1}

    # Release slot with done signal
    runtime.handle_signal({
        "agent_id": "worker_01",
        "task_id": "t_old",
        "signal": "done",
        "is_terminal": True,
    })

    assert slot.busy is False
    assert slot.assigned_task_id == ""

    # Reassign slot to new task
    slot.busy = True
    slot.assigned_task_id = "t_new"
    slot.launch_result = {"launched": True, "job_handle": 0x2}

    # Stale signal from old task arrives late
    runtime.handle_signal({
        "agent_id": "worker_01",
        "task_id": "t_old",  # Mismatched task_id
        "signal": "failed",
        "is_terminal": True,
    })

    # Slot should remain busy with new task
    assert slot.busy is True
    assert slot.assigned_task_id == "t_new"
    assert slot.launch_result["job_handle"] == 0x2


def test_concurrent_signal_and_timeout_race(tmp_path):
    """Test that concurrent terminal signal and timeout don't double-cleanup."""
    # Setup
    (tmp_path / "pools" / "work" / "Queue").mkdir(parents=True)
    worker1_dir = tmp_path / "pools" / "work" / "worker_01"
    worker1_dir.mkdir(parents=True)
    (worker1_dir / "workspace").mkdir()
    (tmp_path / "pools" / "work" / "worker_02" / "workspace").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "Outbox").mkdir(parents=True)

    runtime = WorkRuntime(root_dir=tmp_path, signal_port=18902)

    # Mock cleanup to track calls
    import app.shared.launch_manager as lm_module
    original_cleanup = lm_module.LaunchManager.cleanup_launch

    cleanup_calls = []

    def tracked_cleanup(self, launch_result):
        cleanup_calls.append(launch_result)
        return {"cleaned": True}

    lm_module.LaunchManager.cleanup_launch = tracked_cleanup

    try:
        # Setup slot with expired timeout
        slot = runtime.get_slot("worker_01")
        slot.busy = True
        slot.assigned_task_id = "t_race"
        slot.assigned_at_epoch = time.time() - 400  # Expired
        slot.timeout_seconds = 300
        slot.launch_result = {"launched": True, "job_handle": 0xBEEF}

        errors = []

        def send_done_signal():
            try:
                runtime.handle_signal({
                    "agent_id": "worker_01",
                    "task_id": "t_race",
                    "signal": "done",
                    "is_terminal": True,
                })
            except Exception as e:
                errors.append(e)

        def check_timeout():
            try:
                runtime.check_timeouts()
            except Exception as e:
                errors.append(e)

        # Race: signal and timeout check at same time
        t1 = threading.Thread(target=send_done_signal)
        t2 = threading.Thread(target=check_timeout)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Verify no errors
        assert len(errors) == 0, f"Race errors: {errors}"

        # Cleanup should be called exactly once (idempotent)
        # One path wins, the other sees job_handle=None and skips
        assert len(cleanup_calls) <= 1, f"cleanup_launch called {len(cleanup_calls)} times (should be ≤1)"

        # Slot should be released
        assert slot.busy is False

    finally:
        lm_module.LaunchManager.cleanup_launch = original_cleanup


def test_get_next_idle_slot_thread_safe(tmp_path):
    """Test that get_next_idle_slot returns consistent results under concurrent access."""
    # Setup
    (tmp_path / "pools" / "work" / "Queue").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "worker_01" / "workspace").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "worker_02" / "workspace").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "Outbox").mkdir(parents=True)

    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True)
    for f in ["Online.bat", "StartWriting.bat", "Done.bat", "signal_bridge.py", "WORK_BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")

    runtime = WorkRuntime(root_dir=tmp_path, signal_port=18903)

    results = []

    def get_slot_worker():
        slot = runtime.get_next_idle_slot()
        if slot:
            results.append(slot.slot_id)

    # Launch many concurrent get_next_idle_slot calls
    threads = [threading.Thread(target=get_slot_worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # All should return worker_01 (lowest idle slot)
    assert all(slot_id == "worker_01" for slot_id in results)
    assert len(results) == 10


def test_handle_signal_ignores_non_busy_slot(tmp_path):
    """Test that terminal signals are ignored if slot is not busy."""
    # Setup
    (tmp_path / "pools" / "work" / "Queue").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "worker_01" / "workspace").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "worker_02" / "workspace").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "Outbox").mkdir(parents=True)

    runtime = WorkRuntime(root_dir=tmp_path, signal_port=18904)

    # Mock cleanup to track calls
    import app.shared.launch_manager as lm_module
    original_cleanup = lm_module.LaunchManager.cleanup_launch

    cleanup_calls = []

    def tracked_cleanup(self, launch_result):
        cleanup_calls.append(launch_result)
        return {"cleaned": True}

    lm_module.LaunchManager.cleanup_launch = tracked_cleanup

    try:
        slot = runtime.get_slot("worker_01")
        # Slot is idle (busy=False)
        assert slot.busy is False

        # Send terminal signal
        runtime.handle_signal({
            "agent_id": "worker_01",
            "task_id": "t_phantom",
            "signal": "done",
            "is_terminal": True,
        })

        # Cleanup should NOT be called
        assert len(cleanup_calls) == 0, "cleanup_launch called for non-busy slot"

    finally:
        lm_module.LaunchManager.cleanup_launch = original_cleanup


def test_done_artifact_collection_does_not_block_other_lock_users(tmp_path):
    """Terminal done finalization should not hold the global lock during slow artifact collection."""
    (tmp_path / "pools" / "work" / "Queue").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "worker_01" / "workspace").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "worker_02" / "workspace").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "Outbox").mkdir(parents=True)

    runtime = WorkRuntime(root_dir=tmp_path, signal_port=18905)

    done_slot = runtime.get_slot("worker_01")
    done_slot.busy = True
    done_slot.assigned_task_id = "t_done"
    done_slot.launch_result = {"launched": True, "job_handle": 0xCAFE}

    started_collect = threading.Event()
    allow_collect_to_finish = threading.Event()
    idle_lookup_finished = threading.Event()
    idle_lookup_result = []

    def slow_collect(slot_id, task_id):
        started_collect.set()
        allow_collect_to_finish.wait(timeout=1)
        return {"collected": True, "task_id": task_id, "slot_id": slot_id}

    original_collect = runtime.collect_artifacts_to_outbox
    runtime.collect_artifacts_to_outbox = slow_collect

    try:
        def finalize_done():
            runtime.handle_signal({
                "agent_id": "worker_01",
                "task_id": "t_done",
                "signal": "done",
                "is_terminal": True,
            })

        finalize_thread = threading.Thread(target=finalize_done)
        finalize_thread.start()

        assert started_collect.wait(timeout=0.3), "artifact collection never started"

        def lookup_idle_slot():
            slot = runtime.get_next_idle_slot()
            idle_lookup_result.append(slot.slot_id if slot else None)
            idle_lookup_finished.set()

        lookup_thread = threading.Thread(target=lookup_idle_slot)
        lookup_thread.start()

        assert idle_lookup_finished.wait(timeout=0.1), (
            "get_next_idle_slot was blocked by done artifact collection holding the global lock"
        )
        assert idle_lookup_result == ["worker_02"]

        allow_collect_to_finish.set()
        finalize_thread.join(timeout=1)
        lookup_thread.join(timeout=1)
    finally:
        allow_collect_to_finish.set()
        runtime.collect_artifacts_to_outbox = original_collect


def test_terminal_finalization_claim_prevents_double_cleanup_race(tmp_path):
    """Once one terminal path starts finalizing a slot, competing terminal paths must back off."""
    (tmp_path / "pools" / "work" / "Queue").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "worker_01" / "workspace").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "worker_02" / "workspace").mkdir(parents=True)
    (tmp_path / "pools" / "work" / "Outbox").mkdir(parents=True)

    runtime = WorkRuntime(root_dir=tmp_path, signal_port=18906)

    slot = runtime.get_slot("worker_01")
    slot.busy = True
    slot.assigned_task_id = "t_race_claim"
    slot.assigned_at_epoch = time.time() - 400
    slot.timeout_seconds = 300
    slot.launch_result = {"launched": True, "job_handle": 0xBEEF}

    import app.shared.launch_manager as lm_module
    original_cleanup = lm_module.LaunchManager.cleanup_launch

    cleanup_calls = []
    first_cleanup_started = threading.Event()
    second_cleanup_started = threading.Event()
    allow_cleanup_to_finish = threading.Event()
    errors = []

    def blocking_cleanup(self, launch_result):
        cleanup_calls.append(launch_result)
        if len(cleanup_calls) == 1:
            first_cleanup_started.set()
        elif len(cleanup_calls) == 2:
            second_cleanup_started.set()
        allow_cleanup_to_finish.wait(timeout=1)
        return {"cleaned": True}

    lm_module.LaunchManager.cleanup_launch = blocking_cleanup

    try:
        def send_done_signal():
            try:
                runtime.handle_signal({
                    "agent_id": "worker_01",
                    "task_id": "t_race_claim",
                    "signal": "done",
                    "is_terminal": True,
                })
            except Exception as e:
                errors.append(e)

        def check_timeout():
            try:
                runtime.check_timeouts()
            except Exception as e:
                errors.append(e)

        signal_thread = threading.Thread(target=send_done_signal)
        signal_thread.start()

        assert first_cleanup_started.wait(timeout=0.3), "first terminal cleanup never started"

        timeout_thread = threading.Thread(target=check_timeout)
        timeout_thread.start()

        assert not second_cleanup_started.wait(timeout=0.1), (
            "competing terminal path entered cleanup instead of backing off"
        )

        allow_cleanup_to_finish.set()
        signal_thread.join(timeout=1)
        timeout_thread.join(timeout=1)

        assert len(errors) == 0, f"Unexpected race errors: {errors}"
        assert len(cleanup_calls) == 1, f"cleanup_launch called {len(cleanup_calls)} times"
    finally:
        allow_cleanup_to_finish.set()
        lm_module.LaunchManager.cleanup_launch = original_cleanup
