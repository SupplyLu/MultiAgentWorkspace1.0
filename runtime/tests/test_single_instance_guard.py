import json
import os
import sys
import subprocess
import time
from pathlib import Path

from app.shared.single_instance_guard import SingleInstanceGuard


def test_single_instance_guard_acquires_and_releases(tmp_path):
    guard = SingleInstanceGuard(root_dir=tmp_path, instance_key="work")

    success, message = guard.try_acquire(timeout=0.1)

    assert success is True
    assert message == "acquired"
    assert (tmp_path / ".runtime_locks" / "work.meta.json").exists()

    guard.release()
    assert not (tmp_path / ".runtime_locks" / "work.meta.json").exists()


def test_single_instance_guard_rejects_second_holder(tmp_path):
    first = SingleInstanceGuard(root_dir=tmp_path, instance_key="work")
    second = SingleInstanceGuard(root_dir=tmp_path, instance_key="work")

    success, _ = first.try_acquire(timeout=0.1)
    assert success is True

    success, message = second.try_acquire(timeout=0.1)

    assert success is False
    assert "already running" in message or "lock held" in message

    first.release()


def test_single_instance_guard_writes_pid_metadata(tmp_path):
    guard = SingleInstanceGuard(root_dir=tmp_path, instance_key="desktop_ui")

    success, _ = guard.try_acquire(timeout=0.1)
    assert success is True

    meta_file = tmp_path / ".runtime_locks" / "desktop_ui.meta.json"
    data = json.loads(meta_file.read_text(encoding="utf-8"))

    assert data["pid"] == os.getpid()
    assert data["instance_key"] == "desktop_ui"

    guard.release()


def test_single_instance_guard_allows_reacquire_after_release(tmp_path):
    first = SingleInstanceGuard(root_dir=tmp_path, instance_key="thinking")
    second = SingleInstanceGuard(root_dir=tmp_path, instance_key="thinking")

    success, _ = first.try_acquire(timeout=0.1)
    assert success is True
    first.release()

    success, message = second.try_acquire(timeout=0.1)

    assert success is True
    assert message == "acquired"
    second.release()


def test_single_instance_guard_detects_stale_metadata(tmp_path):
    guard_dir = tmp_path / ".runtime_locks"
    guard_dir.mkdir(parents=True, exist_ok=True)
    meta_file = guard_dir / "post.meta.json"
    meta_file.write_text(json.dumps({"pid": 999999, "instance_key": "post"}), encoding="utf-8")

    guard = SingleInstanceGuard(root_dir=tmp_path, instance_key="post")

    assert guard._is_process_alive(999999) is False


def test_single_instance_guard_blocks_across_processes(tmp_path):
    script = tmp_path / "hold_lock.py"
    script.write_text(
        """
import sys
import time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from app.shared.single_instance_guard import SingleInstanceGuard
root = Path(sys.argv[2])
guard = SingleInstanceGuard(root_dir=root, instance_key=\"work\")
success, message = guard.try_acquire(timeout=0.1)
print(f\"{success}:{message}\", flush=True)
if success:
    time.sleep(3)
    guard.release()
""".strip(),
        encoding="utf-8",
    )

    runtime_dir = Path(__file__).resolve().parents[1]
    proc = subprocess.Popen(
        [sys.executable, str(script), str(runtime_dir), str(tmp_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        time.sleep(0.5)
        second = SingleInstanceGuard(root_dir=tmp_path, instance_key="work")
        success, message = second.try_acquire(timeout=0.1)
        assert success is False
        assert "already running" in message or "lock held" in message
    finally:
        proc.terminate()
        proc.wait(timeout=5)
