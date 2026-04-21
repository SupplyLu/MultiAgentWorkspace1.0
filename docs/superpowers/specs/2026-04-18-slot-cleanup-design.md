# Slot Cleanup Design

**Date:** 2026-04-18
**Status:** Approved
**Scope:** WorkRuntime slot directory cleanup on terminal signals

## Problem Statement

Currently, when a worker reaches terminal state (done/failed/blocked) or times out, the slot directory retains deployment artifacts:

- `BOOTSTRAP.txt`
- `Online.bat`, `StartWriting.bat`, `Done.bat`
- `launch_*.bat`
- `signal_bridge.py`
- `task_*.txt`

These files cause:
1. **Cognitive confusion**: Cannot distinguish old vs new files
2. **Potential execution errors**: Old bats may be mistakenly executed
3. **Cleanup responsibility misplacement**: `dispatch_next()` has partial cleanup (only task_*.txt)

## Design Decision

**Approved approach**: Clean slot directory immediately on terminal signals, keeping only `workspace/` directory.

**Current implementation scope**: `done` signal and `timeout` detection. Code is compatible with `failed`/`blocked` signals, but these are not currently tested as the corresponding lifecycle bats are not yet deployed.

## Implementation

### New Method

```python
def _clean_slot_dir(self, slot: WorkerSlot) -> None:
    """Clean all deployed files in slot directory, keeping only workspace."""
    if not slot.slot_dir.exists():
        return

    for item in slot.slot_dir.iterdir():
        if item.is_dir() and item.name == "workspace":
            continue

        try:
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)
        except OSError:
            pass  # Ignore cleanup failures to not block slot release
```

### Call Sites

1. `handle_signal()`
   - `done`: collect Outbox artifacts first, then call `_clean_slot_dir()`, then clean up worker process
   - `failed` / `blocked`: code-compatible terminal signals; call `_clean_slot_dir()` and process cleanup, but corresponding bats are not currently deployed/tested
2. `check_timeouts()`
   - `timeout`: call `_clean_slot_dir()` after process cleanup, before slot state reset

### Retained Cleanup

`dispatch_next()` lines 146-148 partial cleanup remains as defensive fallback.

## Testing

- Unit test: `test_slot_cleanup_on_done_signal()`
- Unit test: `test_slot_cleanup_on_timeout()`
- Existing lifecycle ownership tests still cover terminal-signal process cleanup for `done` / `failed` / `blocked`
- E2E verification in `real_closed_loop_verify.py`

**Test mapping**
- `done` cleanup: `test_slot_cleanup_on_done_signal()`
- `timeout` cleanup: `test_slot_cleanup_on_timeout()`
- `failed` / `blocked` process cleanup only: existing lifecycle ownership tests

**Note**: `failed`/`blocked` signals are code-compatible in `terminal_signals` set, but no corresponding bats are currently deployed. Directory-cleanup tests for these signals are deferred until the full lifecycle is implemented.

## Verification Criteria

- [x] After done signal, slot directory contains only `workspace/`
- [x] After timeout, slot directory contains only `workspace/`
- [x] All existing tests pass (64/64)
- [x] New cleanup tests pass (2/2)
