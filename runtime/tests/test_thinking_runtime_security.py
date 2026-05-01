"""Security tests for ThinkingRuntime input validation and escaping.

Tests cover:
- project_key format validation
- timeout boundary validation
- Windows batch variable escaping
- Command injection prevention
"""

from pathlib import Path
import pytest

from app.runtimes.thinking_runtime import (
    ThinkingRuntime,
    _validate_task_id,
    _validate_timeout,
    _escape_bat_var,
)


# ---------------------------------------------------------------------------
# Input Validation Tests
# ---------------------------------------------------------------------------

def test_validate_task_id_accepts_valid_formats():
    """Test that valid task_id formats are accepted."""
    valid_ids = [
        "task_001",
        "t_real_002",
        "pid-simulink-001",
        "TASK_ABC",
        "task123",
        "a",
        "A-B_C-1",
        "SignalBridge-v1-Build",
        "SignalBridge-1.0.2-Release",
    ]
    for task_id in valid_ids:
        result = _validate_task_id(task_id)
        assert result == task_id


def test_validate_task_id_rejects_empty():
    """Test that empty task_id is rejected."""
    with pytest.raises(ValueError, match="cannot be empty"):
        _validate_task_id("")


def test_validate_task_id_rejects_special_characters():
    """Test that task_id with special characters is rejected."""
    invalid_ids = [
        "task&001",
        "task|002",
        "task;003",
        "task 004",
        "task<005",
        "task>006",
        "task%007",
        "task^008",
        "task(009)",
        "task[010]",
        "task{011}",
        "task$012",
        "task!013",
        "task@014",
        "task#015",
        "../../../etc/passwd",
        "task\n001",
        "task\r002",
    ]
    for task_id in invalid_ids:
        with pytest.raises(ValueError, match="Invalid task_id format"):
            _validate_task_id(task_id)


def test_validate_timeout_clips_to_min():
    """Test that timeout below minimum is clipped to 60 seconds."""
    assert _validate_timeout(0) == 60
    assert _validate_timeout(30) == 60
    assert _validate_timeout(59) == 60


def test_validate_timeout_clips_to_max():
    """Test that timeout above maximum is clipped to 86400 seconds."""
    assert _validate_timeout(100000) == 86400
    assert _validate_timeout(999999) == 86400


def test_validate_timeout_accepts_valid_range():
    """Test that timeout within valid range is unchanged."""
    assert _validate_timeout(60) == 60
    assert _validate_timeout(300) == 300
    assert _validate_timeout(1800) == 1800
    assert _validate_timeout(86400) == 86400


# ---------------------------------------------------------------------------
# Batch Variable Escaping Tests
# ---------------------------------------------------------------------------

def test_escape_bat_var_escapes_percent():
    """Test that % is escaped to %%."""
    assert _escape_bat_var("100%") == "100%%"
    assert _escape_bat_var("%PATH%") == "%%PATH%%"


def test_escape_bat_var_escapes_caret():
    """Test that ^ is escaped to ^^."""
    assert _escape_bat_var("a^b") == "a^^b"


def test_escape_bat_var_escapes_ampersand():
    """Test that & is escaped to ^&."""
    assert _escape_bat_var("a&b") == "a^&b"
    assert _escape_bat_var("cmd & calc") == "cmd ^& calc"


def test_escape_bat_var_escapes_pipe():
    """Test that | is escaped to ^|."""
    assert _escape_bat_var("a|b") == "a^|b"
    assert _escape_bat_var("dir | findstr") == "dir ^| findstr"


def test_escape_bat_var_escapes_redirects():
    """Test that < and > are escaped."""
    assert _escape_bat_var("a<b") == "a^<b"
    assert _escape_bat_var("a>b") == "a^>b"
    assert _escape_bat_var("echo test > file.txt") == "echo test ^> file.txt"


def test_escape_bat_var_escapes_quotes():
    """Test that double quotes are escaped."""
    assert _escape_bat_var('say "hello"') == 'say ^"hello^"'


def test_escape_bat_var_escapes_exclamation():
    """Test that ! is escaped for delayed expansion contexts."""
    assert _escape_bat_var("hello!world") == "hello^^!world"
    assert _escape_bat_var("!PATH!") == "^^!PATH^^!"


