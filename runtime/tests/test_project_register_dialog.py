"""Tests for ProjectRegisterDialog."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication
except ModuleNotFoundError:  # pragma: no cover
    QApplication = None


def _init_workspace(root):
    for pool in ("task", "thinking", "construct", "gate", "work", "package"):
        (root / "pools" / pool / "Queue").mkdir(parents=True, exist_ok=True)
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "flow_policy.json").write_text(
        """{
  "active_policy": "full_pipeline",
  "default_mode": "build",
  "modes": ["build", "fix", "demo"],
  "pool_descriptions": {
    "task": "任务入口",
    "thinking": "需求拆解",
    "construct": "结构设计",
    "gate": "质量审查",
    "work": "实际施工",
    "package": "收口打包"
  },
  "policies": {
    "full_pipeline": ["task", "thinking", "construct", "gate", "work", "package"]
  }
}
""",
        encoding="utf-8",
    )


@pytest.fixture
def qapp():
    if QApplication is None:
        yield None
        return

    app = QApplication.instance()
    created = False
    if app is None:
        app = QApplication([])
        created = True

    yield app

    if created:
        app.quit()


def test_project_register_dialog_importable():
    """Test that ProjectRegisterDialog can be imported."""
    from app.desktop_ui.views.project_register_dialog import ProjectRegisterDialog

    assert ProjectRegisterDialog is not None


def test_project_register_dialog_instantiable(qapp, tmp_path):
    """Test that ProjectRegisterDialog can be instantiated."""
    from app.desktop_ui.views.project_register_dialog import ProjectRegisterDialog

    _init_workspace(tmp_path)
    dialog = ProjectRegisterDialog(root_dir=tmp_path)
    assert dialog is not None
    assert dialog.windowTitle() == "Project Registration"


def test_project_register_dialog_has_form_fields(qapp, tmp_path):
    """Test that dialog has all required form fields."""
    from app.desktop_ui.views.project_register_dialog import ProjectRegisterDialog

    _init_workspace(tmp_path)
    dialog = ProjectRegisterDialog(root_dir=tmp_path)

    assert hasattr(dialog, '_project_name_input')
    assert hasattr(dialog, '_version_input')
    assert hasattr(dialog, '_mode_combo')
    assert hasattr(dialog, '_route_list')
    assert hasattr(dialog, '_requirements_input')
    assert hasattr(dialog, '_button_box')


def test_project_register_dialog_has_mode_options(qapp, tmp_path):
    """Test that mode combo is populated from policy."""
    from app.desktop_ui.views.project_register_dialog import ProjectRegisterDialog

    _init_workspace(tmp_path)
    dialog = ProjectRegisterDialog(root_dir=tmp_path)

    if hasattr(dialog._mode_combo, 'count'):
        assert dialog._mode_combo.count() == 3


def test_project_register_dialog_submit_creates_queue_file(qapp, tmp_path):
    """Test that submitting dialog registers project and writes queue file."""
    from app.desktop_ui.services.project_registration_service import ProjectRegistrationService
    from app.desktop_ui.views.project_register_dialog import ProjectRegisterDialog

    _init_workspace(tmp_path)
    service = ProjectRegistrationService(tmp_path)
    dialog = ProjectRegisterDialog(service=service)

    if hasattr(dialog._project_name_input, 'setText'):
        dialog._project_name_input.setText('SignalOfBridge')
        dialog._version_input.setText('v1')
        dialog._mode_combo.setCurrentText('build')
        dialog._requirements_input.setPlainText('Implement bridge synchronization module.')

    result = dialog.submit_registration()

    assert result['success'] is True
    assert result['project_key'] == 'SignalOfBridge-v1-build'
    assert result['route'] == ['task', 'thinking', 'construct', 'gate', 'work', 'package']
    assert (tmp_path / 'pools' / 'task' / 'Outbox' / 'SignalOfBridge-v1-build.txt').exists()
