"""TDD tests for Worker BOOTSTRAP constraints."""

from pathlib import Path
import pytest


WORK_BOOTSTRAP = Path("C:/Users/lenovo/Desktop/MultiAgentWorkspace1.0/runtime/tools/WORK_BOOTSTRAP.txt")


def test_worker_01_bootstrap_has_only_three_lifecycle_bats():
    """Verify that worker WORK_BOOTSTRAP.txt template contains exactly 3 lifecycle bats and NO Failed/Blocked bats."""
    bootstrap_file = WORK_BOOTSTRAP
    assert bootstrap_file.exists(), "WORK_BOOTSTRAP.txt template not found"

    content = bootstrap_file.read_text(encoding="utf-8")

    # Must contain the core 3 bats
    assert "Online.bat" in content
    assert "StartWriting.bat" in content
    assert "Done.bat" in content

    # Must NOT contain obsolete bats
    assert "Failed.bat" not in content, "WORK_BOOTSTRAP.txt should not reference Failed.bat"
    assert "Blocked.bat" not in content, "WORK_BOOTSTRAP.txt should not reference Blocked.bat"


def test_worker_bootstrap_uses_bash_compatible_lifecycle_examples():
    """Worker bootstrap must not teach Windows-only call/%VAR% syntax because Claude runs in bash."""
    bootstrap_file = WORK_BOOTSTRAP
    content = bootstrap_file.read_text(encoding="utf-8")

    assert "call Online.bat" not in content
    assert "call StartWriting.bat" not in content
    assert "call Done.bat" not in content
    assert "%AGENT_ID%" not in content
    assert "%TASK_ID%" not in content
    assert 'cmd.exe /c "Online.bat $AGENT_ID $TASK_ID work online"' not in content
    assert 'cmd.exe /c "StartWriting.bat $AGENT_ID $TASK_ID work writing"' not in content
    assert 'cmd.exe /c "Done.bat $AGENT_ID $TASK_ID work done"' not in content

    assert 'cmd //c ".\\\\Online.bat $AGENT_ID $TASK_ID work online"' in content
    assert 'cmd //c ".\\\\StartWriting.bat $AGENT_ID $TASK_ID work writing"' in content
    assert 'cmd //c ".\\\\Done.bat $AGENT_ID $TASK_ID work done"' in content

def test_worker_bootstrap_uses_explicit_relative_bat_paths():
    """Worker bootstrap must use .\\*.bat because cmd won't resolve bare batch names reliably from Git Bash."""
    bootstrap_file = WORK_BOOTSTRAP
    content = bootstrap_file.read_text(encoding="utf-8")

    # Must NOT use bare bat names (cmd can't resolve them)
    assert 'cmd //c "Online.bat $AGENT_ID $TASK_ID work online"' not in content
    assert 'cmd //c "StartWriting.bat $AGENT_ID $TASK_ID work writing"' not in content
    assert 'cmd //c "Done.bat $AGENT_ID $TASK_ID work done"' not in content

    # Must use .\\ explicit relative paths
    assert 'cmd //c ".\\\\Online.bat $AGENT_ID $TASK_ID work online"' in content
    assert 'cmd //c ".\\\\StartWriting.bat $AGENT_ID $TASK_ID work writing"' in content
    assert 'cmd //c ".\\\\Done.bat $AGENT_ID $TASK_ID work done"' in content


def test_worker_bootstrap_requires_reading_task_before_online():
    """Worker must read task_*.txt BEFORE calling Online.bat so it uses the correct TASK_ID."""
    bootstrap_file = WORK_BOOTSTRAP
    content = bootstrap_file.read_text(encoding="utf-8")
    lines = content.split('\n')

    flow_start = next(i for i, line in enumerate(lines) if "### 执行流程" in line)

    # Extract the numbered list part
    flow_lines = []
    for line in lines[flow_start+1:]:
        if line.strip() == "" and flow_lines:
            break
        if line.strip().startswith(("1.", "2.", "3.", "4.", "5.", "6.")):
            flow_lines.append(line.strip())

    # Ensure reading task comes before calling Online
    read_task_idx = next((i for i, line in enumerate(flow_lines) if "读取" in line and "task_" in line), -1)
    online_idx = next((i for i, line in enumerate(flow_lines) if "Online.bat" in line), -1)

    assert read_task_idx >= 0, "Missing step to read task_*.txt"
    assert online_idx >= 0, "Missing step to call Online.bat"
    assert read_task_idx < online_idx, f"Must read task BEFORE calling Online.bat. Current flow:\n" + "\n".join(flow_lines)


def test_work_bootstrap_excludes_gate_specific_content():
    """Work bootstrap must NOT contain Gate-specific instructions (StartReview/Accepted/Denied/BATCH_FIELD)."""
    bootstrap_file = WORK_BOOTSTRAP
    content = bootstrap_file.read_text(encoding="utf-8")

    # Must NOT contain Gate-specific lifecycle bats
    assert "StartReview.bat" not in content, "Work bootstrap should not reference Gate-specific StartReview.bat"
    assert "Accepted.bat" not in content, "Work bootstrap should not reference Gate-specific Accepted.bat"
    assert "Denied.bat" not in content, "Work bootstrap should not reference Gate-specific Denied.bat"

    # Must NOT contain Gate-specific workflow instructions
    assert "BATCH_FIELD" not in content, "Work bootstrap should not reference Gate-specific BATCH_FIELD"
    assert "审查通过" not in content, "Work bootstrap should not contain Gate review approval instructions"
    assert "审查拒绝" not in content, "Work bootstrap should not contain Gate review rejection instructions"

    # Gate Pool example should be removed from lifecycle bat usage section
    assert "# Gate Pool" not in content, "Work bootstrap should not have Gate Pool example section"
