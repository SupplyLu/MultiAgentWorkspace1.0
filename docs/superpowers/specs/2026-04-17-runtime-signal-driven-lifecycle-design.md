# MultiAgentWorkspace1.0 Runtime Signal-Driven Lifecycle Design

> Status: approved on 2026-04-17
> Scope: replace txt-led startup and watcher-led state inference with a runtime-driven, signal-based lifecycle for the first Work Pool pilot

---

## 1. Problem Statement

The current initialization skeleton still treats `BOOTSTRAP.txt`, `CLAUDE.md`, `status.txt`, `progress.txt`, and `outbox.txt` as the main execution-control surface. That model has two problems:

1. **Prompt/control pollution**: too much execution behavior is pushed into txt files that the CLI must read before acting.
2. **Weak supervision**: Runtime learns progress indirectly by polling files and guessing from missing output, which makes failures hard to diagnose in real time.

The new design moves control upward into Runtime. CLI agents remain the execution engine, but Runtime becomes the owner of prompt injection, lifecycle transitions, and supervision.

---

## 2. Goals

1. **Runtime owns startup control**
   - Runtime injects the minimal role/task/lifecycle prompt.
   - txt files stop being the primary startup authority.

2. **CLI agents actively report lifecycle signals**
   - CLI calls lightweight commands such as `Online.bat`, `StartWriting.bat`, and `Done.bat`.
   - Runtime receives explicit lifecycle events instead of inferring them from file side effects.

3. **Replace watcher-led state guessing with event-led supervision**
   - Runtime should know exactly which transition happened and when.
   - Humans and Thinking-layer agents should see a clear event timeline.

4. **Keep the protocol extensible**
   - Work Pool gets the first template.
   - Other pools may use different state templates later.
   - Future lifecycle stages must be addable without rewriting the whole system.

---

## 3. Non-Goals for Phase 1

1. Replace Claude CLI as the execution engine.
2. Fully rebuild every pool runtime before the first pilot works.
3. Fully remove all txt artifacts immediately.
4. Finish the full Cleaner/Basement governance stack in the same first slice.

Phase 1 only needs one trustworthy signal-driven chain on the Work Pool path.

---

## 4. First Principles

### 4.1 Runtime owns prompt authority

Runtime is the source of truth for:
- role identity
- task identity
- current execution phase
- allowed working scope
- required lifecycle commands

CLI should no longer need to read large bootstrap instructions to understand how it should behave.

### 4.2 bat is a thin behavioral entrypoint

`bat` files remain because they are lightweight and easy for the CLI to call, but they must stay thin.

They should not contain business logic. They should only forward a structured signal to a Python driver.

### 4.3 Python is the signal bridge

A Python bridge sits behind the bat entrypoints so we avoid pushing protocol, serialization, validation, and transport complexity into batch scripts.

### 4.4 Runtime owns the state machine

Signals are not the state machine.

CLI emits signals such as `online`, `start_writing`, or `done`. Runtime decides whether a signal is legal for the current pool/template and which state transition it causes.

### 4.5 txt is demoted, not immediately deleted

txt remains useful for:
- task payloads
- human-readable handoff notes
- audit export or snapshots

But txt no longer owns startup logic or primary status progression.

---

## 5. Architecture Overview

The new execution path is:

1. Runtime allocates a slot and prepares task context.
2. Runtime builds and injects a minimal startup prompt.
3. Runtime launches Claude CLI using the existing validated Windows launch chain.
4. CLI calls lifecycle commands (`Online.bat`, `StartWriting.bat`, `Done.bat`, etc.).
5. Each bat forwards to `signal_bridge.py`.
6. `signal_bridge.py` sends a structured event to Runtime.
7. Runtime validates the signal, advances the state machine, appends to the event store, and updates UI/supervision state.
8. Humans and Thinking-layer agents read the event view instead of reverse-engineering progress from three txt files.

---

## 6. Core Components

### 6.1 Runtime Prompt Builder

**Proposed file:** `runtime/app/services/runtime_prompt_builder.py`

Responsibilities:
- build the minimal prompt injected at launch time
- include role/task identity and lifecycle command requirements
- keep prompts short and operational
- avoid loading execution behavior from `BOOTSTRAP.txt`

