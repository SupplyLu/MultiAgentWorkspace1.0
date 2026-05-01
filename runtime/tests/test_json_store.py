"""Test JSONStore thread safety and concurrent update correctness."""

import threading
from pathlib import Path

from app.shared.json_store import JSONStore


def test_json_store_concurrent_updates(tmp_path):
    """Test that concurrent update() calls maintain data consistency.

    This verifies that the entire read-modify-write cycle in update()
    is protected by a single lock acquisition, preventing interleaved
    operations that could cause data loss.
    """
    store_path = tmp_path / "counter.json"
    store = JSONStore(store_path, default_factory=lambda: {"count": 0})
    store.ensure_initialized()

    num_threads = 10
    increments_per_thread = 50
    barrier = threading.Barrier(num_threads)

    def increment_counter():
        # Wait for all threads to be ready
        barrier.wait()

        for _ in range(increments_per_thread):
            store.update(lambda data: {**data, "count": data["count"] + 1})

    threads = []
    for _ in range(num_threads):
        t = threading.Thread(target=increment_counter)
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    # Verify final count is exactly what we expect
    final_data = store.read()
    expected_count = num_threads * increments_per_thread
    assert final_data["count"] == expected_count, (
        f"Expected count={expected_count}, got {final_data['count']}. "
        "This indicates lost updates due to race conditions."
    )


def test_json_store_concurrent_mixed_operations(tmp_path):
    """Test concurrent reads, writes, and updates don't corrupt data."""
    store_path = tmp_path / "mixed.json"
    store = JSONStore(store_path, default_factory=lambda: {"value": 0, "reads": 0})
    store.ensure_initialized()

    num_threads = 8
    barrier = threading.Barrier(num_threads)
    errors = []

    def reader():
        barrier.wait()
        for _ in range(20):
            try:
                data = store.read()
                assert isinstance(data, dict)
                assert "value" in data
            except Exception as e:
                errors.append(f"Reader error: {e}")

    def updater():
        barrier.wait()
        for _ in range(20):
            try:
                store.update(lambda d: {**d, "value": d["value"] + 1})
            except Exception as e:
                errors.append(f"Updater error: {e}")

    threads = []
    for _ in range(num_threads // 2):
        threads.append(threading.Thread(target=reader))
        threads.append(threading.Thread(target=updater))

    for t in threads:
        t.start()

    for t in threads:
        t.join()

    assert not errors, f"Errors during concurrent operations: {errors}"

    final_data = store.read()
    expected_updates = (num_threads // 2) * 20
    assert final_data["value"] == expected_updates


def test_json_store_update_with_slow_updater(tmp_path):
    """Test that slow updater functions don't cause race conditions."""
    import time

    store_path = tmp_path / "slow.json"
    store = JSONStore(store_path, default_factory=lambda: {"items": []})
    store.ensure_initialized()

    num_threads = 5
    barrier = threading.Barrier(num_threads)

    def slow_append(thread_id):
        barrier.wait()

        def updater(data):
            # Simulate slow processing
            time.sleep(0.01)
            items = data["items"].copy()
            items.append(thread_id)
            return {"items": items}

        store.update(updater)

    threads = []
    for i in range(num_threads):
        t = threading.Thread(target=slow_append, args=(i,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    final_data = store.read()
    assert len(final_data["items"]) == num_threads, (
        f"Expected {num_threads} items, got {len(final_data['items'])}. "
        "Lost updates indicate lock was released during update()."
    )
    assert set(final_data["items"]) == set(range(num_threads))
