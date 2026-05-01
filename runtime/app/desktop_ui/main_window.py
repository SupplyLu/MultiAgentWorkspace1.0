"""Main window for the local desktop UI."""

try:
    from PySide6.QtWidgets import QMainWindow, QTabWidget
except ModuleNotFoundError:  # pragma: no cover - fallback for environments without PySide6
    class QMainWindow:
        def setWindowTitle(self, title: str):
            self.window_title = title

        def resize(self, width: int, height: int):
            self.window_size = (width, height)

        def setCentralWidget(self, widget):
            self.central_widget = widget

    class QTabWidget:
        def __init__(self):
            self.tabs = []

        def addTab(self, widget, label: str):
            self.tabs.append((widget, label))

from app.desktop_ui.views.control_view import ControlView
from app.desktop_ui.views.dashboard_view import DashboardView
from pathlib import Path

from app.desktop_ui.views.projects_view import ProjectsView
from app.desktop_ui.views.prompt_profile_view import PromptProfileView


class MainWindow(QMainWindow):
    def __init__(self, prompt_profiles_path: Path | str | None = None, root_dir: Path | str | None = None):
        super().__init__()
        self.setWindowTitle("MultiAgent Workspace Desktop UI")
        self.resize(1200, 800)

        if root_dir is None:
            root_dir = Path(__file__).resolve().parents[3]

        if prompt_profiles_path is None:
            prompt_profiles_path = Path(__file__).resolve().parents[2] / "config" / "prompt_profiles.json"

        tabs = QTabWidget()
        tabs.addTab(DashboardView(root_dir=root_dir), "态势")
        tabs.addTab(ControlView(), "控制")
        tabs.addTab(ProjectsView(), "项目")
        tabs.addTab(PromptProfileView(prompt_profiles_path), "提示词")
        self.setCentralWidget(tabs)
