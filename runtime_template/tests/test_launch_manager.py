"""Test runtime_template launch_manager."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.launch_manager import LaunchManager


class _TerminateJobStub:
    def __init__(self, success_on_attempt=1):
        self.success_on_attempt = success_on_attempt
        self.attempt_count = 0
        self.terminated_handles = []

    def __call__(self, job_handle):
        self.attempt_count += 1
        self.terminated_handles.append(job_handle)
        return self.attempt_count >= self.success_on_attempt


def test_cleanup_launch_preserves_handle_on_failure(monkeypatch):
    terminate_stub = _TerminateJobStub(success_on_attempt=999)
    monkeypatch.setattr("core.launch_manager.terminate_job", terminate_stub)

    manager = LaunchManager()
    launch_result = {"job_handle": 12345, "pid": 1000}

    cleanup_result = manager.cleanup_launch(launch_result)

    assert cleanup_result["cleaned"] is False
    assert cleanup_result["reason"] == "terminate_failed"
    assert launch_result["job_handle"] == 12345
    assert terminate_stub.terminated_handles == [12345]


def test_cleanup_launch_clears_handle_on_success(monkeypatch):
    terminate_stub = _TerminateJobStub(success_on_attempt=1)
    monkeypatch.setattr("core.launch_manager.terminate_job", terminate_stub)

    manager = LaunchManager()
    launch_result = {"job_handle": 12345, "pid": 1000}

    cleanup_result = manager.cleanup_launch(launch_result)

    assert cleanup_result["cleaned"] is True
    assert cleanup_result["reason"] == "terminated"
    assert launch_result["job_handle"] is None
    assert terminate_stub.terminated_handles == [12345]


def test_cleanup_launch_allows_retry_after_initial_failure(monkeypatch):
    terminate_stub = _TerminateJobStub(success_on_attempt=2)
    monkeypatch.setattr("core.launch_manager.terminate_job", terminate_stub)

    manager = LaunchManager()
    launch_result = {"job_handle": 12345, "pid": 1000}

    cleanup_result_1 = manager.cleanup_launch(launch_result)
    assert cleanup_result_1["cleaned"] is False
    assert launch_result["job_handle"] == 12345

    cleanup_result_2 = manager.cleanup_launch(launch_result)
    assert cleanup_result_2["cleaned"] is True
    assert launch_result["job_handle"] is None
    assert terminate_stub.terminated_handles == [12345, 12345]


def test_build_child_env_strips_claude_vars(monkeypatch):
    monkeypatch.setenv("CLAUDE_SESSION", "test")
    monkeypatch.setenv("CLAUDECODE", "test")
    monkeypatch.setenv("CLAUDE_CODE", "test")
    monkeypatch.setenv("NORMAL_VAR", "keep")

    manager = LaunchManager()
    env = manager.build_child_env()

    assert "CLAUDE_SESSION" not in env
    assert "CLAUDECODE" not in env
    assert "CLAUDE_CODE" not in env
    assert env.get("NORMAL_VAR") == "keep"
