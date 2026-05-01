"""Test RuntimeRegistry under concurrent multi-process writes."""

import subprocess
import sys
import time
from pathlib import Path


def test_concurrent_registration_from_multiple_processes(tmp_path):
    """Test that multiple processes registering simultaneously don't lose data.

    This simulates the real scenario where POST, Package, Work, Thinking, etc.
    all start up and register at roughly the same time.
    """
    root_dir = tmp_path / "test_root"
    root_dir.mkdir()

    # Script that each subprocess will run
    script = f"""
import sys
import time
from pathlib import Path
sys.path.insert(0, r"{Path(__file__).parent.parent}")

from app.services.runtime_registry import RuntimeRegistry

pool_name = sys.argv[1]
pid = int(sys.argv[2])
port = int(sys.argv[3])

registry = RuntimeRegistry(root_dir=r"{root_dir}")
registry.register(pool=pool_name, pid=pid, port=port, status="running")

# Simulate some heartbeats
for _ in range(3):
    time.sleep(0.05)
    registry.heartbeat(pool_name)
"""

    script_file = tmp_path / "register_script.py"
    script_file.write_text(script, encoding="utf-8")

    # Launch 6 processes simultaneously (simulating all runtimes starting)
    pools = [
        ("post", 1001, 0),
        ("package", 1002, 19300),
        ("work", 1003, 18800),
        ("thinking", 1004, 18910),
        ("construct", 1005, 19020),
        ("gate", 1006, 19200),
    ]

    processes = []
    for pool_name, pid, port in pools:
        proc = subprocess.Popen(
            [sys.executable, str(script_file), pool_name, str(pid), str(port)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        processes.append((pool_name, proc))

    # Wait for all to complete
    for pool_name, proc in processes:
        proc.wait(timeout=5)
        if proc.returncode != 0:
            stderr = proc.stderr.read().decode()
            raise AssertionError(f"Process {pool_name} failed: {stderr}")

    # Now verify all 6 pools are in the registry
    from app.services.runtime_registry import RuntimeRegistry
    registry = RuntimeRegistry(root_dir=root_dir)
    all_pools = {item["pool"] for item in registry.list_all()}

    expected = {"post", "package", "work", "thinking", "construct", "gate"}
    assert all_pools == expected, f"Expected {expected}, got {all_pools}"
