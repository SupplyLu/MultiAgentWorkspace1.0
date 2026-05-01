"""Security tests for file_queue.py input validation.

Tests that parse_task_file() rejects malicious input in critical headers
to prevent path traversal and command injection attacks.
"""

from pathlib import Path
import pytest

from app.shared.file_queue import parse_task_file, validate_id_field


def test_parse_task_file_rejects_path_traversal_in_task_id(tmp_path):
    """Test that task files with path traversal in TASK_ID are rejected."""
    task_file = tmp_path / "malicious.txt"
    task_file.write_text(
        "TASK_ID: ../../etc/passwd\nFEATURE_ID: test\n\nMalicious content",
        encoding="utf-8"
    )

    result = parse_task_file(task_file)

    # Should return None (skip) rather than crash or process
    assert result is None


def test_parse_task_file_rejects_command_injection_in_task_id(tmp_path):
    """Test that task files with command injection chars in TASK_ID are rejected."""
    malicious_ids = [
        "task_001 & calc.exe",
        "task_001 | whoami",
        "task_001; rm -rf /",
        "task_001 && echo pwned",
        "task_001`whoami`",
        "task_001$(whoami)",
    ]

    for malicious_id in malicious_ids:
        task_file = tmp_path / f"malicious_{malicious_ids.index(malicious_id)}.txt"
        task_file.write_text(
            f"TASK_ID: {malicious_id}\nFEATURE_ID: test\n\nMalicious",
            encoding="utf-8"
        )

        result = parse_task_file(task_file)
        assert result is None, f"Should reject TASK_ID: {malicious_id}"


def test_parse_task_file_rejects_special_chars_in_feature_id(tmp_path):
    """Test that FEATURE_ID with special characters is rejected."""
    task_file = tmp_path / "bad_feature.txt"
    task_file.write_text(
        "TASK_ID: task_001\nFEATURE_ID: feature&injection\n\nContent",
        encoding="utf-8"
    )

    result = parse_task_file(task_file)
    assert result is None


def test_parse_task_file_rejects_special_chars_in_project_name(tmp_path):
    """Test that PROJECT_NAME with special characters is rejected."""
    task_file = tmp_path / "bad_project.txt"
    task_file.write_text(
        "TASK_ID: task_001\nPROJECT_NAME: ../../../evil\n\nContent",
        encoding="utf-8"
    )

    result = parse_task_file(task_file)
    assert result is None


def test_parse_task_file_accepts_valid_ids(tmp_path):
    """Test that task files with valid IDs are accepted."""
    valid_cases = [
        ("task_001", "feature_login"),
        ("t-real-002", "f-dashboard"),
        ("TASK_ABC", "FEATURE_XYZ"),
        ("task123", "feature456"),
    ]

    for task_id, feature_id in valid_cases:
        task_file = tmp_path / f"{task_id}.txt"
        task_file.write_text(
            f"TASK_ID: {task_id}\nFEATURE_ID: {feature_id}\n\nValid content",
            encoding="utf-8"
        )

        result = parse_task_file(task_file)
        assert result is not None, f"Should accept TASK_ID: {task_id}"
        assert result["headers"]["TASK_ID"] == task_id
        assert result["headers"]["FEATURE_ID"] == feature_id


def test_parse_task_file_rejects_empty_task_id(tmp_path):
    """Test that empty TASK_ID is rejected."""
    task_file = tmp_path / "empty_id.txt"
    task_file.write_text(
        "TASK_ID: \nFEATURE_ID: test\n\nContent",
        encoding="utf-8"
    )

    result = parse_task_file(task_file)
    assert result is None


def test_parse_task_file_rejects_too_long_id(tmp_path):
    """Test that IDs exceeding 128 characters are rejected."""
    long_id = "a" * 129
    task_file = tmp_path / "long_id.txt"
    task_file.write_text(
        f"TASK_ID: {long_id}\nFEATURE_ID: test\n\nContent",
        encoding="utf-8"
    )

    result = parse_task_file(task_file)
    assert result is None


def test_validate_id_field_accepts_valid():
    """Test that validate_id_field accepts valid inputs."""
    valid_ids = ["task_001", "t-real-002", "TASK_ABC", "a", "A-B_C-1"]
    for valid_id in valid_ids:
        result = validate_id_field(valid_id, "TEST_FIELD")
        assert result == valid_id


def test_validate_id_field_rejects_invalid():
    """Test that validate_id_field rejects invalid inputs."""
    invalid_ids = [
        "",
        "task&001",
        "task|002",
        "../../../etc/passwd",
        "task 001",
        "task<001",
        "a" * 129,
    ]
    for invalid_id in invalid_ids:
        with pytest.raises(ValueError):
            validate_id_field(invalid_id, "TEST_FIELD")