The prompt should tell the CLI only what it needs to act now.

Example intent:
- who you are
- what task you own
- which input file to read
- which command to call when online
- which command to call when writing starts
- which command to call when blocked/failed/done

### 6.2 Lifecycle Command Layer

**Proposed files:**
- `runtime/tools/Online.bat`
- `runtime/tools/StartThinking.bat`
- `runtime/tools/StartWriting.bat`
- `runtime/tools/StartReview.bat`
- `runtime/tools/Blocked.bat`
- `runtime/tools/Failed.bat`
- `runtime/tools/Done.bat`

Responsibilities:
- expose simple lifecycle commands callable by CLI
- collect a small set of arguments
- forward immediately to the Python signal bridge

These bat files must remain thin wrappers.

### 6.3 Signal Bridge

**Proposed file:** `runtime/tools/signal_bridge.py`

Responsibilities:
- normalize CLI-provided arguments
- construct a structured signal payload
- send it to Runtime through the chosen transport
- return a clear success/failure exit code
- keep the CLI-facing command stable even if transport changes later

This is the protocol execution layer behind bat.

### 6.4 Runtime Signal Server

**Proposed file:** `runtime/app/services/signal_server.py`

Responsibilities:
- receive lifecycle signal payloads
- validate agent/task/signal legality
- resolve which pool template applies
- advance the correct state machine
- append the event to the event store
- publish the update to the monitoring/UI layer

### 6.5 Event Store

**Proposed file:** `runtime/app/services/event_store.py`

Responsibilities:
- persist normalized event records
- provide a simple append-only source of truth for supervision and UI
- support human-readable inspection and machine-driven queries

A simple JSONL or similar append-only store is sufficient for the first phase.

### 6.6 Pool State Template Registry

**Proposed file:** `runtime/app/services/pool_state_templates.py`

Responsibilities:
- define per-pool state templates
- map allowed signals to valid transitions
- keep Work Pool and future Thinking/Gate/Packaging pools decoupled
- make future state expansion data-driven instead of scattering `if/else`

---

## 7. Signal Model vs State Model

### 7.1 Signals are emitted by CLI

Examples:
- `online`
- `start_thinking`
- `start_writing`
- `start_review`
- `blocked`
- `failed`
- `done`

Signals are behavioral declarations: “this action happened now”.

### 7.2 States are owned by Runtime

States describe the Runtime-side lifecycle position.

For the first Work Pool template:
- `state_0 = idle`
- `state_1 = online`
- `state_2 = writing`
- `state_3 = done`

Runtime initializes a reset slot to `state_0`.

Then Runtime interprets signals as transitions:
- `Online` -> `state_0 -> state_1`
- `StartWriting` -> `state_1 -> state_2`
- `Done` -> `state_2 -> state_3`

### 7.3 Do not hardcode Work Pool as the global lifecycle

Future pools may use different templates.

Examples:
- Thinking Pool: `idle -> online -> thinking -> summarizing -> done`
- Gate Pool: `idle -> online -> reviewing -> approved/rejected`
- Packaging Pool: `idle -> online -> packaging -> published`

bat commands should not know state numbers. They emit signals only. Runtime decides the resulting transition using the active pool template.

---

## 8. Event Payload Contract

The first phase payload should be simple and explicit.

Suggested fields:

```json
{
  "timestamp": "2026-04-17T22:15:44Z",
  "agent_id": "worker_01",
  "task_id": "t_103",
  "feature_id": "feature_login",
  "role": "worker",
  "pool": "work",
  "signal": "start_writing",
  "message": "task understood, editing files",
  "artifact_root": "C:/.../runtime/artifacts/tasks/t_103",
  "source": "StartWriting.bat",
  "pid": 12345
}
```

Required fields for phase 1:
- timestamp
- agent_id
- task_id
- signal
- pool

Optional-but-supported fields:
- feature_id
- role
- message
- artifact_root
- pid
- source
- extra metadata for future pools

---

## 9. Recommended Transport Choice

The recommended first transport is:

