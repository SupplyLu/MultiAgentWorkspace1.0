"""Create Pool Dialog - UI for creating new runtime pools."""

from pathlib import Path

from app.desktop_ui.services.pool_creation_service import PoolCreationService, PoolCreationError

try:
    from PySide6.QtWidgets import (
        QCheckBox,
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QFormLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMessageBox,
        QSpinBox,
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

        def resize(self, width: int, height: int):
            pass

        def accept(self):
            pass

        def reject(self):
            pass

    class QComboBox:
        def __init__(self):
            self._items = []
            self._current_text = ""

        def addItem(self, label: str, user_data=None):
            self._items.append((label, user_data))
            if not self._current_text:
                self._current_text = label

        def currentData(self):
            for label, user_data in self._items:
                if label == self._current_text:
                    return user_data
            return None

        def currentText(self):
            return self._current_text

    class QLineEdit:
        def __init__(self):
            self._text = ""

        def setText(self, text: str):
            self._text = text

        def text(self) -> str:
            return self._text

        def setPlaceholderText(self, text: str):
            pass

        def setEnabled(self, enabled: bool):
            pass

    class QTextEdit:
        def __init__(self):
            self._text = ""

        def setPlainText(self, text: str):
            self._text = text

        def toPlainText(self) -> str:
            return self._text

        def setPlaceholderText(self, text: str):
            pass

    class QSpinBox:
        def __init__(self):
            self._value = 2
            self._minimum = 1
            self._maximum = 99

        def setValue(self, value: int):
            self._value = value

        def value(self) -> int:
            return self._value

        def setMinimum(self, min_val: int):
            self._minimum = min_val

        def setMaximum(self, max_val: int):
            self._maximum = max_val

    class QCheckBox:
        def __init__(self, text: str = ""):
            self._text = text
            self._checked = False

        def setText(self, text: str):
            self._text = text

        def text(self) -> str:
            return self._text

        def setChecked(self, checked: bool):
            self._checked = checked

        def isChecked(self) -> bool:
            return self._checked

    class QLabel:
        def __init__(self, text: str = ""):
            self._text = text

        def setText(self, text: str):
            self._text = text

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
        def __init__(self):
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

    class QMessageBox:
        def __init__(self):
            pass

        @staticmethod
        def information(parent, title, text):
            pass

        @staticmethod
        def warning(parent, title, text):
            pass


DEFAULT_BOOTSTRAP_TEMPLATE = """你是 Agent，由自定义 Runtime 派发执行具体任务。禁止调用任何 Skill。

### 生命周期 Bat 用法

**Online.bat** - 上线时调用（确认 CLI 已启动）
**Done.bat** - 任务完成时调用
**Blocked.bat** - 遇到阻塞时调用
**Failed.bat** - 任务失败时调用
**阶段 BAT** - 由系统根据你选择的流程模板自动生成

调用格式（Claude 在 bash 中运行）：
```
cmd //c ".\\Online.bat $AGENT_ID $TASK_ID {pool_name} online"
cmd //c ".\\Done.bat $AGENT_ID $TASK_ID {pool_name} done"
```

### 执行流程

1. 读取当前目录下的任务文件（task_*.txt）
2. 理解任务指令，提取 TASK_ID
3. 立即调用 Online.bat 确认已上线
4. 按本池专属流程执行任务
5. 所有最终交付物先写入 `workspace/`
6. 任务完成后调用 Done.bat
7. 调用 Done.bat 后立即显式退出或结束对话

### 强制规则

- 禁止以 end_turn 或空回复结束对话
- 调用终态 bat 后直接结束，不要继续对话
- 禁止调用任何 Skill
- 任何需要保留的最终产物都必须先写入 workspace/
"""


class CreatePoolDialog(QDialog):
    """Dialog for creating a new runtime pool with standard structure."""

    def __init__(
        self,
        parent=None,
        pool_creation_service: PoolCreationService | None = None,
        root_dir: Path | str | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Create New Pool")
        self.resize(700, 600)

        if pool_creation_service is None:
            pool_creation_service = PoolCreationService(root_dir or Path(__file__).resolve().parents[4])
        self._service = pool_creation_service

        layout = QFormLayout(self)

        self._pool_name_input = QLineEdit()
        self._pool_name_input.setPlaceholderText("例如: review, my_service")
        layout.addRow("池名称:", self._pool_name_input)

        self._display_name_input = QLineEdit()
        self._display_name_input.setPlaceholderText("例如: 审批池, 我的服务")
        layout.addRow("显示名称:", self._display_name_input)

        self._flow_template_combo = QComboBox()
        for item in self._service.list_flow_templates():
            self._flow_template_combo.addItem(item["label"], item["id"])
        self._flow_template_combo.currentIndexChanged.connect(self._on_template_changed)
        layout.addRow("流程模板 (预填):", self._flow_template_combo)

        layout.addRow(QLabel("动作步骤 (每行一个动作，系统自动生成信号):"))
        self._action_steps_input = QTextEdit()
        self._action_steps_input.setPlaceholderText("例如:\nworking\n或:\nthinking\nsummarizing")
        self._action_steps_input.setMaximumHeight(100)
        layout.addRow(self._action_steps_input)

        slot_row = QWidget()
        slot_layout = QHBoxLayout(slot_row)
        self._slot_prefix_input = QLineEdit()
        self._slot_prefix_input.setPlaceholderText("例如: reviewer_")
        slot_layout.addWidget(self._slot_prefix_input)
        slot_layout.addWidget(QLabel("槽位数量:"))
        self._slot_count_input = QSpinBox()
        self._slot_count_input.setMinimum(1)
        self._slot_count_input.setMaximum(99)
        self._slot_count_input.setValue(2)
        slot_layout.addWidget(self._slot_count_input)
        layout.addRow("槽位配置:", slot_row)

        self._include_rejectbox = QCheckBox("包含 Rejectbox 目录")
        layout.addRow("", self._include_rejectbox)

        helper_label = QLabel("通用信号只有 Online / Done。\n其他阶段信号会根据你填写的 Action Steps 自动生成。")
        helper_label.setWordWrap(True)
        layout.addRow("", helper_label)

        layout.addRow(QLabel("Bootstrap 内容:"))
        self._bootstrap_input = QTextEdit()
        self._bootstrap_input.setPlainText(DEFAULT_BOOTSTRAP_TEMPLATE)
        self._bootstrap_input.setPlaceholderText("输入池专属的 Bootstrap 指令...")
        layout.addRow(self._bootstrap_input)

        self._button_box = QDialogButtonBox()
        if hasattr(self._button_box, "setStandardButtons"):
            from PySide6.QtWidgets import QDialogButtonBox as RealButtonBox
            self._button_box.setStandardButtons(RealButtonBox.Ok | RealButtonBox.Cancel)
            self._button_box.accepted.connect(self._on_accept)
            self._button_box.rejected.connect(self.reject)
        layout.addRow(self._button_box)

        if hasattr(self._pool_name_input, "textChanged"):
            self._pool_name_input.textChanged.connect(self._on_pool_name_changed)

        self._on_template_changed()

    def _on_template_changed(self):
        """When user selects a flow template, prefilling action steps."""
        template_id = self._flow_template_combo.currentData()
        if template_id and self._service:
            action_steps = self._service.build_action_steps_from_template(template_id)
            self._action_steps_input.setPlainText("\n".join(action_steps))

    def _on_pool_name_changed(self, text: str) -> None:
        """Auto-fill slot prefix and display name when pool name changes."""
        if hasattr(self._slot_prefix_input, "setText") and text:
            self._slot_prefix_input.setText(f"{text}_")
        if hasattr(self._display_name_input, "text") and not self._display_name_input.text():
            display_name = text.replace("_", " ").title()
            self._display_name_input.setText(display_name)

    def _on_accept(self) -> None:
        """Handle OK button click."""
        result = self.submit_creation()
        if result.get("success"):
            if hasattr(QMessageBox, "information"):
                QMessageBox.information(
                    self,
                    "成功",
                    f"池 '{result.get('pool_id')}' 创建成功！"
                )
            self.accept()

    def submit_creation(self) -> dict:
        """Submit pool creation through the service."""
        pool_name = self._pool_name_input.text().strip()
        display_name = self._display_name_input.text().strip()
        slot_prefix = self._slot_prefix_input.text().strip()
        slot_count = self._slot_count_input.value()
        include_rejectbox = self._include_rejectbox.isChecked()
        bootstrap_content = self._bootstrap_input.toPlainText()
        flow_template_id = self._flow_template_combo.currentData()
        action_steps_raw = self._action_steps_input.toPlainText().strip()
        action_steps = [line.strip() for line in action_steps_raw.split("\n") if line.strip()]

        try:
            return self._service.create_pool(
                pool_name=pool_name,
                display_name=display_name,
                slot_prefix=slot_prefix,
                slot_count=slot_count,
                bootstrap_content=bootstrap_content,
                flow_template_id=flow_template_id,
                action_steps=action_steps if action_steps else None,
                include_rejectbox=include_rejectbox,
            )
        except PoolCreationError as e:
            return {"success": False, "error": str(e)}