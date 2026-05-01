"""Tests for desktop UI pool monitoring functionality."""

from pathlib import Path

import pytest

from app.desktop_ui.data.pool_monitor_service import PoolMonitorService
from app.desktop_ui.views.dashboard_view import DashboardView


class MockRegistryReader:
    def __init__(self, all_pools):
        self._all_pools = all_pools

    def list_all_pools(self):
        return self._all_pools


class MockRuntimeClient:
    def __init__(self, pool_statuses, control_states=None):
        self._pool_statuses = pool_statuses
        self._control_states = control_states or {}

    def get_status(self, pool, port):
        return self._pool_statuses.get(f"{pool}:{port}", {"online": False})

    def get_control_state(self, pool, port=None):
        return self._control_states.get(f"{pool}:{port}", {"paused": False})


class MockPostProgressReader:
    def get_progress(self):
        return {
            "active_registrations": 1,
            "waiting_payload_registrations": 2,
            "blocked_registrations": 0,
            "delivered_registrations": 3,
            "block_reason": None,
        }


def test_pool_monitor_service_aggregates_status():
    """Test that PoolMonitorService correctly fetches and aggregates runtime and slot statuses."""
    service = PoolMonitorService(root_dir=".")

    service._registry_reader = MockRegistryReader(
        [
            {"pool": "work", "port": 18800, "pid": 1001, "status": "running"},
            {"pool": "gate", "port": 19200, "pid": 1002, "status": "running"},
            {"pool": "post", "port": 19120, "pid": 1003, "status": "running"},
            {"pool": "package", "port": 19300, "pid": None, "status": "stopped"},
        ]
    )

    service._runtime_client = MockRuntimeClient(
        {
            "work:18800": {
                "online": True,
                "is_running": True,
                "queue_count": 2,
                "slots": [
                    {
                        "slot_id": "worker_01",
                        "busy": True,
                        "enabled": True,
                        "assigned_task_id": "task_1",
                        "current_state": "state_2",
                    },
                    {
                        "slot_id": "worker_02",
                        "busy": False,
                        "enabled": False,
                        "assigned_task_id": "",
                        "current_state": "idle",
                    },
                ],
            },
            "gate:19200": {
                "online": True,
                "is_running": True,
                "queue_count": 0,
                "slots": [
                    {
                        "slot_id": "guard_01",
                        "busy": False,
                        "enabled": True,
                        "assigned_task_id": "",
                        "current_state": "idle",
                    }
                ],
            },
        },
        {
            "work:18800": {"paused": False},
            "gate:19200": {"paused": True},
            "post:19120": {"paused": False},
        },
    )
    service._post_progress_reader = MockPostProgressReader()

    results = service.get_all_pool_status()

    assert len(results) == 4

    work = results[0]
    assert work["pool"] == "work"
    assert work["runtime"]["queue_count"] == 2
    assert work["runtime"]["slot_total"] == 2
    assert work["runtime"]["slot_enabled"] == 1
    assert work["runtime"]["slot_busy"] == 1
    assert work["slots"][0]["current_state"] == "state_2"
    assert work["slots"][1]["enabled"] is False

    gate = results[1]
    assert gate["pool"] == "gate"
    assert gate["runtime"]["paused"] is True

    post = results[2]
    assert post["pool"] == "post"
    assert post["runtime"]["active_registrations"] == 1
    assert post["runtime"]["delivered_registrations"] == 3

    package = results[3]
    assert package["pool"] == "package"
    assert package["runtime"]["online"] is False


def test_pool_monitor_service_scans_slot_directories_when_runtime_offline(tmp_path):
    from app.desktop_ui.data.pool_monitor_service import PoolMonitorService

    work_dir = tmp_path / "pools" / "work"
    (work_dir / "worker_01").mkdir(parents=True)
    (work_dir / "worker_05").mkdir(parents=True)

    service = PoolMonitorService(root_dir=tmp_path)

    class OfflineRegistryReader:
        def list_all_pools(self):
            return [{"pool": "work", "pid": None, "port": 0, "status": "stopped"}]

    service._registry_reader = OfflineRegistryReader()

    results = service.get_all_pool_status()

    assert len(results) == 1
    assert results[0]["pool"] == "work"
    assert [slot["slot_id"] for slot in results[0]["slots"]] == ["worker_01", "worker_05"]
    assert results[0]["runtime"]["slot_total"] == 2


    """Test that DashboardView correctly formats data from monitor service into cards."""

    class MockMonitorService:
        def get_all_pool_status(self):
            return [
                {
                    "pool": "work",
                    "runtime": {
                        "online": True,
                        "pid": 1001,
                        "port": 18800,
                        "paused": False,
                        "queue_count": 5,
                        "slot_total": 1,
                        "slot_enabled": 1,
                        "slot_busy": 1,
                    },
                    "slots": [
                        {
                            "slot_id": "worker_01",
                            "busy": True,
                            "enabled": True,
                            "assigned_task_id": "task_abc",
                            "current_state": "state_2",
                            "current_stage": "",
                        }
                    ],
                }
            ]

    try:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])

        view = DashboardView(auto_refresh=False)
        view._monitor_service = MockMonitorService()
        pool_statuses = view._monitor_service.get_all_pool_status()
        view._render_pool_statuses(pool_statuses)

        assert hasattr(view, "_pool_column_widgets")
        assert len(view._pool_column_widgets) == 6
        work_col = view._pool_column_widgets[0]
        assert work_col._title_label.text() == "WORK"
        assert len(work_col._workstation_widgets) == 1
        assert work_col._workstation_widgets[0]._slot_id_label.text() == "worker_01"
        assert "01" in work_col._workstation_widgets[0]._status_label.text()
        assert "task_abc" in work_col._workstation_widgets[0]._status_label.text()
    except ImportError:
        pytest.skip("PySide6 not available for UI test")
