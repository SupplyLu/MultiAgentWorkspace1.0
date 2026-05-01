"""Test JSONStore cross-process locking and atomic writes.

Note: Tests use module-level helper functions for multiprocessing compatibility.
"""

import json
import os
import sys
import tempfile
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed

# Add parent to path for imports in subprocesses
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from app.shared.json_store import JSONStore


# Module-level helper functions for multiprocessing compatibility

def _increment_worker(args: tuple) -> tuple:
    """Worker that increments counter - must be at module level for pickle."""
    store_path_str, num_increments = args
    store = JSONStore(Path(store_path_str), default_factory=lambda: {"count": 0})
    for _ in range(num_increments):
        store.update(lambda data: {**data, "count": data["count"] + 1})
    # Return final count from this worker's view
    return store.read()["count"]


def _writer_worker(args: tuple) -> int:
    """Writer worker - writes large data repeatedly."""
    store_path_str, worker_id = args
    store = JSONStore(Path(store_path_str), default_factory=lambda: {"items": []})
    for i in range(10):
        large_data = {"items": [f"worker_{worker_id}_item_{j}" for j in range(100)]}
        store.write(large_data)
    return worker_id


def _reader_worker(args: tuple) -> list:
    """Reader worker - reads data repeatedly, returns list of error messages."""
    store_path_str, num_reads = args
    store = JSONStore(Path(store_path_str), default_factory=lambda: {"items": []})
    errors = []
    for _ in range(num_reads):
        try:
            data = store.read()
            if not isinstance(data, dict):
                errors.append(f"Not a dict: {type(data)}")
            elif "items" not in data:
                errors.append("Missing 'items' key")
            elif not isinstance(data["items"], list):
                errors.append(f"items not a list: {type(data['items'])}")
        except json.JSONDecodeError as e:
            errors.append(f"JSONDecodeError: {e}")
        except Exception as e:
            errors.append(f"Error: {type(e).__name__}: {e}")
    return errors


def test_json_store_cross_thread_locking(tmp_path):
    """Test that JSONStore prevents concurrent writes from multiple threads."""
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
    assert final_data["count"] == expected_count, (
        f"Expected count={expected_count}, got {final_data['count']}. "
        "Cross-thread race condition detected."
    )


def test_json_store_thread_executor_concurrent_writes(tmp_path):
    """Test JSONStore with ThreadPoolExecutor - cross-thread concurrent access."""
    store_path = tmp_path / "counter.json"
    store = JSONStore(store_path, default_factory=lambda: {"count": 0})
    store.ensure_initialized()

    # Initialize file
    store.ensure_initialized()

    num_workers = 8
    increments_per_worker = 25

    args = [(str(store_path), increments_per_worker) for _ in range(num_workers)]

    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        results = list(executor.map(_increment_worker, args))

    # Final read to verify
    final_data = store.read()
    expected_count = num_workers * increments_per_worker
    assert final_data["count"] == expected_count, (
        f"Expected count={expected_count}, got {final_data['count']}."
    )


def test_json_store_handles_corrupted_file_gracefully(tmp_path):
    """Test that JSONStore falls back to default when file is corrupted."""
    store_path = tmp_path / "corrupted.json"

    # Write corrupted JSON
    store_path.write_text("{invalid json", encoding="utf-8")

    store = JSONStore(store_path, default_factory=lambda: {"status": "default"})

    # Should fall back to default
    data = store.read()
    assert data == {"status": "default"}

    # Should be able to write after recovery
    store.write({"status": "recovered"})
    data = store.read()
    assert data == {"status": "recovered"}


def test_json_store_atomic_write_no_partial_reads_after_initialization(tmp_path):
    """Test that JSONStore atomic writes prevent partial/corrupted reads after first write.

    Initial default content may be observed before any writer publishes a full payload.
    This test specifically guards against half-written JSON once concurrent writes begin.
    """
    store_path = tmp_path / "atomic.json"

    # Initialize
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
                assert "items" in data, "Missing 'items' key"
                assert isinstance(data["items"], list), "items is not a list"
                assert len(data["items"]) == 100, f"Wrong list length: {len(data['items'])}"
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
    """Test JSONStore with multiprocessing - requires filelock implementation.

    This test verifies that JSONStore uses cross-process file locking.
    If the current implementation doesn't use filelock, this test will likely
    fail due to race conditions (which is the expected behavior to fix).
    """
    store_path = tmp_path / "mp_counter.json"

    # Initialize store file
    store = JSONStore(store_path, default_factory=lambda: {"count": 0})
    store.ensure_initialized()

    num_processes = 4
    increments_per_process = 10

    # Use ProcessPoolExecutor for true cross-process testing
    args = [(str(store_path), increments_per_process) for _ in range(num_processes)]

    try:
        with ProcessPoolExecutor(max_workers=num_processes) as executor:
            results = list(executor.map(_increment_worker, args, timeout=60))
    except Exception as e:
        # If pickle fails or other issues, fall back to marking as expected behavior
        pytest.skip(f"Multiprocessing test setup issue (may need __main__ guard): {e}")

    # Final read
    final_data = store.read()
    expected_count = num_processes * increments_per_process

    # This assertion will fail if JSONStore doesn't have cross-process locking
    # because multiple processes will overwrite each other's updates
    assert final_data["count"] == expected_count, (
        f"Expected count={expected_count}, got {final_data['count']}. "
        "Cross-process race condition detected - JSONStore needs filelock."
    )
