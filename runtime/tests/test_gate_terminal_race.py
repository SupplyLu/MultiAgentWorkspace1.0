"""Test GateRuntime terminal signal race conditions (Group B security hardening).

验证 approved/rejected 信号竞态时，只有第一个信号能赢得终态清理权。
"""

from pathlib import Path
import threading
import time


def test_gate_approved_rejected_race_only_one_wins(tmp_path):
    """When approved and rejected signals arrive concurrently, only first one should finalize."""
    gate_pool = tmp_path / "pools" / "gate"
    (gate_pool / "Queue").mkdir(parents=True)
    (gate_pool / "Outbox").mkdir(parents=True)
    (gate_pool / "Rejectbox").mkdir(parents=True)
    (gate_pool / "fields").mkdir(parents=True)

    slot_dir = gate_pool / "guard_01"
    slot_dir.mkdir(parents=True)
    workspace_dir = slot_dir / "workspace"
    workspace_dir.mkdir()

    # Create artifact in workspace
    (workspace_dir / "task_001.txt").write_text("approved work", encoding="utf-8")

    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True)
    for f in ["Online.bat", "StartReview.bat", "Accepted.bat", "Denied.bat", "signal_bridge.py", "BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")

    from app.runtimes.gate_runtime import GateRuntime
    runtime = GateRuntime(root_dir=tmp_path, signal_port=19250)

    # Manually assign slot to simulate active task
    slot = runtime.get_slot("guard_01")
    slot.busy = True
    slot.assigned_task_id = "batch_001"
    slot.assigned_at_epoch = time.time()
    slot.launch_result = {"launched": True, "job_handle": None}

    # Send approved and rejected signals concurrently
    results = []

    def send_approved():
        result = runtime.handle_signal({
            "agent_id": "guard_01",
            "task_id": "batch_001",
            "signal": "approved",
        })
        results.append(("approved", result))

    def send_rejected():
        result = runtime.handle_signal({
            "agent_id": "guard_01",
            "task_id": "batch_001",
            "signal": "rejected",
        })
        results.append(("rejected", result))

    t1 = threading.Thread(target=send_approved)
    t2 = threading.Thread(target=send_rejected)

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Only one should have finalized
    # The other should have been blocked by finalizing flag
    assert len(results) == 2

    # Check slot is now idle and not finalizing
    assert slot.busy is False
    assert slot.finalizing is False
    assert slot.assigned_task_id == ""

    # Exactly one artifact collection should have succeeded
    # (Either Outbox has file OR Rejectbox has directory, but not both)
    outbox_files = list((gate_pool / "Outbox").glob("*"))
    rejectbox_dirs = list((gate_pool / "Rejectbox").glob("*"))

    # One and only one terminal path should have collected artifacts
    assert (len(outbox_files) > 0) != (len(rejectbox_dirs) > 0), \
        "Exactly one of approved/rejected should have collected artifacts"
