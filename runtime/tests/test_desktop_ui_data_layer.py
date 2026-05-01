"""Tests for desktop UI data layer (registry reader, runtime client, event snapshot reader)."""

import json
from pathlib import Path


def test_registry_reader_discovers_running_pools(tmp_path):
    """Test that RegistryReader can discover running pools from runtime_registry.json."""
    from app.desktop_ui.data.registry_reader import RegistryReader

    # Create a mock registry file
    registry_file = tmp_path / "runtime_registry.json"
    registry_data = {
        "work": {
            "pool": "work",
            "pid": 12345,
            "port": 18800,
            "status": "running",
            "started_at": 1234567890.0,
            "last_heartbeat": 1234567900.0,
        },
        "thinking": {
            "pool": "thinking",
            "pid": 12346,
            "port": 18910,
            "status": "running",
            "started_at": 1234567891.0,
            "last_heartbeat": 1234567901.0,
        },
    }
    registry_file.write_text(json.dumps(registry_data), encoding="utf-8")

    reader = RegistryReader(root_dir=tmp_path)
    pools = reader.list_running_pools()

    assert len(pools) == 2
    assert pools[0]["pool"] == "work"
    assert pools[0]["port"] == 18800
    assert pools[1]["pool"] == "thinking"
    assert pools[1]["port"] == 18910


def test_registry_reader_returns_empty_when_no_registry(tmp_path):
    """Test that RegistryReader returns empty list when registry file doesn't exist."""
    from app.desktop_ui.data.registry_reader import RegistryReader

    reader = RegistryReader(root_dir=tmp_path)
    pools = reader.list_running_pools()

    assert pools == []


def test_registry_reader_uses_runtime_registry_service(monkeypatch, tmp_path):
    """RegistryReader must reuse RuntimeRegistry instead of bare file reads."""
    from app.desktop_ui.data.registry_reader import RegistryReader

    called = {"list_all": False}

    class FakeRegistry:
        def __init__(self, root_dir):
            assert Path(root_dir) == tmp_path

        def list_all(self):
            called["list_all"] = True
            return [
                {"pool": "work", "status": "running", "started_at": 1, "port": 18800},
                {"pool": "gate", "status": "paused", "started_at": 2, "port": 19200},
            ]

    monkeypatch.setattr("app.desktop_ui.data.registry_reader.RuntimeRegistry", FakeRegistry)

    reader = RegistryReader(root_dir=tmp_path)
    pools = reader.list_running_pools()

    assert called["list_all"] is True
    assert pools == [{"pool": "work", "status": "running", "started_at": 1, "port": 18800}]


def test_registry_reader_marks_dead_runtime_as_stopped(monkeypatch, tmp_path):
    from app.desktop_ui.data.registry_reader import RegistryReader

    registry_file = tmp_path / "runtime_registry.json"
    registry_data = {
        "work": {
            "pool": "work",
            "pid": 12345,
            "port": 18800,
            "status": "running",
            "started_at": 1234567890.0,
            "last_heartbeat": 1234567900.0,
        }
    }
    registry_file.write_text(json.dumps(registry_data), encoding="utf-8")

    monkeypatch.setattr("app.desktop_ui.data.registry_reader._is_pid_alive", lambda pid: False)

    reader = RegistryReader(root_dir=tmp_path)
    pools = reader.list_all_pools()

    assert pools[0]["pool"] == "work"
    assert pools[0]["status"] == "stopped"


def test_runtime_client_fetches_status_from_api(tmp_path):
    """Test that RuntimeClient can fetch status from a running runtime's /api/status."""
    from app.desktop_ui.data.runtime_client import RuntimeClient

    # Mock HTTP response (we'll use a simple dict for now, real impl will use requests/urllib)
    client = RuntimeClient()

    # This will fail because we haven't implemented RuntimeClient yet
    status = client.get_status(pool="work", port=18800)

    assert status is not None
    assert status["pool"] == "work"


def test_runtime_client_marks_pool_offline_on_connection_error(tmp_path):
    """Test that RuntimeClient marks pool as offline when API is unreachable."""
    from app.desktop_ui.data.runtime_client import RuntimeClient

    client = RuntimeClient()

    # Try to connect to a non-existent port
    status = client.get_status(pool="work", port=99999)

    assert status is not None
    assert status["online"] is False
    assert status["pool"] == "work"


def test_event_snapshot_reader_reads_latest_events(tmp_path):
    """Test that EventSnapshotReader can read latest events from event store."""
    from app.desktop_ui.data.event_snapshot_reader import EventSnapshotReader
    from app.services.event_store import EventStore, LifecycleEvent

    # Create event store with some events
    event_store_dir = tmp_path / "events"
    event_store = EventStore(event_store_dir)

    event_store.append(
        LifecycleEvent(
            timestamp="2025-01-01T10:00:00",
            agent_id="worker_01",
            task_id="task_001",
            signal="started",
            from_state="idle",
            to_state="running",
        )
    )

    event_store.append(
        LifecycleEvent(
            timestamp="2025-01-01T10:05:00",
            agent_id="worker_01",
            task_id="task_001",
            signal="completed",
            from_state="running",
            to_state="idle",
        )
    )

    # Now read via EventSnapshotReader
    reader = EventSnapshotReader(root_dir=tmp_path)
    events = reader.get_recent_events(pool="work", agent_id="worker_01", limit=10)

    assert len(events) == 2
    assert events[0]["signal"] == "started"
    assert events[1]["signal"] == "completed"
