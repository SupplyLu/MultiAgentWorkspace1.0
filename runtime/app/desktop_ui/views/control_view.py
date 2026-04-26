"""Control view for runtime operations."""

import json
from datetime import datetime
from pathlib import Path

try:
    from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget, QPushButton, QHBoxLayout
except ModuleNotFoundError:  # pragma: no cover
    class QWidget: pass
    class QLabel: 
        def __init__(self, text: str = ""): self.text = text
    class QVBoxLayout:
        def __init__(self, parent=None): self.parent = parent
        def addWidget(self, widget): pass
    class QHBoxLayout:
        def __init__(self): pass
        def addWidget(self, widget): pass
    class QPushButton:
        def __init__(self, text: str = ""): self.text = text


class ControlView(QWidget):
    def __init__(self, client=None, bridge=None, audit_log_path=None):
        super().__init__()
        self.client = client
        self.bridge = bridge
        self.audit_log_path = audit_log_path or Path("desktop_ui_audit.log")
        self._last_status = None
        
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("运行控制"))

    def handle_pause_action(self, pool: str):
        if not self.client: return
        result = self.client.send_control(pool, "pause")
        self._record_result(pool, "pause", result)

    def handle_resume_action(self, pool: str):
        if not self.client: return
        result = self.client.send_control(pool, "resume")
        self._record_result(pool, "resume", result)

    def handle_restart_action(self, pool: str):
        if not self.bridge: return
        result = self.bridge.restart_pool(pool)
        self._record_result(pool, "restart", result)

    def get_last_operation_status(self) -> str:
        return self._last_status

    def _record_result(self, pool: str, action: str, result: dict):
        self._last_status = "success" if result.get("success") else "failed"
        
        # Write to audit log
        try:
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "pool": pool,
                "action": action,
                "result": "success" if result.get("success") else "failed",
                "error": result.get("error")
            }
            
            with open(self.audit_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry) + "\n")
        except Exception:
            pass
