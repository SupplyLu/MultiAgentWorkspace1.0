"""Tests for ProjectRegistrationService."""

from pathlib import Path

import pytest

from app.desktop_ui.services.project_registration_service import InvalidInputError, ProjectRegistrationService


def _init_workspace(root: Path):
    for pool in ("task", "thinking", "construct", "gate", "work", "package"):
        (root / "pools" / pool / "Queue").mkdir(parents=True, exist_ok=True)
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "flow_policy.json").write_text(
        """{
  "active_policy": "full_pipeline",
  "default_mode": "build",
  "modes": ["build", "fix", "demo"],
  "pool_descriptions": {
    "task": "任务入口",
    "thinking": "需求拆解",
    "construct": "结构设计",
    "gate": "质量审查",
    "work": "实际施工",
    "package": "收口打包"
  },
  "policies": {
    "full_pipeline": ["task", "thinking", "construct", "gate", "work", "package"],
    "direct_to_work": ["task", "work"]
  }
}
""",
        encoding="utf-8",
    )


def test_project_registration_service_importable():
    """Test that ProjectRegistrationService can be imported."""
    assert ProjectRegistrationService is not None


def test_build_project_key_success():
    """Test that project_key is correctly assembled."""
    service = ProjectRegistrationService(Path("."))
    project_key = service.build_project_key("SignalOfBridge", "v1", "Build")

    assert project_key == "SignalOfBridge-v1-Build"


def test_build_project_key_invalid_version():
    """Test that invalid version raises error."""
    service = ProjectRegistrationService(Path("."))

    with pytest.raises(InvalidInputError):
        service.build_project_key("SignalOfBridge", "v1/2", "Build")


@pytest.mark.parametrize(
    "version",
    [
        "",
        " ",
        "v 1",
        "v1 ",
        " v1",
        "v1/2",
        "v-1",
        "v_1",
        "v1!",
        "v#1",
    ],
)
def test_build_project_key_rejects_version_edge_cases(version: str):
    """Test that malformed version edge cases raise errors."""
    service = ProjectRegistrationService(Path("."))

    with pytest.raises(InvalidInputError):
        service.build_project_key("SignalOfBridge", version, "Build")


def test_build_project_key_accepts_flexible_version_formats():
    """Test that flexible version formats are accepted."""
    service = ProjectRegistrationService(Path("."))

    assert service.build_project_key("SignalOfBridge", "v1", "Build") == "SignalOfBridge-v1-Build"
    assert service.build_project_key("SignalOfBridge", "0.1.2", "Demo") == "SignalOfBridge-0.1.2-Demo"
    assert service.build_project_key("SignalOfBridge", "1.3", "Release") == "SignalOfBridge-1.3-Release"


def test_validate_project_key_valid():
    """Test that valid project_key passes validation."""
    service = ProjectRegistrationService(Path("."))
    assert service.validate_project_key("SignalOfBridge-v1-Build") is True
    assert service.validate_project_key("SignalOfBridge-1.3-Release") is True


def test_validate_project_key_invalid():
    """Test that invalid project_key fails validation."""
    service = ProjectRegistrationService(Path("."))
    assert service.validate_project_key("invalid-key") is False


def test_list_available_pools_reads_workspace(tmp_path: Path):
    _init_workspace(tmp_path)
    service = ProjectRegistrationService(tmp_path)

    assert service.list_available_pools() == ["construct", "gate", "package", "task", "thinking", "work"]


@pytest.mark.parametrize(
    "target_pool",
    [
        "thinking",
        "construct",
        "gate",
        "work",
        "package",
    ],
)
def test_validate_target_pool_accepts_available_pools(tmp_path: Path, target_pool: str):
    """Test that all existing target pools pass validation."""
    _init_workspace(tmp_path)
    service = ProjectRegistrationService(tmp_path)

    assert service.validate_target_pool(target_pool) == target_pool


def test_validate_target_pool_rejects_invalid_pool(tmp_path: Path):
    """Test that invalid target_pool raises error with helpful message."""
    _init_workspace(tmp_path)
    service = ProjectRegistrationService(tmp_path)

    with pytest.raises(
        InvalidInputError,
        match="Invalid target pool: 'invalid'. Available pools are:",
    ):
        service.validate_target_pool("invalid")


def test_parse_route_uses_explicit_route(tmp_path: Path):
    _init_workspace(tmp_path)
    service = ProjectRegistrationService(tmp_path)

    assert service.parse_route(["task", "thinking", "work"], "") == ["task", "thinking", "work"]


def test_parse_route_falls_back_to_target_pool(tmp_path: Path):
    _init_workspace(tmp_path)
    service = ProjectRegistrationService(tmp_path)

    assert service.parse_route(None, "work") == ["task", "work"]


def test_parse_route_requires_task_start(tmp_path: Path):
    _init_workspace(tmp_path)
    service = ProjectRegistrationService(tmp_path)

    with pytest.raises(InvalidInputError, match="start from 'task'"):
        service.parse_route(["thinking", "work"], "")