**bat -> Python signal bridge -> local Runtime HTTP API**

Reasoning:
- bat stays lightweight
- Python is easy to debug and evolve
- local HTTP is simple to inspect and test
- UI and other services can later subscribe or query using a familiar interface
- the CLI-facing bat commands remain stable if transport changes later

Named pipes remain a possible future optimization, but are not the recommended first implementation because inspectability and debugging are more important in the pilot phase.

---

## 10. Supervision Model

### 10.1 Replace watcher-led business supervision

The system should stop treating these as the main supervision path:
- status watcher
- outbox watcher
- progress watcher
- watchdog polling that guesses failure because a file did not appear

### 10.2 Keep only minimal liveness supervision

Runtime may still keep lightweight process/liveness checks for:
- whether the CLI process is alive
- whether Runtime is alive
- whether a signal chain unexpectedly stopped

But business lifecycle understanding must come from explicit signals, not from reverse-reading txt residue.

### 10.3 Failure localization becomes precise

Examples:
- process alive but no `online` signal -> startup/protocol problem
- `online` received but no `start_writing` -> task-understanding stage blocked
- `start_writing` received but no `done/blocked/failed` -> execution stage blocked
- `failed` received -> immediate reason available

This is the main operational benefit of the redesign.

---

## 11. Human/Thinking-Layer Visibility

A person or Thinking-layer agent should not need to inspect scattered txt files to understand what is happening.

The Runtime monitoring surface should present a clear event-oriented view.

Minimum useful views:
1. **By slot**
   - current state
   - last signal
   - last updated time
2. **By task**
   - current pool/state
   - event timeline
3. **By anomaly**
   - online-without-progress
   - blocked tasks
   - failed tasks
   - illegal transition attempts

The first implementation can be fed by a simple append-only event store and a lightweight UI model.

---

## 12. Compatibility and Migration

### 12.1 Keep existing txt files temporarily

Existing files such as:
- `brain/BOOTSTRAP.txt`
- `agents/worker_01/BOOTSTRAP.txt`
- `CLAUDE.md`
- `status.txt`
- `progress.txt`
- `outbox.txt`

should be treated as temporary compatibility shells during migration.

### 12.2 Do not keep expanding txt-led startup behavior

New development should not continue moving startup logic into txt files.

The direction is:
- Runtime-driven prompt authority
- signal-driven lifecycle
- event-driven supervision

### 12.3 Work Pool is the pilot

The first real migration target is the Work Pool path for `worker_01`. Other pools can stay on older scaffolding until the new path proves reliable.

---

## 13. Phase 1 Implementation Scope

Phase 1 should land only the minimum reliable chain:

1. runtime prompt builder
2. bat lifecycle command set
3. Python signal bridge
4. Runtime signal server
5. event store
6. first Work Pool state template
7. `worker_01` pilot path wired to `online -> start_writing -> done`
8. monitoring/UI reads signal events instead of using txt files as primary truth

Phase 1 should explicitly avoid expanding into full-system replacement before the pilot works.

---

## 14. Acceptance Criteria

The design is considered successfully implemented for the first pilot when all of the following are true:

1. Runtime launches `worker_01` using the existing validated Windows launch chain.
2. Runtime injects the startup prompt directly instead of depending on txt bootstrap instructions for control.
3. The CLI calls `Online.bat` after entering the task context.
4. The CLI calls `StartWriting.bat` when writing begins.
5. The CLI calls `Done.bat` when work completes.
6. Runtime receives all three signals and records them in order.
7. Runtime advances the Work Pool state template from `state_0` to `state_3`.
8. Humans and Thinking-layer agents can read the event timeline without parsing `status/progress/outbox` as the primary truth source.
9. Primary lifecycle supervision does not depend on polling the three txt files.

---

## 15. Design Summary

The approved direction is:

**bat as a thin CLI-facing entrypoint, Python as the signal bridge, Runtime as the owner of prompt authority and extensible state transitions, and event-driven supervision replacing txt-driven lifecycle inference.**

This keeps CLI lightweight, keeps Runtime observable, and leaves room for future per-pool state templates without hardcoding the Work Pool lifecycle as the only model.
