"""Real Worker Integration test for Thinking Pool.

这不仅是代码层面的模拟集成测试，而是真正拉起 Claude CLI（带 --dangerously-skip-permissions）的闭环验证。
验证 Queue -> dispatch -> Claude 执行 -> Outbox 的完整闭环。
"""

from pathlib import Path
import time
import json

from app.runtimes.thinking_runtime import ThinkingRuntime


# [WARN] 这个测试跑得很慢（可能需要几十秒），因为它真的拉起了 CLI
def test_real_worker_closed_loop():
    root_dir = Path("C:/Users/lenovo/Desktop/MultiAgentWorkspace1.0")
    thinking_pool = root_dir / "pools" / "thinking"
    queue_dir = thinking_pool / "Queue"
    outbox_dir = thinking_pool / "Outbox"

    # 我们用一个特定的任务ID，避免和其他任务混淆
    task_id = "t_real_thinking_001"
    task_file = queue_dir / f"task_{task_id}.txt"

    # 构造任务内容。这里明确告诉 Worker 不要进行实际代码编写，只需要输出一个文本证明它跑过，
    # 并且严格遵守 thinking pool 的 lifecycle 信号
    task_content = f"""FROM: system
TO: thinker
TASK_ID: {task_id}
FEATURE_ID: test
TIMEOUT: 180

Please read BOOTSTRAP.txt in the current directory and follow it exactly.
This is an observation task for the Thinking Pool.
Work only inside workspace/.
Create a file named "thinking_result.txt" in workspace/ with content "This is a real thinking test."
Do not use any Skill.
After finishing the thinking phase, continue to summarizing and then complete the task normally.
"""
    task_file.write_text(task_content, encoding="utf-8")

    # 为了不污染默认端口，我们找个不同的端口
    signal_port = 19250
    runtime = ThinkingRuntime(root_dir=root_dir, signal_port=signal_port)

    # 确认没有使用 mock 的 launch_manager
    runtime.start()

    errors = []

    try:
        # Check initial state
        print(f"[DEBUG] Queue tasks: {runtime.list_queue_tasks()}")
        print(f"[DEBUG] Slots: {list(runtime._slots.keys())}")
        slot = runtime.get_slot("sub_brain_01")
        if slot:
            print(f"[DEBUG] Slot busy: {slot.busy}, assigned: {slot.assigned_task_id}")

        # Dispatch
        result = runtime.dispatch_next(dry_run=False)
        print(f"[DEBUG] Dispatch result: {result}")
        assert result["dispatched"] is True, f"Dispatch failed: {result}"
        assert result["slot_id"] == "sub_brain_01"
        assert result["task_id"] == task_id

        # 轮询等待任务完成 (Timeout: 240s)
        max_wait = 240
        start_wait = time.time()
        is_done = False

        while time.time() - start_wait < max_wait:
            slot = runtime.get_slot("sub_brain_01")
            if not slot.busy:
                is_done = True
                break
            # 同时也检查下超时
            runtime.check_timeouts()
            time.sleep(2)

        assert is_done, "Task did not finish within timeout (240s)."

        # 验证 Outbox
        task_outbox = outbox_dir / task_id
        assert task_outbox.exists()
        result_file = task_outbox / "thinking_result.txt"
        assert result_file.exists()
        assert "This is a real thinking test." in result_file.read_text(encoding="utf-8")

        # 验证事件
        events_file = root_dir / "events" / "thinking" / "events_index.json"
        assert events_file.exists()
        index_data = json.loads(events_file.read_text(encoding="utf-8"))
        events_data = index_data.get("events", [])

        # 过滤出当前 task 的事件
        task_events = [e for e in events_data if e["task_id"] == task_id]
        signals = [e["signal"] for e in task_events]

        assert "online" in signals
        assert "start_thinking" in signals
        assert "start_summarizing" in signals
        assert "done" in signals

    finally:
        runtime.stop()
