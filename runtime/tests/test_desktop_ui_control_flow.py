"""Test desktop UI control flow for pause/resume/restart operations."""

import pytest
from unittest.mock import MagicMock, patch

from app.desktop_ui.views.control_view import ControlView
from app.desktop_ui.services.runtime_command_bridge import RuntimeCommandBridge
from app.desktop_ui.data.runtime_client import RuntimeClient


def test_control_view_triggers_pause_command():
    """Test that ControlView calls RuntimeClient.send_control with 'pause' action."""
    client_mock = MagicMock(spec=RuntimeClient)
    client_mock.send_control.return_value = {"success": True}

    bridge_mock = MagicMock(spec=RuntimeCommandBridge)

    view = ControlView(client=client_mock, bridge=bridge_mock)

    view.handle_pause_action("work")

    client_mock.send_control.assert_called_once_with("work", "pause")


def test_control_view_triggers_resume_command():
    """Test that ControlView calls RuntimeClient.send_control with 'resume' action."""
    client_mock = MagicMock(spec=RuntimeClient)
    client_mock.send_control.return_value = {"success": True}

    bridge_mock = MagicMock(spec=RuntimeCommandBridge)
    view = ControlView(client=client_mock, bridge=bridge_mock)

    view.handle_resume_action("thinking")

    client_mock.send_control.assert_called_once_with("thinking", "resume")


def test_control_view_triggers_restart_command_via_bridge():
    """Test that ControlView calls RuntimeCommandBridge.restart_pool for restart action."""
    client_mock = MagicMock(spec=RuntimeClient)

    bridge_mock = MagicMock(spec=RuntimeCommandBridge)
    bridge_mock.restart_pool.return_value = {"success": True}

    view = ControlView(client=client_mock, bridge=bridge_mock)

    view.handle_restart_action("gate")

    bridge_mock.restart_pool.assert_called_once_with("gate")


def test_control_view_shows_operation_result_on_success():
    """Test that ControlView updates status display when operation succeeds."""
    client_mock = MagicMock(spec=RuntimeClient)
    client_mock.send_control.return_value = {"success": True}

    bridge_mock = MagicMock(spec=RuntimeCommandBridge)
    view = ControlView(client=client_mock, bridge=bridge_mock)

    view.handle_pause_action("work")

    assert view.get_last_operation_status() == "success"


def test_control_view_shows_operation_result_on_failure():
    """Test that ControlView updates status display when operation fails."""
    client_mock = MagicMock(spec=RuntimeClient)
    client_mock.send_control.return_value = {"success": False, "error": "Connection refused"}

    bridge_mock = MagicMock(spec=RuntimeCommandBridge)
    view = ControlView(client=client_mock, bridge=bridge_mock)

    view.handle_pause_action("work")

    assert view.get_last_operation_status() == "failed"


def test_control_view_writes_audit_log(tmp_path):
    """Test that ControlView writes a local audit log for control actions."""
    client_mock = MagicMock(spec=RuntimeClient)
    client_mock.send_control.return_value = {"success": True}

    bridge_mock = MagicMock(spec=RuntimeCommandBridge)
    audit_log = tmp_path / "desktop_ui_audit.log"
    view = ControlView(client=client_mock, bridge=bridge_mock, audit_log_path=audit_log)

    view.handle_pause_action("work")

    content = audit_log.read_text(encoding="utf-8")
    assert '"pool": "work"' in content
    assert '"action": "pause"' in content
    assert '"result": "success"' in content


def test_runtime_client_auto_discovers_port_from_registry(tmp_path):
    """Test that RuntimeClient can auto-discover port from registry when not provided."""
    import json
    from app.desktop_ui.data.runtime_client import RuntimeClient

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
