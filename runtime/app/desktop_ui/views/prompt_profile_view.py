"""Prompt profile editing view for the desktop UI."""

from __future__ import annotations

import json
from pathlib import Path

try:
    from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
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


class PromptProfileStore:
    def __init__(self, config_file: Path | str):
        self.config_file = Path(config_file)

    def load_profiles(self) -> dict:
        if not self.config_file.exists():
            return {}
        return json.loads(self.config_file.read_text(encoding="utf-8"))

    def save_profiles(self, profiles: dict) -> None:
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        self.config_file.write_text(json.dumps(profiles, ensure_ascii=False, indent=2), encoding="utf-8")


class PromptProfileView(QWidget):
    def __init__(self, config_file: Path | str):
        super().__init__()
        self.store = PromptProfileStore(config_file)
        self._profiles = self.store.load_profiles()

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("提示词配置"))

    def list_profile_names(self) -> list[str]:
        return list(self._profiles.keys())
