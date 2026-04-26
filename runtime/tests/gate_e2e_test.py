#!/usr/bin/env python
"""Gate batch closed-loop end-to-end test."""
from pathlib import Path
import json
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.runtimes.gate_runtime import GateRuntime

root = Path('C:/Users/lenovo/Desktop/MultiAgentWorkspace1.0')
gate_pool = root / 'pools' / 'gate'
queue_dir = gate_pool / 'Queue'

# Prepare payload
payload = {}

# Step 1: Create batch folder in Queue
batch_dir = queue_dir / 'batch_gate_e2e_001'
batch_dir.mkdir(parents=True, exist_ok=True)
(batch_dir / 'summary.txt').write_text(
    'TASK_ID: batch_gate_e2e_001\n---\nCore summary, should stay out of workspace outputs',
    encoding='utf-8'
)
(batch_dir / 'task_demo_w001.txt').write_text('FROM: construct\nTO: gate\n---\nTask 1', encoding='utf-8')
(batch_dir / 'task_demo_w002.txt').write_text('FROM: construct\nTO: gate\n---\nTask 2', encoding='utf-8')

payload['step1_batch_created_in_queue'] = batch_dir.exists()

# Step 2: Initialize runtime and list queue
runtime = GateRuntime(root_dir=root, signal_port=19299)
listed = runtime.list_queue_tasks()
payload['step2_listed_tasks'] = [p.name for p in listed]
payload['step2_listed_tasks_is_dir'] = [p.is_dir() for p in listed]

# Step 3: Dispatch (should preprocess folder to fields and generate reference task)
result = runtime.dispatch_next(dry_run=True)
payload['step3_dispatch_success'] = result.get('dispatched', False)
payload['step3_task_id'] = result.get('task_id', '')

slot_id = result.get('slot_id', '')
slot = runtime.get_slot(slot_id)

fields_input = gate_pool / 'fields' / result['task_id'] / 'input'
slot_reference_task = gate_pool / slot_id / f"task_{result['task_id']}.txt"

payload['step3_fields_input_created'] = fields_input.exists()
payload['step3_fields_input_files'] = sorted([p.name for p in fields_input.glob('*')]) if fields_input.exists() else []
payload['step3_slot_reference_task_created'] = slot_reference_task.exists()

# Step 4: Simulate guard extracting work tasks to workspace (NOT summary)
(slot.workspace_dir / 'task_demo_w001.txt').write_text('FROM: gate\nTO: work\n---\nApproved task 1', encoding='utf-8')
(slot.workspace_dir / 'task_demo_w002.txt').write_text('FROM: gate\nTO: work\n---\nApproved task 2', encoding='utf-8')

# Step 5: Send approved signal (should collect workspace to Outbox and cleanup fields)
runtime.handle_signal({
    'agent_id': slot_id,
    'task_id': result['task_id'],
    'signal': 'approved',
    'to_state': 'state_3'
})

outbox_dir = gate_pool / 'Outbox' / result['task_id']

payload['step5_outbox_exists'] = outbox_dir.exists()
payload['step5_outbox_files'] = sorted([p.name for p in outbox_dir.rglob('*') if p.is_file()])
payload['step5_summary_in_outbox_is_false'] = not (outbox_dir / 'summary.txt').exists()
payload['step5_work_tasks_in_outbox'] = (outbox_dir / 'task_demo_w001.txt').exists() and (outbox_dir / 'task_demo_w002.txt').exists()
payload['step5_field_cleaned_up'] = not (gate_pool / 'fields' / result['task_id']).exists()
payload['step5_work_queue_NOT_written'] = not (root / 'pools' / 'work' / 'Queue' / 'task_demo_w001.txt').exists()

print(json.dumps(payload, ensure_ascii=False, indent=2))
