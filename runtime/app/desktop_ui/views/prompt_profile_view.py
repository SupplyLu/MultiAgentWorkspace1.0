"""Bootstrap file store - discovers and manages all *_BOOTSTRAP.txt files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

try:
    from PySide6.QtWidgets import (
        QComboBox,
        QLabel,
        QPushButton,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ModuleNotFoundError:  # pragma: no cover
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

    class QComboBox:
        pass

    class QTextEdit:
        pass

    class QPushButton:
        pass


# Bootstrap file naming patterns and their pool mapping
_BOOTSTRAP_META = {
    "BOOTSTRAP": {
        "pool": "generic",
        "label": "通用 Bootstrap",
        "file": "BOOTSTRAP.txt",
    },
    "WORK_BOOTSTRAP": {
        "pool": "work",
        "label": "Work 层",
        "file": "WORK_BOOTSTRAP.txt",
    },
    "THINKING_BOOTSTRAP": {
        "pool": "thinking",
        "label": "Thinking 层",
        "file": "THINKING_BOOTSTRAP.txt",
    },
    "CONSTRUCT_BOOTSTRAP": {
        "pool": "construct",
        "label": "Construct 层",
        "file": "CONSTRUCT_BOOTSTRAP.txt",
    },
    "GATE_BOOTSTRAP": {
        "pool": "gate",
        "label": "Gate 层",
        "file": "GATE_BOOTSTRAP.txt",
        "subdir": "gate",
    },
}


@dataclass
class BootstrapMeta:
    """Metadata for a single bootstrap file."""
    name: str
    pool: str
    label: str
    file_path: Path

    def __getitem__(self, key: str):
        return getattr(self, key)


class BootstrapStore:
    """Discovers and manages all *_BOOTSTRAP.txt files under the tools directory."""

    def __init__(self, tools_dir: Path | str):
        self._tools_dir = Path(tools_dir)
        self._cache: dict[str, BootstrapMeta] = {}
        self._discover()

    def _discover(self) -> None:
        """Scan tools directory for all bootstrap files."""
        self._cache.clear()
        for name, meta in _BOOTSTRAP_META.items():
            subdir = meta.get("subdir", "")
            file_path = self._tools_dir / subdir / meta["file"] if subdir else self._tools_dir / meta["file"]
            if file_path.exists():
                self._cache[name] = BootstrapMeta(
                    name=name,
                    pool=meta["pool"],
                    label=meta["label"],
                    file_path=file_path,
                )
            else:
                # Register even if missing (user may create it)
                self._cache[name] = BootstrapMeta(
                    name=name,
                    pool=meta["pool"],
                    label=meta["label"],
                    file_path=file_path,
                )

    def list_bootstrap_names(self) -> list[str]:
        """Return names of all discovered bootstrap files."""
        return list(self._cache.keys())

    def list_bootstrap_meta(self) -> list[BootstrapMeta]:
        """Return metadata for all bootstrap files."""
        return list(self._cache.values())

    def load_content(self, name: str) -> str | None:
        """Load the raw text content of a bootstrap file. Returns None if missing."""
        meta = self._cache.get(name)
        if meta is None:
            return None
        if not meta.file_path.exists():
            return None
        return meta.file_path.read_text(encoding="utf-8")

    def save_content(self, name: str, content: str) -> bool:
        """Persist content back to the bootstrap file. Returns True on success."""
        meta = self._cache.get(name)
        if meta is None:
            return False
        meta.file_path.parent.mkdir(parents=True, exist_ok=True)
        meta.file_path.write_text(content, encoding="utf-8")
        return True


class BootstrapEditorView(QWidget):
    """UI view for editing all BOOTSTRAP files."""

    def __init__(self, tools_dir: Path | str | None = None):
        super().__init__()

        if tools_dir is None:
            tools_dir = Path(__file__).resolve().parents[3] / "tools"

        self._store = BootstrapStore(tools_dir=tools_dir)
        self._current_name: str | None = None

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Bootstrap 提示词管理"))

        self._selector = QComboBox()
        if hasattr(self._selector, "addItems"):
            metas = self._store.list_bootstrap_meta()
            for meta in metas:
                self._selector.addItem(meta.label, meta.name)
        if hasattr(self._selector, "currentIndexChanged"):
            self._selector.currentIndexChanged.connect(self._on_selection_changed)

        layout.addWidget(self._selector)

        self._editor = QTextEdit()
        if hasattr(self._editor, "setPlaceholderText"):
            self._editor.setPlaceholderText("选择一个 Bootstrap 文件进行编辑...")
        layout.addWidget(self._editor)

        self._save_button = QPushButton("保存")
        if hasattr(self._save_button, "clicked"):
            self._save_button.clicked.connect(self._on_save_clicked)
        layout.addWidget(self._save_button)

        # Load first bootstrap if available
        if hasattr(self._selector, "count") and self._selector.count() > 0:
            self._on_selection_changed(0)

    def _on_selection_changed(self, index: int) -> None:
        """Load the selected bootstrap file into the editor."""
        if not hasattr(self._selector, "itemData"):
            return

        name = self._selector.itemData(index)
        if name is None:
            return

        self._current_name = name
        content = self._store.load_content(name)
        if content is not None and hasattr(self._editor, "setPlainText"):
            self._editor.setPlainText(content)
        elif hasattr(self._editor, "setPlainText"):
            self._editor.setPlainText("")

    def _on_save_clicked(self) -> None:
        """Save the current editor content back to the bootstrap file."""
        if self._current_name is None:
            return

        if not hasattr(self._editor, "toPlainText"):
            return

        content = self._editor.toPlainText()
        self._store.save_content(self._current_name, content)


class PromptProfileView(BootstrapEditorView):
    """Backward-compatible prompt tab view backed by bootstrap files."""

    def __init__(self, config_file: Path | str | None = None):
        if config_file is None:
            tools_dir = Path(__file__).resolve().parents[3] / "tools"
        else:
            tools_dir = Path(config_file).resolve().parents[1] / "tools"
        super().__init__(tools_dir=tools_dir)
