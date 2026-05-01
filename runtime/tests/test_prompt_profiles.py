"""Tests for the prompt tab backed by bootstrap files."""

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication
except ModuleNotFoundError:  # pragma: no cover
    QApplication = None

from app.desktop_ui.main_window import MainWindow
from app.desktop_ui.views.prompt_profile_view import PromptProfileView


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


def test_prompt_profile_view_uses_tools_directory_from_config_file(qapp, tmp_path):
    """PromptProfileView should resolve a config file path to its sibling tools directory."""
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    config_file = config_dir / "prompt_profiles.json"
    config_file.write_text("{}", encoding="utf-8")

    tools_dir = tmp_path / "tools"
    tools_dir.mkdir(parents=True)
    (tools_dir / "WORK_BOOTSTRAP.txt").write_text("work bootstrap", encoding="utf-8")
    (tools_dir / "THINKING_BOOTSTRAP.txt").write_text("thinking bootstrap", encoding="utf-8")

    view = PromptProfileView(config_file=config_file)

    assert view._store._tools_dir == Path(tools_dir)
    assert view._store.load_content("WORK_BOOTSTRAP") == "work bootstrap"
    assert view._store.load_content("THINKING_BOOTSTRAP") == "thinking bootstrap"


def test_main_window_registers_prompt_profile_tab(qapp, tmp_path):
    """MainWindow should register the prompt tab backed by PromptProfileView."""
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    config_file = config_dir / "prompt_profiles.json"
    config_file.write_text("{}", encoding="utf-8")

    tools_dir = tmp_path / "tools"
    tools_dir.mkdir(parents=True)
    (tools_dir / "WORK_BOOTSTRAP.txt").write_text("work", encoding="utf-8")

    window = MainWindow(prompt_profiles_path=config_file)

    tabs = window.centralWidget() if hasattr(window, "centralWidget") else window.central_widget
    if hasattr(tabs, "tabs"):
        labels = [label for _, label in tabs.tabs]
        prompt_tab = next(widget for widget, label in tabs.tabs if label == "提示词")
    else:
        labels = [tabs.tabText(index) for index in range(tabs.count())]
        prompt_index = labels.index("提示词")
        prompt_tab = tabs.widget(prompt_index)
    assert "提示词" in labels
    assert isinstance(prompt_tab, PromptProfileView)
