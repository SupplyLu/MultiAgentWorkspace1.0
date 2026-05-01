"""Test GateRuntime path trust fixes (Group B security hardening).

验证 GateRuntime 不再信任外部传入的路径，而是从受控 ID 派生内部路径。
"""

from pathlib import Path
import pytest

from app.runtimes.gate_runtime import GateRuntime


def test_build_project_task_txt_does_not_trust_external_field_dir(tmp_path):
    """Test that _build_project_task_txt() does not write external field_dir path into BATCH_FIELD.

    Security requirement: BATCH_FIELD should only contain project_key, not absolute paths.
    Runtime should derive field_dir internally from project_key.
    """
    gate_pool = tmp_path / "pools" / "gate"
    (gate_pool / "Queue").mkdir(parents=True)
    (gate_pool / "Outbox").mkdir(parents=True)
    (gate_pool / "Rejectbox").mkdir(parents=True)
    (gate_pool / "fields").mkdir(parents=True)

    slot_dir = gate_pool / "guard_01"
    slot_dir.mkdir(parents=True)
    (slot_dir / "workspace").mkdir()

    runtime = GateRuntime(root_dir=tmp_path, signal_port=19250)

    # Simulate malicious external path
    malicious_path = Path("/etc/passwd")
    project_key = "SignalBridge-v1-Build"

    # Call the internal method
    task_txt = runtime._build_project_task_txt(project_key, malicious_path)

    # Verify: BATCH_FIELD should NOT contain the external path
    assert "BATCH_FIELD:" in task_txt

    # Extract BATCH_FIELD value
    for line in task_txt.splitlines():
        if line.startswith("BATCH_FIELD:"):
            field_value = line.split(":", 1)[1].strip()
            break
    else:
        pytest.fail("BATCH_FIELD not found in task txt")

    # Security assertion: field value should be project_key only, not absolute path
    assert field_value == project_key, f"Expected project_key '{project_key}', got '{field_value}'"
    assert "/etc/passwd" not in task_txt, "External path leaked into task txt"
    assert str(malicious_path) not in task_txt, "External path leaked into task txt"
