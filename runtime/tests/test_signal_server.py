import json
import urllib.request

from app.services.signal_server import RuntimeSignalServer


def test_signal_server_process_legal_transition(tmp_path):
    server = RuntimeSignalServer(port=18766, event_store_dir=tmp_path)
    server.start()

    try:
        payload = {
            "timestamp": "2026-04-17T10:00:00Z",
            "agent_id": "worker_01",
            "task_id": "t_001",
            "signal": "online",
            "pool": "work",
        }

        req = urllib.request.Request(
            "http://localhost:18766/signal",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=5) as resp:
            result = json.loads(resp.read().decode("utf-8"))

        assert result["accepted"] is True
        assert result["from_state"] == "state_0"
        assert result["to_state"] == "state_1"
        assert result["is_terminal"] is False

    finally:
        server.stop()


def test_signal_server_illegal_transition(tmp_path):
    server = RuntimeSignalServer(port=18767, event_store_dir=tmp_path)
    server.start()

    try:
        payload = {
            "timestamp": "2026-04-17T10:00:00Z",
            "agent_id": "worker_02",
            "task_id": "t_002",
            "signal": "start_writing",
            "pool": "work",
        }

        req = urllib.request.Request(
            "http://localhost:18767/signal",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=5) as resp:
            result = json.loads(resp.read().decode("utf-8"))

        assert result["accepted"] is False
        assert "illegal transition" in result["reason"]

    finally:
        server.stop()


def test_signal_server_full_work_lifecycle(tmp_path):
    server = RuntimeSignalServer(port=18768, event_store_dir=tmp_path)
    server.start()

    try:
        agent_id = "worker_03"
        task_id = "t_003"

        signals = [
            ("online", "state_0", "state_1"),
            ("start_writing", "state_1", "state_2"),
            ("done", "state_2", "state_3"),
        ]

        for signal, expected_from, expected_to in signals:
            payload = {
                "timestamp": "2026-04-17T10:00:00Z",
                "agent_id": agent_id,
                "task_id": task_id,
                "signal": signal,
                "pool": "work",
            }

            req = urllib.request.Request(
                "http://localhost:18768/signal",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=5) as resp:
                result = json.loads(resp.read().decode("utf-8"))

            assert result["accepted"] is True
            assert result["from_state"] == expected_from
            assert result["to_state"] == expected_to

        events = server.event_store.get_events(agent_id=agent_id)
        assert len(events) == 3
        assert events[-1]["to_state"] == "state_3"
        assert events[-1]["is_terminal"] is True

    finally:
        server.stop()


def test_signal_server_allows_new_task_after_terminal_task_on_same_agent(tmp_path):
    server = RuntimeSignalServer(port=18769, event_store_dir=tmp_path)
    server.start()

    try:
        agent_id = "worker_01"
        first_task_id = "t_001"
        second_task_id = "t_002"

        for signal in ["online", "start_writing", "done"]:
            payload = {
                "timestamp": "2026-04-17T10:00:00Z",
                "agent_id": agent_id,
                "task_id": first_task_id,
                "signal": signal,
                "pool": "work",
            }
            req = urllib.request.Request(
                "http://localhost:18769/signal",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            assert result["accepted"] is True

        payload = {
            "timestamp": "2026-04-17T10:01:00Z",
            "agent_id": agent_id,
            "task_id": second_task_id,
            "signal": "online",
            "pool": "work",
        }
        req = urllib.request.Request(
            "http://localhost:18769/signal",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=5) as resp:
            result = json.loads(resp.read().decode("utf-8"))

        assert result["accepted"] is True
        assert result["from_state"] == "state_0"
        assert result["to_state"] == "state_1"

    finally:
        server.stop()
