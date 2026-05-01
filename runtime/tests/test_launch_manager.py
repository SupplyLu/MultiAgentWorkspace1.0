import sys
import types

from app.shared.launch_manager import LaunchManager


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
    """cleanup_launch() should preserve job_handle when terminate_job() fails."""
    terminate_stub = _TerminateJobStub(success_on_attempt=999)
    monkeypatch.setattr("app.shared.launch_manager.terminate_job", terminate_stub)

    manager = LaunchManager()
    launch_result = {"job_handle": 12345, "pid": 1000}

    cleanup_result = manager.cleanup_launch(launch_result)

    assert cleanup_result["cleaned"] is False
    assert cleanup_result["reason"] == "terminate_failed"
    assert launch_result["job_handle"] == 12345  # preserved for retry
    assert terminate_stub.terminated_handles == [12345]


def test_cleanup_launch_clears_handle_on_success(monkeypatch):
    """cleanup_launch() should clear job_handle when terminate_job() succeeds."""
    terminate_stub = _TerminateJobStub(success_on_attempt=1)
    monkeypatch.setattr("app.shared.launch_manager.terminate_job", terminate_stub)

    manager = LaunchManager()
    launch_result = {"job_handle": 12345, "pid": 1000}

    cleanup_result = manager.cleanup_launch(launch_result)

    assert cleanup_result["cleaned"] is True
    assert cleanup_result["reason"] == "terminated"
    assert launch_result["job_handle"] is None  # cleared after success
    assert terminate_stub.terminated_handles == [12345]


def test_cleanup_launch_allows_retry_after_initial_failure(monkeypatch):
    """cleanup_launch() should allow retry after initial failure."""
    terminate_stub = _TerminateJobStub(success_on_attempt=2)
    monkeypatch.setattr("app.shared.launch_manager.terminate_job", terminate_stub)

    manager = LaunchManager()
    launch_result = {"job_handle": 12345, "pid": 1000}

    # First attempt fails
    cleanup_result_1 = manager.cleanup_launch(launch_result)
    assert cleanup_result_1["cleaned"] is False
    assert launch_result["job_handle"] == 12345

    # Second attempt succeeds
    cleanup_result_2 = manager.cleanup_launch(launch_result)
    assert cleanup_result_2["cleaned"] is True
    assert launch_result["job_handle"] is None
    assert terminate_stub.terminated_handles == [12345, 12345]
