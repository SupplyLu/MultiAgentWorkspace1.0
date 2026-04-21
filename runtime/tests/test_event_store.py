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
