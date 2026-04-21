from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
from signal_bridge import resolve_server_url, send_signal, utc_now


def test_signal_bridge_prefers_env_port(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SIGNAL_SERVER_PORT", "18823")
    url = resolve_server_url(None)
    assert url == "http://localhost:18823"


def test_signal_bridge_prefers_explicit_server_url(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SIGNAL_SERVER_PORT", "18823")
    url = resolve_server_url("http://localhost:19999")
    assert url == "http://localhost:19999"


def test_send_signal_dry_run():
    result = send_signal(
        agent_id="worker_01",
        task_id="t_001",
        signal="online",
        pool="work",
        dry_run=True,
    )

    assert result["status"] == "dry_run"
    assert result["payload"]["agent_id"] == "worker_01"
    assert result["payload"]["signal"] == "online"


def test_send_signal_with_all_fields():
    result = send_signal(
        agent_id="worker_01",
        task_id="t_001",
        signal="start_writing",
        feature_id="feature_login",
        role="worker",
        pool="work",
        message="task understood, editing files",
        source="StartWriting.bat",
        dry_run=True,
    )

    assert result["status"] == "dry_run"
    payload = result["payload"]
    assert payload["feature_id"] == "feature_login"
    assert payload["role"] == "worker"
    assert payload["message"] == "task understood, editing files"
    assert payload["source"] == "StartWriting.bat"


def test_utc_now_format():
    ts = utc_now()
    assert "T" in ts
    assert "Z" in ts or "+" in ts
