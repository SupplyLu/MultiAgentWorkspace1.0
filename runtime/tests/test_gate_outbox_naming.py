"""
Test Gate Outbox naming convention: project_key-seq-task_suffix.txt

Gate should output flat .txt files with naming format:
- {project_key}-{seq}-{task_suffix}.txt
- Example: E2ETest-v1-Build-001-task1.txt
- Example: E2ETest-v1-Build-001-task1（simulinkui）.txt

This ensures the project key remains the primary identifier with all atomic
task information appended as suffixes.
"""

import tempfile
from pathlib import Path

from app.runtimes.gate_runtime import GateRuntime


def test_gate_outbox_uses_project_key_prefix_with_task_suffix():
    """
    When guard approves a project-based task with task_*.txt files,
    Gate Runtime should output flat .txt files with naming format:
    {project_key}-{seq}-{task_suffix}.txt

    This preserves the project key as the primary identifier and appends
    atomic task information as suffixes.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        gate_pool = root / "pools" / "gate"
        outbox_dir = gate_pool / "Outbox"
        outbox_dir.mkdir(parents=True)

        queue_dir = gate_pool / "Queue"
        queue_dir.mkdir(parents=True)

        guard_dir = gate_pool / "guard_01"
        workspace_dir = guard_dir / "workspace"
        workspace_dir.mkdir(parents=True)

        # Guard reviews project E2ETest-v1-Build and produces approved task files
        (workspace_dir / "task_001.txt").write_text(
            "FROM: gate\nTO: work\nTASK_ID: task_001\nTITLE: task1\n---\nApproved work task 1",
            encoding="utf-8"
        )
        (workspace_dir / "task_002.txt").write_text(
            "FROM: gate\nTO: work\nTASK_ID: task_002\nTITLE: task2（simulinkui）\n---\nApproved work task 2",
            encoding="utf-8"
        )

        runtime = GateRuntime(root_dir=root, signal_port=19299)

        slot = runtime.get_slot("guard_01")
        slot.busy = True
        slot.assigned_task_id = "E2ETest-v1-Build"

        # Guard sends approved signal
        runtime.handle_signal({
            "agent_id": "guard_01",
            "task_id": "E2ETest-v1-Build",
            "signal": "approved",
            "to_state": "state_3_approved",
            "is_terminal": True,
        })

        # Gate Outbox should contain flat .txt files with project_key prefix
        expected_files = [
            "E2ETest-v1-Build-001-task1.txt",
            "E2ETest-v1-Build-002-task2（simulinkui）.txt",
        ]

        outbox_files = sorted([f.name for f in outbox_dir.iterdir() if f.is_file() and f.suffix == ".txt"])

        assert len(outbox_files) == 2, f"Expected 2 files, got {len(outbox_files)}: {outbox_files}"

        for expected in expected_files:
            assert expected in outbox_files, (
                f"Expected file '{expected}' not found in Outbox. "
                f"Got: {outbox_files}"
            )

        # Verify no directories were created (flat file structure)
        outbox_dirs = [d for d in outbox_dir.iterdir() if d.is_dir()]
        assert len(outbox_dirs) == 0, (
            f"Gate Outbox should contain only flat .txt files, not directories. "
            f"Found directories: {[d.name for d in outbox_dirs]}"
        )

        # Verify slot released
        assert slot.busy is False
        assert slot.assigned_task_id == ""
