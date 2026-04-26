"""TDD tests for Thinking BOOTSTRAP constraints."""

from pathlib import Path
import pytest


THINKING_BOOTSTRAP = Path("C:/Users/lenovo/Desktop/MultiAgentWorkspace1.0/runtime/tools/THINKING_BOOTSTRAP.txt")


def test_thinking_01_bootstrap_has_only_four_lifecycle_bats():
    """Verify that THINKING_BOOTSTRAP.txt template contains exactly 4 lifecycle bats and NO Failed/Blocked bats."""
    bootstrap_file = THINKING_BOOTSTRAP
    assert bootstrap_file.exists(), "THINKING_BOOTSTRAP.txt template not found"

    content = bootstrap_file.read_text(encoding="utf-8")

    # Must contain the core 4 bats for Thinking Pool
    assert "Online.bat" in content
    assert "StartThinking.bat" in content
    assert "StartSummarizing.bat" in content
    assert "Done.bat" in content

    # Must NOT contain obsolete bats
    assert "Failed.bat" not in content, "THINKING_BOOTSTRAP.txt should not reference Failed.bat"
    assert "Blocked.bat" not in content, "THINKING_BOOTSTRAP.txt should not reference Blocked.bat"

    # Must NOT contain Work-specific bats
    assert "StartWriting.bat" not in content, "THINKING_BOOTSTRAP.txt should not reference Work-specific StartWriting.bat"


def test_thinking_bootstrap_uses_bash_compatible_lifecycle_examples():
    """Thinking bootstrap must not teach Windows-only call/%VAR% syntax because Claude runs in bash."""
    bootstrap_file = THINKING_BOOTSTRAP
    content = bootstrap_file.read_text(encoding="utf-8")

    assert "call Online.bat" not in content
    assert "call StartThinking.bat" not in content
    assert "call StartSummarizing.bat" not in content
    assert "call Done.bat" not in content
    assert "%AGENT_ID%" not in content
    assert "%TASK_ID%" not in content
    assert 'cmd.exe /c "Online.bat $AGENT_ID $TASK_ID thinking online"' not in content
    assert 'cmd.exe /c "StartThinking.bat $AGENT_ID $TASK_ID thinking thinking"' not in content
    assert 'cmd.exe /c "Done.bat $AGENT_ID $TASK_ID thinking done"' not in content

    assert 'cmd //c ".\\\\Online.bat $AGENT_ID $TASK_ID thinking online"' in content
    assert 'cmd //c ".\\\\StartThinking.bat $AGENT_ID $TASK_ID thinking thinking"' in content
    assert 'cmd //c ".\\\\StartSummarizing.bat $AGENT_ID $TASK_ID thinking summarizing"' in content
    assert 'cmd //c ".\\\\Done.bat $AGENT_ID $TASK_ID thinking done"' in content


def test_thinking_bootstrap_uses_explicit_relative_bat_paths():
    """Thinking bootstrap must use .\\*.bat because cmd won't resolve bare batch names reliably from Git Bash."""
    bootstrap_file = THINKING_BOOTSTRAP
    content = bootstrap_file.read_text(encoding="utf-8")

    # Must NOT use bare bat names (cmd can't resolve them)
    assert 'cmd //c "Online.bat $AGENT_ID $TASK_ID thinking online"' not in content
    assert 'cmd //c "StartThinking.bat $AGENT_ID $TASK_ID thinking thinking"' not in content
    assert 'cmd //c "StartSummarizing.bat $AGENT_ID $TASK_ID thinking summarizing"' not in content
    assert 'cmd //c "Done.bat $AGENT_ID $TASK_ID thinking done"' not in content

    # Must use .\\ explicit relative paths
    assert 'cmd //c ".\\\\Online.bat $AGENT_ID $TASK_ID thinking online"' in content
    assert 'cmd //c ".\\\\StartThinking.bat $AGENT_ID $TASK_ID thinking thinking"' in content
    assert 'cmd //c ".\\\\StartSummarizing.bat $AGENT_ID $TASK_ID thinking summarizing"' in content
    assert 'cmd //c ".\\\\Done.bat $AGENT_ID $TASK_ID thinking done"' in content


