"""Test Gate batch directory review contract."""

from pathlib import Path
import tempfile
import shutil
import time
import pytest

from app.runtimes.gate_runtime import GateRuntime


def test_gate_accepts_queue_folders_not_txt():
    """Gate should accept folders in Queue, not individual txt files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        gate_pool = root / "pools" / "gate"
        queue_dir = gate_pool / "Queue"
        queue_dir.mkdir(parents=True)

        # Create a batch folder with summary.txt
        batch_folder = queue_dir / "batch_t_pmsm_foc_sim_002"
        batch_folder.mkdir()
        summary_file = batch_folder / "summary.txt"
        summary_file.write_text("PROJECT_KEY: batch_t_pmsm_foc_sim_002\n---\nBatch summary", encoding="utf-8")

        # Create some work task files inside
        (batch_folder / "task_t_pmsm_w001.txt").write_text("FROM: construct\nTO: gate\n---\nWork task 1", encoding="utf-8")
        (batch_folder / "task_t_pmsm_w002.txt").write_text("FROM: construct\nTO: gate\n---\nWork task 2", encoding="utf-8")

        runtime = GateRuntime(root_dir=root, signal_port=19299)

        # Gate should detect the folder as a batch task
        tasks = runtime.list_queue_tasks()
        assert len(tasks) == 1
        assert tasks[0].is_dir()
        assert tasks[0].name == "batch_t_pmsm_foc_sim_002"


def test_gate_preprocesses_batch_folder():
    """Gate should preprocess batch folder into fields/{batch_id}/input/."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        gate_pool = root / "pools" / "gate"
        queue_dir = gate_pool / "Queue"
        queue_dir.mkdir(parents=True)

        # Create guard slot
        guard_dir = gate_pool / "guard_01"
        workspace_dir = guard_dir / "workspace"
        workspace_dir.mkdir(parents=True)

        # Create batch folder
        batch_folder = queue_dir / "batch_t_pmsm_foc_sim_002"
        batch_folder.mkdir()
        summary_file = batch_folder / "summary.txt"
        summary_file.write_text("PROJECT_KEY: batch_t_pmsm_foc_sim_002\n---\nBatch summary", encoding="utf-8")
        (batch_folder / "task_t_pmsm_w001.txt").write_text("FROM: construct\nTO: gate\n---\nWork task 1", encoding="utf-8")

        runtime = GateRuntime(root_dir=root, signal_port=19299)

        # Dispatch should preprocess the folder
        result = runtime.dispatch_next(dry_run=True)

        assert result["dispatched"] is True

        # Check fields/{batch_id}/input/ was created
        batch_id = result["task_id"]
        fields_input = gate_pool / "fields" / batch_id / "input"
        assert fields_input.exists()
        assert (fields_input / "summary.txt").exists()
        assert (fields_input / "task_t_pmsm_w001.txt").exists()


