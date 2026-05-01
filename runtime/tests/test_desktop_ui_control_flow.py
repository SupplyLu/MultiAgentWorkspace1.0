"""Test desktop UI control flow for pause/resume/restart operations."""

import importlib
import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.desktop_ui.services.runtime_command_bridge import RuntimeCommandBridge
from app.desktop_ui.data.runtime_client import RuntimeClient


@pytest.fixture
def control_view_class(monkeypatch):
    """Load ControlView with a fully mocked PySide6 module.

    This prevents Qt from initializing native GUI backends in headless test
    environments where importing PySide6.QtWidgets may crash the interpreter.
    """

    qtwidgets = types.ModuleType("PySide6.QtWidgets")

    class QWidget:
        def __init__(self, *args, **kwargs):
            pass

    class QLabel:
        def __init__(self, text: str = ""):
            self.text = text

    class QVBoxLayout:
        def __init__(self, parent=None):
            self.parent = parent
            self.widgets = []

        def addWidget(self, widget):
            self.widgets.append(widget)

    class QHBoxLayout:
        def __init__(self, *args, **kwargs):
            self.widgets = []

        def addWidget(self, widget):
            self.widgets.append(widget)

    class QPushButton:
        def __init__(self, text: str = ""):
            self.text = text

    qtwidgets.QWidget = QWidget
    qtwidgets.QLabel = QLabel
    qtwidgets.QVBoxLayout = QVBoxLayout
    qtwidgets.QHBoxLayout = QHBoxLayout
    qtwidgets.QPushButton = QPushButton

    pyside6 = types.ModuleType("PySide6")
    pyside6.QtWidgets = qtwidgets

    monkeypatch.setitem(sys.modules, "PySide6", pyside6)
    monkeypatch.setitem(sys.modules, "PySide6.QtWidgets", qtwidgets)

    module = importlib.import_module("app.desktop_ui.views.control_view")
    module = importlib.reload(module)
    return module.ControlView


def test_control_view_triggers_pause_command(control_view_class):
    """Test that ControlView calls RuntimeClient.send_control with 'pause' action."""
    client_mock = MagicMock(spec=RuntimeClient)
    client_mock.send_control.return_value = {"success": True}

    bridge_mock = MagicMock(spec=RuntimeCommandBridge)

    view = control_view_class(client=client_mock, bridge=bridge_mock)

    view.handle_pause_action("work")

    client_mock.send_control.assert_called_once_with("work", "pause")


def test_control_view_triggers_resume_command(control_view_class):
    """Test that ControlView calls RuntimeClient.send_control with 'resume' action."""
    client_mock = MagicMock(spec=RuntimeClient)
    client_mock.send_control.return_value = {"success": True}

    bridge_mock = MagicMock(spec=RuntimeCommandBridge)
    view = control_view_class(client=client_mock, bridge=bridge_mock)

    view.handle_resume_action("thinking")

    client_mock.send_control.assert_called_once_with("thinking", "resume")


def test_control_view_triggers_restart_command_via_bridge(control_view_class):
    """Test that ControlView calls RuntimeCommandBridge.restart_pool for restart action."""
    client_mock = MagicMock(spec=RuntimeClient)

    bridge_mock = MagicMock(spec=RuntimeCommandBridge)
    bridge_mock.restart_pool.return_value = {"success": True}

    view = control_view_class(client=client_mock, bridge=bridge_mock)

    view.handle_restart_action("gate")

    bridge_mock.restart_pool.assert_called_once_with("gate")


def test_control_view_shows_operation_result_on_success(control_view_class):
    """Test that ControlView updates status display when operation succeeds."""
    client_mock = MagicMock(spec=RuntimeClient)
    client_mock.send_control.return_value = {"success": True}

    bridge_mock = MagicMock(spec=RuntimeCommandBridge)
    view = control_view_class(client=client_mock, bridge=bridge_mock)

    view.handle_pause_action("work")

    assert view.get_last_operation_status() == "success"


