"""Tests for dashboard workstation grid layout."""

import pytest

from app.desktop_ui.views.dashboard_view import DashboardView, SlotStatusInferer, RuntimeStatusInferer


def test_slot_status_inference():
    assert SlotStatusInferer.infer_status(
        busy=False, enabled=True, assigned_task_id="", current_state="idle", online=True,
    ) == ("空闲", "white")

    assert SlotStatusInferer.infer_status(
        busy=True, enabled=True, assigned_task_id="task_1", current_state="state_2", online=True,
    ) == ("工作中", "green")

    assert SlotStatusInferer.infer_status(
        busy=False, enabled=False, assigned_task_id="", current_state="idle", online=True,
    ) == ("已下线", "gray")

    assert SlotStatusInferer.infer_status(
        busy=False, enabled=True, assigned_task_id="", current_state="idle", online=False,
    ) == ("离线", "gray")

    assert SlotStatusInferer.infer_status(
        busy=True, enabled=True, assigned_task_id="task_4", current_state="error", online=True,
    ) == ("异常", "yellow")


def test_runtime_status_inference():
    assert RuntimeStatusInferer.infer({"online": True, "paused": False}) == ("运行中", "green")
    assert RuntimeStatusInferer.infer({"online": True, "paused": True}) == ("已暂停", "yellow")
    assert RuntimeStatusInferer.infer({"online": False, "paused": False}) == ("离线", "gray")


def test_dashboard_view_renders_columns():
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
    except ImportError:
        pytest.skip("PySide6 not available for UI test")

    view = DashboardView(auto_refresh=False)
    pool_statuses = [
        {
            "pool": "work",
            "runtime": {
                "online": True,
                "pid": 1001,
                "port": 18800,
                "paused": False,
                "queue_count": 2,
                "slot_total": 2,
                "slot_enabled": 1,
                "slot_busy": 1,
            },
            "slots": [
                {
                    "slot_id": "worker_01",
                    "busy": True,
                    "enabled": True,
                    "assigned_task_id": "task_abc",
                    "assigned_project_name": "Project_A",
                    "current_state": "state_2",
                    "current_stage": "",
                },
                {
                    "slot_id": "worker_02",
                    "busy": False,
                    "enabled": False,
                    "assigned_task_id": "",
                    "assigned_project_name": "",
                    "current_state": "idle",
                    "current_stage": "",
                },
            ],
        }
    ]
    view._render_pool_statuses(pool_statuses)

    assert len(view._pool_column_widgets) == 6
    work_col = view._pool_column_widgets[0]
    assert work_col._title_label.text() == "WORK"
    assert work_col._status_label.text() == "运行中"
    assert len(work_col._workstation_widgets) == 2
    ws_01 = work_col._workstation_widgets[0]
    ws_02 = work_col._workstation_widgets[1]
    assert "01" in ws_01._status_label.text()
    assert "Project_A" in ws_01._status_label.text()
    assert "02" in ws_02._status_label.text()


def test_dashboard_view_skips_refresh_when_in_flight():
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
    except ImportError:
        pytest.skip("PySide6 not available for UI test")

    view = DashboardView(auto_refresh=False)
    view._refresh_in_flight = True
    old_worker = view._worker
    view._refresh_data()
    assert view._worker is old_worker
