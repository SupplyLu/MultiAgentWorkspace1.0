"""Pytest fixtures for runtime_template tests."""

from pathlib import Path

import pytest


@pytest.fixture
def sample_state_machine():
    """Returns a simple state machine JSON dict."""
    return {
        "pool_id": "review",
        "initial_state": "state_0",
        "terminal_states": ["state_3"],
        "transitions": [
            {"from_state": "state_0", "to_state": "state_1", "allowed_signals": ["online"]},
            {"from_state": "state_1", "to_state": "state_2", "allowed_signals": ["start_review"]},
            {"from_state": "state_2", "to_state": "state_3", "allowed_signals": ["done"]},
        ],
    }


@pytest.fixture
def sample_bootstrap():
    """Returns sample BOOTSTRAP content."""
    return "你是 Reviewer Agent，负责审查代码。\n\n生命周期 BAT:\n- Online.bat\n- Done.bat\n\n执行流程:\n1. 读取 Queue/ 中的任务文件\n2. 调用 Online.bat\n3. 完成审查\n4. 调用 Done.bat\n"


@pytest.fixture
def generator_output_dir(tmp_path):
    """Returns a temporary output directory for generator tests."""
    return tmp_path / "generated_runtime"