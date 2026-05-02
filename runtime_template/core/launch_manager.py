from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence
import os
import shutil
import subprocess
import sys

from .windows_process import assign_process_to_job, create_job_object, is_windows, terminate_job


DIRECT_BOOTSTRAP_PROMPT = (
    "You are dispatched as a subagent to execute a specific task. "
    "Do NOT use any skill, planning, or brainstorming tools. "
    "Read BOOTSTRAP.txt, then read RUNTIME_CONTEXT.txt if it exists, "
    "and follow both instructions to execute the task directly."
)

_SANITIZED_ENV_KEYS = {
    "CLAUDECODE",
    "CLAUDE_CODE",
}

@dataclass(slots=True)
class LaunchRequest:
    bat_path: Path
    working_dir: Path | None = None
    extra_args: Sequence[str] = ()
    bootstrap_path: Path | None = None
    runtime_context_path: Path | None = None
    use_job_object: bool = True      # Control Job Object creation for process cleanup
    create_new_console: bool = True  # Control CREATE_NEW_CONSOLE flag for visible window


class LaunchManager:
    """Launch worker processes using visible foreground CLI (consistent with brain direct launch)."""

    def _should_use_job_object(self, request: LaunchRequest) -> bool:
        return is_windows() and request.use_job_object

    def cleanup_launch(self, launch_result: dict[str, Any]) -> dict[str, Any]:
        job_handle = launch_result.get("job_handle")
        if job_handle is None:
            return {"cleaned": False, "reason": "missing_or_already_cleaned"}

        success = terminate_job(job_handle)
        if success:
            launch_result["job_handle"] = None

        return {
            "cleaned": success,
            "job_handle": job_handle if not success else None,
            "reason": "terminated" if success else "terminate_failed",
        }

    def resolve_claude_command(self) -> str:
        claude_cmd = shutil.which("claude.cmd") or shutil.which("claude")
        if not claude_cmd:
            raise FileNotFoundError("Claude CLI not found in PATH")
        return str(Path(claude_cmd).resolve())

    def build_command(self, request: LaunchRequest) -> list[str]:
        if request.bootstrap_path is not None:
            # Generate launch bat (same pattern as RevivalManager._build_launch_bat)
            self._ensure_launch_bat(request)
            bat_path = str(request.bat_path)
            return ["cmd.exe", "/c", bat_path]

        command = ["cmd.exe", "/c", str(request.bat_path)]
        command.extend(request.extra_args)
        return command

    def _ensure_launch_bat(self, request: LaunchRequest) -> None:
        """Write a visible launch bat file that runs Claude through a PowerShell wrapper."""
        agent_dir = str(request.working_dir) if request.working_dir else str(request.bat_path.parent)
        request.bat_path.parent.mkdir(parents=True, exist_ok=True)
        agent_id = request.bat_path.stem.replace("launch_", "", 1)
        claude_command = self.resolve_claude_command().replace("'", "''")
        prompt = DIRECT_BOOTSTRAP_PROMPT.replace("'", "''")

        # Build native interactive CLI arguments for visible worker execution
        args = (
            "--dangerously-skip-permissions "
            f"'{prompt}'"
        )


        request.bat_path.write_text(
            "@echo off\n"
            f"title {agent_id}\n"
            f"cd /d \"{agent_dir}\"\n"
            f"powershell.exe -NoProfile -ExecutionPolicy Bypass -Command \"& '{claude_command}' {args}\"\n"
            "exit /b\n",
            encoding="utf-8",
        )

    def build_child_env(self) -> dict[str, str]:
        env = dict(os.environ)
        # Strip all CLAUDE* env vars to prevent nested session errors
        for key in list(env.keys()):
            if key.startswith("CLAUDE"):
                env.pop(key, None)
        return env

    def launch(self, request: LaunchRequest, dry_run: bool = True) -> dict[str, object]:
        command = self.build_command(request)
        cwd = str(request.working_dir) if request.working_dir else None
        should_use_job_object = self._should_use_job_object(request)
        if dry_run:
            return {
                "launched": False,
                "dry_run": True,
                "command": command,
                "cwd": cwd,
                "job_handle": None,
            }

        creationflags = 0
        if sys.platform == "win32" and request.create_new_console:
            creationflags = subprocess.CREATE_NEW_CONSOLE

        job_handle = create_job_object() if should_use_job_object else None
        process = None
        try:
            process = subprocess.Popen(
                command,
                cwd=cwd,
                env=self.build_child_env(),
                creationflags=creationflags,
            )
            if job_handle is not None and not assign_process_to_job(job_handle, process.pid):
                raise RuntimeError(f"Failed to assign process {process.pid} to Job Object")
            return {
                "launched": True,
                "dry_run": False,
                "command": command,
                "cwd": cwd,
                "pid": process.pid,
                "job_handle": job_handle,
            }
        except Exception:
            if process is not None and process.poll() is None:
                process.terminate()
            if job_handle is not None:
                terminate_job(job_handle)
            raise