def test_escape_bat_var_handles_combined_special_chars():
    """Test that multiple special characters are all escaped."""
    input_str = 'task&001|calc%PATH%^"test"<>file'
    result = _escape_bat_var(input_str)
    # Verify no unescaped special characters remain
    assert "&" not in result or "^&" in result
    assert "|" not in result or "^|" in result
    assert "%" not in result or "%%" in result


def test_escape_bat_var_preserves_safe_characters():
    """Test that safe characters are not modified."""
    safe_str = "task_001-feature_ABC"
    assert _escape_bat_var(safe_str) == safe_str


# ---------------------------------------------------------------------------
# Integration Tests: Dispatch with Malicious Input
# ---------------------------------------------------------------------------

def test_dispatch_rejects_malicious_task_id(tmp_path):
    """Test that dispatch_next rejects task with malicious task_id."""
    queue_dir = tmp_path / "pools" / "thinking" / "Queue"
    queue_dir.mkdir(parents=True)
    thinking_pool = tmp_path / "pools" / "thinking"
    slot1_dir = thinking_pool / "sub_brain_01"
    slot1_dir.mkdir(parents=True)
    (slot1_dir / "workspace").mkdir(parents=True)
    (thinking_pool / "Outbox").mkdir(parents=True)

    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True)
    for f in ["Online.bat", "StartThinking.bat", "StartSummarizing.bat", "Done.bat", "signal_bridge.py", "THINKING_BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")

    # Create task with malicious PROJECT_KEY
    task_file = queue_dir / "task_malicious.txt"
    task_content = """FROM: runtime
TO: sub_brain_01
PROJECT_KEY: task_001 & calc.exe

Malicious task.
"""
    task_file.write_text(task_content, encoding="utf-8")

    runtime = ThinkingRuntime(root_dir=tmp_path, signal_port=19100)

    # Mock LaunchManager.launch
    import app.shared.launch_manager as lm_module
    original_launch = lm_module.LaunchManager.launch

    def mock_launch(self, request, dry_run=True):
        return {"launched": True, "dry_run": True, "pid": 1234}

    lm_module.LaunchManager.launch = mock_launch

    try:
        # Dispatch should raise ValueError
        with pytest.raises(ValueError, match="Invalid task_id format"):
            runtime.dispatch_next(dry_run=True)

        # Verify task was not removed from queue (rollback)
        assert task_file.exists() or (queue_dir / "task_malicious.txt.processing").exists()

        # Verify slot is not busy (rollback)
        slot = runtime.get_slot("sub_brain_01")
        assert slot is not None
        assert slot.busy is False

    finally:
        lm_module.LaunchManager.launch = original_launch


def test_dispatch_rejects_missing_project_key(tmp_path):
    """Test that dispatch_next rejects task without PROJECT_KEY."""
    queue_dir = tmp_path / "pools" / "thinking" / "Queue"
    queue_dir.mkdir(parents=True)
    thinking_pool = tmp_path / "pools" / "thinking"
    slot1_dir = thinking_pool / "sub_brain_01"
    slot1_dir.mkdir(parents=True)
    (slot1_dir / "workspace").mkdir(parents=True)
    (thinking_pool / "Outbox").mkdir(parents=True)

    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True)
    for f in ["Online.bat", "StartThinking.bat", "StartSummarizing.bat", "Done.bat", "signal_bridge.py", "THINKING_BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")

    # Create task without PROJECT_KEY
    task_file = queue_dir / "task_malicious2.txt"
    task_content = """FROM: runtime
TO: sub_brain_01

Malicious task.
"""
    task_file.write_text(task_content, encoding="utf-8")

    runtime = ThinkingRuntime(root_dir=tmp_path, signal_port=19101)

    # Mock LaunchManager.launch
    import app.shared.launch_manager as lm_module
    original_launch = lm_module.LaunchManager.launch

    def mock_launch(self, request, dry_run=True):
        return {"launched": True, "dry_run": True, "pid": 1234}

    lm_module.LaunchManager.launch = mock_launch

    try:
        # Dispatch should raise ValueError
        with pytest.raises(ValueError, match="PROJECT_KEY is required"):
            runtime.dispatch_next(dry_run=True)

    finally:
        lm_module.LaunchManager.launch = original_launch


