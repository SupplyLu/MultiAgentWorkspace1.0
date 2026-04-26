import pytest
from pathlib import Path
from app.runtimes.construct_runtime import ConstructRuntime

def test_construct_preserves_project_key_without_batch_prefix(tmp_path):
    """
    Test that ConstructRuntime does not prepend 'batch_' to project folders,
    preserving the XXX-(Vision)-(Mode) strict naming convention.
    """
    # 1. Setup Construct Pool
    construct_pool = tmp_path / "pools" / "construct"
    queue_dir = construct_pool / "Queue"
    queue_dir.mkdir(parents=True)
    outbox_dir = construct_pool / "Outbox"
    outbox_dir.mkdir(parents=True)
    fields_dir = construct_pool / "fields"
    fields_dir.mkdir(parents=True)
    
    # Setup tools
    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True)
    for f in ["Online.bat", "StartArchitecting.bat", "StartFinalizing.bat", "Done.bat", "signal_bridge.py", "CONSTRUCT_BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")
        
    # Setup Slot
    slot_dir = construct_pool / "constructor_01"
    slot_dir.mkdir(parents=True)
    (slot_dir / "workspace").mkdir()

    runtime = ConstructRuntime(root_dir=tmp_path, signal_port=19024)
    
    # 2. Put a project folder in Queue
    project_key = "SignalOfBridge-v1-Build"
    project_dir = queue_dir / project_key
    project_dir.mkdir()
    (project_dir / "summary.txt").write_text(f"BATCH_ID: {project_key}", encoding="utf-8")
    
    # 3. Preprocess folders (simulate listing tasks)
    tasks = runtime.list_queue_tasks()
    
    # 4. Verify no "task_batch_" prefix is added to the reference file
    assert any(t.name == f"task_{project_key}.txt" for t in tasks), "Reference file should not have batch_ prefix"
    
    # 5. Mock launch and dispatch
    import app.shared.launch_manager as lm_module
    original_launch = lm_module.LaunchManager.launch
    def mock_launch(self, request, dry_run=True):
        return {"launched": True, "dry_run": True}
    lm_module.LaunchManager.launch = mock_launch
    
    try:
        dispatch_res = runtime.dispatch_next(dry_run=True)
        assert dispatch_res["dispatched"] is True
        assert dispatch_res["task_id"] == project_key, "TASK_ID should not have batch_ prefix"
        
        # 6. Verify Outbox collection uses the exact project key
        (slot_dir / "workspace" / "artifact.txt").write_text("done")
        
        collect_res = runtime.collect_artifacts_to_outbox("constructor_01", dispatch_res["task_id"])
        assert collect_res["collected"] is True
        
        final_outbox = outbox_dir / project_key
        assert final_outbox.exists() and final_outbox.is_dir(), f"Outbox directory {final_outbox} should exist without prefix"
    finally:
        lm_module.LaunchManager.launch = original_launch
