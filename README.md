# MultiAgentWorkspace1.0

MultiAgentWorkspace1.0 is a pool-based multi-agent runtime framework for structured task orchestration and execution.

## Implemented Runtime Layers

- Task Pool
- Thinking Pool
- Construct Pool
- Gate Pool (implemented)
- Work Pool
- POST system

## Gate Runtime (v1.0)

Gate layer is implemented in this release:

- Entry: `runtime/app/main_gate.py`
- Runtime: `runtime/app/runtimes/gate_runtime.py`
- Tests: `runtime/tests/test_gate_runtime.py`
- Gate lifecycle tools:
  - `runtime/tools/StartReview.bat`
  - `runtime/tools/Accepted.bat`
  - `runtime/tools/Denied.bat`

## Quick Start

Install dependencies:

```bash
pip install -r requirements.txt
```

Run runtimes (example):

```bash
cd runtime
python -m app.main
python -m app.main_thinking
python -m app.main_construct
python -m app.main_gate
python -m app.main_post
```

## Test

```bash
cd runtime
pytest tests/test_gate_runtime.py -v
```

## Release Notes

This is a clean publish export for 1.0.
The following are intentionally excluded:

- Development manuals
- Handover/handoff documents
- Planning documents
- Runtime logs
- Cache/dirty artifacts
