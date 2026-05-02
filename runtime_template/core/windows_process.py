from __future__ import annotations

from pathlib import Path
from typing import Any
import subprocess


def is_windows() -> bool:
    try:
        import platform

        return platform.system().lower() == "windows"
    except Exception:
        return False



def create_job_object() -> int:
    if not is_windows():
        raise RuntimeError("Job Objects are Windows-only")

    import win32job

    job_handle = win32job.CreateJobObject(None, "")
    if job_handle is None:
        raise RuntimeError("Failed to create Job Object")

    info = win32job.QueryInformationJobObject(
        job_handle, win32job.JobObjectExtendedLimitInformation
    )
    info["BasicLimitInformation"]["LimitFlags"] = (
        win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    )
    win32job.SetInformationJobObject(
        job_handle, win32job.JobObjectExtendedLimitInformation, info
    )
    return job_handle



def assign_process_to_job(job_handle: int, pid: int) -> bool:
    if not is_windows():
        return False

    import win32api
    import win32con
    import win32job

    process_handle = None
    try:
        process_handle = win32api.OpenProcess(
            win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE,
            False,
            pid,
        )
        win32job.AssignProcessToJobObject(job_handle, process_handle)
        return True
    except Exception:
        return False
    finally:
        if process_handle is not None:
            try:
                win32api.CloseHandle(process_handle)
            except Exception:
                pass



def terminate_job(job_handle: int) -> bool:
    if not is_windows():
        return False

    import win32api

    try:
        win32api.CloseHandle(job_handle)
        return True
    except Exception:
        return False



def query_job_process_count(job_handle: int) -> int:
    if not is_windows():
        return 0

    import win32job

    try:
        info = win32job.QueryInformationJobObject(
            job_handle, win32job.JobObjectBasicAccountingInformation
        )
        return info.get("ActiveProcesses", 0)
    except Exception:
        return 0



def build_taskkill_command(pid: int, force: bool = False, tree: bool = False) -> list[str]:
    command = ["taskkill", "/PID", str(pid)]
    if tree:
        command.append("/T")
    if force:
        command.append("/F")
    return command



def kill_process(pid: int, force: bool = False, dry_run: bool = True, tree: bool = False) -> dict[str, Any]:
    command = build_taskkill_command(pid, force=force, tree=tree)
    if dry_run:
        return {"killed": False, "dry_run": True, "command": command, "pid": pid}
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    return {
        "killed": completed.returncode == 0,
        "dry_run": False,
        "command": command,
        "pid": pid,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }



def open_in_explorer(path: str | Path, dry_run: bool = True) -> dict[str, Any]:
    target = str(path)
    command = ["explorer.exe", target]
    if dry_run:
        return {"opened": False, "dry_run": True, "command": command, "path": target}
    process = subprocess.Popen(command)
    return {"opened": True, "dry_run": False, "command": command, "path": target, "pid": process.pid}
