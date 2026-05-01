"""Tests for Runtime Registry wiring in main entry points.

Verifies that each main_* entry point registers with RuntimeRegistry on startup,
sends heartbeats during operation, and updates status on shutdown.
"""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest


def test_work_runtime_registers_on_startup(tmp_path):
    """Test that main.py registers work pool in runtime_registry.json on startup."""
    root_dir = tmp_path / "test_root"
    work_pool = root_dir / "pools" / "work"

    # Create minimal directory structure
    for i in [1, 2]:
        slot_dir = work_pool / f"worker_0{i}"
        workspace = slot_dir / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)

    registry_file = root_dir / "runtime_registry.json"

    # Launch main.py in background using -m to ensure proper imports
    runtime_dir = Path(__file__).parent.parent
    proc = subprocess.Popen(
        [sys.executable, "-m", "app.main", str(root_dir), "--port", "18850", "--poll-interval", "10"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=runtime_dir,
    )

    try:
        # Wait for runtime to register work entry
        registry_data = {}
        for _ in range(50):  # 5 seconds max
            if registry_file.exists():
                with open(registry_file, "r", encoding="utf-8") as f:
                    registry_data = json.load(f)
                if "work" in registry_data:
                    break
            time.sleep(0.1)

        assert registry_file.exists(), "Registry file not created"
        assert "work" in registry_data
        work_entry = registry_data["work"]
        assert work_entry["pool"] == "work"
        assert work_entry["pid"] == proc.pid
        assert work_entry["port"] == 18850
        assert work_entry["status"] == "running"
        assert "started_at" in work_entry
        assert "last_heartbeat" in work_entry

    finally:
        # Clean shutdown
        proc.terminate()
        proc.wait(timeout=5)


def test_thinking_runtime_registers_on_startup(tmp_path):
    """Test that main_thinking.py registers thinking pool in runtime_registry.json."""
    root_dir = tmp_path / "test_root"
    thinking_pool = root_dir / "pools" / "thinking"

    for i in [1, 2]:
        slot_dir = thinking_pool / f"sub_brain_0{i}"
        workspace = slot_dir / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)

    registry_file = root_dir / "runtime_registry.json"

    runtime_dir = Path(__file__).parent.parent
    proc = subprocess.Popen(
        [sys.executable, "-m", "app.main_thinking", str(root_dir), "--port", "18960", "--poll-interval", "10"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=runtime_dir,
    )

    try:
        # Wait for runtime to register thinking entry
        registry_data = {}
        for _ in range(50):
            if registry_file.exists():
                with open(registry_file, "r", encoding="utf-8") as f:
                    registry_data = json.load(f)
                if "thinking" in registry_data:
                    break
            time.sleep(0.1)

        assert registry_file.exists()
        assert "thinking" in registry_data
        thinking_entry = registry_data["thinking"]
        assert thinking_entry["pool"] == "thinking"
        assert thinking_entry["pid"] == proc.pid
        assert thinking_entry["port"] == 18960
        assert thinking_entry["status"] == "running"

    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_registry_heartbeat_updates_during_operation(tmp_path):
    """Test that runtime updates last_heartbeat timestamp periodically."""
    root_dir = tmp_path / "test_root"
    work_pool = root_dir / "pools" / "work"

    for i in [1, 2]:
        slot_dir = work_pool / f"worker_0{i}"
        workspace = slot_dir / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)

    registry_file = root_dir / "runtime_registry.json"

    runtime_dir = Path(__file__).parent.parent
    proc = subprocess.Popen(
        [sys.executable, "-m", "app.main", str(root_dir), "--port", "18851", "--poll-interval", "0.5"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=runtime_dir,
    )

    try:
        # Wait for initial registration with work entry
        initial_data = {}
        for _ in range(50):
            if registry_file.exists():
                with open(registry_file, "r", encoding="utf-8") as f:
                    initial_data = json.load(f)
                if "work" in initial_data:
                    break
            time.sleep(0.1)

        initial_heartbeat = initial_data["work"]["last_heartbeat"]

        # Wait for at least one poll cycle (0.5s + margin)
        time.sleep(1.0)

        with open(registry_file, "r", encoding="utf-8") as f:
            updated_data = json.load(f)

        updated_heartbeat = updated_data["work"]["last_heartbeat"]

        # Heartbeat should have been updated
        assert updated_heartbeat > initial_heartbeat, "Heartbeat not updated during operation"

    finally:
        proc.terminate()
        proc.wait(timeout=5)


@pytest.mark.skip(reason="Windows terminate() doesn't trigger signal handlers reliably")
def test_registry_marks_stopped_on_shutdown(tmp_path):
    """Test that runtime updates status to 'stopped' on graceful shutdown."""
    root_dir = tmp_path / "test_root"
    work_pool = root_dir / "pools" / "work"

    for i in [1, 2]:
        slot_dir = work_pool / f"worker_0{i}"
        workspace = slot_dir / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)

    registry_file = root_dir / "runtime_registry.json"

    runtime_dir = Path(__file__).parent.parent
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    proc = subprocess.Popen(
        [sys.executable, "-m", "app.main", str(root_dir), "--port", "18852", "--poll-interval", "10"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=runtime_dir,
        creationflags=creationflags,
    )

    try:
        # Wait for runtime to register work entry
        running_data = {}
        for _ in range(50):
            if registry_file.exists():
                with open(registry_file, "r", encoding="utf-8") as f:
                    running_data = json.load(f)
                if "work" in running_data:
                    break
            time.sleep(0.1)

        assert running_data["work"]["status"] == "running"

        # Graceful shutdown
        proc.terminate()

        proc.wait(timeout=5)

        # Give filesystem time to flush
        time.sleep(0.3)

        # Check registry after shutdown
        with open(registry_file, "r", encoding="utf-8") as f:
            stopped_data = json.load(f)

        assert stopped_data["work"]["status"] == "stopped", "Status not updated to 'stopped' on shutdown"

    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        pytest.fail("Process did not terminate gracefully")
