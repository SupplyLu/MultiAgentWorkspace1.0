import sys
import types

from app.shared.windows_process import assign_process_to_job


class _Win32ApiStub:
    def __init__(self, process_handle, open_error=None, close_error=None):
        self.process_handle = process_handle
        self.open_error = open_error
        self.close_error = close_error
        self.closed_handles = []

    def OpenProcess(self, *_args):
        if self.open_error is not None:
            raise self.open_error
        return self.process_handle

    def CloseHandle(self, handle):
        self.closed_handles.append(handle)
        if self.close_error is not None:
            raise self.close_error


def test_assign_process_to_job_closes_handle_on_success(monkeypatch):
    process_handle = object()
    win32api = _Win32ApiStub(process_handle)
    assign_calls = []

    def assign_process(job_handle, handle):
        assign_calls.append((job_handle, handle))

    monkeypatch.setattr("app.shared.windows_process.is_windows", lambda: True)
    monkeypatch.setitem(sys.modules, "win32api", win32api)
    monkeypatch.setitem(
        sys.modules,
        "win32con",
        types.SimpleNamespace(PROCESS_SET_QUOTA=1, PROCESS_TERMINATE=2),
    )
    monkeypatch.setitem(
        sys.modules,
        "win32job",
        types.SimpleNamespace(AssignProcessToJobObject=assign_process),
    )

    assert assign_process_to_job(123, 456) is True
    assert assign_calls == [(123, process_handle)]
    assert win32api.closed_handles == [process_handle]


def test_assign_process_to_job_closes_handle_on_failure(monkeypatch):
    process_handle = object()
    win32api = _Win32ApiStub(process_handle)

    def assign_process(_job_handle, _handle):
        raise RuntimeError("assign failed")

    monkeypatch.setattr("app.shared.windows_process.is_windows", lambda: True)
    monkeypatch.setitem(sys.modules, "win32api", win32api)
    monkeypatch.setitem(
        sys.modules,
        "win32con",
        types.SimpleNamespace(PROCESS_SET_QUOTA=1, PROCESS_TERMINATE=2),
    )
    monkeypatch.setitem(
        sys.modules,
        "win32job",
        types.SimpleNamespace(AssignProcessToJobObject=assign_process),
    )

    assert assign_process_to_job(123, 456) is False
    assert win32api.closed_handles == [process_handle]
