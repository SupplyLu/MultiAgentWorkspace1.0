"""Projects view for project-level progress and details."""

try:
    from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget
except ModuleNotFoundError:  # pragma: no cover - fallback for environments without PySide6
    class QWidget:
        pass

    class QLabel:
        def __init__(self, text: str = ""):
            self.text = text

    class QVBoxLayout:
        def __init__(self, parent=None):
            self.parent = parent

        def addWidget(self, widget):
            return None

    class _Signal:
        def connect(self, callback):
            self._callback = callback

    class QPushButton:
        def __init__(self, text: str = ""):
            self.text = text
            self.clicked = _Signal()

from app.desktop_ui.views.project_register_dialog import ProjectRegisterDialog
from app.desktop_ui.views.create_pool_dialog import CreatePoolDialog


class ProjectsView(QWidget):
    def __init__(self, progress_reader=None):
        super().__init__()
        self.progress_reader = progress_reader
        self._register_dialog = None
        self._create_pool_dialog = None
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("项目视图"))

        self._register_button = QPushButton("新建注册")
        layout.addWidget(self._register_button)
        self._register_button.clicked.connect(self._on_register_click)

        self._create_pool_button = QPushButton("创建池")
        layout.addWidget(self._create_pool_button)
        self._create_pool_button.clicked.connect(self._on_create_pool_click)

    def open_register_dialog(self):
        """Create, show, and return the registration dialog."""
        self._register_dialog = ProjectRegisterDialog(self)
        if hasattr(self._register_dialog, "show"):
            self._register_dialog.show()
        return self._register_dialog

    def _on_register_click(self):
        """Handle register button click."""
        return self.open_register_dialog()

    def open_create_pool_dialog(self):
        """Create, show, and return the create pool dialog."""
        self._create_pool_dialog = CreatePoolDialog(self)
        if hasattr(self._create_pool_dialog, "show"):
            self._create_pool_dialog.show()
        return self._create_pool_dialog

    def _on_create_pool_click(self):
        """Handle create pool button click."""
        return self.open_create_pool_dialog()

    def get_progress_summary(self, project_name: str) -> str:
        if not self.progress_reader:
            return "0% (0/0)"
        progress = self.progress_reader.get_progress()
        return f"{project_name}: {progress['percentage']}% ({progress['completed']}/{progress['total']})"

    def get_blockage_alert(self) -> dict:
        if not self.progress_reader:
            return {"blocked": False, "reason": None}
        progress = self.progress_reader.get_progress()
        return {
            "blocked": progress.get("blocked", False),
            "reason": progress.get("block_reason"),
        }
