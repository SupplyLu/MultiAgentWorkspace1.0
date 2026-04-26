import json
import subprocess
import sys
from pathlib import Path


RUNTIME_ROOT = Path(__file__).resolve().parents[1]


def _run_cli(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=RUNTIME_ROOT, capture_output=True, text=True)


def _register_project(
    tmp_path: Path,
    project_key: str,
    *,
    from_pool: str = "task",
    to_pool: str = "thinking",
    route: str | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        "tools/post_register.py",
        "--root-dir",
        str(tmp_path),
        "--project-key",
        project_key,
        "--from-pool",
        from_pool,
        "--to-pool",
        to_pool,
    ]
    if route is not None:
        command.extend(["--route", route])
    return _run_cli(command)



def test_post_register_cli_creates_batch(tmp_path: Path):
    completed = _register_project(tmp_path, "SignalOfBridge-v1-Build")

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["project_key"] == "SignalOfBridge-v1-Build"
    assert payload["status"] == "registered"
    assert payload["from_pool"] == "task"
    assert payload["to_pool"] == "thinking"



def test_post_hold_cli_blocks_batch(tmp_path: Path):
    register_completed = _register_project(tmp_path, "SignalOfBridge-v1-Think")
    assert register_completed.returncode == 0

    hold_cmd = [
        sys.executable,
        "tools/post_hold.py",
        "--root-dir",
        str(tmp_path),
        "--project-key",
        "SignalOfBridge-v1-Think",
        "--action",
        "hold",
    ]
    completed = _run_cli(hold_cmd)

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["project_key"] == "SignalOfBridge-v1-Think"
    assert payload["action_type"] == "hold"



def test_post_status_cli_returns_batch_info(tmp_path: Path):
    register_completed = _register_project(tmp_path, "SignalOfBridge-v1-Route")
    assert register_completed.returncode == 0

    status_cmd = [
        sys.executable,
        "tools/post_status.py",
        "--root-dir",
        str(tmp_path),
        "--project-key",
        "SignalOfBridge-v1-Route",
    ]
    completed = _run_cli(status_cmd)

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["project_key"] == "SignalOfBridge-v1-Route"
    assert payload["status"] == "registered"



def test_post_manifest_cli_returns_batch_snapshot(tmp_path: Path):
    register_completed = _register_project(tmp_path, "SignalOfBridge-v1-Manifest")
    assert register_completed.returncode == 0

    manifest_cmd = [
        sys.executable,
        "tools/post_manifest.py",
        "--root-dir",
        str(tmp_path),
        "--project-key",
        "SignalOfBridge-v1-Manifest",
    ]
    completed = _run_cli(manifest_cmd)

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["project_key"] == "SignalOfBridge-v1-Manifest"
    assert payload["from_pool"] == "task"
    assert payload["to_pool"] == "thinking"
    assert payload["status"] == "registered"
    assert payload["dependencies"] == []



def test_post_dep_cli_creates_dependency(tmp_path: Path):
    first = _register_project(tmp_path, "SignalOfBridge-v1-Source")
    second = _register_project(tmp_path, "SignalOfBridge-v1-Target")
    assert first.returncode == 0
    assert second.returncode == 0

    dep_cmd = [
        sys.executable,
        "tools/post_dep.py",
        "--root-dir",
        str(tmp_path),
        "--source-project-key",
        "SignalOfBridge-v1-Source",
        "--target-project-key",
        "SignalOfBridge-v1-Target",
        "--rule",
        "after_delivered",
    ]
    completed = _run_cli(dep_cmd)

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["source_project_key"] == "SignalOfBridge-v1-Source"
    assert payload["target_project_key"] == "SignalOfBridge-v1-Target"
    assert payload["rule"] == "after_delivered"



