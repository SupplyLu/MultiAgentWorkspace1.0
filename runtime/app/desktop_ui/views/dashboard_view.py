"""Dashboard view for runtime status overview."""

from __future__ import annotations

from pathlib import Path
import re

from app.desktop_ui.data.pool_monitor_service import PoolMonitorService
from app.desktop_ui.data.runtime_client import RuntimeClient
from app.desktop_ui.services.runtime_command_bridge import RuntimeCommandBridge
from app.services.timeout_defaults_store import TimeoutDefaultsStore

try:
    from PySide6.QtCore import QTimer, QThread, Signal as QtSignal
    from PySide6.QtWidgets import (
        QDialog,
        QDialogButtonBox,
        QFormLayout,
        QFrame,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QScrollArea,
        QSpinBox,
        QVBoxLayout,
        QWidget,
    )

    class _DataFetchWorker(QThread):
        data_ready = QtSignal(list)

        def __init__(self, monitor_service):
            super().__init__()
            self._monitor_service = monitor_service

        def run(self):
            try:
                result = self._monitor_service.get_all_pool_status()
            except Exception:
                result = []
            self.data_ready.emit(result)

except ModuleNotFoundError:  # pragma: no cover - fallback for environments without PySide6
    class QWidget:
        def __init__(self, *args, **kwargs):
            pass

    class QDialog(QWidget):
        Accepted = 1

        def __init__(self, parent=None):
            super().__init__()
            self._parent = parent
            self._window_title = ""

        def setWindowTitle(self, title: str):
            self._window_title = title

        def exec(self):
            return 0

        def accept(self):
            return None

        def reject(self):
            return None

    class QLabel:
        def __init__(self, text: str = ""):
            self._text = text

        def text(self):
            return self._text

        def setText(self, text: str):
            self._text = text

        def setStyleSheet(self, style: str):
            self._style = style

        def setWordWrap(self, value: bool):
            self._word_wrap = value

    class _Signal:
        def connect(self, callback):
            self._callback = callback

    class QPushButton:
        def __init__(self, text: str = ""):
            self._text = text
            self.clicked = _Signal()
            self._visible = True

        def text(self):
            return self._text

        def setText(self, text: str):
            self._text = text

        def setStyleSheet(self, style: str):
            self._style = style

        def setFixedWidth(self, width: int):
            self._fixed_width = width

        def setVisible(self, visible: bool):
            self._visible = visible

    class QSpinBox:
        def __init__(self):
            self._minimum = 0
            self._maximum = 0
            self._single_step = 1
            self._value = 0

        def setMinimum(self, value: int):
            self._minimum = value

        def setMaximum(self, value: int):
            self._maximum = value

        def setSingleStep(self, value: int):
            self._single_step = value

        def setValue(self, value: int):
            self._value = value

        def value(self) -> int:
            return self._value

    class QDialogButtonBox:
        Ok = 1
        Cancel = 2

        def __init__(self, buttons=None):
            self.accepted = _Signal()
            self.rejected = _Signal()

    class QVBoxLayout:
        def __init__(self, parent=None):
            self.parent = parent
            self.children = []

        def addWidget(self, widget):
            self.children.append(widget)
            return None

        def addLayout(self, layout):
            self.children.append(layout)
            return None

        def addStretch(self):
            return None

        def setContentsMargins(self, *args):
            return None

        def setSpacing(self, spacing: int):
            return None

        def count(self):
            return len(self.children)

        def takeAt(self, index: int):
            return None

    class QHBoxLayout(QVBoxLayout):
        pass

    class QFormLayout(QVBoxLayout):
        def addRow(self, label, widget=None):
            if widget is None:
                self.children.append(label)
            else:
                self.children.append((label, widget))

    class QFrame(QWidget):
        def setStyleSheet(self, style: str):
            self._style = style

        def setFixedWidth(self, width: int):
            self._fixed_width = width

        def setFixedHeight(self, height: int):
            self._fixed_height = height

    class QScrollArea(QWidget):
        def setWidgetResizable(self, value: bool):
            self._widget_resizable = value

        def setWidget(self, widget):
            self._widget = widget

    class QTimer:
        def __init__(self, parent=None):
            self.parent = parent

    class _FallbackSignal:
        def connect(self, callback):
            self._callback = callback

        def emit(self, value):
            if hasattr(self, "_callback"):
                self._callback(value)

    class QThread:
        def __init__(self, parent=None):
            self.parent = parent

        def start(self):
            self.run()

    class QtSignal:
        def __init__(self, *args, **kwargs):
            self._signal = _FallbackSignal()

        def connect(self, callback):
            self._signal.connect(callback)

        def emit(self, value):
            self._signal.emit(value)

    class _DataFetchWorker(QThread):
        def __init__(self, monitor_service):
            super().__init__()
            self._monitor_service = monitor_service
            self.data_ready = _FallbackSignal()

        def run(self):
            try:
                result = self._monitor_service.get_all_pool_status()
            except Exception:
                result = []
            self.data_ready.emit(result)


