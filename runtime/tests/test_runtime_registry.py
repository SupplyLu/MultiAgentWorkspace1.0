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