def test_post_register_accepts_route_argument(tmp_path: Path):
    command = [
        sys.executable,
        "tools/post_register.py",
        "--root-dir",
        str(tmp_path),
        "--project-key",
        "SignalOfBridge-v1-RoutePlan",
        "--from-pool",
        "thinking",
        "--to-pool",
        "work",
        "--route",
        "thinking,construct,work",
    ]
    completed = _run_cli(command)

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["project_key"] == "SignalOfBridge-v1-RoutePlan"
    assert payload["route"] == ["thinking", "construct", "work"]
    assert payload["cursor"] == 0
    assert payload["current_pool"] == "thinking"
    assert payload["next_pool"] == "construct"



def test_post_modify_cli_updates_remaining_route_with_operator_and_reason(tmp_path: Path):
    register_completed = _register_project(
        tmp_path,
        "SignalOfBridge-v1-Mutate",
        route="task,thinking,construct",
    )
    assert register_completed.returncode == 0

    modify_cmd = [
        sys.executable,
        "tools/post_modify.py",
        "--root-dir",
        str(tmp_path),
        "--project-key",
        "SignalOfBridge-v1-Mutate",
        "--remaining-route",
        "task,construct",
        "--operator",
        "admin",
        "--reason",
        "skip thinking",
    ]
    completed = _run_cli(modify_cmd)

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["project_key"] == "SignalOfBridge-v1-Mutate"
    assert payload["route"] == ["task", "construct"]
    assert payload["route_version"] == 2



def test_post_replay_cli_resets_delivery_status(tmp_path: Path):
    register_completed = _register_project(tmp_path, "SignalOfBridge-v1-Replay")
    assert register_completed.returncode == 0

    replay_cmd = [
        sys.executable,
        "tools/post_replay.py",
        "--root-dir",
        str(tmp_path),
        "--project-key",
        "SignalOfBridge-v1-Replay",
    ]
    completed = _run_cli(replay_cmd)

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["project_key"] == "SignalOfBridge-v1-Replay"
    assert payload["action"]["action_type"] == "replay"



def test_post_delete_cli_skips_project(tmp_path: Path):
    register_completed = _register_project(tmp_path, "SignalOfBridge-v1-Delete")
    assert register_completed.returncode == 0

    delete_cmd = [
        sys.executable,
        "tools/post_delete.py",
        "--root-dir",
        str(tmp_path),
        "--project-key",
        "SignalOfBridge-v1-Delete",
        "--reason",
        "operator skipped project",
    ]
    completed = _run_cli(delete_cmd)

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["project_key"] == "SignalOfBridge-v1-Delete"
    assert payload["status"] == "skipped"
    assert payload["skipped_reason"] == "operator skipped project"



def test_post_register_rejects_invalid_project_key_format(tmp_path: Path):
    command = [
        sys.executable,
        "tools/post_register.py",
        "--root-dir",
        str(tmp_path),
        "--project-key",
        "invalid_key_no_vision",
        "--from-pool",
        "task",
        "--to-pool",
        "thinking",
    ]
    completed = _run_cli(command)

    assert completed.returncode != 0
    payload = json.loads(completed.stdout)
    assert "error" in payload
    assert "Invalid project_key format" in payload["error"]



def test_post_register_rejects_project_key_with_atomic_suffix(tmp_path: Path):
    command = [
        sys.executable,
        "tools/post_register.py",
        "--root-dir",
        str(tmp_path),
        "--project-key",
        "SignalOfBridge-v1-Build-001",
        "--from-pool",
        "task",
        "--to-pool",
        "thinking",
    ]
    completed = _run_cli(command)

    assert completed.returncode != 0
    payload = json.loads(completed.stdout)
    assert "error" in payload
    assert "Invalid project_key format" in payload["error"]



def test_post_register_accepts_valid_project_key_format(tmp_path: Path):
    command = [
        sys.executable,
        "tools/post_register.py",
        "--root-dir",
        str(tmp_path),
        "--project-key",
        "SignalOfBridge-v1-Build",
        "--from-pool",
        "task",
        "--to-pool",
        "thinking",
    ]
    completed = _run_cli(command)

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["project_key"] == "SignalOfBridge-v1-Build"
    assert payload["status"] == "registered"
