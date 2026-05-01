"""Regression tests for Thinking Runtime closed-loop issues.

Bug 1: event_store.append must happen before on_signal hook to ensure events
       are persisted even when the hook throws an exception.
Bug 2: collect_artifacts_to_outbox must not nest project folders - workspace
       subdirectories must be flattened into Outbox/task_id/ without duplication.
"""
from __future__ import annotations

from app.services.event_store import EventStore
from app.services.signal_server import RuntimeSignalServer


class TestEventStorePersistenceBeforeHook:
    """Bug 1: event_store.append must precede on_signal to guarantee persistence."""

    def test_event_stored_even_when_on_signal_hook_raises(self, tmp_path):
        """Event must be written to store even if on_signal callback raises."""
        event_dir = tmp_path / "events"
        event_dir.mkdir(parents=True)
        store = EventStore(store_dir=event_dir)

        server = RuntimeSignalServer(port=19250, event_store_dir=event_dir)

        hook_called = False

        def failing_hook(result):
            nonlocal hook_called
            hook_called = True
            raise RuntimeError("synthetic hook failure")

        server.on_signal = failing_hook
        server.start()

        try:
            payload = {
                "agent_id": "sub_brain_01",
                "task_id": "test-task-001",
                "signal": "online",
                "pool": "thinking",
                "timestamp": "2026-04-28T10:00:00Z",
                "feature_id": "",
                "role": "thinker",
                "message": "done",
                "artifact_root": "",
                "source": "",
                "pid": 0,
            }
            result = server.process_signal(payload)

            assert hook_called, "on_signal hook should have been called"
            assert result["accepted"] is False
            assert result["reason"] == "on_signal hook failed"

            current = store.get_current_state("sub_brain_01", "test-task-001")
            assert current is not None, "event must be persisted even when hook raises"
            assert current != "state_0", "event should advance state from initial"
        finally:
            server.stop()

    def test_event_stored_when_on_signal_succeeds(self, tmp_path):
        """Baseline: event is stored when hook succeeds."""
        event_dir = tmp_path / "events"
        event_dir.mkdir(parents=True)
        store = EventStore(store_dir=event_dir)

        server = RuntimeSignalServer(port=19251, event_store_dir=event_dir)
        server.on_signal = lambda result: None
        server.start()

        try:
            payload = {
                "agent_id": "sub_brain_02",
                "task_id": "test-task-002",
                "signal": "online",
                "pool": "thinking",
                "timestamp": "2026-04-28T10:00:00Z",
                "feature_id": "",
                "role": "thinker",
                "message": "done",
                "artifact_root": "",
                "source": "",
                "pid": 0,
            }
            result = server.process_signal(payload)
            assert result["accepted"] is True

            current = store.get_current_state("sub_brain_02", "test-task-002")
            assert current is not None
        finally:
            server.stop()


class TestThinkingOutboxFlattening:
    """Bug 2: collect_artifacts_to_outbox must avoid duplicate project folder nesting."""

    def test_collect_artifacts_flattens_single_project_folder_into_outbox(self, tmp_path):
        """workspace/<project>/001.txt should become Outbox/<task_id>/001.txt."""
        from app.runtimes.thinking_runtime import ThinkingRuntime

        thinking_pool = tmp_path / "pools" / "thinking"
        (thinking_pool / "Queue").mkdir(parents=True)
        slot_dir = thinking_pool / "sub_brain_01"
        slot_dir.mkdir(parents=True)
        workspace_dir = slot_dir / "workspace"
        workspace_dir.mkdir(parents=True)
        outbox_dir = thinking_pool / "Outbox"
        outbox_dir.mkdir(parents=True)

        project_dir = workspace_dir / "PMSMsim-v1-Build"
        project_dir.mkdir()
        (project_dir / "001.txt").write_text("task 1", encoding="utf-8")
        (project_dir / "002.txt").write_text("task 2", encoding="utf-8")

        runtime = ThinkingRuntime(root_dir=tmp_path, signal_port=19252)

        result = runtime.collect_artifacts_to_outbox("sub_brain_01", "PMSMsim-v1-Build")

        assert result["collected"] is True
        assert (outbox_dir / "PMSMsim-v1-Build" / "001.txt").exists()
        assert (outbox_dir / "PMSMsim-v1-Build" / "002.txt").exists()
        assert not (outbox_dir / "PMSMsim-v1-Build" / "PMSMsim-v1-Build").exists(), (
            "outbox must not contain duplicated project folder nesting"
        )

    def test_collect_artifacts_keeps_root_files_when_workspace_has_no_project_folder(self, tmp_path):
        """Existing flat workspace behavior should continue to work."""
        from app.runtimes.thinking_runtime import ThinkingRuntime

        thinking_pool = tmp_path / "pools" / "thinking"
        (thinking_pool / "Queue").mkdir(parents=True)
        slot_dir = thinking_pool / "sub_brain_01"
        slot_dir.mkdir(parents=True)
        workspace_dir = slot_dir / "workspace"
        workspace_dir.mkdir(parents=True)
        outbox_dir = thinking_pool / "Outbox"
        outbox_dir.mkdir(parents=True)

        (workspace_dir / "summary.md").write_text("summary", encoding="utf-8")
        (workspace_dir / "task_breakdown.md").write_text("breakdown", encoding="utf-8")

        runtime = ThinkingRuntime(root_dir=tmp_path, signal_port=19253)

        result = runtime.collect_artifacts_to_outbox("sub_brain_01", "flat-task")

        assert result["collected"] is True
        assert (outbox_dir / "flat-task" / "summary.md").exists()
        assert (outbox_dir / "flat-task" / "task_breakdown.md").exists()
