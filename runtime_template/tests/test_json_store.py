"""Test runtime_template JSONStore thread safety and concurrent update correctness."""

import threading
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.json_store import JSONStore


def test_json_store_concurrent_updates(tmp_path):
    store_path = tmp_path / "counter.json"
    store = JSONStore(store_path, default_factory=lambda: {"count": 0})
    store.ensure_initialized()

    num_threads = 10
    increments_per_thread = 50
    barrier = threading.Barrier(num_threads)

    def increment_counter():
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

    final_data = store.read()
    expected_count = num_threads * increments_per_thread
    assert final_data["count"] == expected_count


def test_json_store_concurrent_mixed_operations(tmp_path):
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
    import time

    store_path = tmp_path / "slow.json"
    store = JSONStore(store_path, default_factory=lambda: {"items": []})
    store.ensure_initialized()

    num_threads = 5
    barrier = threading.Barrier(num_threads)

    def slow_append(thread_id):
        barrier.wait()

        def updater(data):
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
    assert len(final_data["items"]) == num_threads
    assert set(final_data["items"]) == set(range(num_threads))