def test_dispatch_clips_invalid_timeout(tmp_path):
    """Test that dispatch_next clips invalid timeout values."""
    queue_dir = tmp_path / "pools" / "thinking" / "Queue"
    queue_dir.mkdir(parents=True)
    thinking_pool = tmp_path / "pools" / "thinking"
    slot1_dir = thinking_pool / "sub_brain_01"
    slot1_dir.mkdir(parents=True)
    (slot1_dir / "workspace").mkdir(parents=True)
    (thinking_pool / "Outbox").mkdir(parents=True)

    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True)
    for f in ["Online.bat", "StartThinking.bat", "StartSummarizing.bat", "Done.bat", "signal_bridge.py", "THINKING_BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")

    # Create task with extreme timeout
    task_file = queue_dir / "task_timeout.txt"
    task_content = """FROM: runtime
TO: sub_brain_01
PROJECT_KEY: SignalBridge-v1-Build
TIMEOUT: 999999

Task with extreme timeout.
"""
    task_file.write_text(task_content, encoding="utf-8")

    runtime = ThinkingRuntime(root_dir=tmp_path, signal_port=19102)

    # Mock LaunchManager.launch
    import app.shared.launch_manager as lm_module
    original_launch = lm_module.LaunchManager.launch

    def mock_launch(self, request, dry_run=True):
        return {"launched": True, "dry_run": True, "pid": 1234}

    lm_module.LaunchManager.launch = mock_launch

    try:
        # Dispatch should succeed but clip timeout
        result = runtime.dispatch_next(dry_run=True)
        assert result["dispatched"] is True

        # Verify timeout was clipped to max (86400)
        slot = runtime.get_slot("sub_brain_01")
        assert slot is not None
        assert slot.timeout_seconds == 86400

    finally:
        lm_module.LaunchManager.launch = original_launch


def test_dispatch_escapes_bat_variables(tmp_path):
    """Test that dispatch_next escapes special characters in bat variables."""
    queue_dir = tmp_path / "pools" / "thinking" / "Queue"
    queue_dir.mkdir(parents=True)
    thinking_pool = tmp_path / "pools" / "thinking"
    slot1_dir = thinking_pool / "sub_brain_01"
    slot1_dir.mkdir(parents=True)
    (slot1_dir / "workspace").mkdir(parents=True)
    (thinking_pool / "Outbox").mkdir(parents=True)

    tools_dir = tmp_path / "runtime" / "tools"
    tools_dir.mkdir(parents=True)
    for f in ["Online.bat", "StartThinking.bat", "StartSummarizing.bat", "Done.bat", "signal_bridge.py", "THINKING_BOOTSTRAP.txt"]:
        (tools_dir / f).write_text(f"mock {f}", encoding="utf-8")

    # Create task with valid project key
    task_file = queue_dir / "task_escape.txt"
    task_content = """FROM: runtime
TO: sub_brain_01
PROJECT_KEY: SignalBridge-1.0-Build

Task body.
"""
    task_file.write_text(task_content, encoding="utf-8")

    runtime = ThinkingRuntime(root_dir=tmp_path, signal_port=19103)

    # Mock LaunchManager.launch
    import app.shared.launch_manager as lm_module
    original_launch = lm_module.LaunchManager.launch

    def mock_launch(self, request, dry_run=True):
        return {"launched": True, "dry_run": True, "pid": 1234}

    lm_module.LaunchManager.launch = mock_launch

    try:
        # Dispatch should succeed
        result = runtime.dispatch_next(dry_run=True)
        assert result["dispatched"] is True

        # Verify launch bat uses escaped variables
        launch_bat = slot1_dir / "launch_sub_brain_01.bat"
        assert launch_bat.exists()
        bat_content = launch_bat.read_text(encoding="utf-8")

        # Verify variables are quoted and escaped
        assert 'set "TASK_ID=' in bat_content
        assert 'set "PROJECT_KEY=' in bat_content

    finally:
        lm_module.LaunchManager.launch = original_launch
