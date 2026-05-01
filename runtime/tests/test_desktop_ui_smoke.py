"""Smoke tests for desktop UI module imports and basic structure."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication
except ModuleNotFoundError:  # pragma: no cover
    QApplication = None


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


def test_desktop_ui_module_importable():
    """Test that desktop_ui main_window module can be imported."""
    import app.desktop_ui.main_window


def test_desktop_ui_app_module_importable():
    """Test that desktop_ui app module can be imported."""
    import app.desktop_ui.app


def test_desktop_ui_views_importable():
    """Test that all three view modules can be imported."""
    import app.desktop_ui.views.dashboard_view
    import app.desktop_ui.views.control_view
    import app.desktop_ui.views.projects_view


def test_projects_view_has_register_button(qapp):
    """Test that ProjectsView has register button."""
    from app.desktop_ui.views.projects_view import ProjectsView

    view = ProjectsView()
    assert hasattr(view, "_register_button")


def test_projects_view_can_open_dialog(qapp):
    """Test that ProjectsView has method to open registration dialog."""
    from app.desktop_ui.views.projects_view import ProjectsView

    view = ProjectsView()
    assert hasattr(view, "open_register_dialog")


def test_projects_view_click_creates_dialog(qapp):
    """Test that register click creates dialog instance."""
    from app.desktop_ui.views.projects_view import ProjectsView
    from app.desktop_ui.views.project_register_dialog import ProjectRegisterDialog

    view = ProjectsView()
    dialog = view._on_register_click()

    assert isinstance(dialog, ProjectRegisterDialog)
    assert view._register_dialog is dialog


def test_projects_view_click_shows_dialog(qapp):
    """Test that register click shows the dialog."""
    from app.desktop_ui.views.projects_view import ProjectsView

    view = ProjectsView()
    dialog = view._on_register_click()

    if hasattr(qapp, "processEvents"):
        qapp.processEvents()

    if hasattr(dialog, "isVisible"):
        assert dialog.isVisible() is True
