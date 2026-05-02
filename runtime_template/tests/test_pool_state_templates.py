"""Test runtime_template pool state templates."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.pool_state_templates import (
    PoolStateTemplateRegistry,
)


def test_work_pool_legal_transitions():
    reg = PoolStateTemplateRegistry()
    template = reg.get_template("work")

    assert template is not None
    assert template.initial_state == "state_0"
    assert template.terminal_states == {"state_3", "state_timeout"}

    assert template.get_next_state("state_0", "online") == "state_1"
    assert template.get_next_state("state_1", "start_writing") == "state_2"
    assert template.get_next_state("state_2", "done") == "state_3"
    assert template.get_next_state("state_1", "timeout") == "state_timeout"
    assert template.get_next_state("state_2", "timeout") == "state_timeout"
    assert template.get_next_state("state_0", "start_writing") is None
    assert template.get_next_state("state_3", "online") is None


def test_work_pool_blocked_resets():
    reg = PoolStateTemplateRegistry()
    template = reg.get_template("work")

    assert template.get_next_state("state_1", "blocked") == "state_0"
    assert template.get_next_state("state_2", "blocked") == "state_0"


def test_thinking_pool_template():
    reg = PoolStateTemplateRegistry()
    template = reg.get_template("thinking")

    assert template is not None
    assert template.initial_state == "state_0"
    assert template.get_next_state("state_0", "online") == "state_1"
    assert template.get_next_state("state_1", "start_thinking") == "state_2"
    assert template.get_next_state("state_2", "start_summarizing") == "state_3"
    assert template.get_next_state("state_3", "done") == "state_4"


def test_gate_pool_approved_rejected():
    reg = PoolStateTemplateRegistry()
    template = reg.get_template("gate")

    assert template is not None
    assert template.get_next_state("state_2", "approved") == "state_3_approved"
    assert template.get_next_state("state_2", "rejected") == "state_3_rejected"


def test_unknown_pool_returns_none():
    reg = PoolStateTemplateRegistry()
    assert reg.get_template("nonexistent") is None


def test_is_terminal():
    reg = PoolStateTemplateRegistry()
    work = reg.get_template("work")

    assert work.is_terminal("state_3") is True
    assert work.is_terminal("state_0") is False
    assert work.is_terminal("state_1") is False
