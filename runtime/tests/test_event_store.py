from app.services.event_store import EventStore, LifecycleEvent


def test_event_store_append_and_retrieve(tmp_path):
    store = EventStore(tmp_path)

    event = LifecycleEvent(
        timestamp="2026-04-17T10:00:00Z",
        agent_id="worker_01",
        task_id="t_001",
        signal="online",
        pool="work",
        from_state="state_0",
        to_state="state_1",
    )

    record = store.append(event)
    assert record["agent_id"] == "worker_01"
    assert record["signal"] == "online"
    assert record["to_state"] == "state_1"

    events = store.get_events(agent_id="worker_01")
    assert len(events) == 1
    assert events[0]["signal"] == "online"


def test_event_store_get_current_state(tmp_path):
    store = EventStore(tmp_path)

    event1 = LifecycleEvent(
        timestamp="2026-04-17T10:00:00Z",
        agent_id="worker_01",
        task_id="t_001",
        signal="online",
        pool="work",
        from_state="state_0",
        to_state="state_1",
    )
    store.append(event1)

    event2 = LifecycleEvent(
        timestamp="2026-04-17T10:01:00Z",
        agent_id="worker_01",
        task_id="t_001",
        signal="start_writing",
        pool="work",
        from_state="state_1",
        to_state="state_2",
    )
    store.append(event2)

    assert store.get_current_state("worker_01") == "state_2"
    assert store.get_current_state("nonexistent") is None


def test_event_store_multiple_agents(tmp_path):
    store = EventStore(tmp_path)

    for i in range(3):
        event = LifecycleEvent(
            timestamp=f"2026-04-17T10:0{i}:00Z",
            agent_id=f"worker_{i:02d}",
            task_id=f"t_{i:03d}",
            signal="done",
            pool="work",
            from_state="state_2",
            to_state="state_3",
        )
        store.append(event)

    assert len(store.get_events()) == 3
    assert len(store.get_events(agent_id="worker_01")) == 1
    assert len(store.get_events(task_id="t_000")) == 1


def test_event_store_caps_index_growth(tmp_path):
    store = EventStore(tmp_path, index_limit=5)

    for i in range(8):
        store.append(
            LifecycleEvent(
                timestamp=f"2026-04-17T10:0{i}:00Z",
                agent_id="worker_01",
                task_id=f"t_{i:03d}",
                signal="done",
                pool="work",
                from_state="state_2",
                to_state="state_3",
            )
        )

    index_data = store._index_store.read()
    assert len(index_data["events"]) == 5
    assert index_data["events"][0]["task_id"] == "t_003"
    assert index_data["events"][-1]["task_id"] == "t_007"


def test_event_store_reports_corrupted_event_files(tmp_path):
    store = EventStore(tmp_path, index_limit=10)
    store.append(
        LifecycleEvent(
            timestamp="2026-04-17T10:00:00Z",
            agent_id="worker_01",
            task_id="t_001",
            signal="done",
            pool="work",
            from_state="state_2",
            to_state="state_3",
        )
    )

    index_data = store._index_store.read()
    event_file = index_data["events"][0]["file"]
    from pathlib import Path
    Path(event_file).write_text("{broken", encoding="utf-8")

    events = store.get_events(agent_id="worker_01")
    stats = store.get_index_stats()

    assert events == []
    assert stats["corrupt_files"] >= 1
