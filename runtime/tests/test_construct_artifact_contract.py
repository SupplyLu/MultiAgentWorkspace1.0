import pytest
import shutil
from pathlib import Path
from app.runtimes.construct_runtime import ConstructRuntime

def test_construct_runtime_task_generation_contract(tmp_path: Path):
    """
    Test that ConstructRuntime correctly generates reference tasks that direct
    workers to output artifacts to their workspace/, NOT to BATCH_FIELD/output/.
    """
    # 1. Create a dummy Construct pool environment
    construct_pool_dir = tmp_path / "pools" / "construct"
    queue_dir = construct_pool_dir / "Queue"
    queue_dir.mkdir(parents=True)

    # Create a dummy batch folder in Queue
    batch_dir = queue_dir / "t_pmsm_foc_sim_001"
    batch_dir.mkdir()
    (batch_dir / "summary.txt").write_text("BATCH_ID: t_pmsm_foc_sim_001", encoding="utf-8")

    # 2. Initialize ConstructRuntime with dummy paths
    runtime = ConstructRuntime(root_dir=tmp_path)
    # Ensure it sees our dummy directories
    runtime._queue_dir = queue_dir
    runtime._construct_fields_dir = construct_pool_dir / "fields"
    runtime._construct_fields_dir.mkdir(parents=True, exist_ok=True)

    # 3. Trigger folder preprocessing
    runtime._preprocess_queue_folders()

    # 4. Verify the generated task reference file
    ref_file = queue_dir / "task_t_pmsm_foc_sim_001.txt"
    assert ref_file.exists(), "Reference task file should be generated"

    content = ref_file.read_text(encoding="utf-8")

    # The regression we are testing for:
    # The generated instructions should explicitly tell the worker to output to workspace/
    # It must preserve PROJECT_ROOT planning semantics for Work fields
    # It must NOT direct the worker to output to BATCH_FIELD/output/
    # It must NOT direct the worker to write any task into downstream Queue

    assert "into workspace/" in content, (
        "Contract violation: Task template does not explicitly tell worker "
        "to output to workspace/ (which is required by BOOTSTRAP and "
        "collect_artifacts_to_outbox)."
    )

    assert "PROJECT_ROOT:" in content, (
        "Contract violation: Construct task template must preserve PROJECT_ROOT so the constructor "
        "can create or specify the Work field project root without performing downstream delivery."
    )

    assert "to BATCH_FIELD/output/" not in content or "Do NOT" in content.split("to BATCH_FIELD/output/")[0].splitlines()[-1], (
        "Contract violation: Task template still directs worker to output to "
        "BATCH_FIELD/output/ as a positive directive, which will be lost during cleanup. "
        "It may only appear in a Do NOT / forbidden statement."
    )

    assert "pools/work/Queue" not in content, (
        "Contract violation: Construct task template must not direct any concrete downstream Queue delivery."
    )
    assert "write any task file to downstream Queue" in content or "Do NOT write any task file to downstream Queue" in content, (
        "Contract violation: Construct task template must explicitly forbid downstream Queue delivery."
    )

    # The template must contain a clear positive directive to output to workspace
    lines = content.splitlines()
    workspace_directive = [l for l in lines if "workspace/" in l and ("Write" in l or "Output" in l or "Deliver" in l)]
    assert workspace_directive, (
        "Contract violation: Task template must contain an explicit positive directive "
        "(Write/Output/Deliver) to workspace/, not just a prohibition."
    )
