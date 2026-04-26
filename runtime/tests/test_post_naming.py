"""
Tests for POST naming validation rules.

POST naming follows strict conventions:
- Project key: XXX-(Vision)-(Mode) (e.g., SignalOfBridge-v1-Build)
- Atomic workorder: XXX-(Vision)-(Mode)-NNN (e.g., SignalOfBridge-v1-Build-001)
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
        assert is_valid_project_key("SignalOfBridge-v1-Build")
        assert is_valid_project_key("MyProject-v2-Design")
        assert is_valid_project_key("A-v1-Test")
        assert is_valid_project_key("LongerProjectName-v10-Build")

    def test_invalid_project_key_missing_vision(self):
        """Project key without vision should fail."""
        assert not is_valid_project_key("SignalOfBridge-Build")

    def test_invalid_project_key_missing_mode(self):
        """Project key without mode should fail."""
        assert not is_valid_project_key("SignalOfBridge-v1")

    def test_invalid_project_key_wrong_vision_format(self):
        """Project key with wrong vision format should fail."""
        assert not is_valid_project_key("SignalOfBridge-1-Build")
        assert not is_valid_project_key("SignalOfBridge-version1-Build")

    def test_invalid_project_key_empty(self):
        """Empty string should fail."""
        assert not is_valid_project_key("")

    def test_invalid_project_key_with_atomic_suffix(self):
        """Project key with atomic suffix should fail."""
        assert not is_valid_project_key("SignalOfBridge-v1-Build-001")


class TestAtomicWorkorderValidation:
    """Test atomic workorder format validation."""

    def test_valid_atomic_workorder(self):
        """Valid atomic workorders should pass validation."""
        assert is_valid_atomic_workorder("SignalOfBridge-v1-Build-001")
        assert is_valid_atomic_workorder("MyProject-v2-Design-999")
        assert is_valid_atomic_workorder("A-v1-Test-042")

    def test_invalid_atomic_workorder_missing_number(self):
        """Atomic workorder without number should fail."""
        assert not is_valid_atomic_workorder("SignalOfBridge-v1-Build")

    def test_invalid_atomic_workorder_wrong_number_format(self):
        """Atomic workorder with wrong number format should fail."""
        assert not is_valid_atomic_workorder("SignalOfBridge-v1-Build-1")
        assert not is_valid_atomic_workorder("SignalOfBridge-v1-Build-01")
        assert not is_valid_atomic_workorder("SignalOfBridge-v1-Build-1234")

    def test_invalid_atomic_workorder_empty(self):
        """Empty string should fail."""
        assert not is_valid_atomic_workorder("")

    def test_invalid_atomic_workorder_project_key_only(self):
        """Project key format should fail atomic validation."""
        assert not is_valid_atomic_workorder("SignalOfBridge-v1-Build")


class TestProjectKeyExtraction:
    """Test project key extraction from atomic workorder."""

    def test_extract_from_valid_atomic(self):
        """Should extract project key from valid atomic workorder."""
        assert extract_project_key("SignalOfBridge-v1-Build-001") == "SignalOfBridge-v1-Build"
        assert extract_project_key("MyProject-v2-Design-999") == "MyProject-v2-Design"
        assert extract_project_key("A-v1-Test-042") == "A-v1-Test"

    def test_extract_from_project_key_returns_same(self):
        """Should return the same string if already a project key."""
        assert extract_project_key("SignalOfBridge-v1-Build") == "SignalOfBridge-v1-Build"

    def test_extract_from_invalid_format_returns_none(self):
        """Should return None for invalid formats."""
        assert extract_project_key("InvalidFormat") is None
        assert extract_project_key("") is None
        assert extract_project_key("SignalOfBridge-Build") is None
