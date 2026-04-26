"""Integration test for Thinking Pool Runtime closed loop.

验证 Queue -> dispatch -> online -> thinking -> summarizing -> done -> Outbox 的完整闭环。
使用特殊的 bootstrap bypass，不实际启动 Claude CLI，只通过 signal_bridge.py 模拟 Worker。
"""

from pathlib import Path
import pytest
import threading
import time

from app.runtimes.thinking_runtime import ThinkingRuntime


def test_thinking_runtime_closed_loop_integration(tmp_path):
    """
    Test a full successful lifecycle of a Thinking task:
    Queue -> dispatched -> simulated online/thinking/summarizing/done -> Outbox
    """
    # 1. Setup paths
    root_dir = tmp_path
    thinking_pool = root_dir / "pools" / "thinking"
    queue_dir = thinking_pool / "Queue"
    queue_dir.mkdir(parents=True)
    outbox_dir = thinking_pool / "Outbox"
    outbox_dir.mkdir(parents=True)

    # Setup one slot
    slot1_dir = thinking_pool / "sub_brain_01"
    slot1_dir.mkdir(parents=True)
    workspace_dir = slot1_dir / "workspace"
    workspace_dir.mkdir()

    # Create real lifecycle tools
    tools_dir = root_dir / "runtime" / "tools"
    tools_dir.mkdir(parents=True)

    # 只需要真实模拟 signal_bridge.py 即可，因为在 integration test 里
    # 我们直接在测试线程中用 Python 调 `signal_bridge.py` 来模拟 Worker 发送信号
    import shutil
    real_tools_dir = Path("C:/Users/lenovo/Desktop/MultiAgentWorkspace1.0/runtime/tools")
    shutil.copy(real_tools_dir / "signal_bridge.py", tools_dir / "signal_bridge.py")

    for f in ["Online.bat", "StartThinking.bat", "StartSummarizing.bat", "Done.bat", "THINKING_BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")

    # Create task
    task_id = "t_int_001"
    task_file = queue_dir / "task_int.txt"
    task_file.write_text(f"TASK_ID: {task_id}\nFEATURE_ID: f_int_001\n\nDo some deep thinking.", encoding="utf-8")

    # 2. Init Runtime
    signal_port = 19150
    runtime = ThinkingRuntime(root_dir=root_dir, signal_port=signal_port)

    # 替换 launch manager，防止真正拉起 PowerShell
    import app.shared.launch_manager as lm_module
    original_launch = lm_module.LaunchManager.launch

    def mock_launch(self, request, dry_run=True):
        return {"launched": True, "dry_run": True, "job_handle": None}

    lm_module.LaunchManager.launch = mock_launch

    # Start signal server
    runtime.start()

    errors = []

    try:
        # 3. Dispatch
        result = runtime.dispatch_next(dry_run=False)
        assert result["dispatched"] is True
        assert result["slot_id"] == "sub_brain_01"
        assert result["task_id"] == task_id

        # 4. Simulate Worker Lifecycle
        import subprocess
        import sys

        def send_signal(signal_name):
            cmd = [
                sys.executable,
                str(tools_dir / "signal_bridge.py"),
                "--agent-id", "sub_brain_01",
                "--task-id", task_id,
                "--signal", signal_name,
                "--pool", "thinking",
                "--server-url", f"http://localhost:{signal_port}"
            ]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode != 0:
                errors.append(f"Failed to send {signal_name}: {res.stderr}")

        # online -> start_thinking -> start_summarizing -> done
        send_signal("online")
        time.sleep(0.1)

        send_signal("start_thinking")
        time.sleep(0.1)

        # Simulate work artifact
        (workspace_dir / "thinking_draft.txt").write_text("deep thoughts", encoding="utf-8")

        send_signal("start_summarizing")
        time.sleep(0.1)

        # Simulate more artifacts
        (workspace_dir / "summary.md").write_text("# Summary", encoding="utf-8")

        send_signal("done")
        time.sleep(0.5)  # give server time to process done signal

        # 5. Verify assertions
        assert len(errors) == 0, f"Errors during signal sending: {errors}"

        # Verify slot released
        slot = runtime.get_slot("sub_brain_01")
        assert slot.busy is False

        # Verify outbox artifacts
        task_outbox = outbox_dir / task_id
        assert task_outbox.exists()
        assert (task_outbox / "thinking_draft.txt").exists()
        assert (task_outbox / "summary.md").exists()

        # Verify slot directory cleaned up (only workspace remains)
        assert sorted(p.name for p in slot1_dir.iterdir()) == ["workspace"]

        # Verify events
        import json
        events_file = root_dir / "events" / "thinking" / "events_index.json"
        assert events_file.exists()
        index_data = json.loads(events_file.read_text(encoding="utf-8"))
        events_data = index_data.get("events", [])
        signals = [e["signal"] for e in events_data]
        assert "online" in signals
        assert "start_thinking" in signals
        assert "start_summarizing" in signals
        assert "done" in signals

    finally:
        runtime.stop()
        lm_module.LaunchManager.launch = original_launch
