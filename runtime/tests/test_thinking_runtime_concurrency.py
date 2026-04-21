"""Concurrency-safety tests for ThinkingRuntime slot state management.

复制自 test_work_runtime_concurrency.py，针对 Thinking Pool 特化：
- 验证并发派发不会重复分配槽位
- 验证 stale signal 被忽略
- 验证 signal 与 timeout 并发时无双重 cleanup
"""

from pathlib import Path
import pytest
import threading
import time

from app.runtimes.thinking_runtime import ThinkingRuntime


def test_concurrent_dispatch_slot_reservation_race(tmp_path):
    """Test that concurrent dispatch_next calls don't double-assign the same slot."""
    # Setup
    queue_dir = tmp_path / "pools" / "thinking" / "Queue"
    queue_dir.mkdir(parents=True)
    thinking_pool = tmp_path / "pools" / "thinking"

    for i in [1, 2]:
        slot_dir = thinking_pool / f"sub_brain_0{i}"
        slot_dir.mkdir(parents=True)
        (slot_dir / "workspace").mkdir()

    (thinking_pool / "Outbox").mkdir(parents=True)

    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True)
    for f in ["Online.bat", "StartThinking.bat", "StartSummarizing.bat", "Done.bat", "signal_bridge.py", "BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")

    # Create two tasks
    (queue_dir / "task_001.txt").write_text("TASK_ID: t_001\nFEATURE_ID: f_001\n\nbody1", encoding="utf-8")
    (queue_dir / "task_002.txt").write_text("TASK_ID: t_002\nFEATURE_ID: f_002\n\nbody2", encoding="utf-8")

    runtime = ThinkingRuntime(root_dir=tmp_path, signal_port=19100)

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
        slot1 = runtime.get_slot("sub_brain_01")
        slot2 = runtime.get_slot("sub_brain_02")
        assert slot1.busy and slot2.busy

    finally:
        lm_module.LaunchManager.launch = original_launch


def test_stale_signal_ignored_after_slot_reuse(tmp_path):
    """Test that stale terminal signals from previous tasks are ignored."""
    thinking_pool = tmp_path / "pools" / "thinking"
    (thinking_pool / "Queue").mkdir(parents=True)
    slot1_dir = thinking_pool / "sub_brain_01"
    slot1_dir.mkdir(parents=True)
    (slot1_dir / "workspace").mkdir()
    (thinking_pool / "sub_brain_02" / "workspace").mkdir(parents=True)
    (thinking_pool / "Outbox").mkdir(parents=True)

    runtime = ThinkingRuntime(root_dir=tmp_path, signal_port=19101)

    # Simulate slot lifecycle: task_old -> done -> task_new
    slot = runtime.get_slot("sub_brain_01")
    slot.busy = True
    slot.assigned_task_id = "t_old"
    slot.launch_result = {"launched": True, "job_handle": 0x1}

    # Release slot with done signal
    runtime.handle_signal({
        "agent_id": "sub_brain_01",
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
        "agent_id": "sub_brain_01",
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
    thinking_pool = tmp_path / "pools" / "thinking"
    (thinking_pool / "Queue").mkdir(parents=True)
    slot1_dir = thinking_pool / "sub_brain_01"
    slot1_dir.mkdir(parents=True)
    (slot1_dir / "workspace").mkdir()
    (thinking_pool / "sub_brain_02" / "workspace").mkdir(parents=True)
    (thinking_pool / "Outbox").mkdir(parents=True)

    runtime = ThinkingRuntime(root_dir=tmp_path, signal_port=19102)

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
        slot = runtime.get_slot("sub_brain_01")
        slot.busy = True
        slot.assigned_task_id = "t_race"
        slot.assigned_at_epoch = time.time() - 400  # Expired
        slot.timeout_seconds = 300
        slot.launch_result = {"launched": True, "job_handle": 0xBEEF}

        errors = []

        def send_done_signal():
            try:
                runtime.handle_signal({
                    "agent_id": "sub_brain_01",
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
        assert len(cleanup_calls) <= 1, f"cleanup_launch called {len(cleanup_calls)} times (should be <=1)"

        # Slot should be released
        assert slot.busy is False

    finally:
        lm_module.LaunchManager.cleanup_launch = original_cleanup


def test_handle_signal_ignores_non_busy_slot(tmp_path):
    """Test that terminal signals are ignored if slot is not busy."""
    thinking_pool = tmp_path / "pools" / "thinking"
    (thinking_pool / "Queue").mkdir(parents=True)
    (thinking_pool / "sub_brain_01" / "workspace").mkdir(parents=True)
    (thinking_pool / "sub_brain_02" / "workspace").mkdir(parents=True)
    (thinking_pool / "Outbox").mkdir(parents=True)

    runtime = ThinkingRuntime(root_dir=tmp_path, signal_port=19103)

    # Mock cleanup to track calls
    import app.shared.launch_manager as lm_module
    original_cleanup = lm_module.LaunchManager.cleanup_launch

    cleanup_calls = []

    def tracked_cleanup(self, launch_result):
        cleanup_calls.append(launch_result)
        return {"cleaned": True}

    lm_module.LaunchManager.cleanup_launch = tracked_cleanup

    try:
        slot = runtime.get_slot("sub_brain_01")
        # Slot is idle (busy=False)
        assert slot.busy is False

        # Send terminal signal
        runtime.handle_signal({
            "agent_id": "sub_brain_01",
            "task_id": "t_phantom",
            "signal": "done",
            "is_terminal": True,
        })

        # Cleanup should NOT be called
        assert len(cleanup_calls) == 0, "cleanup_launch called for non-busy slot"

    finally:
        lm_module.LaunchManager.cleanup_launch = original_cleanup


def test_get_next_idle_slot_thread_safe(tmp_path):
    """Test that get_next_idle_slot returns consistent results under concurrent access."""
    thinking_pool = tmp_path / "pools" / "thinking"
    (thinking_pool / "Queue").mkdir(parents=True)
    (thinking_pool / "sub_brain_01" / "workspace").mkdir(parents=True)
    (thinking_pool / "sub_brain_02" / "workspace").mkdir(parents=True)
    (thinking_pool / "Outbox").mkdir(parents=True)

    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True)
    for f in ["Online.bat", "StartThinking.bat", "StartSummarizing.bat", "Done.bat", "signal_bridge.py", "BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")

    runtime = ThinkingRuntime(root_dir=tmp_path, signal_port=19104)

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

    # All should return sub_brain_01 (lowest idle slot)
    assert all(slot_id == "sub_brain_01" for slot_id in results)
    assert len(results) == 10