def test_write_queue_file_success_with_body(tmp_path: Path):
    """Test queue file generation with non-empty requirements body."""
    service = ProjectRegistrationService(tmp_path)

    queue_file_path = service.write_queue_file(
        project_key="SignalOfBridge-v1-Build",
        target_pool="construct",
        mode="Build",
        requirements="Implement bridge synchronization module.",
    )

    expected_path = tmp_path / "pools" / "task" / "Outbox" / "SignalOfBridge-v1-Build.txt"
    expected_content = (
        "PROJECT_KEY: SignalOfBridge-v1-Build\n"
        "SOURCE_POOL: task\n"
        "TARGET_POOL: construct\n"
        "MODE: Build\n"
        "\n"
        "Implement bridge synchronization module."
    )

    assert queue_file_path == expected_path
    assert queue_file_path.read_text(encoding="utf-8") == expected_content


def test_write_queue_file_success_with_empty_body(tmp_path: Path):
    """Test queue file generation preserves header and blank line when body is empty."""
    service = ProjectRegistrationService(tmp_path)

    queue_file_path = service.write_queue_file(
        project_key="SignalOfBridge-v1-Build",
        target_pool="thinking",
        mode="Review",
        requirements="",
    )

    expected_content = (
        "PROJECT_KEY: SignalOfBridge-v1-Build\n"
        "SOURCE_POOL: task\n"
        "TARGET_POOL: thinking\n"
        "MODE: Review\n"
        "\n"
    )

    assert queue_file_path.exists()
    assert queue_file_path.read_text(encoding="utf-8") == expected_content


def test_write_queue_file_returns_expected_queue_path(tmp_path: Path):
    """Test returned path points to task Outbox file."""
    service = ProjectRegistrationService(tmp_path)

    queue_file_path = service.write_queue_file(
        project_key="SignalOfBridge-v1-Build",
        target_pool="work",
        mode="Build",
        requirements="Run work pipeline.",
    )

    assert queue_file_path == tmp_path / "pools" / "task" / "Outbox" / "SignalOfBridge-v1-Build.txt"


def test_register_success(tmp_path: Path):
    """Test successful registration returns success result and creates queue file."""
    _init_workspace(tmp_path)
    service = ProjectRegistrationService(tmp_path)

    result = service.register(
        project_name="SignalOfBridge",
        version="v1",
        mode="Build",
        target_pool="thinking",
        requirements="Implement bridge synchronization module.",
    )

    assert result["success"] is True
    assert result["project_key"] == "SignalOfBridge-v1-Build"
    assert result["target_pool"] == "thinking"
    assert result["route"] == ["task", "thinking"]
    assert "queue_file" in result

    expected_queue_file = tmp_path / "pools" / "task" / "Outbox" / "SignalOfBridge-v1-Build.txt"
    assert expected_queue_file.exists()


def test_register_duplicate_project_fails(tmp_path: Path):
    """Test that duplicate registration fails and does not overwrite queue file."""
    _init_workspace(tmp_path)
    service = ProjectRegistrationService(tmp_path)

    result1 = service.register(
        project_name="TestProject",
        version="v1",
        mode="Build",
        target_pool="construct",
        requirements="First registration.",
    )
    assert result1["success"] is True

    queue_file = tmp_path / "pools" / "task" / "Outbox" / "TestProject-v1-Build.txt"
    original_content = queue_file.read_text(encoding="utf-8")

    result2 = service.register(
        project_name="TestProject",
        version="v1",
        mode="Build",
        target_pool="construct",
        requirements="Second registration attempt.",
    )

    assert result2["success"] is False
    assert "already exists" in result2["error"]

    current_content = queue_file.read_text(encoding="utf-8")
    assert current_content == original_content
    assert "First registration." in current_content
    assert "Second registration attempt." not in current_content


def test_register_fails_before_registration_when_queue_path_is_blocked(tmp_path: Path):
    """Test Queue path pre-check blocks registration before registry write."""
    _init_workspace(tmp_path)
    service = ProjectRegistrationService(tmp_path)

    blocked_queue_path = tmp_path / "pools" / "task" / "Outbox"
    blocked_queue_path.unlink(missing_ok=True)
    blocked_queue_path.parent.mkdir(parents=True, exist_ok=True)
    blocked_queue_path.write_text("not a directory", encoding="utf-8")

    result = service.register(
        project_name="BlockedQueueProject",
        version="v1",
        mode="Build",
        target_pool="work",
        requirements="Should fail before registration.",
    )

    assert result["success"] is False
    assert "Outbox" in result["error"]

    from app.services.post_registry import PostRegistry

    registry = PostRegistry(tmp_path)
    assert registry.get_project("BlockedQueueProject-v1-Build") is None


def test_register_with_empty_requirements(tmp_path: Path):
    """Test successful registration with empty requirements still works."""
    _init_workspace(tmp_path)
    service = ProjectRegistrationService(tmp_path)

    result = service.register(
        project_name="EmptyReqProject",
        version="v2",
        mode="Review",
        target_pool="gate",
        requirements="",
    )

    assert result["success"] is True
    assert result["project_key"] == "EmptyReqProject-v2-Review"

    queue_file = tmp_path / "pools" / "task" / "Outbox" / "EmptyReqProject-v2-Review.txt"
    assert queue_file.exists()
    content = queue_file.read_text(encoding="utf-8")
    assert "PROJECT_KEY: EmptyReqProject-v2-Review" in content
    assert "TARGET_POOL: gate" in content
