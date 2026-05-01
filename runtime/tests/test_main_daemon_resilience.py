import importlib
from pathlib import Path


def test_post_main_includes_backoff_reset_and_cap():
    module = importlib.import_module("app.main_post")
    source = Path(module.__file__).read_text(encoding="utf-8")

    assert "consecutive_failures = 0" in source
    assert "max_backoff = 60.0" in source
    assert "backoff = min(2 ** consecutive_failures, max_backoff)" in source
    assert "consecutive_failures = 0" in source.split("while True:", 1)[1]
    assert "time.sleep(backoff)" in source


def test_all_runtime_mains_include_resilience_pattern():
    module_names = [
        "app.main",
        "app.main_thinking",
        "app.main_construct",
        "app.main_gate",
        "app.main_package",
    ]

    for module_name in module_names:
        module = importlib.import_module(module_name)
        source = Path(module.__file__).read_text(encoding="utf-8")

        assert "consecutive_failures = 0" in source, module_name
        assert "max_backoff = 60.0" in source, module_name
        assert "backoff = min(2 ** consecutive_failures, max_backoff)" in source, module_name
        assert "logger.error(f\"Cycle failed (attempt {consecutive_failures}): {e}\", exc_info=True)" in source, module_name
