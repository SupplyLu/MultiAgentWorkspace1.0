import pytest
import tempfile
import json
import time
import threading
from pathlib import Path


def test_terminal_signals_include_done_failed_blocked():
    """测试：终态信号集包含 done/failed/blocked"""
    from app.runtimes.work_runtime import WorkRuntime

    # 创建一个 mock runtime，通过检查 handle_signal 的行为来验证
    with tempfile.TemporaryDirectory() as tmpdir:
        pools_dir = Path(tmpdir) / "pools" / "work"
        pools_dir.mkdir(parents=True, exist_ok=True)
        (pools_dir / "Queue").mkdir(exist_ok=True)
        (pools_dir / "Outbox").mkdir(exist_ok=True)

        for worker_id in ["worker_01", "worker_02"]:
            worker_dir = pools_dir / worker_id
            worker_dir.mkdir(exist_ok=True)
            (worker_dir / "workspace").mkdir(exist_ok=True)

        runtime = WorkRuntime(root_dir=Path(tmpdir), signal_port=18765)

        # 验证 done/failed/blocked 都能释放 slot
        for signal in ["done", "failed", "blocked"]:
            slot = runtime.get_slot("worker_01")
            slot.busy = True
            slot.assigned_task_id = f"t_{signal}"

            runtime.handle_signal({
                "agent_id": "worker_01",
                "task_id": f"t_{signal}",
                "signal": signal,
                "is_terminal": True,
            })

            assert slot.busy is False, f"{signal} 应该释放 slot"
            assert slot.assigned_task_id == "", f"{signal} 应该清空 task_id"


def test_work_runtime_launch_bat_includes_lifecycle_commands():
    """Work Pool launch bat 包含在线/写作/完成命令的环境变量和调用"""
    import tempfile
    from pathlib import Path
    from app.runtimes.work_runtime import WorkRuntime

    with tempfile.TemporaryDirectory() as tmpdir:
        pools_dir = Path(tmpdir) / "pools" / "work"
        pools_dir.mkdir(parents=True, exist_ok=True)
        queue_dir = pools_dir / "Queue"
        queue_dir.mkdir(exist_ok=True)
        (pools_dir / "Outbox").mkdir(exist_ok=True)

        worker1_dir = pools_dir / "worker_01"
        worker1_dir.mkdir(exist_ok=True)
        (worker1_dir / "workspace").mkdir(exist_ok=True)

        tools_dir = Path(tmpdir) / "runtime" / "tools"
        tools_dir.mkdir(parents=True, exist_ok=True)
        for file_name in ["Online.bat", "StartWriting.bat", "Done.bat", "signal_bridge.py", "WORK_BOOTSTRAP.txt"]:
            (tools_dir / file_name).write_text(f"mock {file_name}", encoding="utf-8")

        # Create task file
        task_file = queue_dir / "task_001.txt"
        task_file.write_text("TASK_ID: t_001\nFEATURE_ID: feature_login\n\n写一个登录页面", encoding="utf-8")

        runtime = WorkRuntime(root_dir=Path(tmpdir), signal_port=18765)
        runtime._lifecycle_tools_dir = tools_dir

        # Mock launch
        import app.shared.launch_manager as lm_module
        original_launch = lm_module.LaunchManager.launch

        def mock_launch(self, request, dry_run=True):
            return {"launched": True, "dry_run": True, "command": ["cmd"], "cwd": str(worker1_dir), "pid": 1234, "job_handle": None}

        lm_module.LaunchManager.launch = mock_launch

        try:
            runtime.dispatch_next(dry_run=True)

            # Check launch bat content
            launch_bat = worker1_dir / "launch_worker_01.bat"
            assert launch_bat.exists()
            bat_content = launch_bat.read_text(encoding="utf-8")

            assert "worker_01" in bat_content
            assert "t_001" in bat_content
            assert "work" in bat_content
            assert "WORK_BOOTSTRAP.txt" in bat_content

        finally:
            lm_module.LaunchManager.launch = original_launch





