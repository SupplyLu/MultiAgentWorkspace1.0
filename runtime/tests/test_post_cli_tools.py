import json
import subprocess
import sys
from pathlib import Path


def test_post_register_cli_creates_batch(tmp_path: Path):
    command = [
        sys.executable,
        "tools/post_register.py",
        "--root-dir",
        str(tmp_path),
        "--batch-id",
        "feat_001",
        "--name",
        "login feature",
        "--from-pool",
        "task",
        "--to-pool",
        "thinking",
        "--branch-id",
        "feat_001_b1",
        "--feature-id",
        "login_ui",
        "--task-body",
        "task one",
        "--outbox-path",
        "pools/thinking/Outbox/feat_001_b1",
    ]
    completed = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["batch_id"] == "feat_001"


def test_post_hold_cli_blocks_batch(tmp_path: Path):
    # First register a batch
    register_cmd = [
        sys.executable,
        "tools/post_register.py",
        "--root-dir",
        str(tmp_path),
        "--batch-id",
        "feat_002",
        "--name",
        "test feature",
        "--from-pool",
        "task",
        "--to-pool",
        "thinking",
        "--branch-id",
        "feat_002_b1",
        "--feature-id",
        "test_ui",
        "--task-body",
        "task body",
        "--outbox-path",
        "pools/thinking/Outbox/feat_002_b1",
    ]
    subprocess.run(register_cmd, cwd=Path(__file__).resolve().parents[1], capture_output=True)

    # Then hold it
    hold_cmd = [
        sys.executable,
        "tools/post_hold.py",
        "--root-dir",
        str(tmp_path),
        "--batch-id",
        "feat_002",
        "--action",
        "hold",
    ]
    completed = subprocess.run(hold_cmd, cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["action_type"] == "hold"


def test_post_status_cli_returns_batch_info(tmp_path: Path):
    # First register a batch
    register_cmd = [
        sys.executable,
        "tools/post_register.py",
        "--root-dir",
        str(tmp_path),
        "--batch-id",
        "feat_003",
        "--name",
        "status test",
        "--from-pool",
        "task",
        "--to-pool",
        "thinking",
        "--branch-id",
        "feat_003_b1",
        "--feature-id",
        "status_ui",
        "--task-body",
        "task body",
        "--outbox-path",
        "pools/thinking/Outbox/feat_003_b1",
    ]
    subprocess.run(register_cmd, cwd=Path(__file__).resolve().parents[1], capture_output=True)

    # Then query status
    status_cmd = [
        sys.executable,
        "tools/post_status.py",
        "--root-dir",
        str(tmp_path),
        "--batch-id",
        "feat_003",
    ]
    completed = subprocess.run(status_cmd, cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["batch_id"] == "feat_003"
    assert payload["status"] == "registered"


def test_post_modify_cli_updates_branch_target(tmp_path: Path):
    # Register a batch first
    register_cmd = [
        sys.executable,
        "tools/post_register.py",
        "--root-dir", str(tmp_path),
        "--batch-id", "feat_004",
        "--name", "modify test",
        "--from-pool", "task",
        "--to-pool", "thinking",
        "--branch-id", "feat_004_b1",
        "--feature-id", "modify_ui",
        "--task-body", "original body",
        "--outbox-path", "pools/thinking/Outbox/feat_004_b1",
    ]
    subprocess.run(register_cmd, cwd=Path(__file__).resolve().parents[1], capture_output=True)

    # Modify the branch
    modify_cmd = [
        sys.executable,
        "tools/post_modify.py",
        "--root-dir", str(tmp_path),
        "--batch-id", "feat_004",
        "--branch-id", "feat_004_b1",
        "--field", "task_body",
        "--value", "updated body",
    ]
    completed = subprocess.run(modify_cmd, cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["branch_id"] == "feat_004_b1"
    assert payload["task_body"] == "updated body"


def test_post_delete_cli_marks_branch_skipped(tmp_path: Path):
    # Register a batch first
    register_cmd = [
        sys.executable,
        "tools/post_register.py",
        "--root-dir", str(tmp_path),
        "--batch-id", "feat_005",
        "--name", "delete test",
        "--from-pool", "task",
        "--to-pool", "thinking",
        "--branch-id", "feat_005_b1",
        "--feature-id", "delete_ui",
        "--task-body", "task body",
        "--outbox-path", "pools/thinking/Outbox/feat_005_b1",
    ]
    subprocess.run(register_cmd, cwd=Path(__file__).resolve().parents[1], capture_output=True)

    # Delete (skip) the branch
    delete_cmd = [
        sys.executable,
        "tools/post_delete.py",
        "--root-dir", str(tmp_path),
        "--batch-id", "feat_005",
        "--branch-id", "feat_005_b1",
    ]
    completed = subprocess.run(delete_cmd, cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["branch_id"] == "feat_005_b1"
    assert payload["status"] == "skipped"


def test_post_manifest_cli_returns_batch_snapshot(tmp_path: Path):
    # Register a batch first
    register_cmd = [
        sys.executable,
        "tools/post_register.py",
        "--root-dir", str(tmp_path),
        "--batch-id", "feat_006",
        "--name", "manifest test",
        "--from-pool", "task",
        "--to-pool", "thinking",
        "--branch-id", "feat_006_b1",
        "--feature-id", "manifest_ui",
        "--task-body", "task body",
        "--outbox-path", "pools/thinking/Outbox/feat_006_b1",
    ]
    subprocess.run(register_cmd, cwd=Path(__file__).resolve().parents[1], capture_output=True)

    # Get manifest
    manifest_cmd = [
        sys.executable,
        "tools/post_manifest.py",
        "--root-dir", str(tmp_path),
        "--batch-id", "feat_006",
    ]
    completed = subprocess.run(manifest_cmd, cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["batch_id"] == "feat_006"
    assert payload["name"] == "manifest test"
    assert len(payload["branches"]) == 1
    assert payload["branches"][0]["branch_id"] == "feat_006_b1"


def test_post_dep_cli_creates_dependency(tmp_path: Path):
    # Register two batches
    for batch_id in ["feat_007", "feat_008"]:
        register_cmd = [
            sys.executable,
            "tools/post_register.py",
            "--root-dir", str(tmp_path),
            "--batch-id", batch_id,
            "--name", f"{batch_id} test",
            "--from-pool", "task",
            "--to-pool", "thinking",
            "--branch-id", f"{batch_id}_b1",
            "--feature-id", f"{batch_id}_ui",
            "--task-body", "task body",
            "--outbox-path", f"pools/thinking/Outbox/{batch_id}_b1",
        ]
        subprocess.run(register_cmd, cwd=Path(__file__).resolve().parents[1], capture_output=True)

    # Add dependency
    dep_cmd = [
        sys.executable,
        "tools/post_dep.py",
        "--root-dir", str(tmp_path),
        "--after", "feat_007",
        "--before", "feat_008",
        "--rule", "after_delivered",
    ]
    completed = subprocess.run(dep_cmd, cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["source_batch_id"] == "feat_007"
    assert payload["target_batch_id"] == "feat_008"
    assert payload["rule"] == "after_delivered"

def test_post_replay_cli_resets_delivery_status(tmp_path: Path):
    # Register a batch first
    register_cmd = [
        sys.executable,
        "tools/post_register.py",
        "--root-dir", str(tmp_path),
        "--batch-id", "feat_replay_001",
        "--name", "replay test",
        "--from-pool", "task",
        "--to-pool", "thinking",
        "--branch-id", "feat_replay_001_b1",
        "--feature-id", "replay_ui",
        "--task-body", "task body",
        "--outbox-path", "pools/thinking/Outbox/feat_replay_001_b1",
    ]
    subprocess.run(register_cmd, cwd=Path(__file__).resolve().parents[1], capture_output=True)

    # Replay the batch
    replay_cmd = [
        sys.executable,
        "tools/post_replay.py",
        "--root-dir", str(tmp_path),
        "--batch-id", "feat_replay_001",
    ]
    completed = subprocess.run(replay_cmd, cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["batch_id"] == "feat_replay_001"
    assert "feat_replay_001_b1" in payload["replayed_branches"]
    assert payload["action"]["action_type"] == "replay"
