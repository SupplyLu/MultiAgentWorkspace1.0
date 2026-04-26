"""Test desktop UI POST progress view and blockage observation."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication
except ModuleNotFoundError:  # pragma: no cover
    QApplication = None

from app.desktop_ui.data.post_progress_reader import PostProgressReader
from app.desktop_ui.views.projects_view import ProjectsView


@pytest.fixture
def qapp():
    if QApplication is None:
        yield None
        return

    app = QApplication.instance()
    created = False
    if app is None:
        app = QApplication([])
        created = True

    yield app

    if created:
        app.quit()


def test_progress_reader_calculates_percentage_from_project_files(tmp_path):
    """Test that PostProgressReader calculates progress percentage from projects."""
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    # Setup: create post_index.json with 2 projects
    post_index = {"projects": ["SignalOfBridge-v1-Build", "AnotherApp-v1-Build"], "dependencies": [], "deliveries": [], "manager_actions": []}
    (tmp_path / "post_index.json").write_text(json.dumps(post_index), encoding="utf-8")

    # Setup: project_1 delivered
    project_1 = {
        "project_key": "SignalOfBridge-v1-Build",
        "from_pool": "task",
        "to_pool": "work",
        "route": ["task", "thinking", "construct", "gate", "work"],
        "cursor": 4,
        "current_pool": "work",
        "next_pool": None,
        "status": "delivered",
        "route_version": 1,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:01:00Z",
    }
    (tmp_path / "projects" / "SignalOfBridge-v1-Build.json").write_text(json.dumps(project_1), encoding="utf-8")

    # Setup: project_2 blocked
    project_2 = {
        "project_key": "AnotherApp-v1-Build",
        "from_pool": "task",
        "to_pool": "work",
        "route": ["task", "thinking", "construct", "gate", "work"],
        "cursor": 3,
        "current_pool": "gate",
        "next_pool": "work",
        "status": "blocked",
        "blocked_reason": "Connection timeout to API",
        "route_version": 1,
        "created_at": "2026-01-01T00:02:00Z",
        "updated_at": "2026-01-01T00:03:00Z",
    }
    (tmp_path / "projects" / "AnotherApp-v1-Build.json").write_text(json.dumps(project_2), encoding="utf-8")

    reader = PostProgressReader(transfers_dir=tmp_path)
    progress = reader.get_progress()

    # 1 delivered / 2 total = 50%
    assert progress["percentage"] == 50
    assert progress["total"] == 2
    assert progress["completed"] == 1


def test_progress_reader_derives_current_stage(tmp_path):
    """Test that PostProgressReader derives current stage from project current_pool."""
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    post_index = {"projects": ["SignalOfBridge-v1-Build"], "dependencies": [], "deliveries": [], "manager_actions": []}
    (tmp_path / "post_index.json").write_text(json.dumps(post_index), encoding="utf-8")

    project_1 = {
        "project_key": "SignalOfBridge-v1-Build",
        "from_pool": "task",
        "to_pool": "work",
        "route": ["task", "thinking", "construct", "gate", "work"],
        "cursor": 1,
        "current_pool": "thinking",
        "next_pool": "construct",
        "status": "in_progress",
        "route_version": 1,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:01:00Z",
    }
    (tmp_path / "projects" / "SignalOfBridge-v1-Build.json").write_text(json.dumps(project_1), encoding="utf-8")

    reader = PostProgressReader(transfers_dir=tmp_path)
    progress = reader.get_progress()

    assert progress["current_pool"] == "thinking"
    assert progress["stage"] == "processing"


def test_progress_reader_derives_blockage_reason(tmp_path):
    """Test that PostProgressReader derives blockage reason when project is blocked."""
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    post_index = {"projects": ["SignalOfBridge-v1-Build"], "dependencies": [], "deliveries": [], "manager_actions": []}
    (tmp_path / "post_index.json").write_text(json.dumps(post_index), encoding="utf-8")

    project_1 = {
        "project_key": "SignalOfBridge-v1-Build",
        "from_pool": "task",
        "to_pool": "work",
        "route": ["task", "thinking", "construct", "gate", "work"],
        "cursor": 1,
        "current_pool": "thinking",
        "next_pool": "construct",
        "status": "blocked",
        "blocked_reason": "API rate limit exceeded",
        "route_version": 1,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:05:00Z",
    }
    (tmp_path / "projects" / "SignalOfBridge-v1-Build.json").write_text(json.dumps(project_1), encoding="utf-8")

    reader = PostProgressReader(transfers_dir=tmp_path)
    progress = reader.get_progress()

    assert progress["blocked"] is True
    assert "rate limit" in progress["block_reason"].lower()


def test_progress_reader_handles_waiting_status_as_processing(tmp_path):
    """Test that PostProgressReader treats 'waiting' status as processing stage."""
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    post_index = {"projects": ["SignalOfBridge-v1-Build"], "dependencies": [], "deliveries": [], "manager_actions": []}
    (tmp_path / "post_index.json").write_text(json.dumps(post_index), encoding="utf-8")

    project_1 = {
        "project_key": "SignalOfBridge-v1-Build",
        "from_pool": "task",
        "to_pool": "work",
        "route": ["task", "thinking", "construct", "gate", "work"],
        "cursor": 0,
        "current_pool": "task",
        "next_pool": "thinking",
        "status": "waiting",
        "route_version": 1,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:01:00Z",
    }
    (tmp_path / "projects" / "SignalOfBridge-v1-Build.json").write_text(json.dumps(project_1), encoding="utf-8")

    reader = PostProgressReader(transfers_dir=tmp_path)
    progress = reader.get_progress()

    assert progress["stage"] == "processing"


def test_progress_reader_returns_idle_when_no_projects(tmp_path):
    """Test that PostProgressReader returns idle state when no projects registered."""
    reader = PostProgressReader(transfers_dir=tmp_path)
    progress = reader.get_progress()

    assert progress["percentage"] == 0
    assert progress["completed"] == 0
    assert progress["total"] == 0
    assert progress["current_pool"] is None
    assert progress["stage"] == "idle"
    assert progress["blocked"] is False
    assert progress["block_reason"] is None


def test_projects_view_shows_progress_summary(qapp):
    """Test that ProjectsView displays progress summary for POST projects."""
    reader_mock = MagicMock(spec=PostProgressReader)
    reader_mock.get_progress.return_value = {
        "percentage": 75,
        "completed": 15,
        "total": 20,
        "current_pool": "gate",
        "stage": "processing",
        "blocked": False,
        "block_reason": None,
    }

    view = ProjectsView(progress_reader=reader_mock)
    summary = view.get_progress_summary("test_post")

    assert "75%" in summary
    assert "15/20" in summary
    reader_mock.get_progress.assert_called_once()


def test_projects_view_shows_blockage_alert(qapp):
    """Test that ProjectsView highlights blocked projects."""
    reader_mock = MagicMock(spec=PostProgressReader)
    reader_mock.get_progress.return_value = {
        "percentage": 30,
        "completed": 3,
        "total": 10,
        "current_pool": "thinking",
        "stage": "blocked",
        "blocked": True,
        "block_reason": "Connection timeout to API",
    }

    view = ProjectsView(progress_reader=reader_mock)
    alert = view.get_blockage_alert()

    assert alert["blocked"] is True
    assert "timeout" in alert["reason"].lower()