def test_launch_manager_injects_signal_server_port_into_worker_env(monkeypatch: pytest.MonkeyPatch):
    """LaunchManager 子进程环境应注入 SIGNAL_SERVER_PORT。"""
    from app.shared.launch_manager import LaunchManager, LaunchRequest

    monkeypatch.setenv("SIGNAL_SERVER_PORT", "18855")

    manager = LaunchManager()
    env = manager.build_child_env()

    assert env.get("SIGNAL_SERVER_PORT") == "18855"

    """完整的 signal -> state transition -> event 链路"""
    from app.services.signal_server import RuntimeSignalServer

    with tempfile.TemporaryDirectory() as tmpdir:
        server = RuntimeSignalServer(
            port=18799,
            event_store_dir=Path(tmpdir) / "events",
        )
        server.start()
        time.sleep(0.5)

        try:
            import urllib.request

            # 发送 online
            payload = json.dumps({
                "timestamp": "2026-04-18T10:00:00Z",
                "agent_id": "worker_01",
                "task_id": "t_001",
                "signal": "online",
                "pool": "work",
                "role": "worker",
                "feature_id": "feature_login",
            }).encode()
            req = urllib.request.Request(
                "http://localhost:18799/signal",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                r1 = json.loads(resp.read())

            assert r1["accepted"] is True
            assert r1["from_state"] == "state_0"
            assert r1["to_state"] == "state_1"

            # 发送 start_writing
            payload = json.dumps({
                "timestamp": "2026-04-18T10:01:00Z",
                "agent_id": "worker_01",
                "task_id": "t_001",
                "signal": "start_writing",
                "pool": "work",
            }).encode()
            req = urllib.request.Request(
                "http://localhost:18799/signal",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                r2 = json.loads(resp.read())

            assert r2["accepted"] is True
            assert r2["from_state"] == "state_1"
            assert r2["to_state"] == "state_2"

            # 发送 done
            payload = json.dumps({
                "timestamp": "2026-04-18T10:05:00Z",
                "agent_id": "worker_01",
                "task_id": "t_001",
                "signal": "done",
                "pool": "work",
                "message": "work completed",
            }).encode()
            req = urllib.request.Request(
                "http://localhost:18799/signal",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                r3 = json.loads(resp.read())

            assert r3["accepted"] is True
            assert r3["from_state"] == "state_2"
            assert r3["to_state"] == "state_3"
            assert r3["is_terminal"] is True

            # 验证事件存储
            events = server.event_store.get_events(agent_id="worker_01")
            assert len(events) == 3
            assert events[0]["signal"] == "online"
            assert events[1]["signal"] == "start_writing"
            assert events[2]["signal"] == "done"
            assert events[2]["to_state"] == "state_3"

        finally:
            server.stop()



def test_work_runtime_signal_server_illegal_transition_rejected():
    """非法信号转换被拒绝"""
    from app.services.signal_server import RuntimeSignalServer

    with tempfile.TemporaryDirectory() as tmpdir:
        server = RuntimeSignalServer(
            port=18800,
            event_store_dir=Path(tmpdir) / "events",
        )
        server.start()
        time.sleep(0.5)

        try:
            import urllib.request

            # 跳过 online，直接发 start_writing
            payload = json.dumps({
                "agent_id": "worker_02",
                "task_id": "t_002",
                "signal": "start_writing",
                "pool": "work",
            }).encode()
            req = urllib.request.Request(
                "http://localhost:18800/signal",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                r = json.loads(resp.read())

            assert r["accepted"] is False
            assert "illegal transition" in r["reason"]

        finally:
            server.stop()



def test_work_runtime_on_signal_hook_fires():
    """signal 处理后 on_signal hook 被调用"""
    from app.services.signal_server import RuntimeSignalServer

    with tempfile.TemporaryDirectory() as tmpdir:
        received = []
        server = RuntimeSignalServer(
            port=18801,
            event_store_dir=Path(tmpdir) / "events",
        )
        server.on_signal = lambda r: received.append(r)
        server.start()
        time.sleep(0.5)

        try:
            import urllib.request

            payload = json.dumps({
                "agent_id": "worker_03",
                "task_id": "t_003",
                "signal": "online",
                "pool": "work",
            }).encode()
            req = urllib.request.Request(
                "http://localhost:18801/signal",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5):
                pass

            time.sleep(0.3)
            assert len(received) == 1
            assert received[0]["agent_id"] == "worker_03"
            assert received[0]["to_state"] == "state_1"

        finally:
            server.stop()
