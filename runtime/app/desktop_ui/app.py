"""Desktop UI application entry point."""

try:
    from PySide6.QtWidgets import QApplication
except ModuleNotFoundError:  # pragma: no cover - fallback for environments without PySide6
    class QApplication:
        def __init__(self, args):
            self.args = args

        def exec(self):
            return 0

from app.desktop_ui.main_window import MainWindow


def create_app(argv=None):
    argv = argv or []
    return QApplication(argv)


def main(argv=None):
    app = create_app(argv)
    window = MainWindow()
    if hasattr(window, "show"):
        window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
