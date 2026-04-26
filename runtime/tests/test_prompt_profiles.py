"""Test prompt profile loading and desktop UI presentation."""

import json

from app.desktop_ui.views.prompt_profile_view import PromptProfileStore, PromptProfileView
from app.desktop_ui.main_window import MainWindow


def test_prompt_profiles_roundtrip(tmp_path):
    """Prompt profiles should round-trip through JSON storage."""
    config_file = tmp_path / "prompt_profiles.json"
    store = PromptProfileStore(config_file)

    profiles = {
        "default": {
            "label": "默认",
            "system_prompt": "You are the default profile.",
            "temperature": 0.2,
        },
        "review": {
            "label": "评审",
            "system_prompt": "You are the reviewer profile.",
            "temperature": 0.1,
        },
    }

    store.save_profiles(profiles)
    loaded = store.load_profiles()

    assert loaded == profiles


def test_prompt_profile_view_displays_profiles(tmp_path):
    """PromptProfileView should expose all available profile names."""
    config_file = tmp_path / "prompt_profiles.json"
    config_file.write_text(
        json.dumps(
            {
                "default": {"label": "默认", "system_prompt": "A", "temperature": 0.2},
                "review": {"label": "评审", "system_prompt": "B", "temperature": 0.1},
            }
        ),
        encoding="utf-8",
    )

    view = PromptProfileView(config_file=config_file)

    assert view.list_profile_names() == ["default", "review"]


def test_main_window_registers_prompt_profile_tab(tmp_path):
    """MainWindow should register the prompt profile tab."""
    config_file = tmp_path / "prompt_profiles.json"
    config_file.write_text(
        json.dumps(
            {
                "default": {"label": "默认", "system_prompt": "A", "temperature": 0.2}
            }
        ),
        encoding="utf-8",
    )

    window = MainWindow(prompt_profiles_path=config_file)

    labels = [label for _, label in window.central_widget.tabs]
    assert "提示词" in labels
