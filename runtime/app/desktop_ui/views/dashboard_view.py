"""Dashboard view for runtime status overview."""

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


class DashboardView(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("态势总览"))