DEFAULT_POOLS = ["work", "thinking", "construct", "gate", "post", "package"]
EXECUTION_POOLS = {"work", "thinking", "construct", "gate", "package"}


class TimeoutSettingsDialog(QDialog):
    def __init__(self, pool_name: str, current_timeout_seconds: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{pool_name.upper()} Timeout")
        self._spin_box = QSpinBox()
        if hasattr(self._spin_box, "setMinimum"):
            self._spin_box.setMinimum(60)
        if hasattr(self._spin_box, "setMaximum"):
            self._spin_box.setMaximum(86400)
        if hasattr(self._spin_box, "setSingleStep"):
            self._spin_box.setSingleStep(60)
        if hasattr(self._spin_box, "setValue"):
            self._spin_box.setValue(current_timeout_seconds)

        layout = QFormLayout(self)
        layout.addRow("Timeout (seconds):", self._spin_box)
        hint = QLabel("仅对后续新任务生效")
        if hasattr(hint, "setStyleSheet"):
            hint.setStyleSheet("color: #666666; font-size: 12px;")
        if hasattr(hint, "setWordWrap"):
            hint.setWordWrap(True)
        layout.addRow(hint)

        self._button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        if hasattr(self._button_box, "accepted"):
            self._button_box.accepted.connect(self.accept)
        if hasattr(self._button_box, "rejected"):
            self._button_box.rejected.connect(self.reject)
        layout.addRow(self._button_box)

    def selected_timeout_seconds(self) -> int:
        if hasattr(self._spin_box, "value"):
            return self._spin_box.value()
        return 60


class _DashboardOrderStore:
    def __init__(self, root_dir: Path | str):
        self._root_dir = Path(root_dir)
        self._order_file = self._root_dir / "runtime" / "state" / "dashboard_column_order.json"

    def load(self) -> list[str]:
        try:
            if not self._order_file.exists():
                return list(DEFAULT_POOLS)
            import json
            data = json.loads(self._order_file.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                return list(DEFAULT_POOLS)
            ordered = [pool for pool in data if pool in DEFAULT_POOLS]
            for pool in DEFAULT_POOLS:
                if pool not in ordered:
                    ordered.append(pool)
            return ordered
        except Exception:
            return list(DEFAULT_POOLS)

    def save(self, order: list[str]) -> None:
        try:
            import json
            self._order_file.parent.mkdir(parents=True, exist_ok=True)
            self._order_file.write_text(json.dumps(order, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass



class SlotStatusInferer:
    @staticmethod
    def infer_status(*, busy: bool, enabled: bool, assigned_task_id: str, current_state: str, online: bool) -> tuple[str, str]:
        task_id = assigned_task_id.strip()
        state = (current_state or "").strip().lower()

        if not online:
            return "离线", "gray"
        if not enabled:
            return "已下线", "gray"
        if state in {"error", "failed", "exception", "abnormal", "process_died"}:
            return "异常", "yellow"
        if busy:
            return "工作中", "green"
        if task_id:
            return "待收口", "yellow"
        return "空闲", "white"


class RuntimeStatusInferer:
    @staticmethod
    def infer(runtime: dict) -> tuple[str, str]:
        online = runtime.get("online", False)
        paused = runtime.get("paused", False)
        if not online:
            return "离线", "gray"
        if paused:
            return "已暂停", "yellow"
        return "运行中", "green"


class WorkstationWidget(QFrame):
    def __init__(self, pool_name: str, runtime: dict, slot: dict | None, index_label: str, runtime_client: RuntimeClient):
        super().__init__()
        self._pool_name = pool_name
        self._runtime = runtime
        self._slot = slot or {}
        self._runtime_client = runtime_client

        busy = self._slot.get("busy", False)
        enabled = self._slot.get("enabled", runtime.get("online", False))
        assigned_task_id = self._slot.get("assigned_task_id", "")
        current_state = self._slot.get("current_stage") or self._slot.get("current_state") or ""
        status_text, color_name = SlotStatusInferer.infer_status(
            busy=busy,
            enabled=enabled,
            assigned_task_id=assigned_task_id,
            current_state=current_state,
            online=runtime.get("online", False),
        )

        task_text = self._slot.get("assigned_project_name") or assigned_task_id or ""
        display = f"{index_label} {status_text}" if not task_text else f"{index_label} {task_text}"
        self._status_label = QLabel(display)
        self._slot_id_label = QLabel(self._slot.get("slot_id", "未配置"))

        layout = QHBoxLayout(self)
        if hasattr(layout, "setContentsMargins"):
            layout.setContentsMargins(4, 2, 4, 2)
        if hasattr(layout, "setSpacing"):
            layout.setSpacing(4)
        if hasattr(layout, "addWidget"):
            layout.addWidget(self._status_label)

        if hasattr(self, "setStyleSheet"):
            self.setStyleSheet(self._build_style(color_name))
        if hasattr(self, "setFixedHeight"):
            self.setFixedHeight(28)

    def _bring_online(self):
        slot_id = self._slot.get("slot_id")
        port = self._runtime.get("port")
        if slot_id and port:
            self._runtime_client.send_slot_control(self._pool_name, "online", slot_id, port)

    def _take_offline(self):
        slot_id = self._slot.get("slot_id")
        port = self._runtime.get("port")
        if slot_id and port:
            self._runtime_client.send_slot_control(self._pool_name, "offline", slot_id, port)

    @staticmethod
    def _build_style(color_name: str) -> str:
        background = {
            "green": "#dff6e4",
            "yellow": "#fff4cc",
            "gray": "#efefef",
            "white": "#ffffff",
        }.get(color_name, "#ffffff")
        return (
            "QFrame {"
            f"background-color: {background};"
            "border: 1px solid #d0d0d0;"
            "border-radius: 4px;"
            "padding: 2px 6px;"
            "}"
        )


class RuntimeColumnWidget(QFrame):
    def __init__(self, pool_name: str, runtime: dict, slots: list[dict], runtime_client: RuntimeClient, command_bridge: RuntimeCommandBridge, owner_view=None, can_move_left: bool = True, can_move_right: bool = True):
        super().__init__()
        self._pool_name = pool_name
        self._runtime = runtime
        self._runtime_client = runtime_client
        self._command_bridge = command_bridge
        self._owner_view = owner_view
        self._workstation_widgets: list[WorkstationWidget] = []

        status_text, color_name = RuntimeStatusInferer.infer(runtime)
        self._title_label = QLabel(pool_name.upper())
        self._status_label = QLabel(status_text)
        self._move_left_button = QPushButton("←")
        self._move_right_button = QPushButton("→")
        self._timeout_button = QPushButton("Timeout")

        layout = QVBoxLayout(self)
        if hasattr(layout, "setContentsMargins"):
            layout.setContentsMargins(6, 6, 6, 6)
        if hasattr(layout, "setSpacing"):
            layout.setSpacing(4)

        header_row = QHBoxLayout()
        if hasattr(header_row, "addWidget"):
            header_row.addWidget(self._title_label)
        if hasattr(header_row, "addStretch"):
            header_row.addStretch()
        if hasattr(header_row, "addWidget"):
            header_row.addWidget(self._timeout_button)
        if hasattr(layout, "addLayout"):
            layout.addLayout(header_row)
        if hasattr(layout, "addWidget"):
            layout.addWidget(self._status_label)

        # 显示当前默认超时
        default_timeout = runtime.get("default_timeout_seconds")
        if default_timeout is not None and pool_name in EXECUTION_POOLS:
            timeout_display = QLabel(f"默认超时: {default_timeout}s")
            if hasattr(timeout_display, "setStyleSheet"):
                timeout_display.setStyleSheet("font-size: 11px; color: #555555;")
            if hasattr(layout, "addWidget"):
                layout.addWidget(timeout_display)

        button_row = QHBoxLayout()
        self._start_button = QPushButton("Online")
        self._stop_button = QPushButton("Offline")
        if hasattr(button_row, "addWidget"):
            button_row.addWidget(self._start_button)
            button_row.addWidget(self._stop_button)
        if hasattr(layout, "addLayout"):
            layout.addLayout(button_row)

        for index_label, slot in self._build_workstations(slots):
            station = WorkstationWidget(
                pool_name=pool_name,
                runtime=runtime,
                slot=slot,
                index_label=index_label,
                runtime_client=runtime_client,
            )
            self._workstation_widgets.append(station)
            if hasattr(layout, "addWidget"):
                layout.addWidget(station)

        if hasattr(layout, "addStretch"):
            layout.addStretch()

        move_row = QHBoxLayout()
        if hasattr(move_row, "addWidget"):
            move_row.addWidget(self._move_left_button)
            move_row.addWidget(self._move_right_button)
        if hasattr(layout, "addLayout"):
            layout.addLayout(move_row)

        if hasattr(self._start_button, "clicked"):
            self._start_button.clicked.connect(self._start)
        if hasattr(self._stop_button, "clicked"):
            self._stop_button.clicked.connect(self._stop)
        if hasattr(self._move_left_button, "clicked"):
            self._move_left_button.clicked.connect(self._move_left)
        if hasattr(self._move_right_button, "clicked"):
            self._move_right_button.clicked.connect(self._move_right)
        if hasattr(self._timeout_button, "clicked"):
            self._timeout_button.clicked.connect(self._open_timeout_settings)

        if hasattr(self._title_label, "setStyleSheet"):
            self._title_label.setStyleSheet("font-size: 13px; font-weight: 700;")
        if hasattr(self._move_left_button, "setFixedWidth"):
            self._move_left_button.setFixedWidth(36)
        if hasattr(self._move_right_button, "setFixedWidth"):
            self._move_right_button.setFixedWidth(36)
        if hasattr(self._timeout_button, "setFixedWidth"):
            self._timeout_button.setFixedWidth(70)
        if hasattr(self._move_left_button, "setVisible"):
            self._move_left_button.setVisible(can_move_left)
        if hasattr(self._move_right_button, "setVisible"):
            self._move_right_button.setVisible(can_move_right)
        if pool_name not in EXECUTION_POOLS and hasattr(self._timeout_button, "setStyleSheet"):
            self._timeout_button.setStyleSheet("color: #999999;")
        if hasattr(self, "setStyleSheet"):
            self.setStyleSheet(self._build_style(color_name))
        if hasattr(self, "setFixedWidth"):
            self.setFixedWidth(220)

    def _move_left(self):
        print(f"[DEBUG] {self._pool_name} Left clicked")
        if self._owner_view:
            self._owner_view._move_pool_by_step(self._pool_name, -1)

    def _move_right(self):
        print(f"[DEBUG] {self._pool_name} Right clicked")
        if self._owner_view:
            self._owner_view._move_pool_by_step(self._pool_name, 1)

    def _build_workstations(self, slots: list[dict]) -> list[tuple[str, dict | None]]:
        sorted_slots = sorted(
            slots,
            key=lambda slot: self._slot_sort_key(slot.get("slot_id", "")),
        )
        return [
            (self._display_label_for_slot(slot.get("slot_id", "--")), slot)
            for slot in sorted_slots
        ]

    @staticmethod
    def _display_label_for_slot(slot_id: str) -> str:
        match = re.search(r"(\d+)$", slot_id or "")
        if not match:
            return slot_id or "--"
        return f"{int(match.group(1)):02d}"

    @staticmethod
    def _slot_sort_key(slot_id: str) -> tuple[int, int, str]:
        match = re.search(r"(\d+)$", slot_id or "")
        if match:
            return (0, int(match.group(1)), slot_id or "")
        return (1, 0, slot_id or "")

    def _start(self):
        self._command_bridge.start_pool(self._pool_name)

    def _stop(self):
        self._command_bridge.stop_pool(self._pool_name)

    def _pause(self):
        port = self._runtime.get("port")
        if port:
            self._runtime_client.send_control(self._pool_name, "pause", port)

    def _resume(self):
        port = self._runtime.get("port")
        if port:
            self._runtime_client.send_control(self._pool_name, "resume", port)

    def _open_timeout_settings(self):
        pool_name = self._pool_name
        if pool_name not in EXECUTION_POOLS:
            return
        root_dir = self._owner_view._monitor_service._root_dir if self._owner_view else None
        if root_dir is None:
            return
        store = TimeoutDefaultsStore(root_dir=root_dir)
        current = store.get(pool_name)
        dialog = TimeoutSettingsDialog(pool_name=pool_name, current_timeout_seconds=current)
        if hasattr(dialog, "exec"):
            result = dialog.exec()
        else:
            result = 0
        accepted_code = getattr(QDialog, "Accepted", 1)
        if result == accepted_code:
            new_timeout = dialog.selected_timeout_seconds()
            store.set(pool_name, new_timeout)
            if self._owner_view:
                self._owner_view._refresh_data()
            print(f"[TimeoutSettings] {pool_name} timeout updated to {new_timeout}s")

    @staticmethod
    def _build_style(color_name: str) -> str:
        background = {
            "green": "#f4fbf4",
            "yellow": "#fff9e8",
            "gray": "#f2f2f2",
            "white": "#ffffff",
        }.get(color_name, "#ffffff")
        return (
            "QFrame {"
            f"background-color: {background};"
            "border: 1px solid #bfbfbf;"
            "border-radius: 10px;"
            "}"
        )


class DashboardView(QWidget):
    RuntimeColumnWidget = RuntimeColumnWidget

    def __init__(self, root_dir: Path | str | None = None, auto_refresh: bool = True):
        super().__init__()

        if root_dir is None:
            root_dir = Path(__file__).resolve().parents[3]

        self._monitor_service = PoolMonitorService(root_dir=root_dir)
        self._runtime_client = RuntimeClient(root_dir=root_dir)
        self._command_bridge = RuntimeCommandBridge(root_dir=root_dir)
        self._order_store = _DashboardOrderStore(root_dir=root_dir)
        self._pool_order = self._order_store.load()
        self._drag_source_pool: str | None = None
        self._pool_column_widgets: list[RuntimeColumnWidget] = []

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("工位监控"))

        self._scroll_area = QScrollArea()
        if hasattr(self._scroll_area, "setWidgetResizable"):
            self._scroll_area.setWidgetResizable(True)

        self._content_widget = QWidget()
        self._content_layout = QHBoxLayout(self._content_widget)
        if hasattr(self._content_layout, "setContentsMargins"):
            self._content_layout.setContentsMargins(12, 12, 12, 12)
        if hasattr(self._content_layout, "setSpacing"):
            self._content_layout.setSpacing(12)

        if hasattr(self._scroll_area, "setWidget"):
            self._scroll_area.setWidget(self._content_widget)
        layout.addWidget(self._scroll_area)

        self._timer = QTimer(self)
        self._refresh_in_flight = False
        self._worker = None
        if auto_refresh and hasattr(self._timer, "timeout"):
            self._timer.timeout.connect(self._refresh_data)
        if auto_refresh and hasattr(self._timer, "start"):
            self._timer.start(2000)

        if auto_refresh:
            self._refresh_data()

    def _clear_content(self) -> None:
        self._pool_column_widgets = []
        if not hasattr(self._content_layout, "count"):
            return
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            widget = item.widget() if item and hasattr(item, "widget") else None
            if widget is not None and hasattr(widget, "deleteLater"):
                widget.deleteLater()

    def _normalize_pool_order(self, pool_statuses: list[dict]) -> list[dict]:
        by_pool = {item.get("pool"): item for item in pool_statuses}
        ordered = []
        for pool in self._pool_order:
            ordered.append(by_pool.get(pool, {"pool": pool, "runtime": {"online": False, "paused": False, "queue_count": 0, "slot_enabled": 0, "slot_busy": 0}, "slots": []}))
        return ordered

    def _move_pool_before(self, source_pool: str, target_pool: str) -> None:
        if source_pool == target_pool:
            return
        if source_pool not in self._pool_order or target_pool not in self._pool_order:
            return
        self._pool_order.remove(source_pool)
        target_index = self._pool_order.index(target_pool)
        self._pool_order.insert(target_index, source_pool)
        self._order_store.save(self._pool_order)

    def _move_pool_by_step(self, source_pool: str, step: int) -> None:
        print(f"[DEBUG] _move_pool_by_step called: pool={source_pool}, step={step}")
        if source_pool not in self._pool_order:
            print(f"[DEBUG] pool {source_pool} not in order")
            return
        current_index = self._pool_order.index(source_pool)
        target_index = current_index + step
        print(f"[DEBUG] current_index={current_index}, target_index={target_index}, len={len(self._pool_order)}")
        if target_index < 0 or target_index >= len(self._pool_order):
            print(f"[DEBUG] target_index out of bounds")
            return
        self._pool_order[current_index], self._pool_order[target_index] = self._pool_order[target_index], self._pool_order[current_index]
        print(f"[DEBUG] new order: {self._pool_order}")
        self._order_store.save(self._pool_order)
        print(f"[DEBUG] calling _render_pool_statuses")
        self._render_pool_statuses(getattr(self, "_last_pool_statuses", []))

    def _render_pool_statuses(self, pool_statuses):
        self._last_pool_statuses = list(pool_statuses)
        self._clear_content()
        ordered_pool_statuses = self._normalize_pool_order(pool_statuses)
        total = len(ordered_pool_statuses)
        for index, pool_data in enumerate(ordered_pool_statuses):
            pool_name = pool_data["pool"]
            runtime = pool_data.get("runtime", {})
            slots = pool_data.get("slots", [])
            column = self.RuntimeColumnWidget(
                pool_name=pool_name,
                runtime=runtime,
                slots=slots,
                runtime_client=self._runtime_client,
                command_bridge=self._command_bridge,
                owner_view=self,
                can_move_left=index > 0,
                can_move_right=index < total - 1,
            )
            self._pool_column_widgets.append(column)
            if hasattr(self._content_layout, "addWidget"):
                self._content_layout.addWidget(column)
        if hasattr(self._content_layout, "addStretch"):
            self._content_layout.addStretch()

    def _apply_refresh_result(self, pool_statuses):
        self._refresh_in_flight = False
        self._render_pool_statuses(pool_statuses)

    def _refresh_data(self):
        if self._refresh_in_flight:
            return
        self._refresh_in_flight = True
        self._worker = _DataFetchWorker(self._monitor_service)
        self._worker.data_ready.connect(self._apply_refresh_result)
        self._worker.start()
