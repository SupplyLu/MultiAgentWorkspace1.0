"""Tests for Bootstrap management in the prompt profile view."""

from pathlib import Path

import pytest

from app.desktop_ui.views.prompt_profile_view import BootstrapStore, BootstrapEditorView


def test_bootstrap_store_discovers_all_bootstrap_files(tmp_path):
    """BootstrapStore finds all BOOTSTRAP files under the tools directory."""
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir(parents=True)
    gate_dir = tools_dir / "gate"
    gate_dir.mkdir(parents=True)

    # Create the actual bootstrap files
    (tools_dir / "BOOTSTRAP.txt").write_text("generic bootstrap", encoding="utf-8")
    (tools_dir / "WORK_BOOTSTRAP.txt").write_text("work bootstrap", encoding="utf-8")
    (tools_dir / "THINKING_BOOTSTRAP.txt").write_text("thinking bootstrap", encoding="utf-8")
    (tools_dir / "CONSTRUCT_BOOTSTRAP.txt").write_text("construct bootstrap", encoding="utf-8")
    (gate_dir / "GATE_BOOTSTRAP.txt").write_text("gate bootstrap", encoding="utf-8")

    store = BootstrapStore(tools_dir=tools_dir)
    names = store.list_bootstrap_names()

    assert len(names) == 5
    assert "BOOTSTRAP" in names
    assert "WORK_BOOTSTRAP" in names
    assert "THINKING_BOOTSTRAP" in names
    assert "CONSTRUCT_BOOTSTRAP" in names
    assert "GATE_BOOTSTRAP" in names


def test_bootstrap_store_loads_content_for_each_file(tmp_path):
    """BootstrapStore loads the raw text content of each bootstrap file."""
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir(parents=True)

    (tools_dir / "WORK_BOOTSTRAP.txt").write_text("work content here", encoding="utf-8")
    (tools_dir / "THINKING_BOOTSTRAP.txt").write_text("thinking content here", encoding="utf-8")

    store = BootstrapStore(tools_dir=tools_dir)

    assert store.load_content("WORK_BOOTSTRAP") == "work content here"
    assert store.load_content("THINKING_BOOTSTRAP") == "thinking content here"


def test_bootstrap_store_saves_content_to_file(tmp_path):
    """BootstrapStore persists edited content back to the correct file."""
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir(parents=True)

    (tools_dir / "THINKING_BOOTSTRAP.txt").write_text("original", encoding="utf-8")

    store = BootstrapStore(tools_dir=tools_dir)
    store.save_content("THINKING_BOOTSTRAP", "modified content")

    assert (tools_dir / "THINKING_BOOTSTRAP.txt").read_text(encoding="utf-8") == "modified content"


def test_bootstrap_store_returns_none_for_missing_bootstrap(tmp_path):
    """BootstrapStore returns None when loading a bootstrap name that doesn't exist."""
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir(parents=True)

    store = BootstrapStore(tools_dir=tools_dir)

    assert store.load_content("NONEXISTENT") is None


def test_bootstrap_store_reports_all_fields_for_each_bootstrap(tmp_path):
    """BootstrapStore provides metadata (pool, label, description) for each bootstrap."""
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir(parents=True)

    (tools_dir / "BOOTSTRAP.txt").write_text("generic", encoding="utf-8")
    (tools_dir / "WORK_BOOTSTRAP.txt").write_text("work", encoding="utf-8")
    (tools_dir / "THINKING_BOOTSTRAP.txt").write_text("thinking", encoding="utf-8")
    (tools_dir / "CONSTRUCT_BOOTSTRAP.txt").write_text("construct", encoding="utf-8")

    store = BootstrapStore(tools_dir=tools_dir)
    metas = store.list_bootstrap_meta()

    metas_by_name = {m["name"]: m for m in metas}

    assert metas_by_name["WORK_BOOTSTRAP"]["pool"] == "work"
    assert metas_by_name["THINKING_BOOTSTRAP"]["pool"] == "thinking"
    assert metas_by_name["CONSTRUCT_BOOTSTRAP"]["pool"] == "construct"
    assert metas_by_name["BOOTSTRAP"]["pool"] == "generic"
    assert metas_by_name["WORK_BOOTSTRAP"]["label"] == "Work 层"
    assert metas_by_name["THINKING_BOOTSTRAP"]["label"] == "Thinking 层"


def test_bootstrap_editor_view_displays_all_bootstrap_options(tmp_path):
    """BootstrapEditorView lists all bootstrap files in a selector."""
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir(parents=True)

    (tools_dir / "WORK_BOOTSTRAP.txt").write_text("work", encoding="utf-8")
    (tools_dir / "THINKING_BOOTSTRAP.txt").write_text("thinking", encoding="utf-8")

    try:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])

        view = BootstrapEditorView(tools_dir=tools_dir)

        # Check that the view has a selector with bootstrap names
        assert hasattr(view, "_selector")
        assert hasattr(view, "_editor")
        assert hasattr(view, "_save_button")

        # Verify selector has items
        if hasattr(view._selector, "count"):
            assert view._selector.count() >= 2

    except ImportError:
        pytest.skip("PySide6 not available for UI test")