def test_control_view_shows_operation_result_on_failure(control_view_class):
    """Test that ControlView updates status display when operation fails."""
    client_mock = MagicMock(spec=RuntimeClient)
    client_mock.send_control.return_value = {"success": False, "error": "Connection refused"}

    bridge_mock = MagicMock(spec=RuntimeCommandBridge)
    view = control_view_class(client=client_mock, bridge=bridge_mock)

    view.handle_pause_action("work")

    assert view.get_last_operation_status() == "failed"


def test_control_view_writes_audit_log(tmp_path, control_view_class):
    """Test that ControlView writes a local audit log for control actions."""
    client_mock = MagicMock(spec=RuntimeClient)
    client_mock.send_control.return_value = {"success": True}

    bridge_mock = MagicMock(spec=RuntimeCommandBridge)
    audit_log = tmp_path / "desktop_ui_audit.log"
    view = control_view_class(client=client_mock, bridge=bridge_mock, audit_log_path=audit_log)

    view.handle_pause_action("work")

    content = audit_log.read_text(encoding="utf-8")
    assert '"pool": "work"' in content
    assert '"action": "pause"' in content
    assert '"result": "success"' in content


def test_runtime_command_bridge_stop_marks_invalid_pid_as_stopped(tmp_path):
    bridge = RuntimeCommandBridge(root_dir=tmp_path)
    registry_file = tmp_path / "runtime_registry.json"
    registry_file.write_text(json.dumps({
        "work": {"pool": "work", "pid": 0, "port": 18800, "status": "running"}
    }), encoding="utf-8")

    result = bridge.stop_pool("work")

    assert result["success"] is True
    updated = json.loads(registry_file.read_text(encoding="utf-8"))
    assert updated["work"]["status"] == "stopped"


def test_runtime_command_bridge_stop_falls_back_to_force_kill(monkeypatch, tmp_path):
    bridge = RuntimeCommandBridge(root_dir=tmp_path)
    registry_file = tmp_path / "runtime_registry.json"
    registry_file.write_text(json.dumps({
        "work": {"pool": "work", "pid": 12345, "port": 18800, "status": "running"}
    }), encoding="utf-8")

    calls = []

    def fake_kill_process(pid, force=False, dry_run=True, tree=False):
        calls.append({"pid": pid, "force": force, "tree": tree})
        if force:
            return {"killed": True}
        return {"killed": False, "stderr": "need force"}

    monkeypatch.setattr("app.desktop_ui.services.runtime_command_bridge.kill_process", fake_kill_process)
    monkeypatch.setattr("app.desktop_ui.services.runtime_command_bridge._is_pid_alive", lambda pid: True)

    result = bridge.stop_pool("work")

    assert result["success"] is True
    assert calls == [
        {"pid": 12345, "force": False, "tree": True},
        {"pid": 12345, "force": True, "tree": True},
    ]


    """Test that RuntimeClient can auto-discover port from registry when not provided."""

    # Create mock registry
    registry_file = tmp_path / "runtime_registry.json"
    registry_data = {
        "work": {
            "pool": "work",
            "pid": 12345,
            "port": 18800,
            "status": "running",
        }
    }
    registry_file.write_text(json.dumps(registry_data), encoding="utf-8")

    client = RuntimeClient(root_dir=tmp_path)

    # send_control without explicit port should look up from registry
    # (This will fail in real HTTP, but we're testing the port lookup logic)
    result = client.send_control("work", "pause")

    # Should have attempted to use port 18800 from registry
    # (will fail with connection error, but error should NOT be "Port required")
    assert result["success"] is False
    assert result["error"] != "Port required"


def test_runtime_client_uses_runtime_registry_service_for_port_lookup(monkeypatch, tmp_path):
    """RuntimeClient must use RuntimeRegistry service instead of bare file reads."""
    called = {"get": False}

    class FakeRegistry:
        def __init__(self, root_dir):
            assert Path(root_dir) == tmp_path

        def get(self, pool):
            called["get"] = True
            assert pool == "work"
            return {"pool": "work", "port": 18800, "status": "running"}

    monkeypatch.setattr("app.desktop_ui.data.runtime_client.RuntimeRegistry", FakeRegistry)

    client = RuntimeClient(root_dir=tmp_path)
    port = client._get_port_for_pool("work")

    assert called["get"] is True
    assert port == 18800