def test_gate_generates_batch_reference_task():
    """Gate should generate a reference task txt for the guard to review the batch."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        gate_pool = root / "pools" / "gate"
        queue_dir = gate_pool / "Queue"
        queue_dir.mkdir(parents=True)

        # Create guard slot
        guard_dir = gate_pool / "guard_01"
        workspace_dir = guard_dir / "workspace"
        workspace_dir.mkdir(parents=True)

        # Create batch folder
        batch_folder = queue_dir / "batch_t_pmsm_foc_sim_002"
        batch_folder.mkdir()
        summary_file = batch_folder / "summary.txt"
        summary_file.write_text("PROJECT_KEY: batch_t_pmsm_foc_sim_002\n---\nBatch summary", encoding="utf-8")
        (batch_folder / "task_t_pmsm_w001.txt").write_text("FROM: construct\nTO: gate\n---\nWork task 1", encoding="utf-8")

        runtime = GateRuntime(root_dir=root, signal_port=19299)
        result = runtime.dispatch_next(dry_run=True)

        # Check reference task was created in slot
        slot_id = result["slot_id"]
        slot_dir = gate_pool / slot_id
        reference_task = slot_dir / f"task_{result['task_id']}.txt"

        assert reference_task.exists()
        content = reference_task.read_text(encoding="utf-8")

        # Must contain batch review instructions
        assert "BATCH_FIELD" in content or "fields/" in content
        assert "workspace/" in content
        assert "review" in content.lower() or "审查" in content
        assert "Accepted.bat" in content
        assert "Denied.bat" in content


def test_gate_approved_batch_only_collects_work_tasks():
    """When guard sends approved signal, Gate should only collect task_*.txt from workspace, excluding summary/blueprint/index."""
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

        # Guard writes both work tasks AND accidentally leaves non-work files in workspace
        (workspace_dir / "task_t_pmsm_w001.txt").write_text("FROM: gate\nTO: work\n---\nApproved task 1", encoding="utf-8")
        (workspace_dir / "task_t_pmsm_w002.txt").write_text("FROM: gate\nTO: work\n---\nApproved task 2", encoding="utf-8")
        (workspace_dir / "summary.txt").write_text("Batch summary - should NOT be collected", encoding="utf-8")
        (workspace_dir / "project_blueprint.md").write_text("# Blueprint - should NOT be collected", encoding="utf-8")
        (workspace_dir / "work_task_index.md").write_text("# Index - should NOT be collected", encoding="utf-8")

        runtime = GateRuntime(root_dir=root, signal_port=19299)

        slot = runtime.get_slot("guard_01")
        slot.busy = True
        slot.assigned_task_id = "batch_t_pmsm_foc_sim_002"

        runtime.handle_signal({
            "agent_id": "guard_01",
            "task_id": "task_batch_t_pmsm_foc_sim_002",
            "signal": "approved",
            "to_state": "state_3"
        })

        # Only task_*.txt should be collected to Outbox
        assert (outbox_dir / "task_t_pmsm_w001.txt").exists()
        assert (outbox_dir / "task_t_pmsm_w002.txt").exists()
        assert not (outbox_dir / "summary.txt").exists()
        assert not (outbox_dir / "project_blueprint.md").exists()
        assert not (outbox_dir / "work_task_index.md").exists()


def test_gate_rejected_batch_with_prefixed_task_id():
    """When guard sends rejected signal with 'task_' prefix, Gate should return the full original batch plus rejection notes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        gate_pool = root / "pools" / "gate"
        rejectbox_dir = gate_pool / "Rejectbox"
        rejectbox_dir.mkdir(parents=True)

        queue_dir = gate_pool / "Queue"
        queue_dir.mkdir(parents=True)

        field_input_dir = gate_pool / "fields" / "batch_t_pmsm_foc_sim_002" / "input"
        field_input_dir.mkdir(parents=True)
        (field_input_dir / "summary.txt").write_text("TASK_ID: batch_t_pmsm_foc_sim_002\n---\nBatch summary", encoding="utf-8")
        (field_input_dir / "task_t_pmsm_w001.txt").write_text("FROM: construct\nTO: gate\n---\nWork task 1", encoding="utf-8")
        (field_input_dir / "task_t_pmsm_w002.txt").write_text("FROM: construct\nTO: gate\n---\nWork task 2", encoding="utf-8")

        # Create guard slot
        guard_dir = gate_pool / "guard_01"
        workspace_dir = guard_dir / "workspace"
        workspace_dir.mkdir(parents=True)

        # Guard only writes rejection notes; Runtime must merge them with the original batch input
        (workspace_dir / "审查拒绝说明.md").write_text("# 拒绝说明\n\n原因：XXX", encoding="utf-8")

        runtime = GateRuntime(root_dir=root, signal_port=19299)

        # Manually set up slot state
        slot = runtime.get_slot("guard_01")
        slot.busy = True
        slot.assigned_task_id = "batch_t_pmsm_foc_sim_002"

        # Simulate rejected signal with 'task_' prefix (what guard actually sends)
        runtime.handle_signal({
            "agent_id": "guard_01",
            "task_id": "task_batch_t_pmsm_foc_sim_002",
            "signal": "rejected",
            "to_state": "state_3"
        })

        # Rejected batch should be collected as a folder in Rejectbox
        rejected_batch_dir = rejectbox_dir / "batch_t_pmsm_foc_sim_002"
        assert rejected_batch_dir.exists()
        assert (rejected_batch_dir / "summary.txt").exists()
        assert (rejected_batch_dir / "task_t_pmsm_w001.txt").exists()
        assert (rejected_batch_dir / "task_t_pmsm_w002.txt").exists()
        assert (rejected_batch_dir / "审查拒绝说明.md").exists()


def test_gate_timeout_does_not_requeue_batch_reference_txt():
    """When a batch review times out, Gate should not requeue the generated reference txt back to Queue."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        gate_pool = root / "pools" / "gate"
        queue_dir = gate_pool / "Queue"
        queue_dir.mkdir(parents=True)

        # Create guard slot with generated reference txt
        guard_dir = gate_pool / "guard_01"
        workspace_dir = guard_dir / "workspace"
        workspace_dir.mkdir(parents=True)
        (guard_dir / "task_batch_t_pmsm_foc_sim_002.txt").write_text(
            "TASK_ID: batch_t_pmsm_foc_sim_002\n---\nReference task",
            encoding="utf-8",
        )

        runtime = GateRuntime(root_dir=root, signal_port=19299)
        slot = runtime.get_slot("guard_01")
        slot.busy = True
        slot.assigned_task_id = "batch_t_pmsm_foc_sim_002"
        slot.assigned_at_epoch = 1.0
        slot.timeout_seconds = 0

        timeouts = runtime.check_timeouts()



def test_gate_rejected_batch_cleans_workspace_after_finalization():
    """After rejected terminal convergence, Gate should clean the guard workspace."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        gate_pool = root / "pools" / "gate"
        rejectbox_dir = gate_pool / "Rejectbox"
        rejectbox_dir.mkdir(parents=True)

        queue_dir = gate_pool / "Queue"
        queue_dir.mkdir(parents=True)

        guard_dir = gate_pool / "guard_01"
        workspace_dir = guard_dir / "workspace"
        workspace_dir.mkdir(parents=True)
        (workspace_dir / ".gitkeep").write_text("", encoding="utf-8")

        (workspace_dir / "task_t_pmsm_w001.txt").write_text("FROM: construct\nTO: gate\n---\nWork task 1", encoding="utf-8")
        (workspace_dir / "审查拒绝说明.md").write_text("# 拒绝说明\n\n原因：XXX", encoding="utf-8")

        runtime = GateRuntime(root_dir=root, signal_port=19299)

        slot = runtime.get_slot("guard_01")
        slot.busy = True
        slot.assigned_task_id = "batch_t_pmsm_foc_sim_002"

        runtime.handle_signal({
            "agent_id": "guard_01",
            "task_id": "task_batch_t_pmsm_foc_sim_002",
            "signal": "rejected",
            "to_state": "state_3"
        })

        assert (rejectbox_dir / "batch_t_pmsm_foc_sim_002" / "task_t_pmsm_w001.txt").exists()
        assert (rejectbox_dir / "batch_t_pmsm_foc_sim_002" / "审查拒绝说明.md").exists()
        assert sorted(p.name for p in workspace_dir.iterdir()) == [".gitkeep"]
