"""Tests for Runtime Registry - tracks running pool runtimes with PID and port info."""

import os
from pathlib import Path
import time

from app.services.runtime_registry import RuntimeRegistry


def test_runtime_registry_records_pool_pid_port(tmp_path):
    """Test that RuntimeRegistry can record and retrieve runtime info."""
    registry = RuntimeRegistry(root_dir=tmp_path)

    # Register a runtime
    registry.register(
        pool="work",
        pid=12345,
        port=18800,
        status="running"
    )

    # Retrieve runtime info
    info = registry.get("work")

    assert info is not None
    assert info["pool"] == "work"
    assert info["pid"] == 12345
    assert info["port"] == 18800
    assert info["status"] == "running"
    assert "started_at" in info
    assert "last_heartbeat" in info


def test_runtime_registry_updates_existing_entry(tmp_path):
    """Test that re-registering updates the existing entry."""
    registry = RuntimeRegistry(root_dir=tmp_path)

    # Register initially
    registry.register(pool="thinking", pid=11111, port=18910, status="running")

    # Update with new PID
    registry.register(pool="thinking", pid=22222, port=18910, status="running")

    info = registry.get("thinking")
    assert info["pid"] == 22222


def test_runtime_registry_lists_all_runtimes(tmp_path):
    """Test that list_all returns all registered runtimes."""
    registry = RuntimeRegistry(root_dir=tmp_path)

    registry.register(pool="work", pid=1, port=18800, status="running")
    registry.register(pool="thinking", pid=2, port=18910, status="running")
    registry.register(pool="construct", pid=3, port=19020, status="running")

    all_runtimes = registry.list_all()

    assert len(all_runtimes) == 3
    assert any(r["pool"] == "work" for r in all_runtimes)
    assert any(r["pool"] == "thinking" for r in all_runtimes)
    assert any(r["pool"] == "construct" for r in all_runtimes)


def test_runtime_registry_unregister_removes_entry(tmp_path):
    """Test that unregister removes a runtime from the registry."""
    registry = RuntimeRegistry(root_dir=tmp_path)

    registry.register(pool="gate", pid=4, port=19200, status="running")
    assert registry.get("gate") is not None

    registry.unregister(pool="gate")
    assert registry.get("gate") is None


def test_runtime_registry_heartbeat_updates_timestamp(tmp_path):
    """Test that heartbeat updates the last_heartbeat timestamp."""
    registry = RuntimeRegistry(root_dir=tmp_path)

    registry.register(pool="post", pid=5, port=19400, status="running")

    info_before = registry.get("post")
    time.sleep(0.01)

    registry.heartbeat(pool="post")

    info_after = registry.get("post")
    assert info_after["last_heartbeat"] >= info_before["last_heartbeat"]


def test_runtime_registry_persists_to_disk(tmp_path):
    """Test that registry data persists across instances."""
    registry1 = RuntimeRegistry(root_dir=tmp_path)
    registry1.register(pool="work", pid=999, port=18800, status="running")

    # Create new instance pointing to same directory
    registry2 = RuntimeRegistry(root_dir=tmp_path)
    info = registry2.get("work")

    assert info is not None
    assert info["pid"] == 999
    assert info["port"] == 18800


def test_runtime_registry_preserves_other_pools_across_instances(tmp_path):
    """Test that separate RuntimeRegistry instances do not overwrite each other's pools."""
    registry1 = RuntimeRegistry(root_dir=tmp_path)
    registry2 = RuntimeRegistry(root_dir=tmp_path)

    registry1.register(pool="post", pid=101, port=19400, status="running")
    registry2.register(pool="package", pid=202, port=19300, status="running")
    registry1.heartbeat("post")

    registry3 = RuntimeRegistry(root_dir=tmp_path)
    all_pools = {item["pool"] for item in registry3.list_all()}

    assert all_pools == {"post", "package"}
import pytest
from filelock import FileLock

def test_runtime_registry_lock_timeout(tmp_path):
    """Test that RuntimeRegistry raises TimeoutError if lock cannot be acquired."""
    registry = RuntimeRegistry(root_dir=tmp_path)

    # Pre-acquire the lock to simulate another process holding it
    lock_file = tmp_path / "runtime_registry.json.lock"
    external_lock = FileLock(lock_file)

    with external_lock:
        # Should raise TimeoutError because lock is held and registry sets timeout=5.0
        # For testing we want it to fail faster, but we'll patch the timeout
        import unittest.mock as mock
        with mock.patch("app.shared.json_store.FileLock") as mock_filelock:
            # Create a mock lock that immediately raises Timeout
            from filelock import Timeout

            # Setup the mock lock instance
            mock_lock_instance = mock.MagicMock()
            mock_lock_instance.__enter__.side_effect = Timeout(lock_file)
            mock_filelock.return_value = mock_lock_instance

            with pytest.raises(TimeoutError, match="Timeout acquiring lock for runtime registry"):
                registry.register(pool="work", pid=1, port=18800, status="running")


def test_runtime_registry_handles_non_dict_payloads(tmp_path):
    registry_file = tmp_path / "runtime_registry.json"
    registry_file.write_text("[1, 2, 3]", encoding="utf-8")

    registry = RuntimeRegistry(root_dir=tmp_path)

    assert registry.get("work") is None
    assert registry.list_all() == []
