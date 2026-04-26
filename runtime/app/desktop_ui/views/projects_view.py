"""Projects view for project-level progress and details."""

try:
    from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
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


class ProjectsView(QWidget):
    def __init__(self, progress_reader=None):
        super().__init__()
        self.progress_reader = progress_reader
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("项目视图"))

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
