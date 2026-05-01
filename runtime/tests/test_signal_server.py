import json
import urllib.error
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

        try:
            urllib.request.urlopen(req, timeout=5)
            assert False, "Expected HTTPError 400"
        except urllib.error.HTTPError as e:
            assert e.code == 400
            result = json.loads(e.read().decode("utf-8"))

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


def test_signal_server_missing_content_type_returns_400(tmp_path):
    """Missing Content-Type header should return HTTP 400."""
    server = RuntimeSignalServer(port=18770, event_store_dir=tmp_path)
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
            "http://localhost:18770/signal",
            data=json.dumps(payload).encode("utf-8"),
            # No Content-Type header set
            method="POST",
        )

        try:
            urllib.request.urlopen(req, timeout=5)
            assert False, "Expected HTTPError 400"
        except urllib.error.HTTPError as e:
            assert e.code == 400
            result = json.loads(e.read().decode("utf-8"))

        assert result["accepted"] is False

    finally:
        server.stop()


def test_signal_server_wrong_content_type_returns_400(tmp_path):
    """Wrong Content-Type header (not application/json) should return HTTP 400."""
    server = RuntimeSignalServer(port=18771, event_store_dir=tmp_path)
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
            "http://localhost:18771/signal",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "text/plain"},
            method="POST",
        )

        try:
            urllib.request.urlopen(req, timeout=5)
            assert False, "Expected HTTPError 400"
        except urllib.error.HTTPError as e:
            assert e.code == 400
            result = json.loads(e.read().decode("utf-8"))

        assert result["accepted"] is False

    finally:
        server.stop()


def test_signal_server_oversized_body_returns_400(tmp_path):
    """Body larger than 10MB should return HTTP 400."""
    server = RuntimeSignalServer(port=18772, event_store_dir=tmp_path)
    server.start()

    try:
        payload = {
            "timestamp": "2026-04-17T10:00:00Z",
            "agent_id": "worker_01",
            "task_id": "t_001",
            "signal": "online",
            "pool": "work",
            "data": "x" * (11 * 1024 * 1024),  # 11MB - exceeds 10MB limit
        }

        req = urllib.request.Request(
            "http://localhost:18772/signal",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            urllib.request.urlopen(req, timeout=5)
            assert False, "Expected HTTPError 400"
        except urllib.error.HTTPError as e:
            assert e.code == 400
            result = json.loads(e.read().decode("utf-8"))

        assert result["accepted"] is False

    finally:
        server.stop()


def test_signal_server_hook_failure_returns_500_and_accepted_false(tmp_path):
    """on_signal hook exception should return HTTP 500 with accepted=false."""
    server = RuntimeSignalServer(port=18773, event_store_dir=tmp_path)
    server.start()

    def failing_hook(result):
        raise RuntimeError("hook deliberately failed")

    server.on_signal = failing_hook

    try:
        payload = {
            "timestamp": "2026-04-17T10:00:00Z",
            "agent_id": "worker_01",
            "task_id": "t_001",
            "signal": "online",
            "pool": "work",
        }

        req = urllib.request.Request(
            "http://localhost:18773/signal",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            urllib.request.urlopen(req, timeout=5)
            assert False, "Expected HTTPError 500"
        except urllib.error.HTTPError as e:
            assert e.code == 500
            result = json.loads(e.read().decode("utf-8"))

        assert result["accepted"] is False
        assert result["reason"] == "on_signal hook failed"
        # Event is persisted before hook runs (durability guarantee)
        events = server.event_store.get_events(agent_id="worker_01")
        assert len(events) == 1
        assert events[0]["signal"] == "online"

    finally:
        server.stop()


def test_signal_server_illegal_transition_returns_400(tmp_path):
    """Illegal transition should return HTTP 400 with accepted=false."""
    server = RuntimeSignalServer(port=18774, event_store_dir=tmp_path)
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
            "http://localhost:18774/signal",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            urllib.request.urlopen(req, timeout=5)
            assert False, "Expected HTTPError 400"
        except urllib.error.HTTPError as e:
            assert e.code == 400
            result = json.loads(e.read().decode("utf-8"))

        assert result["accepted"] is False

    finally:
        server.stop()


def test_signal_server_unknown_pool_returns_400(tmp_path):
    """Unknown pool should return HTTP 400 with accepted=false."""
    server = RuntimeSignalServer(port=18775, event_store_dir=tmp_path)
    server.start()

    try:
        payload = {
            "timestamp": "2026-04-17T10:00:00Z",
            "agent_id": "worker_01",
            "task_id": "t_001",
            "signal": "online",
            "pool": "nonexistent_pool",
        }

        req = urllib.request.Request(
            "http://localhost:18775/signal",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            urllib.request.urlopen(req, timeout=5)
            assert False, "Expected HTTPError 400"
        except urllib.error.HTTPError as e:
            assert e.code == 400
            result = json.loads(e.read().decode("utf-8"))

        assert result["accepted"] is False

    finally:
        server.stop()


def test_signal_server_missing_fields_returns_400(tmp_path):
    """Missing required fields should return HTTP 400 with accepted=false."""
    server = RuntimeSignalServer(port=18776, event_store_dir=tmp_path)
    server.start()

    try:
        payload = {
            "timestamp": "2026-04-17T10:00:00Z",
            "agent_id": "",
            "task_id": "t_001",
            "signal": "online",
            "pool": "work",
        }

        req = urllib.request.Request(
            "http://localhost:18776/signal",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            urllib.request.urlopen(req, timeout=5)
            assert False, "Expected HTTPError 400"
        except urllib.error.HTTPError as e:
            assert e.code == 400
            result = json.loads(e.read().decode("utf-8"))

        assert result["accepted"] is False

    finally:
        server.stop()
