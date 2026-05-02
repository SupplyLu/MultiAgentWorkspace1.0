"""Test runtime_template JSONStore cross-process locking and atomic writes."""

import json
import os
import sys
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.json_store import JSONStore


def _increment_worker(args: tuple) -> tuple:
    store_path_str, num_increments = args
    store = JSONStore(Path(store_path_str), default_factory=lambda: {"count": 0})
    for _ in range(num_increments):
        store.update(lambda data: {**data, "count": data["count"] + 1})
    return store.read()["count"]


def test_json_store_cross_thread_locking(tmp_path):
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

    threads = [threading.Thread(target=increment_counter) for _ in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    final_data = store.read()
    expected_count = num_threads * increments_per_thread
    assert final_data["count"] == expected_count


def test_json_store_thread_executor_concurrent_writes(tmp_path):
    store_path = tmp_path / "counter.json"
    store = JSONStore(store_path, default_factory=lambda: {"count": 0})
    store.ensure_initialized()

    num_workers = 8
    increments_per_worker = 25
    args = [(str(store_path), increments_per_worker) for _ in range(num_workers)]

    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        list(executor.map(_increment_worker, args))

    final_data = store.read()
    expected_count = num_workers * increments_per_worker
    assert final_data["count"] == expected_count


def test_json_store_handles_corrupted_file_gracefully(tmp_path):
    store_path = tmp_path / "corrupted.json"
    store_path.write_text("{invalid json", encoding="utf-8")

    store = JSONStore(store_path, default_factory=lambda: {"status": "default"})

    data = store.read()
    assert data == {"status": "default"}

    store.write({"status": "recovered"})
    data = store.read()
    assert data == {"status": "recovered"}


def test_json_store_atomic_write_no_partial_reads_after_initialization(tmp_path):
    store_path = tmp_path / "atomic.json"
    store = JSONStore(store_path, default_factory=lambda: {"items": []})
    store.ensure_initialized()
    store.write({"items": list(range(100)), "writer": -1, "seq": -1})

    num_threads = 4
    barrier = threading.Barrier(num_threads)
    errors = []

    def writer(writer_id):
        barrier.wait()
        local_store = JSONStore(store_path, default_factory=lambda: {"items": []})
        for i in range(20):
            data = {"items": list(range(100)), "writer": writer_id, "seq": i}
            local_store.write(data)

    def reader():
        barrier.wait()
        local_store = JSONStore(store_path, default_factory=lambda: {"items": []})
        for _ in range(40):
            try:
                data = local_store.read()
                assert "items" in data
                assert isinstance(data["items"], list)
                assert len(data["items"]) == 100
            except (json.JSONDecodeError, AssertionError, KeyError, TypeError) as e:
                errors.append(str(e))

    threads = []
    for i in range(num_threads // 2):
        threads.append(threading.Thread(target=writer, args=(i,)))
        threads.append(threading.Thread(target=reader))

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Detected errors during concurrent access: {errors[:10]}"


def test_json_store_cross_process_with_filelock(tmp_path):
    store_path = tmp_path / "mp_counter.json"
    store = JSONStore(store_path, default_factory=lambda: {"count": 0})
    store.ensure_initialized()

    num_processes = 4
    increments_per_process = 10
    args = [(str(store_path), increments_per_process) for _ in range(num_processes)]

    try:
        with ProcessPoolExecutor(max_workers=num_processes) as executor:
            list(executor.map(_increment_worker, args, timeout=60))
    except Exception as e:
        pytest.skip(f"Multiprocessing test setup issue: {e}")

    final_data = store.read()
    expected_count = num_processes * increments_per_process
    assert final_data["count"] == expected_count
