import subprocess
import sys
import time
from pathlib import Path


def _wait_for_exit(proc: subprocess.Popen, timeout: float = 5.0) -> int | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        code = proc.poll()
        if code is not None:
            return code
        time.sleep(0.1)
    return None


def test_work_runtime_rejects_second_instance(tmp_path):
    root_dir = tmp_path / "test_root"
    work_pool = root_dir / "pools" / "work"

    for i in [1, 2]:
        slot_dir = work_pool / f"worker_0{i}"
        (slot_dir / "workspace").mkdir(parents=True, exist_ok=True)

    runtime_dir = Path(__file__).parent.parent

    first = subprocess.Popen(
        [sys.executable, "-m", "app.main", str(root_dir), "--port", "18850", "--poll-interval", "10"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=runtime_dir,
        text=True,
    )

    second = None
    try:
        time.sleep(0.8)
        second = subprocess.Popen(
            [sys.executable, "-m", "app.main", str(root_dir), "--port", "18851", "--poll-interval", "10"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=runtime_dir,
            text=True,
        )

        exit_code = _wait_for_exit(second, timeout=5.0)
        assert exit_code == 1

        stdout, stderr = second.communicate(timeout=1)
        combined = f"{stdout}\n{stderr}"
        assert "启动被拒绝" in combined or "already running" in combined
    finally:
        first.terminate()
        first.wait(timeout=5)
        if second and second.poll() is None:
            second.terminate()
            second.wait(timeout=5)
