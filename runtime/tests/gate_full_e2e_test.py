#!/usr/bin/env python
"""Gate full batch closed-loop test with real Construct output."""
from pathlib import Path
import json
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.runtimes.gate_runtime import GateRuntime

root = Path('C:/Users/lenovo/Desktop/MultiAgentWorkspace1.0')
gate_pool = root / 'pools' / 'gate'
queue_dir = gate_pool / 'Queue'

payload = {}

# Step 1: Verify batch exists in Queue
batch_dir = queue_dir / 'batch_t_pmsm_foc_sim_002'
payload['step1_batch_exists_in_queue'] = batch_dir.exists()
payload['step1_batch_file_count'] = len(list(batch_dir.glob('*'))) if batch_dir.exists() else 0

# Step 2: Initialize runtime and list queue
runtime = GateRuntime(root_dir=root, signal_port=19299)
listed = runtime.list_queue_tasks()
payload['step2_listed_tasks'] = [p.name for p in listed]
payload['step2_first_task_is_dir'] = listed[0].is_dir() if listed else False

# Step 3: Dispatch (should preprocess folder to fields and generate reference task)
result = runtime.dispatch_next(dry_run=True)
payload['step3_dispatch_success'] = result.get('dispatched', False)
payload['step3_task_id'] = result.get('task_id', '')

slot_id = result.get('slot_id', '')
slot = runtime.get_slot(slot_id)

fields_input = gate_pool / 'fields' / result['task_id'] / 'input'
slot_reference_task = gate_pool / slot_id / f"task_{result['task_id']}.txt"

payload['step3_fields_input_created'] = fields_input.exists()
payload['step3_fields_input_file_count'] = len(list(fields_input.glob('*'))) if fields_input.exists() else 0
payload['step3_fields_has_blueprint'] = (fields_input / 'project_blueprint.md').exists() if fields_input.exists() else False
payload['step3_fields_has_work_tasks'] = len(list(fields_input.glob('task_*.txt'))) if fields_input.exists() else 0
payload['step3_slot_reference_task_created'] = slot_reference_task.exists()

# Step 4: Simulate guard extracting ONLY work tasks to workspace (NOT blueprint/index)
work_task_files = sorted(fields_input.glob('task_*.txt')) if fields_input.exists() else []
for task_file in work_task_files:
    content = task_file.read_text(encoding='utf-8')
    # Guard would review and potentially modify, but for test we just copy
    (slot.workspace_dir / task_file.name).write_text(content, encoding='utf-8')

payload['step4_workspace_file_count'] = len(list(slot.workspace_dir.glob('*')))
payload['step4_workspace_has_blueprint'] = (slot.workspace_dir / 'project_blueprint.md').exists()
payload['step4_workspace_work_task_count'] = len(list(slot.workspace_dir.glob('task_*.txt')))

# Step 5: Send approved signal (should collect workspace to Outbox and cleanup fields)
runtime.handle_signal({
    'agent_id': slot_id,
    'task_id': result['task_id'],
    'signal': 'approved',
    'to_state': 'state_3'
})

outbox_dir = gate_pool / 'Outbox' / result['task_id']

payload['step5_outbox_exists'] = outbox_dir.exists()
payload['step5_outbox_file_count'] = len(list(outbox_dir.rglob('*'))) if outbox_dir.exists() else 0
payload['step5_outbox_has_blueprint'] = (outbox_dir / 'project_blueprint.md').exists() if outbox_dir.exists() else False
payload['step5_outbox_work_task_count'] = len(list(outbox_dir.glob('task_*.txt'))) if outbox_dir.exists() else 0
payload['step5_field_cleaned_up'] = not (gate_pool / 'fields' / result['task_id']).exists()
payload['step5_work_queue_NOT_written'] = not (root / 'pools' / 'work' / 'Queue' / 'task_t_pmsm_w001.txt').exists()

print(json.dumps(payload, ensure_ascii=False, indent=2))
