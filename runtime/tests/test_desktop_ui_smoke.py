"""Smoke tests for desktop UI module imports and basic structure."""


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