def test_thinking_bootstrap_requires_reading_task_before_online():
    """Thinking must read task_*.txt BEFORE calling Online.bat so it uses the correct TASK_ID."""
    bootstrap_file = THINKING_BOOTSTRAP
    content = bootstrap_file.read_text(encoding="utf-8")
    lines = content.split('\n')

    flow_start = next(i for i, line in enumerate(lines) if "### 执行流程" in line)

    # Extract the numbered list part
    flow_lines = []
    for line in lines[flow_start+1:]:
        if line.strip() == "" and flow_lines:
            break
        if line.strip().startswith(("1.", "2.", "3.", "4.", "5.", "6.", "7.")):
            flow_lines.append(line.strip())

    # Ensure reading task comes before calling Online
    read_task_idx = next((i for i, line in enumerate(flow_lines) if "读取" in line and "task_" in line), -1)
    online_idx = next((i for i, line in enumerate(flow_lines) if "Online.bat" in line), -1)

    assert read_task_idx >= 0, "Missing step to read task_*.txt"
    assert online_idx >= 0, "Missing step to call Online.bat"
    assert read_task_idx < online_idx, f"Must read task BEFORE calling Online.bat. Current flow:\n" + "\n".join(flow_lines)


def test_thinking_bootstrap_excludes_work_and_gate_specific_content():
    """Thinking bootstrap must NOT contain Work-specific or Gate-specific instructions."""
    bootstrap_file = THINKING_BOOTSTRAP
    content = bootstrap_file.read_text(encoding="utf-8")

    # Must NOT contain Work-specific lifecycle bats
    assert "StartWriting.bat" not in content, "Thinking bootstrap should not reference Work-specific StartWriting.bat"

    # Must NOT contain Gate-specific lifecycle bats
    assert "StartReview.bat" not in content, "Thinking bootstrap should not reference Gate-specific StartReview.bat"
    assert "Accepted.bat" not in content, "Thinking bootstrap should not reference Gate-specific Accepted.bat"
    assert "Denied.bat" not in content, "Thinking bootstrap should not reference Gate-specific Denied.bat"

    # Must NOT contain Gate-specific workflow instructions
    assert "BATCH_FIELD" not in content, "Thinking bootstrap should not reference Gate-specific BATCH_FIELD"
    assert "审查通过" not in content, "Thinking bootstrap should not contain Gate review approval instructions"
    assert "审查拒绝" not in content, "Thinking bootstrap should not contain Gate review rejection instructions"

    # Work Pool example should be removed from lifecycle bat usage section
    assert "# Work Pool" not in content, "Thinking bootstrap should not have Work Pool example section"
    # Gate Pool example should be removed
    assert "# Gate Pool" not in content, "Thinking bootstrap should not have Gate Pool example section"
    # Construct Pool example should be removed
    assert "# Construct Pool" not in content, "Thinking bootstrap should not have Construct Pool example section"


def test_thinking_bootstrap_enforces_project_folder_output_semantic():
    """Thinking bootstrap must explicitly require creating XXX-(Vision)-(Mode) folder in workspace and placing task outputs inside."""
    bootstrap_file = THINKING_BOOTSTRAP
    content = bootstrap_file.read_text(encoding="utf-8")

    # Must mention deriving folder name from input task filename
    assert "任务文件名" in content or "输入文件名" in content or "task filename" in content.lower(), \
        "THINKING_BOOTSTRAP.txt must mention deriving folder name from input task filename"

    # Must mention creating a folder in workspace
    assert "workspace/" in content and ("文件夹" in content or "folder" in content.lower()), \
        "THINKING_BOOTSTRAP.txt must mention creating a folder in workspace/"

    # Must mention the XXX-(Vision)-(Mode) naming pattern
    assert "XXX-(Vision)-(Mode)" in content or "(Vision)" in content, \
        "THINKING_BOOTSTRAP.txt must mention the XXX-(Vision)-(Mode) naming pattern"

    # Must mention placing task outputs (.txt) inside the folder
    assert (".txt" in content and ("放入" in content or "放在" in content or "写入" in content or "place" in content.lower())), \
        "THINKING_BOOTSTRAP.txt must mention placing .txt task outputs inside the folder"
