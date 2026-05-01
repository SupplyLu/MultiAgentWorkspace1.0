"""
Tests for POST naming validation rules.

POST naming follows strict conventions:
- Project key: ProjectName-Version-Mode (e.g., SignalBridge-v1-Build, SignalBridge-2.0.1-Demo)
- Atomic workorder: {ProjectKey}-{SubTaskName}{Seq} (e.g., SignalBridge-v1-Build-UIupgrade001)
"""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "app" / "services" / "post_naming.py"
SPEC = spec_from_file_location("post_naming", MODULE_PATH)
post_naming = module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
SPEC.loader.exec_module(post_naming)

is_valid_project_key = post_naming.is_valid_project_key
is_valid_atomic_workorder = post_naming.is_valid_atomic_workorder
extract_project_key = post_naming.extract_project_key


class TestProjectKeyValidation:
    """Test project key format validation."""

    def test_valid_project_key(self):
        """Valid project keys should pass validation."""
        assert is_valid_project_key("SignalBridge-1-Build")
        assert is_valid_project_key("SignalBridge-v1-Build")
        assert is_valid_project_key("SignalBridge-0.1.2-Demo")
        assert is_valid_project_key("SignalBridge-1.3-Release")
        assert is_valid_project_key("LongerProjectName-2.0.1-Build")

    def test_invalid_project_key_missing_version(self):
        """Project key without version should fail."""
        assert not is_valid_project_key("SignalBridge-Build")

    def test_invalid_project_key_missing_mode(self):
        """Project key without mode should fail."""
        assert not is_valid_project_key("SignalBridge-v1")

    def test_invalid_project_key_empty(self):
        """Empty string should fail."""
        assert not is_valid_project_key("")

    def test_invalid_project_key_with_atomic_suffix(self):
        """Project key with atomic suffix should fail."""
        assert not is_valid_project_key("SignalBridge-v1-Build-UIupgrade001")

    def test_invalid_project_key_with_illegal_version_chars(self):
        """Project key with unsupported version chars should fail."""
        assert not is_valid_project_key("SignalBridge-v1/2-Build")
        assert not is_valid_project_key("SignalBridge-v1:2-Build")


class TestAtomicWorkorderValidation:
    """Test atomic workorder format validation."""

    def test_valid_atomic_workorder(self):
        """Valid atomic workorders should pass validation."""
        assert is_valid_atomic_workorder("SignalBridge-v1-Build-UIupgrade001")
        assert is_valid_atomic_workorder("MyProject-v2-Design-BackendPatch999")
        assert is_valid_atomic_workorder("SignalBridge-0.1.2-Demo-DeviceBridge003")

    def test_invalid_atomic_workorder_missing_suffix(self):
        """Atomic workorder without subtask suffix should fail."""
        assert not is_valid_atomic_workorder("SignalBridge-v1-Build")

    def test_invalid_atomic_workorder_missing_seq(self):
        """Atomic workorder without numeric sequence should fail."""
        assert not is_valid_atomic_workorder("SignalBridge-v1-Build-UIupgrade")

    def test_invalid_atomic_workorder_empty(self):
        """Empty string should fail."""
        assert not is_valid_atomic_workorder("")

    def test_invalid_atomic_workorder_project_key_only(self):
        """Project key format should fail atomic validation."""
        assert not is_valid_atomic_workorder("SignalBridge-v1-Build")


class TestProjectKeyExtraction:
    """Test project key extraction from atomic workorder."""

    def test_extract_from_valid_atomic(self):
        """Should extract project key from valid atomic workorder."""
        assert extract_project_key("SignalBridge-v1-Build-UIupgrade001") == "SignalBridge-v1-Build"
        assert extract_project_key("MyProject-v2-Design-BackendPatch999") == "MyProject-v2-Design"
        assert extract_project_key("SignalBridge-0.1.2-Demo-DeviceBridge003") == "SignalBridge-0.1.2-Demo"

    def test_extract_from_project_key_returns_same(self):
        """Should return the same string if already a project key."""
        assert extract_project_key("SignalBridge-v1-Build") == "SignalBridge-v1-Build"
        assert extract_project_key("SignalBridge-2.0.1-Demo") == "SignalBridge-2.0.1-Demo"

    def test_extract_from_invalid_format_returns_none(self):
        """Should return None for invalid formats."""
        assert extract_project_key("InvalidFormat") is None
        assert extract_project_key("") is None
        assert extract_project_key("SignalBridge-Build") is None
