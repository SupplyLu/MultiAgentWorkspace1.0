"""Desktop UI application entry point."""

from pathlib import Path

from app.shared.single_instance_guard import SingleInstanceGuard

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
    root_dir = Path(__file__).resolve().parents[3]

    guard = SingleInstanceGuard(root_dir=root_dir, instance_key="desktop_ui")
    success, message = guard.try_acquire(timeout=0.1)

    if not success:
        print(f"[Desktop UI] {message}")
        print("提示：桌面 UI 已在运行，请勿重复启动")
        return 1

    app = create_app(argv)
    window = MainWindow(root_dir=root_dir)
    if hasattr(window, "show"):
        window.show()

    exit_code = app.exec()
    guard.release()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
