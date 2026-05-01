"""Dialog for project registration with interactive route selection."""

from pathlib import Path

from app.desktop_ui.services.project_registration_service import ProjectRegistrationService

try:
    from PySide6.QtWidgets import (
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QFormLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QPushButton,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ModuleNotFoundError:  # pragma: no cover - fallback for environments without PySide6
    class QDialog:
        def __init__(self, parent=None):
            self._parent = parent
            self._window_title = ""

        def setWindowTitle(self, title: str):
            self._window_title = title

        def windowTitle(self) -> str:
            return self._window_title

    class QLineEdit:
        def __init__(self):
            self._text = ""

        def setText(self, text: str):
            self._text = text

        def text(self) -> str:
            return self._text

    class QTextEdit:
        def __init__(self):
            self._text = ""

        def setPlainText(self, text: str):
            self._text = text

        def toPlainText(self) -> str:
            return self._text

    class QComboBox:
        def __init__(self):
            self._items = []
            self._current_text = ""

        def addItems(self, items):
            self._items.extend(items)
            if self._items and not self._current_text:
                self._current_text = self._items[0]

        def count(self) -> int:
            return len(self._items)

        def setCurrentText(self, text: str):
            self._current_text = text

        def currentText(self) -> str:
            return self._current_text

    class QLabel:
        def __init__(self, text: str = ""):
            self._text = text

        def setText(self, text: str):
            self._text = text

    class QListWidget:
        def __init__(self):
            self._items = []

        def addItem(self, text: str):
            self._items.append(text)

        def clear(self):
            self._items = []

        def count(self) -> int:
            return len(self._items)

        def currentRow(self) -> int:
            return 0

        def takeItem(self, row: int):
            if 0 <= row < len(self._items):
                self._items.pop(row)

    class QPushButton:
        def __init__(self, text: str = ""):
            self._text = text
            self._callback = None

        def setText(self, text: str):
            self._text = text

        def text(self) -> str:
            return self._text

        def clicked(self):
            class Signal:
                def connect(self, cb):
                    pass
            return Signal()

    class QDialogButtonBox:
        pass

    class QWidget:
        pass

    class QVBoxLayout:
        def __init__(self, parent=None):
            pass

        def addWidget(self, widget):
            pass

        def addLayout(self, layout):
            pass

    class QHBoxLayout:
        def __init__(self):
            pass

        def addWidget(self, widget):
            pass

        def addStretch(self):
            pass

    class QFormLayout:
        def __init__(self, parent=None):
            pass

        def addRow(self, label, widget=None):
            pass


class ProjectRegisterDialog(QDialog):
    """Dialog for collecting project registration input with interactive route building."""

    def __init__(self, parent=None, service: ProjectRegistrationService | None = None, root_dir: Path | str | None = None):
        super().__init__(parent)
        self.setWindowTitle("Project Registration")
        self._service = service or ProjectRegistrationService(root_dir or Path(__file__).resolve().parents[4])

        self._project_name_input = QLineEdit()
        self._version_input = QLineEdit()
        self._mode_combo = QComboBox()
        self._route_list = QListWidget()
        self._route_description_label = QLabel("")
        self._requirements_input = QTextEdit()
        self._button_box = QDialogButtonBox()

        # Populate mode dropdown
        available_modes = self._service.list_available_modes()
        if available_modes and hasattr(self._mode_combo, "addItems"):
            self._mode_combo.addItems(available_modes)
            default_mode = self._service.get_default_mode()
            if default_mode and hasattr(self._mode_combo, "setCurrentText"):
                self._mode_combo.setCurrentText(default_mode)

        # Build route section with pool buttons
        self._route_section = self._build_route_section()

        # Build form layout
        layout = QFormLayout(self)
        layout.addRow("项目名:", self._project_name_input)
        layout.addRow("版本号:", self._version_input)
        layout.addRow("Mode:", self._mode_combo)
        layout.addRow("链路:", self._route_section)
        layout.addRow("项目总要求:", self._requirements_input)

        if hasattr(self._button_box, "setStandardButtons"):
            from PySide6.QtWidgets import QDialogButtonBox as RealButtonBox
            self._button_box.setStandardButtons(RealButtonBox.Ok | RealButtonBox.Cancel)
            self._button_box.accepted.connect(self._on_accept)
            self._button_box.rejected.connect(self.reject)
        layout.addRow(self._button_box)

        # Initialize with default route
        self._reset_route_to_default()

    def _build_route_section(self) -> QWidget:
        """Build the route selection section with pool buttons and route list."""
        container = QWidget()
        main_layout = QVBoxLayout(container)

        # Pool selection buttons
        pool_buttons_widget = QWidget()
        pool_buttons_layout = QHBoxLayout(pool_buttons_widget)

        available_pools = self._service.list_available_pools()
        for pool_name in available_pools:
            btn = QPushButton(pool_name)
            if hasattr(btn, "clicked"):
                btn.clicked.connect(lambda checked, p=pool_name: self._on_pool_clicked(p))
            pool_buttons_layout.addWidget(btn)

        pool_buttons_layout.addStretch()
        main_layout.addWidget(QLabel("点击添加池到链路:"))
        main_layout.addWidget(pool_buttons_widget)
        if hasattr(self._route_description_label, "setWordWrap"):
            self._route_description_label.setWordWrap(True)
        if hasattr(self._route_description_label, "setStyleSheet"):
            self._route_description_label.setStyleSheet("color: #666666; font-size: 12px;")
        self._refresh_route_descriptions()
        main_layout.addWidget(self._route_description_label)

        # Route display list
        main_layout.addWidget(QLabel("当前链路 (双击删除, task 为首项):"))
        if hasattr(self._route_list, "itemDoubleClicked"):
            self._route_list.itemDoubleClicked.connect(self._on_item_double_clicked)
        main_layout.addWidget(self._route_list)

        # Route control buttons
        controls_widget = QWidget()
        controls_layout = QHBoxLayout(controls_widget)

        delete_last_btn = QPushButton("删除最后一个")
        if hasattr(delete_last_btn, "clicked"):
            delete_last_btn.clicked.connect(self._on_delete_last)
        controls_layout.addWidget(delete_last_btn)

        clear_btn = QPushButton("清空")
        if hasattr(clear_btn, "clicked"):
            clear_btn.clicked.connect(self._on_clear_route)
        controls_layout.addWidget(clear_btn)

        reset_btn = QPushButton("恢复默认")
        if hasattr(reset_btn, "clicked"):
            reset_btn.clicked.connect(self._reset_route_to_default)
        controls_layout.addWidget(reset_btn)

        controls_layout.addStretch()
        main_layout.addWidget(controls_widget)

        return container

    def _on_pool_clicked(self, pool_name: str):
        """Handle pool button click - add to route if valid."""
        current_route = self._get_current_route()

        # Don't allow duplicate consecutive pools
        if current_route and current_route[-1] == pool_name:
            return

        # task must be first, can only be added once at start
        if pool_name == "task":
            if not current_route:
                self._route_list.addItem(pool_name)
            return

        # For other pools, add after ensuring we have a starting point
        if not current_route:
            # Auto-add task as first item if not present
            self._route_list.addItem("task")

        self._route_list.addItem(pool_name)
        self._refresh_route_descriptions()

    def _on_delete_last(self):
        """Remove the last item from route (but keep task if it's the only item)."""
        count = self._route_list.count()
        if count > 1:
            self._route_list.takeItem(count - 1)
            self._refresh_route_descriptions()

    def _on_item_double_clicked(self, item):
        """Handle double click on a route item to delete it."""
        if hasattr(self._route_list, "row") and hasattr(self._route_list, "takeItem"):
            row = self._route_list.row(item)
            self._route_list.takeItem(row)
            self._refresh_route_descriptions()

    def _on_clear_route(self):
        """Clear the route list."""
        self._route_list.clear()
        self._refresh_route_descriptions()

    def _reset_route_to_default(self):
        """Reset route to the default from flow policy."""
        self._route_list.clear()
        default_route = self._service.get_default_route()
        for pool in default_route:
            self._route_list.addItem(pool)
        self._refresh_route_descriptions()

    def _refresh_route_descriptions(self):
        """Refresh one-line duty descriptions for current route."""
        route = self._get_current_route()
        lines = []
        for pool in route:
            description = self._service.get_pool_description(pool)
            if description:
                lines.append(f"{pool}: {description}")
            else:
                lines.append(pool)
        self._route_description_label.setText("\n".join(lines))

    def _get_current_route(self) -> list[str]:
        """Get current route as list of strings."""
        route = []
        if hasattr(self._route_list, "count") and hasattr(self._route_list, "item"):
            for i in range(self._route_list.count()):
                item = self._route_list.item(i)
                if item is None:
                    continue
                if hasattr(item, "text"):
                    route.append(item.text())
                elif isinstance(item, str):
                    route.append(item)
        elif hasattr(self._route_list, "_items"):
            route.extend(self._route_list._items)
        return route

    def _on_accept(self):
        """Handle OK button click."""
        result = self.submit_registration()
        if result.get("success"):
            self.accept()

    def submit_registration(self) -> dict:
        """Submit current form fields through the registration service."""
        return self._service.register(
            project_name=self._project_name_input.text(),
            version=self._version_input.text(),
            mode=self._mode_combo.currentText(),
            target_pool="",
            requirements=self._requirements_input.toPlainText(),
            route=self._get_current_route(),
        )
